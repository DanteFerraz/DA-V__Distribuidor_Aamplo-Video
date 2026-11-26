# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Adaptador Nativo Pure-Python (`ctypes`) para ViGEmClient.dll (Windows x64) — DA-V v5.2
Autor: Dante Ferraz (MonoTech)

Substitui a dependencia rigida de compilacao/instalacao do pacote `vgamepad` no CI,
carregando diretamente o binario pre-compilado MIT `third_party/vigem/x64/ViGEmClient.dll`:
- Conexao preguicosa (`lazy`) ao barramento `ViGEmBus` com reconexao automatica se o driver
  for instalado em tempo de execucao sem reiniciar o aplicativo;
- Structs C com campos sem sinal (`c_ubyte`) para gatilhos e eixos DS4/X360;
- Retencao forte de callbacks `WINFUNCTYPE` contra coleta de lixo (GC);
- Desplugue deterministico (`vigem_target_remove` + `vigem_target_free`) em `close()`.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from ctypes import (
    CDLL,
    Structure,
    c_short,
    c_ubyte,
    c_uint,
    c_ushort,
    c_void_p,
    wintypes,
)
from enum import IntEnum, IntFlag
from pathlib import Path
from typing import Callable, Optional

from src.dav.modules.universal_input.models import GamepadButtonMask, GamepadStateDTO

logger = logging.getLogger("DAV.UniversalInput.ViGEmCtypes")

VIGEM_ERROR_NONE = 0x20000000


class XusbButton(IntFlag):
    DPAD_UP = 0x0001
    DPAD_DOWN = 0x0002
    DPAD_LEFT = 0x0004
    DPAD_RIGHT = 0x0008
    START = 0x0010
    BACK = 0x0020
    LEFT_THUMB = 0x0040
    RIGHT_THUMB = 0x0080
    LEFT_SHOULDER = 0x0100
    RIGHT_SHOULDER = 0x0200
    GUIDE = 0x0400
    A = 0x1000
    B = 0x2000
    X = 0x4000
    Y = 0x8000


class Ds4Button(IntFlag):
    THUMB_RIGHT = 1 << 15
    THUMB_LEFT = 1 << 14
    OPTIONS = 1 << 13
    SHARE = 1 << 12
    TRIGGER_RIGHT = 1 << 11
    TRIGGER_LEFT = 1 << 10
    SHOULDER_RIGHT = 1 << 9
    SHOULDER_LEFT = 1 << 8
    TRIANGLE = 1 << 7
    CIRCLE = 1 << 6
    CROSS = 1 << 5
    SQUARE = 1 << 4


class Ds4SpecialButton(IntFlag):
    PS = 1 << 0
    TOUCHPAD = 1 << 1


class Ds4Dpad(IntEnum):
    NORTH = 0x0
    NORTHEAST = 0x1
    EAST = 0x2
    SOUTHEAST = 0x3
    SOUTH = 0x4
    SOUTHWEST = 0x5
    WEST = 0x6
    NORTHWEST = 0x7
    NONE = 0x8


class XUSB_REPORT(Structure):
    _fields_ = [
        ("wButtons", c_ushort),
        ("bLeftTrigger", c_ubyte),
        ("bRightTrigger", c_ubyte),
        ("sThumbLX", c_short),
        ("sThumbLY", c_short),
        ("sThumbRX", c_short),
        ("sThumbRY", c_short),
    ]


class DS4_LIGHTBAR_COLOR(Structure):
    _fields_ = [
        ("Red", c_ubyte),
        ("Green", c_ubyte),
        ("Blue", c_ubyte),
    ]


class DS4_REPORT(Structure):
    _fields_ = [
        ("bThumbLX", c_ubyte),
        ("bThumbLY", c_ubyte),
        ("bThumbRX", c_ubyte),
        ("bThumbRY", c_ubyte),
        ("wButtons", c_ushort),
        ("bSpecial", c_ubyte),
        ("bTriggerL", c_ubyte),
        ("bTriggerR", c_ubyte),
    ]


def _candidate_search_roots() -> list[Path]:
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    # Raiz do repositorio (src/dav/modules/universal_input/vigem_ctypes.py -> parents[4])
    try:
        roots.append(Path(__file__).resolve().parents[4])
    except IndexError:
        pass
    roots.append(Path.cwd())
    return roots


def find_vigem_client_dll() -> Optional[Path]:
    """Localiza `ViGEmClient.dll` x64 pre-compilada (bundle PyInstaller, repo ou vgamepad)."""
    rel_candidates = (
        Path("third_party") / "vigem" / "x64" / "ViGEmClient.dll",
        Path("_internal") / "third_party" / "vigem" / "x64" / "ViGEmClient.dll",
        Path("ViGEmClient.dll"),
    )
    for root in _candidate_search_roots():
        for rel in rel_candidates:
            cand = root / rel
            if cand.is_file():
                return cand
    # Fallback opcional se o pacote `vgamepad` estiver instalado no ambiente Python
    try:
        import importlib.util

        spec = importlib.util.find_spec("vgamepad")
        if spec and spec.origin:
            vg_dll = Path(spec.origin).parent / "win" / "vigem" / "client" / "x64" / "ViGEmClient.dll"
            if vg_dll.is_file():
                return vg_dll
    except Exception:
        pass
    sys32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "ViGEmClient.dll"
    if sys32.is_file():
        return sys32
    return None


def find_vigem_bus_installer_msi() -> Optional[Path]:
    """Localiza o instalador offline `ViGEmBusSetup_x64.msi` versionado no repositorio/bundle."""
    rel_candidates = (
        Path("third_party") / "vigem" / "install" / "x64" / "ViGEmBusSetup_x64.msi",
        Path("_internal") / "third_party" / "vigem" / "install" / "x64" / "ViGEmBusSetup_x64.msi",
    )
    for root in _candidate_search_roots():
        for rel in rel_candidates:
            cand = root / rel
            if cand.is_file():
                return cand
    return None


class _ViGEmApi:
    """Wrapper de assinaturas C de `ViGEmClient.dll`."""

    def __init__(self, dll_path: Path):
        self.dll_path = dll_path
        lib = CDLL(str(dll_path))
        self.lib = lib

        self.vigem_alloc = lib.vigem_alloc
        self.vigem_alloc.argtypes = ()
        self.vigem_alloc.restype = c_void_p

        self.vigem_free = lib.vigem_free
        self.vigem_free.argtypes = (c_void_p,)
        self.vigem_free.restype = None

        self.vigem_connect = lib.vigem_connect
        self.vigem_connect.argtypes = (c_void_p,)
        self.vigem_connect.restype = c_uint

        self.vigem_disconnect = lib.vigem_disconnect
        self.vigem_disconnect.argtypes = (c_void_p,)
        self.vigem_disconnect.restype = None

        self.vigem_target_x360_alloc = lib.vigem_target_x360_alloc
        self.vigem_target_x360_alloc.argtypes = ()
        self.vigem_target_x360_alloc.restype = c_void_p

        self.vigem_target_ds4_alloc = lib.vigem_target_ds4_alloc
        self.vigem_target_ds4_alloc.argtypes = ()
        self.vigem_target_ds4_alloc.restype = c_void_p

        self.vigem_target_free = lib.vigem_target_free
        self.vigem_target_free.argtypes = (c_void_p,)
        self.vigem_target_free.restype = None

        self.vigem_target_add = lib.vigem_target_add
        self.vigem_target_add.argtypes = (c_void_p, c_void_p)
        self.vigem_target_add.restype = c_uint

        self.vigem_target_remove = lib.vigem_target_remove
        self.vigem_target_remove.argtypes = (c_void_p, c_void_p)
        self.vigem_target_remove.restype = c_uint

        self.vigem_target_is_attached = lib.vigem_target_is_attached
        self.vigem_target_is_attached.argtypes = (c_void_p,)
        self.vigem_target_is_attached.restype = wintypes.BOOL

        self.vigem_target_x360_update = lib.vigem_target_x360_update
        self.vigem_target_x360_update.argtypes = (c_void_p, c_void_p, XUSB_REPORT)
        self.vigem_target_x360_update.restype = c_uint

        self.vigem_target_ds4_update = lib.vigem_target_ds4_update
        self.vigem_target_ds4_update.argtypes = (c_void_p, c_void_p, DS4_REPORT)
        self.vigem_target_ds4_update.restype = c_uint

        self.vigem_target_x360_register_notification = lib.vigem_target_x360_register_notification
        self.vigem_target_x360_register_notification.argtypes = (c_void_p, c_void_p, c_void_p, c_void_p)
        self.vigem_target_x360_register_notification.restype = c_uint

        self.vigem_target_x360_unregister_notification = lib.vigem_target_x360_unregister_notification
        self.vigem_target_x360_unregister_notification.argtypes = (c_void_p,)
        self.vigem_target_x360_unregister_notification.restype = None

        self.vigem_target_ds4_register_notification = lib.vigem_target_ds4_register_notification
        self.vigem_target_ds4_register_notification.argtypes = (c_void_p, c_void_p, c_void_p, c_void_p)
        self.vigem_target_ds4_register_notification.restype = c_uint

        self.vigem_target_ds4_unregister_notification = lib.vigem_target_ds4_unregister_notification
        self.vigem_target_ds4_unregister_notification.argtypes = (c_void_p,)
        self.vigem_target_ds4_unregister_notification.restype = None


class _SharedViGEmBus:
    """Gerenciador singleton lazy/thread-safe do cliente ViGEmBus."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._api: Optional[_ViGEmApi] = None
        self._busp: Optional[int] = None

    def ensure_connected(self) -> tuple[_ViGEmApi, int]:
        if sys.platform != "win32":
            raise RuntimeError("ViGEmClient nativo requer Windows.")
        with self._lock:
            if self._api is None:
                dll_path = find_vigem_client_dll()
                if dll_path is None:
                    raise FileNotFoundError("ViGEmClient.dll (x64) nao encontrada.")
                self._api = _ViGEmApi(dll_path)

            if self._busp:
                return self._api, self._busp

            busp = self._api.vigem_alloc()
            if not busp:
                raise RuntimeError("vigem_alloc retornou ponteiro nulo.")
            err = int(self._api.vigem_connect(busp))
            if err != VIGEM_ERROR_NONE:
                self._api.vigem_free(busp)
                raise RuntimeError(f"ViGEmBus indisponivel (erro 0x{err:08X}).")
            self._busp = int(busp)
            return self._api, self._busp

    def is_bus_ready(self) -> bool:
        try:
            self.ensure_connected()
            return True
        except Exception:
            return False


_SHARED_BUS = _SharedViGEmBus()


def is_vigem_dll_available() -> bool:
    return find_vigem_client_dll() is not None


def is_vigem_bus_ready() -> bool:
    return _SHARED_BUS.is_bus_ready()


def build_xusb_report(state: GamepadStateDTO) -> XUSB_REPORT:
    """Converte o DTO canonico de controle para `XUSB_REPORT` (Xbox 360)."""
    m = int(state.buttons_mask)
    w_btn = 0
    for bit, xbtn in (
        (GamepadButtonMask.SOUTH, XusbButton.A),
        (GamepadButtonMask.EAST, XusbButton.B),
        (GamepadButtonMask.WEST, XusbButton.X),
        (GamepadButtonMask.NORTH, XusbButton.Y),
        (GamepadButtonMask.LB, XusbButton.LEFT_SHOULDER),
        (GamepadButtonMask.RB, XusbButton.RIGHT_SHOULDER),
        (GamepadButtonMask.BACK, XusbButton.BACK),
        (GamepadButtonMask.START, XusbButton.START),
        (GamepadButtonMask.LS, XusbButton.LEFT_THUMB),
        (GamepadButtonMask.RS, XusbButton.RIGHT_THUMB),
        (GamepadButtonMask.GUIDE, XusbButton.GUIDE),
        (GamepadButtonMask.DPAD_UP, XusbButton.DPAD_UP),
        (GamepadButtonMask.DPAD_DOWN, XusbButton.DPAD_DOWN),
        (GamepadButtonMask.DPAD_LEFT, XusbButton.DPAD_LEFT),
        (GamepadButtonMask.DPAD_RIGHT, XusbButton.DPAD_RIGHT),
    ):
        if m & int(bit):
            w_btn |= int(xbtn)

    rep = XUSB_REPORT()
    rep.wButtons = w_btn & 0xFFFF
    rep.bLeftTrigger = max(0, min(255, int(state.lt_u8)))
    rep.bRightTrigger = max(0, min(255, int(state.rt_u8)))
    rep.sThumbLX = max(-32768, min(32767, int(state.lx_i16)))
    # XInput usa Y positivo para cima; protocolo canonico usa Y negativo para cima
    rep.sThumbLY = max(-32768, min(32767, -int(state.ly_i16)))
    rep.sThumbRX = max(-32768, min(32767, int(state.rx_i16)))
    rep.sThumbRY = max(-32768, min(32767, -int(state.ry_i16)))
    return rep


def build_ds4_report(state: GamepadStateDTO) -> DS4_REPORT:
    """Converte o DTO canonico de controle para `DS4_REPORT` (Sony DualShock 4)."""
    m = int(state.buttons_mask)
    w_btn = 0
    for bit, dbtn in (
        (GamepadButtonMask.SOUTH, Ds4Button.CROSS),
        (GamepadButtonMask.EAST, Ds4Button.CIRCLE),
        (GamepadButtonMask.WEST, Ds4Button.SQUARE),
        (GamepadButtonMask.NORTH, Ds4Button.TRIANGLE),
        (GamepadButtonMask.LB, Ds4Button.SHOULDER_LEFT),
        (GamepadButtonMask.RB, Ds4Button.SHOULDER_RIGHT),
        (GamepadButtonMask.BACK, Ds4Button.SHARE),
        (GamepadButtonMask.START, Ds4Button.OPTIONS),
        (GamepadButtonMask.LS, Ds4Button.THUMB_LEFT),
        (GamepadButtonMask.RS, Ds4Button.THUMB_RIGHT),
    ):
        if m & int(bit):
            w_btn |= int(dbtn)

    lt_v = max(0, min(255, int(state.lt_u8)))
    rt_v = max(0, min(255, int(state.rt_u8)))
    if lt_v > 12:
        w_btn |= int(Ds4Button.TRIGGER_LEFT)
    if rt_v > 12:
        w_btn |= int(Ds4Button.TRIGGER_RIGHT)

    up = bool(m & int(GamepadButtonMask.DPAD_UP))
    dn = bool(m & int(GamepadButtonMask.DPAD_DOWN))
    lf = bool(m & int(GamepadButtonMask.DPAD_LEFT))
    rt = bool(m & int(GamepadButtonMask.DPAD_RIGHT))
    if up and rt:
        dpad = Ds4Dpad.NORTHEAST
    elif up and lf:
        dpad = Ds4Dpad.NORTHWEST
    elif dn and rt:
        dpad = Ds4Dpad.SOUTHEAST
    elif dn and lf:
        dpad = Ds4Dpad.SOUTHWEST
    elif up:
        dpad = Ds4Dpad.NORTH
    elif dn:
        dpad = Ds4Dpad.SOUTH
    elif lf:
        dpad = Ds4Dpad.WEST
    elif rt:
        dpad = Ds4Dpad.EAST
    else:
        dpad = Ds4Dpad.NONE
    w_btn = (w_btn & ~0xF) | int(dpad)

    special = 0
    if m & int(GamepadButtonMask.GUIDE):
        special |= int(Ds4SpecialButton.PS)
    if m & int(GamepadButtonMask.TOUCHPAD_CLICK):
        special |= int(Ds4SpecialButton.TOUCHPAD)

    rep = DS4_REPORT()
    rep.bThumbLX = max(0, min(255, int(round((int(state.lx_i16) + 32768) / 257.0))))
    rep.bThumbLY = max(0, min(255, int(round((int(state.ly_i16) + 32768) / 257.0))))
    rep.bThumbRX = max(0, min(255, int(round((int(state.rx_i16) + 32768) / 257.0))))
    rep.bThumbRY = max(0, min(255, int(round((int(state.ry_i16) + 32768) / 257.0))))
    rep.wButtons = w_btn & 0xFFFF
    rep.bSpecial = special & 0xFF
    rep.bTriggerL = lt_v
    rep.bTriggerR = rt_v
    return rep


class NativeViGEmX360Device:
    """Controle Xbox 360 Virtual nativo via `ViGEmClient.dll` + retorno de Force-Feedback."""

    profile_name = "x360"

    def __init__(self, on_rumble: Callable[[int, int], None]):
        self._api, self._busp = _SHARED_BUS.ensure_connected()
        self._on_rumble = on_rumble
        self._target: Optional[int] = int(self._api.vigem_target_x360_alloc())
        if not self._target:
            raise RuntimeError("vigem_target_x360_alloc falhou.")
        err = int(self._api.vigem_target_add(self._busp, self._target))
        if err != VIGEM_ERROR_NONE:
            self._api.vigem_target_free(self._target)
            self._target = None
            raise RuntimeError(f"vigem_target_add(x360) falhou (0x{err:08X}).")

        self._cb_cfunc = None
        if hasattr(ctypes, "WINFUNCTYPE"):
            cb_type = ctypes.WINFUNCTYPE(None, c_void_p, c_void_p, c_ubyte, c_ubyte, c_ubyte, c_void_p)

            def _notif(_client, _target, large_motor: int, small_motor: int, _led: int, _user):
                try:
                    self._on_rumble(int(large_motor) * 257, int(small_motor) * 257)
                except Exception:
                    pass

            self._cb_cfunc = cb_type(_notif)
            try:
                self._api.vigem_target_x360_register_notification(self._busp, self._target, self._cb_cfunc, None)
            except Exception:
                self._cb_cfunc = None

    def apply_state(self, state: GamepadStateDTO) -> None:
        if not self._target:
            return
        rep = build_xusb_report(state)
        self._api.vigem_target_x360_update(self._busp, self._target, rep)

    def reset_neutral(self) -> None:
        self.apply_state(GamepadStateDTO(connected=True))

    def close(self) -> None:
        if not self._target:
            return
        target = self._target
        self._target = None
        try:
            self.apply_state(GamepadStateDTO(connected=True))
        except Exception:
            pass
        if self._cb_cfunc is not None:
            try:
                self._api.vigem_target_x360_unregister_notification(target)
            except Exception:
                pass
            self._cb_cfunc = None
        try:
            self._api.vigem_target_remove(self._busp, target)
        except Exception:
            pass
        try:
            self._api.vigem_target_free(target)
        except Exception:
            pass


class NativeViGEmDS4Device:
    """Controle Sony DualShock 4 Virtual nativo via `ViGEmClient.dll` + Touchpad & Rumble."""

    profile_name = "ds4"

    def __init__(self, on_rumble: Callable[[int, int], None]):
        self._api, self._busp = _SHARED_BUS.ensure_connected()
        self._on_rumble = on_rumble
        self._target: Optional[int] = int(self._api.vigem_target_ds4_alloc())
        if not self._target:
            raise RuntimeError("vigem_target_ds4_alloc falhou.")
        err = int(self._api.vigem_target_add(self._busp, self._target))
        if err != VIGEM_ERROR_NONE:
            self._api.vigem_target_free(self._target)
            self._target = None
            raise RuntimeError(f"vigem_target_add(ds4) falhou (0x{err:08X}).")

        self._cb_cfunc = None
        if hasattr(ctypes, "WINFUNCTYPE"):
            cb_type = ctypes.WINFUNCTYPE(
                None, c_void_p, c_void_p, c_ubyte, c_ubyte, DS4_LIGHTBAR_COLOR, c_void_p
            )

            def _notif(_client, _target, large_motor: int, small_motor: int, _lightbar, _user):
                try:
                    self._on_rumble(int(large_motor) * 257, int(small_motor) * 257)
                except Exception:
                    pass

            self._cb_cfunc = cb_type(_notif)
            try:
                self._api.vigem_target_ds4_register_notification(self._busp, self._target, self._cb_cfunc, None)
            except Exception:
                self._cb_cfunc = None

    def apply_state(self, state: GamepadStateDTO) -> None:
        if not self._target:
            return
        rep = build_ds4_report(state)
        self._api.vigem_target_ds4_update(self._busp, self._target, rep)

    def reset_neutral(self) -> None:
        self.apply_state(GamepadStateDTO(connected=True))

    def close(self) -> None:
        if not self._target:
            return
        target = self._target
        self._target = None
        if self._cb_cfunc is not None:
            try:
                self._api.vigem_target_ds4_unregister_notification(target)
            except Exception:
                pass
            self._cb_cfunc = None
        try:
            self._api.vigem_target_remove(self._busp, target)
        except Exception:
            pass
        try:
            self._api.vigem_target_free(target)
        except Exception:
            pass
