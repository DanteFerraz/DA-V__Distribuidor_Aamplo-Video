# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Hub Multi-Acesso de Controles Virtuais no Host (`VirtualGamepadHub`) — DA-V v5.1
Autor: Dante Ferraz (MonoTech)

Capacidades:
- Suporta ate **8 controles virtuais simultaneos** conectados a partir de 1 ou diversos acessos
  remotos diferentes (`(peer_id, local_slot) -> host_slot 0..7`);
- Selecao inteligente de perfil virtual fiel ao controle do cliente:
  - Cliente com **DualShock 4** ou **DualSense** -> instancia **DualShock 4 Virtual** (`VDS4Gamepad`
    no Windows `ViGEmBus` / Sony DualShock 4 `054c:09cc` no Linux `/dev/uinput`), preservando
    botoes PlayStation, Touchpad Click e ultrapassando o teto de 4 jogadores do XInput;
  - Cliente com **Xbox**, **Switch Pro** ou **Gamepad Generico** -> instancia **Xbox 360 Virtual**
    (`VX360Gamepad` nos primeiros 4 slots XInput, transbordando slots 5..8 para `VDS4Gamepad`);
- Captura eventos de Force-Feedback (Rumble) dos jogos em tempo real e oferece metodo direto de
  **Teste de Controle (Vibrar Cliente)** roteado com precisao ao `peer_id` correspondente.
"""

from __future__ import annotations

import logging
import os
import select
import struct
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.dav.modules.universal_input.models import (
    ControllerKind,
    GamepadButtonMask,
    GamepadSlotDTO,
    GamepadStateDTO,
    RumbleRequestDTO,
)
from src.dav.modules.universal_input.vigem_ctypes import (
    NativeViGEmDS4Device,
    NativeViGEmX360Device,
    find_vigem_bus_installer_msi,
    is_vigem_bus_ready,
    is_vigem_dll_available,
)

logger = logging.getLogger("DAV.UniversalInput.VirtualHub")

MAX_VIRTUAL_SLOTS = 8


class _BaseVirtualDevice:
    profile_name: str = "synthetic"

    def apply_state(self, state: GamepadStateDTO) -> None:
        pass

    def reset_neutral(self) -> None:
        self.apply_state(GamepadStateDTO(connected=True))

    def close(self) -> None:
        pass


class _SyntheticVirtualDevice(_BaseVirtualDevice):
    def __init__(self, profile_name: str = "synthetic_x360"):
        self.profile_name = profile_name
        self.last_state: GamepadStateDTO = GamepadStateDTO()

    def apply_state(self, state: GamepadStateDTO) -> None:
        self.last_state = state


class _WinViGEmX360Device(_BaseVirtualDevice):
    """Controle Xbox 360 Virtual no Windows via `vgamepad.VX360Gamepad` + retorno de vibracao."""

    profile_name = "x360"

    def __init__(self, on_rumble: Callable[[int, int], None]):
        import vgamepad as vg  # type: ignore

        self._vg = vg
        self._pad = vg.VX360Gamepad()
        self._on_rumble = on_rumble
        self._cb_ref = self._rumble_callback
        try:
            self._pad.register_notification(callback_function=self._cb_ref)
        except Exception:
            pass

    def _rumble_callback(self, _client, _target, large_motor: int, small_motor: int, _led_number: int, _user_data) -> None:
        try:
            self._on_rumble(int(large_motor) * 257, int(small_motor) * 257)
        except Exception:
            pass

    def apply_state(self, state: GamepadStateDTO) -> None:
        vg = self._vg
        pad = self._pad
        pad.reset()
        m = state.buttons_mask
        b = vg.XUSB_BUTTON
        for bit, xbtn in (
            (GamepadButtonMask.SOUTH, b.XUSB_GAMEPAD_A),
            (GamepadButtonMask.EAST, b.XUSB_GAMEPAD_B),
            (GamepadButtonMask.WEST, b.XUSB_GAMEPAD_X),
            (GamepadButtonMask.NORTH, b.XUSB_GAMEPAD_Y),
            (GamepadButtonMask.LB, b.XUSB_GAMEPAD_LEFT_SHOULDER),
            (GamepadButtonMask.RB, b.XUSB_GAMEPAD_RIGHT_SHOULDER),
            (GamepadButtonMask.BACK, b.XUSB_GAMEPAD_BACK),
            (GamepadButtonMask.START, b.XUSB_GAMEPAD_START),
            (GamepadButtonMask.LS, b.XUSB_GAMEPAD_LEFT_THUMB),
            (GamepadButtonMask.RS, b.XUSB_GAMEPAD_RIGHT_THUMB),
            (GamepadButtonMask.GUIDE, b.XUSB_GAMEPAD_GUIDE),
            (GamepadButtonMask.DPAD_UP, b.XUSB_GAMEPAD_DPAD_UP),
            (GamepadButtonMask.DPAD_DOWN, b.XUSB_GAMEPAD_DPAD_DOWN),
            (GamepadButtonMask.DPAD_LEFT, b.XUSB_GAMEPAD_DPAD_LEFT),
            (GamepadButtonMask.DPAD_RIGHT, b.XUSB_GAMEPAD_DPAD_RIGHT),
        ):
            if m & int(bit):
                pad.press_button(button=xbtn)

        pad.left_trigger(value=max(0, min(255, int(state.lt_u8))))
        pad.right_trigger(value=max(0, min(255, int(state.rt_u8))))
        # XInput Y positivo = cima; protocolo canonico Y negativo = cima
        pad.left_joystick(
            x_value=max(-32768, min(32767, int(state.lx_i16))),
            y_value=max(-32768, min(32767, -int(state.ly_i16))),
        )
        pad.right_joystick(
            x_value=max(-32768, min(32767, int(state.rx_i16))),
            y_value=max(-32768, min(32767, -int(state.ry_i16))),
        )
        pad.update()

    def close(self) -> None:
        try:
            self._pad.unregister_notification()
        except Exception:
            pass
        try:
            self._pad.reset()
            self._pad.update()
        except Exception:
            pass
        self._pad = None


class _WinViGEmDS4Device(_BaseVirtualDevice):
    """Controle Sony DualShock 4 Virtual no Windows via `vgamepad.VDS4Gamepad` + Touchpad & Rumble."""

    profile_name = "ds4"

    def __init__(self, on_rumble: Callable[[int, int], None]):
        import vgamepad as vg  # type: ignore

        self._vg = vg
        self._pad = vg.VDS4Gamepad()
        self._on_rumble = on_rumble
        self._cb_ref = self._rumble_callback
        try:
            self._pad.register_notification(callback_function=self._cb_ref)
        except Exception:
            pass

    def _rumble_callback(self, _client, _target, large_motor: int, small_motor: int, *_rest) -> None:
        try:
            self._on_rumble(int(large_motor) * 257, int(small_motor) * 257)
        except Exception:
            pass

    def apply_state(self, state: GamepadStateDTO) -> None:
        vg = self._vg
        pad = self._pad
        pad.reset()
        m = state.buttons_mask
        b = vg.DS4_BUTTONS
        for bit, dbtn in (
            (GamepadButtonMask.SOUTH, b.DS4_BUTTON_CROSS),
            (GamepadButtonMask.EAST, b.DS4_BUTTON_CIRCLE),
            (GamepadButtonMask.WEST, b.DS4_BUTTON_SQUARE),
            (GamepadButtonMask.NORTH, b.DS4_BUTTON_TRIANGLE),
            (GamepadButtonMask.LB, b.DS4_BUTTON_SHOULDER_LEFT),
            (GamepadButtonMask.RB, b.DS4_BUTTON_SHOULDER_RIGHT),
            (GamepadButtonMask.BACK, b.DS4_BUTTON_SHARE),
            (GamepadButtonMask.START, b.DS4_BUTTON_OPTIONS),
            (GamepadButtonMask.LS, b.DS4_BUTTON_THUMB_LEFT),
            (GamepadButtonMask.RS, b.DS4_BUTTON_THUMB_RIGHT),
        ):
            if m & int(bit):
                pad.press_button(button=dbtn)

        sb = vg.DS4_SPECIAL_BUTTONS
        if m & int(GamepadButtonMask.GUIDE):
            pad.press_special_button(special_button=sb.DS4_SPECIAL_BUTTON_PS)
        if m & int(GamepadButtonMask.TOUCHPAD_CLICK):
            pad.press_special_button(special_button=sb.DS4_SPECIAL_BUTTON_TOUCHPAD)

        up = bool(m & int(GamepadButtonMask.DPAD_UP))
        dn = bool(m & int(GamepadButtonMask.DPAD_DOWN))
        lf = bool(m & int(GamepadButtonMask.DPAD_LEFT))
        rt = bool(m & int(GamepadButtonMask.DPAD_RIGHT))
        d = vg.DS4_DPAD_DIRECTIONS
        if up and rt:
            dpad_dir = d.DS4_BUTTON_DPAD_NORTHEAST
        elif up and lf:
            dpad_dir = d.DS4_BUTTON_DPAD_NORTHWEST
        elif dn and rt:
            dpad_dir = d.DS4_BUTTON_DPAD_SOUTHEAST
        elif dn and lf:
            dpad_dir = d.DS4_BUTTON_DPAD_SOUTHWEST
        elif up:
            dpad_dir = d.DS4_BUTTON_DPAD_NORTH
        elif dn:
            dpad_dir = d.DS4_BUTTON_DPAD_SOUTH
        elif lf:
            dpad_dir = d.DS4_BUTTON_DPAD_WEST
        elif rt:
            dpad_dir = d.DS4_BUTTON_DPAD_EAST
        else:
            dpad_dir = d.DS4_BUTTON_DPAD_NONE
        pad.directional_pad(direction=dpad_dir)

        lt_v = max(0, min(255, int(state.lt_u8)))
        rt_v = max(0, min(255, int(state.rt_u8)))
        if lt_v > 12:
            pad.press_button(button=b.DS4_BUTTON_TRIGGER_LEFT)
        if rt_v > 12:
            pad.press_button(button=b.DS4_BUTTON_TRIGGER_RIGHT)
        pad.left_trigger(value=lt_v)
        pad.right_trigger(value=rt_v)

        # DS4 eixos em [0..255] com centro em 128 (Y=0 cima, Y=255 baixo)
        lx_u8 = max(0, min(255, int(round((state.lx_i16 + 32768) / 257.0))))
        ly_u8 = max(0, min(255, int(round((state.ly_i16 + 32768) / 257.0))))
        rx_u8 = max(0, min(255, int(round((state.rx_i16 + 32768) / 257.0))))
        ry_u8 = max(0, min(255, int(round((state.ry_i16 + 32768) / 257.0))))
        pad.left_joystick(x_value=lx_u8, y_value=ly_u8)
        pad.right_joystick(x_value=rx_u8, y_value=ry_u8)
        pad.update()

    def close(self) -> None:
        try:
            self._pad.unregister_notification()
        except Exception:
            pass
        try:
            self._pad.reset()
            self._pad.update()
        except Exception:
            pass
        self._pad = None


class _LinuxUInputVirtualGamepad(_BaseVirtualDevice):
    """
    Gamepad virtual de kernel Linux (`/dev/uinput`) com suporte a Xbox 360 (`045e:028e`) e
    Sony DualShock 4 (`054c:09cc`), incluindo recepcao bidirecional de Force-Feedback (`EV_FF`).
    """

    def __init__(self, as_ds4: bool, slot_idx: int, on_rumble: Callable[[int, int], None]):
        if sys.platform == "win32":
            raise RuntimeError("Requer Linux.")
        import fcntl

        self._fcntl = fcntl
        self.profile_name = "uinput_ds4" if as_ds4 else "uinput_x360"
        self._on_rumble = on_rumble
        self._running = True
        self._effects: Dict[int, Tuple[int, int]] = {}

        uinput_path = "/dev/uinput" if os.path.exists("/dev/uinput") else "/dev/input/uinput"
        self._fd = os.open(uinput_path, os.O_RDWR | os.O_NONBLOCK)

        try:
            # UI_SET_EVBIT(EV_KEY=1, EV_ABS=3, EV_SYN=0, EV_FF=0x15)
            for evb in (0x00, 0x01, 0x03, 0x15):
                fcntl.ioctl(self._fd, 0x40045564, evb)
            # UI_SET_FFBIT(FF_RUMBLE=0x50)
            fcntl.ioctl(self._fd, 0x4004556B, 0x50)

            for kbit in (0x130, 0x131, 0x133, 0x134, 0x136, 0x137, 0x13A, 0x13B, 0x13C, 0x13D, 0x13E):
                fcntl.ioctl(self._fd, 0x40045565, kbit)
            for abit in (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x10, 0x11):
                fcntl.ioctl(self._fd, 0x40045567, abit)

            if as_ds4:
                name_b = f"Sony Interactive Entertainment Wireless Controller (DA-V #{slot_idx + 1})\x00".encode("utf-8")[:80].ljust(80, b"\x00")
                id_b = struct.pack("@HHHH", 0x03, 0x054C, 0x09CC, 0x0111)
            else:
                name_b = b"Microsoft X-Box 360 pad\x00".ljust(80, b"\x00")
                id_b = struct.pack("@HHHH", 0x03, 0x045E, 0x028E, 0x0110)

            absmax = [0] * 64
            absmin = [0] * 64
            absfuzz = [0] * 64
            absflat = [0] * 64
            for stick_ax in (0x00, 0x01, 0x03, 0x04):
                absmin[stick_ax] = -32768
                absmax[stick_ax] = 32767
                absflat[stick_ax] = 128
            absmax[0x02] = 255
            absmax[0x05] = 255
            absmin[0x10] = -1
            absmax[0x10] = 1
            absmin[0x11] = -1
            absmax[0x11] = 1

            udev = (
                name_b
                + id_b
                + struct.pack("@I", 16)  # ff_effects_max = 16
                + struct.pack("@64i", *absmax)
                + struct.pack("@64i", *absmin)
                + struct.pack("@64i", *absfuzz)
                + struct.pack("@64i", *absflat)
            )
            os.write(self._fd, udev)
            fcntl.ioctl(self._fd, 0x5501)  # UI_DEV_CREATE
            self._ff_thread = threading.Thread(target=self._ff_reader_loop, daemon=True, name=f"DAV-UInputFF-{slot_idx}")
            self._ff_thread.start()
        except Exception:
            os.close(self._fd)
            self._fd = -1
            raise

    def _ff_reader_loop(self) -> None:
        ev_s = struct.Struct("@llHHi")
        while self._running and self._fd >= 0:
            try:
                r, _, _ = select.select([self._fd], [], [], 0.10)
                if not r:
                    continue
                raw = os.read(self._fd, ev_s.size)
                if len(raw) < ev_s.size:
                    continue
                _, _, ev_t, code, val = ev_s.unpack(raw)
                if ev_t == 0x15:  # EV_FF play/stop
                    if val > 0:
                        low, high = self._effects.get(code, (42000, 30000))
                        self._on_rumble(low, high)
                    else:
                        self._on_rumble(0, 0)
                elif ev_t == 0x1A and code == 1:  # EV_UINPUT / UI_FF_UPLOAD
                    # Responde UI_BEGIN_FF_UPLOAD / UI_END_FF_UPLOAD (96 bytes em x86_64) para nao bloquear o jogo
                    up_buf = bytearray(96)
                    struct.pack_into("@I", up_buf, 0, val)
                    try:
                        self._fcntl.ioctl(self._fd, 0xC06055C8, up_buf)  # UI_BEGIN_FF_UPLOAD
                        eff_id = struct.unpack_from("@h", up_buf, 10)[0]
                        low_m, high_m = struct.unpack_from("@HH", up_buf, 24)
                        self._effects[eff_id] = (low_m or 42000, high_m or 30000)
                        struct.pack_into("@i", up_buf, 4, 0)  # retval = 0
                        self._fcntl.ioctl(self._fd, 0x406055C9, up_buf)  # UI_END_FF_UPLOAD
                    except Exception:
                        pass
                elif ev_t == 0x1A and code == 2:  # UI_FF_ERASE
                    er_buf = bytearray(12)
                    struct.pack_into("@I", er_buf, 0, val)
                    try:
                        self._fcntl.ioctl(self._fd, 0xC00C55CA, er_buf)
                        struct.pack_into("@i", er_buf, 4, 0)
                        self._fcntl.ioctl(self._fd, 0x400C55CB, er_buf)
                    except Exception:
                        pass
            except Exception:
                time.sleep(0.02)

    def apply_state(self, state: GamepadStateDTO) -> None:
        if self._fd < 0:
            return
        ev_s = struct.Struct("@llHHi")
        m = state.buttons_mask
        evs = [
            (0x01, 0x130, 1 if (m & int(GamepadButtonMask.SOUTH)) else 0),
            (0x01, 0x131, 1 if (m & int(GamepadButtonMask.EAST)) else 0),
            (0x01, 0x133, 1 if (m & int(GamepadButtonMask.WEST)) else 0),
            (0x01, 0x134, 1 if (m & int(GamepadButtonMask.NORTH)) else 0),
            (0x01, 0x136, 1 if (m & int(GamepadButtonMask.LB)) else 0),
            (0x01, 0x137, 1 if (m & int(GamepadButtonMask.RB)) else 0),
            (0x01, 0x13A, 1 if (m & int(GamepadButtonMask.BACK)) else 0),
            (0x01, 0x13B, 1 if (m & int(GamepadButtonMask.START)) else 0),
            (0x01, 0x13D, 1 if (m & int(GamepadButtonMask.LS)) else 0),
            (0x01, 0x13E, 1 if (m & int(GamepadButtonMask.RS)) else 0),
            (0x01, 0x13C, 1 if (m & int(GamepadButtonMask.GUIDE)) else 0),
            (0x03, 0x00, int(state.lx_i16)),
            (0x03, 0x01, int(state.ly_i16)),
            (0x03, 0x03, int(state.rx_i16)),
            (0x03, 0x04, int(state.ry_i16)),
            (0x03, 0x02, int(state.lt_u8)),
            (0x03, 0x05, int(state.rt_u8)),
            (
                0x03,
                0x10,
                (-1 if (m & int(GamepadButtonMask.DPAD_LEFT)) else (1 if (m & int(GamepadButtonMask.DPAD_RIGHT)) else 0)),
            ),
            (
                0x03,
                0x11,
                (-1 if (m & int(GamepadButtonMask.DPAD_UP)) else (1 if (m & int(GamepadButtonMask.DPAD_DOWN)) else 0)),
            ),
            (0x00, 0x00, 0),
        ]
        buf = b"".join(ev_s.pack(0, 0, t, c, v) for t, c, v in evs)
        try:
            os.write(self._fd, buf)
        except OSError:
            pass

    def close(self) -> None:
        self._running = False
        if self._fd >= 0:
            try:
                self._fcntl.ioctl(self._fd, 0x5502)  # UI_DEV_DESTROY
            except Exception:
                pass
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = -1


def check_host_gamepad_driver_status() -> Dict[str, Any]:
    """Verifica disponibilidade do driver virtual (`ViGEmBus` no Windows / `/dev/uinput` no Linux)."""
    if sys.platform == "win32":
        has_native_dll = is_vigem_dll_available()
        bus_ready = False
        if has_native_dll:
            bus_ready = is_vigem_bus_ready()
            if not bus_ready:
                drivers_dir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "drivers")
                bus_ready = os.path.isfile(os.path.join(drivers_dir, "ViGEmBus.sys"))
        has_vgamepad = has_native_dll
        if not has_native_dll:
            try:
                import vgamepad as vg  # type: ignore

                has_vgamepad = True
                drivers_dir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "drivers")
                bus_ready = os.path.isfile(os.path.join(drivers_dir, "ViGEmBus.sys"))
                if not bus_ready:
                    try:
                        pad = vg.VX360Gamepad()
                        pad.reset()
                        del pad
                        bus_ready = True
                    except Exception:
                        bus_ready = False
            except Exception:
                has_vgamepad = False
        return {
            "platform": "win32",
            "driver_name": "Nefarius ViGEmBus",
            "python_lib_installed": bool(has_vgamepad),
            "driver_ready": bool(has_vgamepad and bus_ready),
        }

    uinput_ok = any(os.path.exists(p) and os.access(p, os.W_OK) for p in ("/dev/uinput", "/dev/input/uinput"))
    return {
        "platform": "linux",
        "driver_name": "Linux Kernel /dev/uinput",
        "python_lib_installed": True,
        "driver_ready": uinput_ok,
    }


def install_vigembus_driver_win32() -> Tuple[bool, str]:
    """Aciona instalacao assistida do driver ViGEmBus via MSI offline embutido ou fallback winget + UAC."""
    if sys.platform != "win32":
        return False, "Instalador ViGEmBus aplica-se apenas ao Windows."
    try:
        import ctypes

        msi_path = find_vigem_bus_installer_msi()
        if msi_path is not None and msi_path.is_file():
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", "msiexec.exe", f'/i "{msi_path}" /qb', None, 1
            )
            if int(ret) <= 32:
                return False, f"Autorizacao UAC recusada (codigo={ret})."
            return True, "Instalador offline ViGEmBus (MSI) iniciado via UAC."

        cmd_args = '/c winget install --id Nefarius.ViGEmBus --exact --accept-package-agreements --accept-source-agreements'
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", cmd_args, None, 1)
        if int(ret) <= 32:
            return False, f"Autorizacao UAC recusada (codigo={ret})."
        return True, "Instalador oficial Nefarius.ViGEmBus iniciado via UAC."
    except Exception as exc:
        return False, f"Falha ao iniciar instalacao do ViGEmBus: {exc}"


class VirtualGamepadHub:
    """
    Gerenciador central de ate 8 Controles Virtuais no Host:
    - Aloca slots para diversos controles vindos de 1..4 acessos remotos simultaneos;
    - Encaminha vibracoes geradas pelos jogos e pelo botao **Testar Controle** ao cliente correto.
    """

    def __init__(
        self,
        on_rumble_to_peer: Optional[Callable[[str, bytes], None]] = None,
        on_roster_changed: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
        force_synthetic: bool = False,
    ):
        self._on_rumble_to_peer = on_rumble_to_peer
        self._on_roster_changed = on_roster_changed
        self._force_synthetic = bool(force_synthetic or os.environ.get("DAV_HEADLESS_SYNTHETIC") == "1")
        self._lock = threading.Lock()
        # (peer_id, local_slot) -> host_slot
        self._key_to_slot: Dict[Tuple[str, int], int] = {}
        # host_slot -> dict(peer_id, local_slot, device, meta: GamepadSlotDTO, last_rumble_mono)
        self._slots: Dict[int, Dict[str, Any]] = {}
        self._req_seq = 0
        self._last_roster_emit = 0.0

    def _count_x360_locked(self) -> int:
        return sum(1 for info in self._slots.values() if info["device"].profile_name == "x360")

    def _create_virtual_device_locked(
        self,
        host_slot: int,
        peer_id: str,
        local_slot: int,
        kind: ControllerKind,
    ) -> _BaseVirtualDevice:
        want_ds4 = kind in (ControllerKind.DUALSHOCK4, ControllerKind.DUALSENSE) or self._count_x360_locked() >= 4

        def _game_rumble_cb(low_u16: int, high_u16: int) -> None:
            self._handle_game_ff(host_slot, peer_id, local_slot, low_u16, high_u16)

        if self._force_synthetic:
            return _SyntheticVirtualDevice(profile_name="synthetic_ds4" if want_ds4 else "synthetic_x360")

        if sys.platform == "win32":
            try:
                if want_ds4:
                    return NativeViGEmDS4Device(on_rumble=_game_rumble_cb)
                return NativeViGEmX360Device(on_rumble=_game_rumble_cb)
            except Exception as native_exc:
                try:
                    if want_ds4:
                        return _WinViGEmDS4Device(on_rumble=_game_rumble_cb)
                    return _WinViGEmX360Device(on_rumble=_game_rumble_cb)
                except Exception as vg_exc:
                    logger.warning(
                        f"[GamepadHub] ViGEmBus indisponivel (nativo={native_exc}; vgamepad={vg_exc}); "
                        "mantendo slot em modo diagnostico."
                    )
                    return _SyntheticVirtualDevice(profile_name="diag_sem_vigem")

        try:
            return _LinuxUInputVirtualGamepad(as_ds4=want_ds4, slot_idx=host_slot, on_rumble=_game_rumble_cb)
        except Exception as exc:
            logger.warning(f"[GamepadHub] /dev/uinput sem permissao ({exc}); autorize Polkit Admin.")
            return _SyntheticVirtualDevice(profile_name="diag_sem_uinput")

    def _handle_game_ff(self, host_slot: int, peer_id: str, local_slot: int, low_u16: int, high_u16: int) -> None:
        if self._on_rumble_to_peer is None:
            return
        now = time.monotonic()
        with self._lock:
            entry = self._slots.get(host_slot)
            if entry is None:
                return
            if (low_u16 > 0 or high_u16 > 0) and (now - entry["last_rumble_mono"]) < 0.025:
                return
            entry["last_rumble_mono"] = now
            self._req_seq += 1
            req_id = self._req_seq

        dur = 220 if (low_u16 > 0 or high_u16 > 0) else 10
        dto = RumbleRequestDTO(
            local_slot=local_slot,
            is_test_pulse=False,
            low_freq_u16=low_u16,
            high_freq_u16=high_u16,
            duration_ms=dur,
            request_id=req_id,
        )
        self._on_rumble_to_peer(peer_id, dto.pack())

    def handle_gamepad_state(self, peer_id: str, state: GamepadStateDTO) -> bool:
        key = (str(peer_id), int(state.local_slot))
        roster_changed = False
        should_emit_live = False

        with self._lock:
            if not state.connected:
                slot = self._key_to_slot.pop(key, None)
                if slot is not None:
                    entry = self._slots.pop(slot, None)
                    if entry:
                        entry["device"].close()
                    roster_changed = True
            else:
                slot = self._key_to_slot.get(key)
                if slot is None:
                    slot = next((s for s in range(MAX_VIRTUAL_SLOTS) if s not in self._slots), None)
                    if slot is None:
                        return False
                    dev = self._create_virtual_device_locked(slot, str(peer_id), int(state.local_slot), state.kind)
                    meta = GamepadSlotDTO(
                        host_slot=slot,
                        peer_id=str(peer_id),
                        local_slot=int(state.local_slot),
                        kind=state.kind,
                        emulated_profile=dev.profile_name,
                        device_name=state.device_name or state.kind.display_label,
                        connected=True,
                        buttons_mask=state.buttons_mask,
                        lt_u8=state.lt_u8,
                        rt_u8=state.rt_u8,
                        lx_i16=state.lx_i16,
                        ly_i16=state.ly_i16,
                        rx_i16=state.rx_i16,
                        ry_i16=state.ry_i16,
                    )
                    self._key_to_slot[key] = slot
                    self._slots[slot] = {
                        "peer_id": str(peer_id),
                        "local_slot": int(state.local_slot),
                        "device": dev,
                        "meta": meta,
                        "last_rumble_mono": 0.0,
                    }
                    roster_changed = True
                else:
                    entry = self._slots[slot]
                    old_meta: GamepadSlotDTO = entry["meta"]
                    entry["meta"] = GamepadSlotDTO(
                        host_slot=slot,
                        peer_id=str(peer_id),
                        local_slot=int(state.local_slot),
                        kind=state.kind,
                        emulated_profile=entry["device"].profile_name,
                        device_name=state.device_name or old_meta.device_name,
                        connected=True,
                        buttons_mask=state.buttons_mask,
                        lt_u8=state.lt_u8,
                        rt_u8=state.rt_u8,
                        lx_i16=state.lx_i16,
                        ly_i16=state.ly_i16,
                        rx_i16=state.rx_i16,
                        ry_i16=state.ry_i16,
                    )
                self._slots[slot]["device"].apply_state(state)

            now = time.monotonic()
            if roster_changed or (now - self._last_roster_emit) >= 0.08:
                self._last_roster_emit = now
                should_emit_live = True
                snap = [e["meta"].to_dict() for _, e in sorted(self._slots.items())]
            else:
                snap = []

        if should_emit_live and self._on_roster_changed is not None:
            try:
                self._on_roster_changed(snap)
            except Exception:
                pass
        return True

    def trigger_test_rumble(
        self,
        host_slot: Optional[int] = None,
        low_u16: int = 52000,
        high_u16: int = 38000,
        duration_ms: int = 500,
    ) -> List[Tuple[str, bytes]]:
        """
        Gera comando(s) `RumbleRequestDTO` para fazer vibrar o controle fisico do cliente remoto:
        - Se `host_slot` for informado, vibra exatamente o controle daquele slot;
        - Se `host_slot is None`, envia pulso de teste para todos os controles/clientes conectados
          (ou broadcast `local_slot=0xFF` para cada peer conectado mesmo antes do primeiro botao pressionado!).
        """
        dispatches: List[Tuple[str, bytes]] = []
        with self._lock:
            if host_slot is not None:
                entry = self._slots.get(int(host_slot))
                if entry is not None:
                    self._req_seq += 1
                    req = RumbleRequestDTO(
                        local_slot=entry["local_slot"],
                        is_test_pulse=True,
                        low_freq_u16=low_u16,
                        high_freq_u16=high_u16,
                        duration_ms=duration_ms,
                        request_id=self._req_seq,
                    )
                    dispatches.append((entry["peer_id"], req.pack()))
            else:
                if self._slots:
                    for _, entry in sorted(self._slots.items()):
                        self._req_seq += 1
                        req = RumbleRequestDTO(
                            local_slot=entry["local_slot"],
                            is_test_pulse=True,
                            low_freq_u16=low_u16,
                            high_freq_u16=high_u16,
                            duration_ms=duration_ms,
                            request_id=self._req_seq,
                        )
                        dispatches.append((entry["peer_id"], req.pack()))

        if self._on_rumble_to_peer is not None:
            for pid, raw in dispatches:
                self._on_rumble_to_peer(pid, raw)
        return dispatches

    def get_roster_snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [e["meta"].to_dict() for _, e in sorted(self._slots.items())]

    def remove_peer(self, peer_id: str) -> None:
        removed = False
        with self._lock:
            keys = [k for k in self._key_to_slot if k[0] == str(peer_id)]
            for k in keys:
                sl = self._key_to_slot.pop(k, None)
                if sl is not None:
                    entry = self._slots.pop(sl, None)
                    if entry:
                        entry["device"].close()
                    removed = True
            snap = [e["meta"].to_dict() for _, e in sorted(self._slots.items())]
        if removed and self._on_roster_changed is not None:
            try:
                self._on_roster_changed(snap)
            except Exception:
                pass

    def release_all_neutral(self) -> None:
        with self._lock:
            for entry in self._slots.values():
                entry["device"].reset_neutral()

    def close(self) -> None:
        with self._lock:
            for entry in self._slots.values():
                entry["device"].close()
            self._slots.clear()
            self._key_to_slot.clear()
