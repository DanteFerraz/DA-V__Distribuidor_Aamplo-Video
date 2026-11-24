# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Injetor Nativo Win32 de Ultra-Baixa Latencia via `user32.SendInput` — DA-V v5.0
Autor: Dante Ferraz (MonoTech)

Mapeia coordenadas normalizadas `[0..65535]` do monitor transmitido diretamente para o
espaco `VirtualScreen` multi-monitor do Windows (`MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK`)
e injeta teclas por ScanCode fisico Set-1 (`KEYEVENTF_SCANCODE`), garantindo alinhamento de
40 bytes na uniao `INPUT` em arquiteturas x64.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Optional

from src.dav.modules.remote_desktop.injector_base import BaseInputInjector, MonitorBounds
from src.dav.modules.remote_desktop.keymap import hid_to_win32_scancode
from src.dav.modules.remote_desktop.protocol import (
    EvType,
    InputEventPacket,
    MouseBtn,
    unpack_wheel_deltas,
)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

XBUTTON1 = 0x0001
XBUTTON2 = 0x0002

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_uint16),
        ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_uint32),
        ("wParamL", ctypes.c_uint16),
        ("wParamH", ctypes.c_uint16),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("u", _INPUT_UNION),
    ]


class Win32InputInjector(BaseInputInjector):
    """Injetor nativo Windows 10/11 baseado em `user32.SendInput` (< 0.05 ms/evento)."""

    def __init__(self, bounds: Optional[MonitorBounds] = None):
        super().__init__(bounds=bounds)
        if sys.platform != "win32":
            raise RuntimeError("Win32InputInjector requer Windows.")
        self._user32 = ctypes.windll.user32
        self._shell32 = ctypes.windll.shell32
        self._user32.SendInput.argtypes = [
            ctypes.c_uint,
            ctypes.POINTER(_INPUT),
            ctypes.c_int,
        ]
        self._user32.SendInput.restype = ctypes.c_uint
        try:
            self._is_admin = bool(self._shell32.IsUserAnAdmin())
        except Exception:
            self._is_admin = False

    @property
    def backend_name(self) -> str:
        return "win32_sendinput_admin" if self._is_admin else "win32_sendinput"

    @property
    def is_elevated(self) -> bool:
        return self._is_admin

    def _map_abs_to_virtual_desk(self, norm_x: int, norm_y: int) -> tuple[int, int]:
        nx = max(0, min(65535, int(norm_x)))
        ny = max(0, min(65535, int(norm_y)))

        px_x = self.bounds.left + (nx * max(1, self.bounds.width - 1)) / 65535.0
        px_y = self.bounds.top + (ny * max(1, self.bounds.height - 1)) / 65535.0

        vx = self._user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = self._user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = max(1, self._user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
        vh = max(1, self._user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))

        abs_x = int(round(((px_x - vx) * 65535.0) / max(1, vw - 1)))
        abs_y = int(round(((px_y - vy) * 65535.0) / max(1, vh - 1)))
        return max(0, min(65535, abs_x)), max(0, min(65535, abs_y))

    def _send_mouse(self, dx: int, dy: int, flags: int, mouse_data: int = 0) -> bool:
        inp = _INPUT()
        inp.type = INPUT_MOUSE
        inp.u.mi = _MOUSEINPUT(
            dx=int(dx),
            dy=int(dy),
            mouseData=int(mouse_data) & 0xFFFFFFFF,
            dwFlags=int(flags) & 0xFFFFFFFF,
            time=0,
            dwExtraInfo=0,
        )
        sent = self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
        return sent == 1

    def _send_key(self, hid_code: int, is_up: bool) -> bool:
        sc, is_ext = hid_to_win32_scancode(hid_code)
        if sc <= 0:
            return False
        flags = KEYEVENTF_SCANCODE
        if is_ext:
            flags |= KEYEVENTF_EXTENDEDKEY
        if is_up:
            flags |= KEYEVENTF_KEYUP
        inp = _INPUT()
        inp.type = INPUT_KEYBOARD
        inp.u.ki = _KEYBDINPUT(
            wVk=0,
            wScan=int(sc) & 0xFFFF,
            dwFlags=flags,
            time=0,
            dwExtraInfo=0,
        )
        sent = self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
        return sent == 1

    def _inject_native(self, pkt: InputEventPacket) -> bool:
        et = pkt.ev_type
        if et == EvType.MOVE_ABS:
            ax, ay = self._map_abs_to_virtual_desk(pkt.x_val, pkt.y_val)
            return self._send_mouse(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK)

        if et == EvType.MOVE_REL:
            return self._send_mouse(pkt.x_val, pkt.y_val, MOUSEEVENTF_MOVE)

        if et in (EvType.BTN_DOWN, EvType.BTN_UP):
            is_down = (et == EvType.BTN_DOWN)
            # Posiciona o cursor antes do clique caso coordenadas validas tenham vindo juntas
            if 0 <= pkt.x_val <= 65535 and 0 <= pkt.y_val <= 65535 and (pkt.x_val > 0 or pkt.y_val > 0):
                ax, ay = self._map_abs_to_virtual_desk(pkt.x_val, pkt.y_val)
                self._send_mouse(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK)

            ok = True
            mask = pkt.buttons_mask
            if mask & MouseBtn.LEFT:
                ok = self._send_mouse(0, 0, MOUSEEVENTF_LEFTDOWN if is_down else MOUSEEVENTF_LEFTUP) and ok
            if mask & MouseBtn.RIGHT:
                ok = self._send_mouse(0, 0, MOUSEEVENTF_RIGHTDOWN if is_down else MOUSEEVENTF_RIGHTUP) and ok
            if mask & MouseBtn.MIDDLE:
                ok = self._send_mouse(0, 0, MOUSEEVENTF_MIDDLEDOWN if is_down else MOUSEEVENTF_MIDDLEUP) and ok
            if mask & MouseBtn.BACK:
                ok = self._send_mouse(0, 0, MOUSEEVENTF_XDOWN if is_down else MOUSEEVENTF_XUP, XBUTTON1) and ok
            if mask & MouseBtn.FORWARD:
                ok = self._send_mouse(0, 0, MOUSEEVENTF_XDOWN if is_down else MOUSEEVENTF_XUP, XBUTTON2) and ok
            return ok

        if et == EvType.WHEEL:
            dx, dy = unpack_wheel_deltas(pkt.key_or_wheel)
            ok = True
            if dy != 0:
                ok = self._send_mouse(0, 0, MOUSEEVENTF_WHEEL, dy) and ok
            if dx != 0:
                ok = self._send_mouse(0, 0, MOUSEEVENTF_HWHEEL, dx) and ok
            return ok

        if et == EvType.KEY_DOWN:
            return self._send_key(pkt.key_or_wheel, is_up=False)

        if et == EvType.KEY_UP:
            return self._send_key(pkt.key_or_wheel, is_up=True)

        return False
