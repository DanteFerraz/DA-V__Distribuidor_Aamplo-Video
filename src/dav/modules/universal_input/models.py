# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Modelos de Dominio Imutaveis e DTOs Binarios da Fatia `universal_input` — DA-V v5.1
Autor: Dante Ferraz (MonoTech)

Define os contratos de dados puros (isentos de acoplamento com UI/PySide6) para:
- Traducao semantica fiel ao teclado do cliente conectado (`ClientKeyboardProfileDTO`, `UniversalKeyActionDTO`);
- Estado universal normalizado de controles (`GamepadStateDTO`: DualShock 4, DualSense, Xbox, Switch Pro e Genericos);
- Comandos bidirecionais de vibracao Force-Feedback e diagnostico (`RumbleRequestDTO`, `RumbleAckDTO`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, IntFlag
import json
import struct
import time
from typing import Any, Dict, Optional, Tuple


class ControllerKind(IntEnum):
    """Familia fisica do controle detectado no cliente."""

    GENERIC = 0
    XBOX = 1
    DUALSHOCK4 = 2
    DUALSENSE = 3
    SWITCH_PRO = 4

    @property
    def display_label(self) -> str:
        labels = {
            ControllerKind.GENERIC: "Gamepad Generico (HID/DirectInput)",
            ControllerKind.XBOX: "Xbox Wireless / XInput",
            ControllerKind.DUALSHOCK4: "PlayStation DualShock 4",
            ControllerKind.DUALSENSE: "PlayStation DualSense (PS5)",
            ControllerKind.SWITCH_PRO: "Nintendo Switch Pro",
        }
        return labels.get(self, "Gamepad Universal")


class GamepadButtonMask(IntFlag):
    """Mascara canonica de 16 bits unificando Xbox, PlayStation (DS4/DualSense) e DirectInput."""

    NONE = 0x0000
    SOUTH = 0x0001           # Xbox A | PlayStation Cross (X)
    EAST = 0x0002            # Xbox B | PlayStation Circle (O)
    WEST = 0x0004            # Xbox X | PlayStation Square ([])
    NORTH = 0x0008           # Xbox Y | PlayStation Triangle (/\)
    LB = 0x0010              # L1 / Left Bumper
    RB = 0x0020              # R1 / Right Bumper
    BACK = 0x0040            # View / Share / Create / Select
    START = 0x0080           # Menu / Options / Start
    LS = 0x0100              # L3 (Left Stick Click)
    RS = 0x0200              # R3 (Right Stick Click)
    GUIDE = 0x0400           # Xbox Guide / PS Button / Home
    TOUCHPAD_CLICK = 0x0800  # DualShock 4 & DualSense Touchpad Click / Misc
    DPAD_UP = 0x1000
    DPAD_DOWN = 0x2000
    DPAD_LEFT = 0x4000
    DPAD_RIGHT = 0x8000


_STICK_PAIR_STRUCT = struct.Struct("!hh")
_RUMBLE_STRUCT = struct.Struct("!BBHHHIQ")  # 20 bytes


@dataclass(frozen=True, slots=True)
class ClientKeyboardProfileDTO:
    """Perfil do layout de teclado ativo na maquina do cliente conectado."""

    layout_code: str = "pt-BR"
    os_family: str = "windows"
    variant: str = "abnt2"
    hkl_hex: str = "0x00000416"

    def to_dict(self) -> Dict[str, str]:
        return {
            "layout_code": self.layout_code,
            "os_family": self.os_family,
            "variant": self.variant,
            "hkl_hex": self.hkl_hex,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClientKeyboardProfileDTO":
        return cls(
            layout_code=str(data.get("layout_code") or "pt-BR"),
            os_family=str(data.get("os_family") or "unknown"),
            variant=str(data.get("variant") or "standard"),
            hkl_hex=str(data.get("hkl_hex") or "0x0"),
        )


@dataclass(frozen=True, slots=True)
class UniversalKeyActionDTO:
    """
    Instrucao atomica gerada pelo tradutor do teclado do cliente:
    - `mode == 'hid'`: tecla fisica de acao/jogo/atalho (`hid_code`, `is_up`).
    - `mode == 'unicode'`: caractere exato resolvido pelo layout do cliente (`codepoint` UTF-32, ex: '~' = 0x7E).
    """

    mode: str  # "hid" | "unicode"
    hid_code: int = 0
    codepoint: int = 0
    is_up: bool = False
    modifiers_mask: int = 0


@dataclass(frozen=True, slots=True)
class GamepadStateDTO:
    """Estado instantaneo normalizado de um controle (empacotavel em exatos 24B no PT_INPUT)."""

    local_slot: int = 0
    kind: ControllerKind = ControllerKind.GENERIC
    connected: bool = True
    buttons_mask: int = 0
    lt_u8: int = 0
    rt_u8: int = 0
    lx_i16: int = 0
    ly_i16: int = 0
    rx_i16: int = 0
    ry_i16: int = 0
    device_name: str = ""
    client_ts_us: int = 0

    @property
    def is_neutral(self) -> bool:
        return (
            self.buttons_mask == 0
            and self.lt_u8 == 0
            and self.rt_u8 == 0
            and abs(self.lx_i16) < 256
            and abs(self.ly_i16) < 256
            and abs(self.rx_i16) < 256
            and abs(self.ry_i16) < 256
        )

    def to_packet_fields(self) -> Tuple[int, int, int, int, int, int]:
        """
        Converte para os campos `(buttons_byte, modifiers_byte, x_val, y_val, key_or_wheel, client_ts_us)`
        do `InputEventPacket` de 24 bytes (`EvType.GAMEPAD_STATE`).
        """
        slot_nibble = max(0, min(15, int(self.local_slot)))
        kind_bits = (int(self.kind) & 0x07) << 4
        conn_bit = 0x80 if self.connected else 0x00
        b_byte = conn_bit | kind_bits | slot_nibble
        m_byte = 0

        lx = max(-32768, min(32767, int(self.lx_i16)))
        ly = max(-32768, min(32767, int(self.ly_i16)))
        rx = max(-32768, min(32767, int(self.rx_i16)))
        ry = max(-32768, min(32767, int(self.ry_i16)))

        xv = struct.unpack("!i", _STICK_PAIR_STRUCT.pack(lx, ly))[0]
        yv = struct.unpack("!i", _STICK_PAIR_STRUCT.pack(rx, ry))[0]

        btns = int(self.buttons_mask) & 0xFFFF
        lt = max(0, min(255, int(self.lt_u8)))
        rt = max(0, min(255, int(self.rt_u8)))
        kw = (btns << 16) | (lt << 8) | rt
        ts = self.client_ts_us if self.client_ts_us > 0 else int(time.perf_counter_ns() // 1000)
        return (b_byte, m_byte, xv, yv, kw, ts)

    @classmethod
    def from_packet_fields(
        cls,
        buttons_byte: int,
        modifiers_byte: int,
        x_val: int,
        y_val: int,
        key_or_wheel: int,
        client_ts_us: int,
    ) -> "GamepadStateDTO":
        _ = modifiers_byte
        connected = bool(buttons_byte & 0x80)
        raw_kind = (buttons_byte >> 4) & 0x07
        try:
            kind = ControllerKind(raw_kind)
        except ValueError:
            kind = ControllerKind.GENERIC
        local_slot = buttons_byte & 0x0F

        lx, ly = _STICK_PAIR_STRUCT.unpack(struct.pack("!i", int(x_val)))
        rx, ry = _STICK_PAIR_STRUCT.unpack(struct.pack("!i", int(y_val)))

        kw = int(key_or_wheel) & 0xFFFFFFFF
        btns = (kw >> 16) & 0xFFFF
        lt = (kw >> 8) & 0xFF
        rt = kw & 0xFF
        return cls(
            local_slot=local_slot,
            kind=kind,
            connected=connected,
            buttons_mask=btns,
            lt_u8=lt,
            rt_u8=rt,
            lx_i16=lx,
            ly_i16=ly,
            rx_i16=rx,
            ry_i16=ry,
            client_ts_us=int(client_ts_us),
        )


@dataclass(frozen=True, slots=True)
class GamepadSlotDTO:
    """Metadados de um slot virtual ativo no Host (exibido no Testador de Controles)."""

    host_slot: int
    peer_id: str
    local_slot: int
    kind: ControllerKind
    emulated_profile: str  # "x360" | "ds4" | "uinput_ds4" | "uinput_x360" | "synthetic"
    device_name: str
    connected: bool = True
    buttons_mask: int = 0
    lt_u8: int = 0
    rt_u8: int = 0
    lx_i16: int = 0
    ly_i16: int = 0
    rx_i16: int = 0
    ry_i16: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "host_slot": self.host_slot,
            "peer_id": self.peer_id,
            "local_slot": self.local_slot,
            "kind": int(self.kind),
            "kind_label": self.kind.display_label,
            "emulated_profile": self.emulated_profile,
            "device_name": self.device_name or self.kind.display_label,
            "connected": self.connected,
            "buttons_mask": self.buttons_mask,
            "lt_u8": self.lt_u8,
            "rt_u8": self.rt_u8,
            "lx_i16": self.lx_i16,
            "ly_i16": self.ly_i16,
            "rx_i16": self.rx_i16,
            "ry_i16": self.ry_i16,
        }


@dataclass(frozen=True, slots=True)
class RumbleRequestDTO:
    """Pedido de vibracao bimotor enviado pelo Host ao controle fisico do cliente remoto."""

    local_slot: int = 0       # 0xFF = vibrar todos os controles conectados neste cliente
    is_test_pulse: bool = False
    low_freq_u16: int = 46000
    high_freq_u16: int = 34000
    duration_ms: int = 450
    request_id: int = 1
    sent_ts_us: int = 0

    def pack(self) -> bytes:
        ts = self.sent_ts_us if self.sent_ts_us > 0 else int(time.perf_counter_ns() // 1000)
        return _RUMBLE_STRUCT.pack(
            int(self.local_slot) & 0xFF,
            1 if self.is_test_pulse else 0,
            max(0, min(65535, int(self.low_freq_u16))),
            max(0, min(65535, int(self.high_freq_u16))),
            max(10, min(5000, int(self.duration_ms))),
            int(self.request_id) & 0xFFFFFFFF,
            int(ts) & 0xFFFFFFFFFFFFFFFF,
        )

    @classmethod
    def unpack(cls, raw: bytes) -> Optional["RumbleRequestDTO"]:
        if not raw or len(raw) < _RUMBLE_STRUCT.size:
            return None
        slot, flags, low, high, dur, req_id, ts = _RUMBLE_STRUCT.unpack(raw[: _RUMBLE_STRUCT.size])
        return cls(
            local_slot=slot,
            is_test_pulse=bool(flags & 0x01),
            low_freq_u16=low,
            high_freq_u16=high,
            duration_ms=dur,
            request_id=req_id,
            sent_ts_us=ts,
        )


@dataclass(frozen=True, slots=True)
class RumbleAckDTO:
    """Confirmacao devolvida pelo cliente apos vibrar o controle fisico."""

    local_slot: int
    ok: bool
    request_id: int
    sent_ts_us: int
    device_name: str
    backend: str = ""

    def to_json_bytes(self) -> bytes:
        return json.dumps(
            {
                "local_slot": self.local_slot,
                "ok": self.ok,
                "request_id": self.request_id,
                "sent_ts_us": self.sent_ts_us,
                "device_name": self.device_name,
                "backend": self.backend,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> Optional["RumbleAckDTO"]:
        try:
            d = json.loads(raw.decode("utf-8"))
            if not isinstance(d, dict):
                return None
            return cls(
                local_slot=int(d.get("local_slot", 0)),
                ok=bool(d.get("ok", False)),
                request_id=int(d.get("request_id", 0)),
                sent_ts_us=int(d.get("sent_ts_us", 0)),
                device_name=str(d.get("device_name", "")),
                backend=str(d.get("backend", "")),
            )
        except Exception:
            return None
