# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Injetores Nativos Linux (Kernel `/dev/uinput` + Wayland Portal RemoteDesktop + X11 XTest) — DA-V v5.0
Autor: Dante Ferraz (MonoTech)

Cascata sem subprocessos por evento:
1. `LinuxUInputInjector`: Dispositivo HID virtual no kernel (`/dev/uinput`, `< 0,05 ms`), universal
   para Wayland + X11 + janelas administrativas quando autorizado via Polkit (`pkexec`) ou grupo `input`.
2. `WaylandPortalInputInjector`: Canal de comandos sobre o helper XDG `org.freedesktop.portal.RemoteDesktop`.
3. `X11XTestInjector`: `libX11.so.6` + `libXtst.so.6` via `ctypes` mantendo `Display*` aberto.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import struct
import sys
import time
from typing import Callable, Optional

from src.dav.modules.remote_desktop.injector_base import BaseInputInjector, MonitorBounds
from src.dav.modules.remote_desktop.keymap import (
    hid_to_linux_evdev,
    hid_to_x11_keycode,
    supported_evdev_keycodes,
)
from src.dav.modules.remote_desktop.protocol import (
    EvType,
    InputEventPacket,
    MouseBtn,
    unpack_wheel_deltas,
)

# Constantes Linux input/uinput (`linux/input-event-codes.h` & `linux/uinput.h`)
EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03

SYN_REPORT = 0x00
REL_X = 0x00
REL_Y = 0x01
REL_HWHEEL = 0x06
REL_WHEEL = 0x08
ABS_X = 0x00
ABS_Y = 0x01

BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
BTN_SIDE = 0x113
BTN_EXTRA = 0x114

BUS_USB = 0x03

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_SET_ABSBIT = 0x40045567
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

_INPUT_EVENT_STRUCT = struct.Struct("@llHHi")  # timeval (sec, usec), type, code, value (24B em x86_64)


class LinuxUInputInjector(BaseInputInjector):
    """Dispositivo HID virtual de kernel `/dev/uinput` (Wayland + X11 + Admin)."""

    def __init__(self, bounds: Optional[MonitorBounds] = None):
        super().__init__(bounds=bounds)
        if sys.platform == "win32":
            raise RuntimeError("LinuxUInputInjector requer Linux.")
        import fcntl

        self._fcntl = fcntl
        uinput_path = "/dev/uinput" if os.path.exists("/dev/uinput") else "/dev/input/uinput"
        self._fd = os.open(uinput_path, os.O_WRONLY | os.O_NONBLOCK)

        try:
            fcntl.ioctl(self._fd, UI_SET_EVBIT, EV_KEY)
            fcntl.ioctl(self._fd, UI_SET_EVBIT, EV_REL)
            fcntl.ioctl(self._fd, UI_SET_EVBIT, EV_ABS)
            fcntl.ioctl(self._fd, UI_SET_EVBIT, EV_SYN)

            for btn in (BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA):
                fcntl.ioctl(self._fd, UI_SET_KEYBIT, btn)
            for key_code in supported_evdev_keycodes():
                fcntl.ioctl(self._fd, UI_SET_KEYBIT, key_code)

            for rel_axis in (REL_X, REL_Y, REL_WHEEL, REL_HWHEEL):
                fcntl.ioctl(self._fd, UI_SET_RELBIT, rel_axis)
            for abs_axis in (ABS_X, ABS_Y):
                fcntl.ioctl(self._fd, UI_SET_ABSBIT, abs_axis)

            # Struct `uinput_user_dev` classica (name[80], input_id[8], ff_effects_max[4], absmax[64*4], absmin[64*4], absfuzz[64*4], absflat[64*4] = 1116 bytes)
            name_bytes = b"DA-V Remote Workspace HID\x00".ljust(80, b"\x00")
            id_bytes = struct.pack("@HHHH", BUS_USB, 0x1D6B, 0x0104, 1)
            ff_max = struct.pack("@I", 0)
            absmax = [0] * 64
            absmin = [0] * 64
            absfuzz = [0] * 64
            absflat = [0] * 64
            absmax[ABS_X] = 65535
            absmax[ABS_Y] = 65535
            udev_struct = (
                name_bytes
                + id_bytes
                + ff_max
                + struct.pack("@64i", *absmax)
                + struct.pack("@64i", *absmin)
                + struct.pack("@64i", *absfuzz)
                + struct.pack("@64i", *absflat)
            )
            os.write(self._fd, udev_struct)
            fcntl.ioctl(self._fd, UI_DEV_CREATE)
            time.sleep(0.05)
        except Exception:
            os.close(self._fd)
            self._fd = -1
            raise

    @property
    def backend_name(self) -> str:
        return "linux_uinput_kernel"

    @property
    def is_elevated(self) -> bool:
        return True

    def _emit(self, events: list[tuple[int, int, int]]) -> bool:
        if self._fd < 0:
            return False
        buf = bytearray()
        for ev_t, code, val in events:
            buf.extend(_INPUT_EVENT_STRUCT.pack(0, 0, ev_t, code, int(val)))
        buf.extend(_INPUT_EVENT_STRUCT.pack(0, 0, EV_SYN, SYN_REPORT, 0))
        try:
            os.write(self._fd, bytes(buf))
            return True
        except OSError:
            return False

    def _inject_native(self, pkt: InputEventPacket) -> bool:
        et = pkt.ev_type
        if et == EvType.MOVE_ABS:
            nx = max(0, min(65535, int(pkt.x_val)))
            ny = max(0, min(65535, int(pkt.y_val)))
            return self._emit([(EV_ABS, ABS_X, nx), (EV_ABS, ABS_Y, ny)])

        if et == EvType.MOVE_REL:
            return self._emit([(EV_REL, REL_X, int(pkt.x_val)), (EV_REL, REL_Y, int(pkt.y_val))])

        if et in (EvType.BTN_DOWN, EvType.BTN_UP):
            val = 1 if et == EvType.BTN_DOWN else 0
            evs: list[tuple[int, int, int]] = []
            if 0 <= pkt.x_val <= 65535 and 0 <= pkt.y_val <= 65535 and (pkt.x_val > 0 or pkt.y_val > 0):
                evs.append((EV_ABS, ABS_X, pkt.x_val))
                evs.append((EV_ABS, ABS_Y, pkt.y_val))
            mask = pkt.buttons_mask
            if mask & MouseBtn.LEFT:
                evs.append((EV_KEY, BTN_LEFT, val))
            if mask & MouseBtn.RIGHT:
                evs.append((EV_KEY, BTN_RIGHT, val))
            if mask & MouseBtn.MIDDLE:
                evs.append((EV_KEY, BTN_MIDDLE, val))
            if mask & MouseBtn.BACK:
                evs.append((EV_KEY, BTN_SIDE, val))
            if mask & MouseBtn.FORWARD:
                evs.append((EV_KEY, BTN_EXTRA, val))
            return self._emit(evs) if evs else False

        if et == EvType.WHEEL:
            dx, dy = unpack_wheel_deltas(pkt.key_or_wheel)
            evs = []
            if dy != 0:
                steps_y = int(round(dy / 120.0)) or (1 if dy > 0 else -1)
                evs.append((EV_REL, REL_WHEEL, steps_y))
            if dx != 0:
                steps_x = int(round(dx / 120.0)) or (1 if dx > 0 else -1)
                evs.append((EV_REL, REL_HWHEEL, steps_x))
            return self._emit(evs) if evs else False

        if et in (EvType.KEY_DOWN, EvType.KEY_UP):
            ev_key = hid_to_linux_evdev(pkt.key_or_wheel)
            if ev_key <= 0:
                return False
            return self._emit([(EV_KEY, ev_key, 1 if et == EvType.KEY_DOWN else 0)])

        return False

    def close(self) -> None:
        super().close()
        if self._fd >= 0:
            try:
                self._fcntl.ioctl(self._fd, UI_DEV_DESTROY)
            except Exception:
                pass
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = -1


class WaylandPortalInputInjector(BaseInputInjector):
    """Ponte para sessao XDG `org.freedesktop.portal.RemoteDesktop` sem root."""

    def __init__(self, send_cmd_fn: Callable[[str], bool], bounds: Optional[MonitorBounds] = None):
        super().__init__(bounds=bounds)
        self._send_cmd = send_cmd_fn

    @property
    def backend_name(self) -> str:
        return "wayland_xdg_portal"

    def _inject_native(self, pkt: InputEventPacket) -> bool:
        et = pkt.ev_type
        if et == EvType.MOVE_ABS:
            px = (max(0, min(65535, pkt.x_val)) / 65535.0) * max(1, self.bounds.width - 1)
            py = (max(0, min(65535, pkt.y_val)) / 65535.0) * max(1, self.bounds.height - 1)
            return self._send_cmd(f"M_ABS {px:.2f} {py:.2f}\n")
        if et == EvType.MOVE_REL:
            return self._send_cmd(f"M_REL {float(pkt.x_val):.2f} {float(pkt.y_val):.2f}\n")
        if et in (EvType.BTN_DOWN, EvType.BTN_UP):
            state = 1 if et == EvType.BTN_DOWN else 0
            if 0 <= pkt.x_val <= 65535 and 0 <= pkt.y_val <= 65535 and (pkt.x_val > 0 or pkt.y_val > 0):
                px = (pkt.x_val / 65535.0) * max(1, self.bounds.width - 1)
                py = (pkt.y_val / 65535.0) * max(1, self.bounds.height - 1)
                self._send_cmd(f"M_ABS {px:.2f} {py:.2f}\n")
            ok = True
            for mask_bit, ev_btn in (
                (MouseBtn.LEFT, BTN_LEFT),
                (MouseBtn.RIGHT, BTN_RIGHT),
                (MouseBtn.MIDDLE, BTN_MIDDLE),
                (MouseBtn.BACK, BTN_SIDE),
                (MouseBtn.FORWARD, BTN_EXTRA),
            ):
                if pkt.buttons_mask & mask_bit:
                    ok = self._send_cmd(f"BTN {ev_btn} {state}\n") and ok
            return ok
        if et == EvType.WHEEL:
            dx, dy = unpack_wheel_deltas(pkt.key_or_wheel)
            ok = True
            if dy != 0:
                steps = -1 if dy > 0 else 1  # Portal axis: negativo = scroll up
                ok = self._send_cmd(f"WHEEL 0 {steps}\n") and ok
            if dx != 0:
                steps_x = 1 if dx > 0 else -1
                ok = self._send_cmd(f"WHEEL 1 {steps_x}\n") and ok
            return ok
        if et in (EvType.KEY_DOWN, EvType.KEY_UP):
            ev_key = hid_to_linux_evdev(pkt.key_or_wheel)
            if ev_key <= 0:
                return False
            state = 1 if et == EvType.KEY_DOWN else 0
            return self._send_cmd(f"KEY {ev_key} {state}\n")
        return False


class X11XTestInjector(BaseInputInjector):
    """Injetor X11 nativo via `libX11.so.6` + `libXtst.so.6` mantendo conexao Display aberta."""

    def __init__(self, bounds: Optional[MonitorBounds] = None):
        super().__init__(bounds=bounds)
        if sys.platform == "win32":
            raise RuntimeError("X11XTestInjector requer Linux/X11.")
        x11_name = ctypes.util.find_library("X11") or "libX11.so.6"
        xtst_name = ctypes.util.find_library("Xtst") or "libXtst.so.6"
        self._x11 = ctypes.CDLL(x11_name)
        self._xtst = ctypes.CDLL(xtst_name)

        self._x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self._x11.XOpenDisplay.restype = ctypes.c_void_p
        self._x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self._x11.XCloseDisplay.restype = ctypes.c_int
        self._x11.XFlush.argtypes = [ctypes.c_void_p]
        self._x11.XFlush.restype = ctypes.c_int

        self._xtst.XTestFakeMotionEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong
        ]
        self._xtst.XTestFakeMotionEvent.restype = ctypes.c_int
        self._xtst.XTestFakeRelativeMotionEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_ulong
        ]
        self._xtst.XTestFakeRelativeMotionEvent.restype = ctypes.c_int
        self._xtst.XTestFakeButtonEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong
        ]
        self._xtst.XTestFakeButtonEvent.restype = ctypes.c_int
        self._xtst.XTestFakeKeyEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong
        ]
        self._xtst.XTestFakeKeyEvent.restype = ctypes.c_int

        self._dpy = self._x11.XOpenDisplay(None)
        if not self._dpy:
            raise RuntimeError("XOpenDisplay retornou NULL (sessao X11 indisponivel).")

    @property
    def backend_name(self) -> str:
        return "linux_x11_xtest"

    def _inject_native(self, pkt: InputEventPacket) -> bool:
        if not self._dpy:
            return False
        et = pkt.ev_type
        if et == EvType.MOVE_ABS:
            px = self.bounds.left + int(round((max(0, min(65535, pkt.x_val)) * max(1, self.bounds.width - 1)) / 65535.0))
            py = self.bounds.top + int(round((max(0, min(65535, pkt.y_val)) * max(1, self.bounds.height - 1)) / 65535.0))
            self._xtst.XTestFakeMotionEvent(self._dpy, -1, px, py, 0)
            self._x11.XFlush(self._dpy)
            return True

        if et == EvType.MOVE_REL:
            self._xtst.XTestFakeRelativeMotionEvent(self._dpy, int(pkt.x_val), int(pkt.y_val), 0)
            self._x11.XFlush(self._dpy)
            return True

        if et in (EvType.BTN_DOWN, EvType.BTN_UP):
            is_press = 1 if et == EvType.BTN_DOWN else 0
            if 0 <= pkt.x_val <= 65535 and 0 <= pkt.y_val <= 65535 and (pkt.x_val > 0 or pkt.y_val > 0):
                px = self.bounds.left + int(round((pkt.x_val * max(1, self.bounds.width - 1)) / 65535.0))
                py = self.bounds.top + int(round((pkt.y_val * max(1, self.bounds.height - 1)) / 65535.0))
                self._xtst.XTestFakeMotionEvent(self._dpy, -1, px, py, 0)
            for bit, xbtn in (
                (MouseBtn.LEFT, 1),
                (MouseBtn.MIDDLE, 2),
                (MouseBtn.RIGHT, 3),
                (MouseBtn.BACK, 8),
                (MouseBtn.FORWARD, 9),
            ):
                if pkt.buttons_mask & bit:
                    self._xtst.XTestFakeButtonEvent(self._dpy, xbtn, is_press, 0)
            self._x11.XFlush(self._dpy)
            return True

        if et == EvType.WHEEL:
            dx, dy = unpack_wheel_deltas(pkt.key_or_wheel)
            if dy != 0:
                btn = 4 if dy > 0 else 5
                self._xtst.XTestFakeButtonEvent(self._dpy, btn, 1, 0)
                self._xtst.XTestFakeButtonEvent(self._dpy, btn, 0, 0)
            if dx != 0:
                btn_x = 7 if dx > 0 else 6
                self._xtst.XTestFakeButtonEvent(self._dpy, btn_x, 1, 0)
                self._xtst.XTestFakeButtonEvent(self._dpy, btn_x, 0, 0)
            self._x11.XFlush(self._dpy)
            return True

        if et in (EvType.KEY_DOWN, EvType.KEY_UP):
            kc = hid_to_x11_keycode(pkt.key_or_wheel)
            if kc <= 0:
                return False
            self._xtst.XTestFakeKeyEvent(self._dpy, kc, 1 if et == EvType.KEY_DOWN else 0, 0)
            self._x11.XFlush(self._dpy)
            return True

        return False

    def close(self) -> None:
        super().close()
        if getattr(self, "_dpy", None):
            try:
                self._x11.XCloseDisplay(self._dpy)
            except Exception:
                pass
            self._dpy = None
