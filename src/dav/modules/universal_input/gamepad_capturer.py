# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Capturador Multi-Controle e Executor Local de Vibracao (Rumble) no Cliente — DA-V v5.1
Autor: Dante Ferraz (MonoTech)

Cascata Universal Plug-and-Play (Zero configuracao manual):
1. `_Sdl2GamepadBackend` (`pysdl2` + `pysdl2-dll`):
   - Reconhece nativamente PlayStation DualShock 4, DualSense (PS5 USB & Bluetooth com Touchpad + Rumble),
     Xbox 360/One/Series, Switch Pro e centenas de controles via `SDL_GameControllerDB`;
   - Fallback automatico `SDL_Joystick` + `SDL_Haptic` para Gamepads Genericos DirectInput/USB sem marca!
2. `_WinNativeGamepadBackend` (`xinput1_4.dll` + `winmm.dll` via `ctypes`):
   - Contingencia zero-dependencia no Windows para Xbox/XInput (com `XInputSetState` rumble) e DirectInput.
3. `_LinuxEvdevGamepadBackend` (`/dev/input/event*` + `FF_RUMBLE` ioctl):
   - Contingencia zero-dependencia no Linux com leitura nao-bloqueante e vibracao de kernel.
4. `SyntheticGamepadBackend`:
   - Dispositivo deterministico em memoria para testes automatizados e validacao de rumble E2E.
"""

from __future__ import annotations

import ctypes
import glob
import logging
import os
import struct
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from src.dav.modules.universal_input.gamepad_normalizer import (
    apply_radial_deadzone,
    classify_controller_kind,
    clamp_u8,
    normalize_generic_joystick,
    pov_hat_degrees_to_dpad_mask,
    sdl_hat_to_dpad_mask,
)
from src.dav.modules.universal_input.models import (
    ControllerKind,
    GamepadButtonMask,
    GamepadStateDTO,
)

logger = logging.getLogger("DAV.UniversalInput.Capturer")


class BaseGamepadBackend:
    """Contrato interno de backend de leitura e vibracao fisica local."""

    backend_name: str = "base"

    def poll_states(self) -> List[GamepadStateDTO]:
        return []

    def rumble(self, local_slot: int, low_u16: int, high_u16: int, duration_ms: int) -> Tuple[bool, str]:
        return False, "Backend sem suporte a vibracao"

    def close(self) -> None:
        pass


class SyntheticGamepadBackend(BaseGamepadBackend):
    """Controle sintetico controlavel programaticamente para testes unitarios e E2E."""

    backend_name = "synthetic"

    def __init__(self, initial_controllers: int = 1, kind: ControllerKind = ControllerKind.DUALSENSE):
        self._lock = threading.Lock()
        self._states: Dict[int, GamepadStateDTO] = {}
        self.rumble_log: List[Tuple[int, int, int, int]] = []
        for slot in range(max(0, int(initial_controllers))):
            self._states[slot] = GamepadStateDTO(
                local_slot=slot,
                kind=kind,
                connected=True,
                device_name=f"Synthetic {kind.display_label} #{slot + 1}",
            )

    def set_synthetic_state(self, state: GamepadStateDTO) -> None:
        with self._lock:
            self._states[state.local_slot] = state

    def poll_states(self) -> List[GamepadStateDTO]:
        with self._lock:
            return list(self._states.values())

    def rumble(self, local_slot: int, low_u16: int, high_u16: int, duration_ms: int) -> Tuple[bool, str]:
        with self._lock:
            if local_slot == 0xFF:
                if not self._states:
                    return False, "Nenhum controle sintetico conectado"
                names = []
                for sl, st in self._states.items():
                    self.rumble_log.append((sl, low_u16, high_u16, duration_ms))
                    names.append(st.device_name)
                return True, ", ".join(names)

            st = self._states.get(local_slot)
            if st is None or not st.connected:
                return False, f"Slot local {local_slot} desconectado"
            self.rumble_log.append((local_slot, low_u16, high_u16, duration_ms))
            return True, st.device_name


class _Sdl2GamepadBackend(BaseGamepadBackend):
    """Backend universal SDL2 cobrindo DualShock 4, DualSense, Xbox, Switch Pro e Genericos HID."""

    backend_name = "sdl2_universal"

    def __init__(self):
        # Permite ler controles mesmo quando o foco estiver em outra janela/overlay e habilita HIDAPI PS4/PS5 Rumble
        os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
        os.environ.setdefault("SDL_HINT_JOYSTICK_HIDAPI_PS4", "1")
        os.environ.setdefault("SDL_HINT_JOYSTICK_HIDAPI_PS4_RUMBLE", "1")
        os.environ.setdefault("SDL_HINT_JOYSTICK_HIDAPI_PS5", "1")
        os.environ.setdefault("SDL_HINT_JOYSTICK_HIDAPI_PS5_RUMBLE", "1")
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

        import sdl2  # type: ignore

        self._sdl = sdl2
        flags = sdl2.SDL_INIT_JOYSTICK | sdl2.SDL_INIT_GAMECONTROLLER | sdl2.SDL_INIT_HAPTIC
        if sdl2.SDL_InitSubSystem(flags) < 0:
            raise RuntimeError("Falha ao inicializar subsistema SDL2 GameController.")

        sdl2.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
        sdl2.SDL_SetHint(b"SDL_JOYSTICK_HIDAPI_PS4_RUMBLE", b"1")
        sdl2.SDL_SetHint(b"SDL_JOYSTICK_HIDAPI_PS5_RUMBLE", b"1")
        sdl2.SDL_GameControllerEventState(sdl2.SDL_ENABLE)
        sdl2.SDL_JoystickEventState(sdl2.SDL_ENABLE)

        self._lock = threading.Lock()
        # slot -> dict(instance_id, gc_ptr, joy_ptr, haptic_ptr, kind, name)
        self._open_slots: Dict[int, dict] = {}
        self._last_rescan = 0.0

    def _sync_devices_locked(self) -> None:
        sdl = self._sdl
        sdl.SDL_JoystickUpdate()
        sdl.SDL_GameControllerUpdate()

        # Remove desconectados
        dead_slots = []
        active_instances = set()
        for slot, info in self._open_slots.items():
            joy = info["joy_ptr"]
            if not joy or not sdl.SDL_JoystickGetAttached(joy):
                dead_slots.append(slot)
            else:
                active_instances.add(info["instance_id"])
        for sl in dead_slots:
            self._close_slot_locked(sl)

        n_joy = sdl.SDL_NumJoysticks()
        for dev_idx in range(min(16, max(0, int(n_joy)))):
            inst_id = sdl.SDL_JoystickGetDeviceInstanceID(dev_idx)
            if inst_id in active_instances:
                continue
            free_slot = next((s for s in range(8) if s not in self._open_slots), None)
            if free_slot is None:
                break

            gc_ptr = None
            joy_ptr = None
            haptic_ptr = None
            name_str = ""
            if sdl.SDL_IsGameController(dev_idx):
                gc_ptr = sdl.SDL_GameControllerOpen(dev_idx)
                if gc_ptr:
                    joy_ptr = sdl.SDL_GameControllerGetJoystick(gc_ptr)
                    raw_n = sdl.SDL_GameControllerName(gc_ptr)
                    name_str = raw_n.decode("utf-8", errors="ignore") if raw_n else ""
            if joy_ptr is None:
                joy_ptr = sdl.SDL_JoystickOpen(dev_idx)
                if joy_ptr:
                    raw_n = sdl.SDL_JoystickName(joy_ptr)
                    name_str = raw_n.decode("utf-8", errors="ignore") if raw_n else ""

            if not joy_ptr:
                continue

            vid = int(sdl.SDL_JoystickGetVendor(joy_ptr)) if hasattr(sdl, "SDL_JoystickGetVendor") else 0
            pid = int(sdl.SDL_JoystickGetProduct(joy_ptr)) if hasattr(sdl, "SDL_JoystickGetProduct") else 0
            kind = classify_controller_kind(vid, pid, name_str)

            if gc_ptr is None:
                try:
                    haptic_ptr = sdl.SDL_HapticOpenFromJoystick(joy_ptr)
                    if haptic_ptr and sdl.SDL_HapticRumbleSupported(haptic_ptr):
                        sdl.SDL_HapticRumbleInit(haptic_ptr)
                except Exception:
                    haptic_ptr = None

            self._open_slots[free_slot] = {
                "instance_id": inst_id,
                "gc_ptr": gc_ptr,
                "joy_ptr": joy_ptr,
                "haptic_ptr": haptic_ptr,
                "kind": kind,
                "vid": vid,
                "pid": pid,
                "name": name_str or kind.display_label,
            }
            active_instances.add(inst_id)

    def _close_slot_locked(self, slot: int) -> None:
        info = self._open_slots.pop(slot, None)
        if not info:
            return
        sdl = self._sdl
        if info.get("haptic_ptr"):
            try:
                sdl.SDL_HapticClose(info["haptic_ptr"])
            except Exception:
                pass
        if info.get("gc_ptr"):
            try:
                sdl.SDL_GameControllerClose(info["gc_ptr"])
            except Exception:
                pass
        elif info.get("joy_ptr"):
            try:
                sdl.SDL_JoystickClose(info["joy_ptr"])
            except Exception:
                pass

    def poll_states(self) -> List[GamepadStateDTO]:
        sdl = self._sdl
        now = time.monotonic()
        with self._lock:
            if (now - self._last_rescan) >= 0.65 or not self._open_slots:
                self._last_rescan = now
                self._sync_devices_locked()
            else:
                sdl.SDL_JoystickUpdate()
                sdl.SDL_GameControllerUpdate()

            results: List[GamepadStateDTO] = []
            for slot, info in sorted(self._open_slots.items()):
                joy = info["joy_ptr"]
                if not joy or not sdl.SDL_JoystickGetAttached(joy):
                    continue
                gc = info["gc_ptr"]
                kind: ControllerKind = info["kind"]
                dev_name: str = info["name"]

                if gc:
                    btn_map = (
                        (sdl.SDL_CONTROLLER_BUTTON_A, GamepadButtonMask.SOUTH),
                        (sdl.SDL_CONTROLLER_BUTTON_B, GamepadButtonMask.EAST),
                        (sdl.SDL_CONTROLLER_BUTTON_X, GamepadButtonMask.WEST),
                        (sdl.SDL_CONTROLLER_BUTTON_Y, GamepadButtonMask.NORTH),
                        (sdl.SDL_CONTROLLER_BUTTON_LEFTSHOULDER, GamepadButtonMask.LB),
                        (sdl.SDL_CONTROLLER_BUTTON_RIGHTSHOULDER, GamepadButtonMask.RB),
                        (sdl.SDL_CONTROLLER_BUTTON_BACK, GamepadButtonMask.BACK),
                        (sdl.SDL_CONTROLLER_BUTTON_START, GamepadButtonMask.START),
                        (sdl.SDL_CONTROLLER_BUTTON_LEFTSTICK, GamepadButtonMask.LS),
                        (sdl.SDL_CONTROLLER_BUTTON_RIGHTSTICK, GamepadButtonMask.RS),
                        (sdl.SDL_CONTROLLER_BUTTON_GUIDE, GamepadButtonMask.GUIDE),
                        (sdl.SDL_CONTROLLER_BUTTON_DPAD_UP, GamepadButtonMask.DPAD_UP),
                        (sdl.SDL_CONTROLLER_BUTTON_DPAD_DOWN, GamepadButtonMask.DPAD_DOWN),
                        (sdl.SDL_CONTROLLER_BUTTON_DPAD_LEFT, GamepadButtonMask.DPAD_LEFT),
                        (sdl.SDL_CONTROLLER_BUTTON_DPAD_RIGHT, GamepadButtonMask.DPAD_RIGHT),
                    )
                    mask = 0
                    for sdl_btn, bit in btn_map:
                        if sdl.SDL_GameControllerGetButton(gc, sdl_btn):
                            mask |= int(bit)

                    for extra_attr in ("SDL_CONTROLLER_BUTTON_TOUCHPAD", "SDL_CONTROLLER_BUTTON_MISC1"):
                        eb = getattr(sdl, extra_attr, None)
                        if eb is not None and sdl.SDL_GameControllerGetButton(gc, eb):
                            mask |= int(GamepadButtonMask.TOUCHPAD_CLICK)

                    lx_r = int(sdl.SDL_GameControllerGetAxis(gc, sdl.SDL_CONTROLLER_AXIS_LEFTX))
                    ly_r = int(sdl.SDL_GameControllerGetAxis(gc, sdl.SDL_CONTROLLER_AXIS_LEFTY))
                    rx_r = int(sdl.SDL_GameControllerGetAxis(gc, sdl.SDL_CONTROLLER_AXIS_RIGHTX))
                    ry_r = int(sdl.SDL_GameControllerGetAxis(gc, sdl.SDL_CONTROLLER_AXIS_RIGHTY))
                    lt_r = int(sdl.SDL_GameControllerGetAxis(gc, sdl.SDL_CONTROLLER_AXIS_TRIGGERLEFT))
                    rt_r = int(sdl.SDL_GameControllerGetAxis(gc, sdl.SDL_CONTROLLER_AXIS_TRIGGERRIGHT))

                    lx, ly = apply_radial_deadzone(lx_r, ly_r)
                    rx, ry = apply_radial_deadzone(rx_r, ry_r)
                    results.append(
                        GamepadStateDTO(
                            local_slot=slot,
                            kind=kind,
                            connected=True,
                            buttons_mask=mask,
                            lt_u8=clamp_u8(lt_r / 128.5),
                            rt_u8=clamp_u8(rt_r / 128.5),
                            lx_i16=lx,
                            ly_i16=ly,
                            rx_i16=rx,
                            ry_i16=ry,
                            device_name=dev_name,
                        )
                    )
                else:
                    # Gamepad Generico fora do GameControllerDB
                    n_ax = min(8, max(0, int(sdl.SDL_JoystickNumAxes(joy))))
                    axes = [int(sdl.SDL_JoystickGetAxis(joy, i)) for i in range(n_ax)]
                    n_bt = min(20, max(0, int(sdl.SDL_JoystickNumButtons(joy))))
                    btns = [bool(sdl.SDL_JoystickGetButton(joy, i)) for i in range(n_bt)]
                    hat_mask = 0
                    if int(sdl.SDL_JoystickNumHats(joy)) > 0:
                        hat_mask = sdl_hat_to_dpad_mask(int(sdl.SDL_JoystickGetHat(joy, 0)))
                    results.append(
                        normalize_generic_joystick(
                            local_slot=slot,
                            axes_i16=axes,
                            buttons_pressed=btns,
                            hat_dpad_mask=hat_mask,
                            vendor_id=info["vid"],
                            product_id=info["pid"],
                            device_name=dev_name,
                        )
                    )
            return results

    def _rumble_single_locked(self, slot: int, low_u16: int, high_u16: int, duration_ms: int) -> Tuple[bool, str]:
        info = self._open_slots.get(slot)
        if not info:
            return False, f"Slot {slot + 1} desconectado"
        sdl = self._sdl
        gc = info.get("gc_ptr")
        if gc and hasattr(sdl, "SDL_GameControllerRumble"):
            rc = sdl.SDL_GameControllerRumble(gc, int(low_u16), int(high_u16), int(duration_ms))
            if rc == 0:
                return True, info["name"]
        joy = info.get("joy_ptr")
        if joy and hasattr(sdl, "SDL_JoystickRumble"):
            rc = sdl.SDL_JoystickRumble(joy, int(low_u16), int(high_u16), int(duration_ms))
            if rc == 0:
                return True, info["name"]
        hap = info.get("haptic_ptr")
        if hap:
            strength = max(0.15, min(1.0, max(low_u16, high_u16) / 65535.0))
            if sdl.SDL_HapticRumblePlay(hap, ctypes.c_float(strength), int(duration_ms)) == 0:
                return True, info["name"]
        return False, f"{info['name']} (sem motor haptico exposto)"

    def rumble(self, local_slot: int, low_u16: int, high_u16: int, duration_ms: int) -> Tuple[bool, str]:
        with self._lock:
            self._sync_devices_locked()
            if local_slot == 0xFF:
                if not self._open_slots:
                    return False, "Nenhum controle conectado no cliente"
                ok_names = []
                for sl in sorted(self._open_slots):
                    ok, nm = self._rumble_single_locked(sl, low_u16, high_u16, duration_ms)
                    if ok:
                        ok_names.append(nm)
                if ok_names:
                    return True, ", ".join(ok_names)
                return False, "Controles conectados nao aceitaram comando de vibracao"
            return self._rumble_single_locked(local_slot, low_u16, high_u16, duration_ms)

    def close(self) -> None:
        with self._lock:
            for sl in list(self._open_slots.keys()):
                self._close_slot_locked(sl)


class _XInputGamepadStruct(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_uint16),
        ("bLeftTrigger", ctypes.c_uint8),
        ("bRightTrigger", ctypes.c_uint8),
        ("sThumbLX", ctypes.c_int16),
        ("sThumbLY", ctypes.c_int16),
        ("sThumbRX", ctypes.c_int16),
        ("sThumbRY", ctypes.c_int16),
    ]


class _XInputStateStruct(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_uint32), ("Gamepad", _XInputGamepadStruct)]


class _XInputVibrationStruct(ctypes.Structure):
    _fields_ = [("wLeftMotorSpeed", ctypes.c_uint16), ("wRightMotorSpeed", ctypes.c_uint16)]


class _JoyInfoExStruct(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("dwXpos", ctypes.c_uint32),
        ("dwYpos", ctypes.c_uint32),
        ("dwZpos", ctypes.c_uint32),
        ("dwRpos", ctypes.c_uint32),
        ("dwUpos", ctypes.c_uint32),
        ("dwVpos", ctypes.c_uint32),
        ("dwButtons", ctypes.c_uint32),
        ("dwButtonNumber", ctypes.c_uint32),
        ("dwPOV", ctypes.c_uint32),
        ("dwReserved1", ctypes.c_uint32),
        ("dwReserved2", ctypes.c_uint32),
    ]


class _WinNativeGamepadBackend(BaseGamepadBackend):
    """Contingencia nativa Windows (XInput + WinMM DirectInput) sem exigir DLL externa."""

    backend_name = "win32_xinput_winmm"
    _XINPUT_GAMEPAD = _XInputGamepadStruct
    _XINPUT_STATE = _XInputStateStruct
    _XINPUT_VIBRATION = _XInputVibrationStruct
    _JOYINFOEX = _JoyInfoExStruct

    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("Requer Windows.")
        self._xinput = None
        for dll_name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
            try:
                self._xinput = ctypes.WinDLL(dll_name)
                break
            except Exception:
                continue
        self._winmm = ctypes.windll.winmm
        self._stop_timers: Dict[int, threading.Timer] = {}

    def poll_states(self) -> List[GamepadStateDTO]:
        states: List[GamepadStateDTO] = []
        xinput_count = 0
        if self._xinput is not None:
            for idx in range(4):
                st = self._XINPUT_STATE()
                if self._xinput.XInputGetState(idx, ctypes.byref(st)) == 0:
                    xinput_count += 1
                    gp = st.Gamepad
                    wb = int(gp.wButtons)
                    mask = 0
                    for xbit, mbit in (
                        (0x1000, GamepadButtonMask.SOUTH),
                        (0x2000, GamepadButtonMask.EAST),
                        (0x4000, GamepadButtonMask.WEST),
                        (0x8000, GamepadButtonMask.NORTH),
                        (0x0100, GamepadButtonMask.LB),
                        (0x0200, GamepadButtonMask.RB),
                        (0x0020, GamepadButtonMask.BACK),
                        (0x0010, GamepadButtonMask.START),
                        (0x0040, GamepadButtonMask.LS),
                        (0x0080, GamepadButtonMask.RS),
                        (0x0400, GamepadButtonMask.GUIDE),
                        (0x0001, GamepadButtonMask.DPAD_UP),
                        (0x0002, GamepadButtonMask.DPAD_DOWN),
                        (0x0004, GamepadButtonMask.DPAD_LEFT),
                        (0x0008, GamepadButtonMask.DPAD_RIGHT),
                    ):
                        if wb & xbit:
                            mask |= int(mbit)
                    # XInput Y positivo e para cima; protocolo canonico segue padrao SDL/USB (negativo = cima)
                    lx, ly = apply_radial_deadzone(int(gp.sThumbLX), max(-32768, min(32767, -int(gp.sThumbLY))))
                    rx, ry = apply_radial_deadzone(int(gp.sThumbRX), max(-32768, min(32767, -int(gp.sThumbRY))))
                    states.append(
                        GamepadStateDTO(
                            local_slot=idx,
                            kind=ControllerKind.XBOX,
                            connected=True,
                            buttons_mask=mask,
                            lt_u8=int(gp.bLeftTrigger),
                            rt_u8=int(gp.bRightTrigger),
                            lx_i16=lx,
                            ly_i16=ly,
                            rx_i16=rx,
                            ry_i16=ry,
                            device_name=f"Xbox / XInput Controller #{idx + 1}",
                        )
                    )

        # Se nenhum XInput ativo, verifica controles DirectInput genericos via WinMM
        if xinput_count == 0 and self._winmm is not None:
            for jid in range(4):
                ji = self._JOYINFOEX()
                ji.dwSize = ctypes.sizeof(self._JOYINFOEX)
                ji.dwFlags = 0xFF  # JOY_RETURNALL
                if self._winmm.joyGetPosEx(jid, ctypes.byref(ji)) == 0:
                    axes = [
                        int(ji.dwXpos) - 32768,
                        int(ji.dwYpos) - 32768,
                        int(ji.dwZpos) - 32768,
                        int(ji.dwRpos) - 32768,
                    ]
                    btns = [bool(ji.dwButtons & (1 << b)) for b in range(16)]
                    hat = pov_hat_degrees_to_dpad_mask(int(ji.dwPOV))
                    states.append(
                        normalize_generic_joystick(
                            local_slot=jid,
                            axes_i16=axes,
                            buttons_pressed=btns,
                            hat_dpad_mask=hat,
                            device_name=f"DirectInput Gamepad #{jid + 1}",
                        )
                    )
        return states

    def _set_xinput_vib(self, slot: int, low_u16: int, high_u16: int) -> bool:
        if self._xinput is None or not (0 <= slot < 4):
            return False
        vib = self._XINPUT_VIBRATION(int(low_u16) & 0xFFFF, int(high_u16) & 0xFFFF)
        return self._xinput.XInputSetState(slot, ctypes.byref(vib)) == 0

    def rumble(self, local_slot: int, low_u16: int, high_u16: int, duration_ms: int) -> Tuple[bool, str]:
        targets = [0, 1, 2, 3] if local_slot == 0xFF else [local_slot]
        vibrated = []
        for sl in targets:
            if self._set_xinput_vib(sl, low_u16, high_u16):
                vibrated.append(f"XInput #{sl + 1}")
                old_t = self._stop_timers.pop(sl, None)
                if old_t:
                    old_t.cancel()
                t = threading.Timer(max(0.05, duration_ms / 1000.0), self._set_xinput_vib, args=(sl, 0, 0))
                t.daemon = True
                t.start()
                self._stop_timers[sl] = t
        if vibrated:
            return True, ", ".join(vibrated)
        return False, "Nenhum controle XInput ativo no slot solicitado"

    def close(self) -> None:
        for sl, t in list(self._stop_timers.items()):
            t.cancel()
            self._set_xinput_vib(sl, 0, 0)
        self._stop_timers.clear()


class _LinuxEvdevGamepadBackend(BaseGamepadBackend):
    """Contingencia Linux direta via `/dev/input/event*` com suporte a `FF_RUMBLE`."""

    backend_name = "linux_evdev"

    def __init__(self):
        if sys.platform == "win32":
            raise RuntimeError("Requer Linux.")
        import fcntl

        self._fcntl = fcntl
        self._fds: Dict[int, dict] = {}
        self._last_scan = 0.0

    def _scan_devices(self) -> None:
        for sl, info in list(self._fds.items()):
            if not os.path.exists(info["path"]):
                try:
                    os.close(info["fd"])
                except Exception:
                    pass
                del self._fds[sl]

        known_paths = {info["path"] for info in self._fds.values()}
        for path in sorted(glob.glob("/dev/input/event*")):
            if path in known_paths or len(self._fds) >= 8:
                continue
            try:
                fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
            except OSError:
                try:
                    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                except OSError:
                    continue
            # Verifica nome via EVIOCGNAME(256) = 0x81004506
            try:
                buf = bytearray(256)
                self._fcntl.ioctl(fd, 0x81004506, buf)
                name = bytes(buf).split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
            except Exception:
                name = ""
            low = name.lower()
            if not any(
                kw in low
                for kw in ("controller", "gamepad", "joystick", "xbox", "dualshock", "dualsense", "wireless", "pad", "8bitdo")
            ) or "da-v" in low or "motion sensors" in low or "touchpad" in low:
                os.close(fd)
                continue

            free_sl = next(s for s in range(8) if s not in self._fds)
            self._fds[free_sl] = {
                "fd": fd,
                "path": path,
                "name": name or f"Linux Gamepad #{free_sl + 1}",
                "kind": classify_controller_kind(0, 0, name),
                "btns": 0,
                "lt": 0,
                "rt": 0,
                "lx": 0,
                "ly": 0,
                "rx": 0,
                "ry": 0,
                "ff_id": -1,
            }

    def poll_states(self) -> List[GamepadStateDTO]:
        now = time.monotonic()
        if (now - self._last_scan) >= 1.0 or not self._fds:
            self._last_scan = now
            self._scan_devices()

        ev_struct = struct.Struct("@llHHi")
        ev_sz = ev_struct.size
        out: List[GamepadStateDTO] = []

        for sl, info in sorted(self._fds.items()):
            fd = info["fd"]
            while True:
                try:
                    raw = os.read(fd, ev_sz * 16)
                except (BlockingIOError, OSError):
                    break
                if not raw:
                    break
                for off in range(0, (len(raw) // ev_sz) * ev_sz, ev_sz):
                    _, _, ev_t, code, val = ev_struct.unpack_from(raw, off)
                    if ev_t == 0x01:  # EV_KEY
                        bmap = {
                            0x130: GamepadButtonMask.SOUTH,
                            0x131: GamepadButtonMask.EAST,
                            0x133: GamepadButtonMask.WEST,
                            0x134: GamepadButtonMask.NORTH,
                            0x136: GamepadButtonMask.LB,
                            0x137: GamepadButtonMask.RB,
                            0x13A: GamepadButtonMask.BACK,
                            0x13B: GamepadButtonMask.START,
                            0x13D: GamepadButtonMask.LS,
                            0x13E: GamepadButtonMask.RS,
                            0x13C: GamepadButtonMask.GUIDE,
                        }
                        bit = bmap.get(code)
                        if bit is not None:
                            if val:
                                info["btns"] |= int(bit)
                            else:
                                info["btns"] &= ~int(bit)
                    elif ev_t == 0x03:  # EV_ABS
                        if code == 0x00:
                            info["lx"] = val
                        elif code == 0x01:
                            info["ly"] = val
                        elif code == 0x03:
                            info["rx"] = val
                        elif code == 0x04:
                            info["ry"] = val
                        elif code == 0x02:
                            info["lt"] = clamp_u8(val)
                        elif code == 0x05:
                            info["rt"] = clamp_u8(val)
                        elif code == 0x10:  # HAT0X
                            info["btns"] &= ~int(GamepadButtonMask.DPAD_LEFT | GamepadButtonMask.DPAD_RIGHT)
                            if val < 0:
                                info["btns"] |= int(GamepadButtonMask.DPAD_LEFT)
                            elif val > 0:
                                info["btns"] |= int(GamepadButtonMask.DPAD_RIGHT)
                        elif code == 0x11:  # HAT0Y
                            info["btns"] &= ~int(GamepadButtonMask.DPAD_UP | GamepadButtonMask.DPAD_DOWN)
                            if val < 0:
                                info["btns"] |= int(GamepadButtonMask.DPAD_UP)
                            elif val > 0:
                                info["btns"] |= int(GamepadButtonMask.DPAD_DOWN)

            lx, ly = apply_radial_deadzone(info["lx"], info["ly"])
            rx, ry = apply_radial_deadzone(info["rx"], info["ry"])
            out.append(
                GamepadStateDTO(
                    local_slot=sl,
                    kind=info["kind"],
                    connected=True,
                    buttons_mask=info["btns"],
                    lt_u8=info["lt"],
                    rt_u8=info["rt"],
                    lx_i16=lx,
                    ly_i16=ly,
                    rx_i16=rx,
                    ry_i16=ry,
                    device_name=info["name"],
                )
            )
        return out

    def rumble(self, local_slot: int, low_u16: int, high_u16: int, duration_ms: int) -> Tuple[bool, str]:
        targets = list(self._fds.keys()) if local_slot == 0xFF else ([local_slot] if local_slot in self._fds else [])
        if not targets:
            return False, "Nenhum gamepad evdev ativo"
        ev_struct = struct.Struct("@llHHi")
        ok_names = []
        for sl in targets:
            info = self._fds[sl]
            try:
                # struct ff_effect para FF_RUMBLE (0x50) em x86_64 = 48 bytes
                eff = bytearray(48)
                struct.pack_into("@HhHHHHHH", eff, 0, 0x50, int(info["ff_id"]), 0, 0, 0, int(duration_ms), 0, 0)
                struct.pack_into("@HH", eff, 16, int(low_u16) & 0xFFFF, int(high_u16) & 0xFFFF)
                self._fcntl.ioctl(info["fd"], 0x40304580, eff)  # EVIOCSFF
                eff_id = struct.unpack_from("@h", eff, 2)[0]
                info["ff_id"] = eff_id
                os.write(info["fd"], ev_struct.pack(0, 0, 0x15, eff_id, 1))
                ok_names.append(info["name"])
            except Exception:
                continue
        if ok_names:
            return True, ", ".join(ok_names)
        return False, "Permissao de escrita insuficiente em /dev/input/event* para vibrar"

    def close(self) -> None:
        for info in self._fds.values():
            try:
                os.close(info["fd"])
            except Exception:
                pass
        self._fds.clear()


class UniversalGamepadCapturer:
    """
    Orquestrador de captura continua e vibracao de controles no Cliente:
    - Pode ser ativado/pausado em tempo real pelo botao `ZONE_GAMEPAD` da barra flutuante;
    - Ao pausar, envia automaticamente um pacote `connected=True` neutro (zerando botoes/eixos)
      para evitar que o personagem continue andando no Host;
    - Responde instantaneamente a comandos `rumble(...)` vindos do Host ou do Testador local.
    """

    def __init__(
        self,
        on_state_changed: Optional[Callable[[GamepadStateDTO], None]] = None,
        poll_hz: int = 125,
        prefer_synthetic: bool = False,
        backend: Optional[BaseGamepadBackend] = None,
    ):
        self._on_state = on_state_changed
        self._interval = 1.0 / float(max(30, min(250, int(poll_hz))))
        self._enabled = False
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_sent: Dict[int, Tuple[GamepadStateDTO, float]] = {}
        self._latest_snapshot: List[GamepadStateDTO] = []
        self._lock = threading.Lock()
        self.backend: BaseGamepadBackend = backend or self._init_best_backend(prefer_synthetic)

    @staticmethod
    def _init_best_backend(prefer_synthetic: bool) -> BaseGamepadBackend:
        if prefer_synthetic or os.environ.get("DAV_HEADLESS_SYNTHETIC") == "1":
            return SyntheticGamepadBackend(initial_controllers=0)
        try:
            return _Sdl2GamepadBackend()
        except Exception as sdl_exc:
            logger.debug(f"[Gamepad] SDL2 indisponivel ({sdl_exc}); usando backend nativo do SO.")
        if sys.platform == "win32":
            return _WinNativeGamepadBackend()
        return _LinuxEvdevGamepadBackend()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        val = bool(enabled)
        if val == self._enabled:
            return
        self._enabled = val
        if not val:
            # Emite estado neutro imediato para soltar botoes/analogicos no Host
            with self._lock:
                prev_slots = list(self._last_sent.keys())
                self._last_sent.clear()
            if self._on_state:
                for sl in prev_slots:
                    self._on_state(GamepadStateDTO(local_slot=sl, connected=True))

    def get_local_controllers(self) -> List[GamepadStateDTO]:
        with self._lock:
            return list(self._latest_snapshot)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="DAV-Gamepad-Client")
        self._thread.start()

    def _states_differ(self, a: GamepadStateDTO, b: GamepadStateDTO) -> bool:
        return (
            a.connected != b.connected
            or a.buttons_mask != b.buttons_mask
            or abs(a.lt_u8 - b.lt_u8) >= 2
            or abs(a.rt_u8 - b.rt_u8) >= 2
            or abs(a.lx_i16 - b.lx_i16) >= 180
            or abs(a.ly_i16 - b.ly_i16) >= 180
            or abs(a.rx_i16 - b.rx_i16) >= 180
            or abs(a.ry_i16 - b.ry_i16) >= 180
        )

    def _poll_loop(self) -> None:
        while self._running:
            t0 = time.perf_counter()
            try:
                states = self.backend.poll_states()
                with self._lock:
                    self._latest_snapshot = states

                if self._enabled and self._on_state is not None:
                    now_m = time.monotonic()
                    seen_slots = set()
                    for st in states:
                        seen_slots.add(st.local_slot)
                        prev_entry = self._last_sent.get(st.local_slot)
                        if (
                            prev_entry is None
                            or self._states_differ(st, prev_entry[0])
                            or (now_m - prev_entry[1]) >= 0.12
                        ):
                            self._last_sent[st.local_slot] = (st, now_m)
                            self._on_state(st)

                    # Notifica desconexao caso um controle local tenha sido removido do USB
                    for old_sl in list(self._last_sent.keys()):
                        if old_sl not in seen_slots:
                            del self._last_sent[old_sl]
                            self._on_state(GamepadStateDTO(local_slot=old_sl, connected=False))
            except Exception as exc:
                logger.debug(f"[Gamepad] Aviso no loop de leitura: {exc}")

            elapsed = time.perf_counter() - t0
            sleep_s = (0.040 if not self._enabled else self._interval) - elapsed
            if sleep_s > 0.001:
                time.sleep(sleep_s)

    def trigger_rumble(
        self,
        local_slot: int = 0xFF,
        low_u16: int = 46000,
        high_u16: int = 34000,
        duration_ms: int = 450,
    ) -> Tuple[bool, str]:
        return self.backend.rumble(local_slot, low_u16, high_u16, duration_ms)

    def close(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.4)
        self._thread = None
        self.backend.close()
