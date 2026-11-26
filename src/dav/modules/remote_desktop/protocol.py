# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Protocolo Binario de Input Sub-Milissegundo (PT_INPUT) e Canal Confiavel ARQ (PT_WORKSPACE) — DA-V v5.0
Autor: Dante Ferraz (MonoTech)

Especificacao:
1. `InputEventPacket` (24 bytes exatos, `!BBBBiiIQ`):
   - Eventos HID em tempo real (mouse absoluto/relativo, botoes, scroll, teclado, heartbeat e soltura global).
2. `WorkspaceChannel` (`!BBHII` = 12 bytes de cabecalho + payload):
   - Canal confiavel leve com retransmissao seletiva ordenada sobre UDP AEAD para sincronizacao
     de permissoes, Clipboard, transferencia P2P de arquivos e terminal persistente PTY/ConPTY,
     alem de mensagens rapidas sem bloqueio (`INPUT_ECHO` para sonda Input-to-Photon).
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from enum import IntEnum
import json
import struct
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

INPUT_STRUCT = struct.Struct("!BBBBiiIQ")
INPUT_PACKET_SIZE = INPUT_STRUCT.size  # 24 bytes
INPUT_PROTOCOL_VERSION = 1

WS_HEADER_STRUCT = struct.Struct("!BBHII")
WS_HEADER_SIZE = WS_HEADER_STRUCT.size  # 12 bytes
WS_ECHO_STRUCT = struct.Struct("!QQ")

WS_FLAG_ACK_ONLY = 0x01
WS_FLAG_RELIABLE = 0x02


class EvType(IntEnum):
    MOVE_ABS = 1
    MOVE_REL = 2
    BTN_DOWN = 3
    BTN_UP = 4
    WHEEL = 5
    KEY_DOWN = 6
    KEY_UP = 7
    HEARTBEAT = 8
    RELEASE_ALL = 9
    KEY_UNICODE = 10
    GAMEPAD_STATE = 11


class MouseBtn(IntEnum):
    NONE = 0x00
    LEFT = 0x01
    RIGHT = 0x02
    MIDDLE = 0x04
    BACK = 0x08
    FORWARD = 0x10


class KeyMod(IntEnum):
    NONE = 0x00
    SHIFT = 0x01
    CTRL = 0x02
    ALT = 0x04
    META = 0x08


class WsMsgType(IntEnum):
    ACK = 0x00
    PERM_UPDATE = 0x01
    INPUT_ECHO = 0x02
    CLIPBOARD_TEXT = 0x03
    FILE_META = 0x04
    FILE_CHUNK = 0x05
    FILE_DONE = 0x06
    SHELL_STDIN = 0x07
    SHELL_STDOUT = 0x08
    SHELL_RESIZE = 0x09
    CLIENT_INPUT_PROFILE = 0x0A
    GAMEPAD_RUMBLE = 0x0B
    GAMEPAD_RUMBLE_ACK = 0x0C
    GAMEPAD_ROSTER = 0x0D
    PLI_REQ = 0x0E


def pack_wheel_deltas(dx: int, dy: int) -> int:
    """Empacota deltas assinados horizontal e vertical (int16, int16) em uint32."""
    cx = max(-32768, min(32767, int(dx)))
    cy = max(-32768, min(32767, int(dy)))
    raw = struct.pack("!hh", cx, cy)
    return struct.unpack("!I", raw)[0]


def unpack_wheel_deltas(packed: int) -> Tuple[int, int]:
    """Extrai (dx, dy) assinados de um uint32."""
    raw = struct.pack("!I", int(packed) & 0xFFFFFFFF)
    return struct.unpack("!hh", raw)


@dataclass(slots=True)
class InputEventPacket:
    ev_type: int
    buttons_mask: int = 0
    modifiers_mask: int = 0
    x_val: int = 0
    y_val: int = 0
    key_or_wheel: int = 0
    client_ts_us: int = 0
    version: int = INPUT_PROTOCOL_VERSION

    @property
    def is_critical_transition(self) -> bool:
        return self.ev_type in (
            EvType.BTN_DOWN,
            EvType.BTN_UP,
            EvType.KEY_DOWN,
            EvType.KEY_UP,
            EvType.RELEASE_ALL,
            EvType.KEY_UNICODE,
        )

    def pack(self) -> bytes:
        ts = self.client_ts_us if self.client_ts_us > 0 else int(time.perf_counter_ns() // 1000)
        return INPUT_STRUCT.pack(
            self.version & 0xFF,
            int(self.ev_type) & 0xFF,
            int(self.buttons_mask) & 0xFF,
            int(self.modifiers_mask) & 0xFF,
            int(self.x_val),
            int(self.y_val),
            int(self.key_or_wheel) & 0xFFFFFFFF,
            int(ts) & 0xFFFFFFFFFFFFFFFF,
        )

    @classmethod
    def unpack(cls, data: bytes) -> Optional["InputEventPacket"]:
        if not data or len(data) != INPUT_PACKET_SIZE:
            return None
        ver, ev_t, btns, mods, xv, yv, kw, ts_us = INPUT_STRUCT.unpack(data)
        if ver != INPUT_PROTOCOL_VERSION:
            return None
        if ev_t < EvType.MOVE_ABS or ev_t > EvType.GAMEPAD_STATE:
            return None
        return cls(
            version=ver,
            ev_type=ev_t,
            buttons_mask=btns,
            modifiers_mask=mods,
            x_val=xv,
            y_val=yv,
            key_or_wheel=kw,
            client_ts_us=ts_us,
        )


@dataclass(slots=True)
class WorkspaceMessage:
    msg_type: int
    payload: bytes
    channel_id: int = 0
    msg_seq: int = 0
    reliable: bool = True

    def decode_json(self) -> Optional[Dict[str, Any]]:
        try:
            obj = json.loads(self.payload.decode("utf-8"))
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None


def pack_input_echo(client_ts_us: int, host_inject_us: int = 0) -> bytes:
    """Constroi frame leve nao-bloqueante WS_INPUT_ECHO (12B hdr + 16B payload = 28 bytes)."""
    eff_host = host_inject_us if host_inject_us > 0 else int(time.perf_counter_ns() // 1000)
    payload = WS_ECHO_STRUCT.pack(
        int(client_ts_us) & 0xFFFFFFFFFFFFFFFF,
        int(eff_host) & 0xFFFFFFFFFFFFFFFF,
    )
    hdr = WS_HEADER_STRUCT.pack(int(WsMsgType.INPUT_ECHO), 0, 0, 0, 0)
    return hdr + payload


def unpack_input_echo(payload: bytes) -> Optional[Tuple[int, int]]:
    if not payload or len(payload) < WS_ECHO_STRUCT.size:
        return None
    return WS_ECHO_STRUCT.unpack(payload[: WS_ECHO_STRUCT.size])


class WorkspaceChannel:
    """
    Canal ARQ seletivo leve e ordenado para mensagens de Area de Trabalho sobre UDP AEAD.
    Garante entrega sem perdas para permissoes, Clipboard, blocos de arquivo e PTY.
    """

    def __init__(self, max_window: int = 128):
        self._max_window = max(16, int(max_window))
        self._lock = threading.Lock()
        self._tx_seq: int = 0
        self._rx_expected_seq: int = 1
        self._highest_contiguous_rx: int = 0
        self._unacked: "collections.OrderedDict[int, Dict[str, Any]]" = collections.OrderedDict()
        self._rx_buffer: Dict[int, WorkspaceMessage] = {}

    @property
    def pending_unacked_count(self) -> int:
        with self._lock:
            return len(self._unacked)

    def send_unreliable(self, msg_type: int, payload: bytes = b"", channel_id: int = 0) -> bytes:
        with self._lock:
            ack_seq = self._highest_contiguous_rx
        hdr = WS_HEADER_STRUCT.pack(
            int(msg_type) & 0xFF,
            0,
            int(channel_id) & 0xFFFF,
            0,
            ack_seq & 0xFFFFFFFF,
        )
        return hdr + (payload or b"")

    def send_reliable(self, msg_type: int, payload: bytes = b"", channel_id: int = 0) -> bytes:
        body = bytes(payload or b"")
        with self._lock:
            self._tx_seq += 1
            seq = self._tx_seq
            ack_seq = self._highest_contiguous_rx
            hdr = WS_HEADER_STRUCT.pack(
                int(msg_type) & 0xFF,
                WS_FLAG_RELIABLE,
                int(channel_id) & 0xFFFF,
                seq & 0xFFFFFFFF,
                ack_seq & 0xFFFFFFFF,
            )
            frame = hdr + body
            while len(self._unacked) >= self._max_window:
                self._unacked.popitem(last=False)
            self._unacked[seq] = {
                "msg_type": int(msg_type) & 0xFF,
                "channel_id": int(channel_id) & 0xFFFF,
                "payload": body,
                "sent_mono": time.monotonic(),
                "retries": 0,
            }
            return frame

    def send_json(self, msg_type: int, data: Dict[str, Any], channel_id: int = 0) -> bytes:
        raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return self.send_reliable(msg_type, raw, channel_id=channel_id)

    def build_ack_frame(self) -> bytes:
        with self._lock:
            ack_seq = self._highest_contiguous_rx
        return WS_HEADER_STRUCT.pack(
            int(WsMsgType.ACK),
            WS_FLAG_ACK_ONLY,
            0,
            0,
            ack_seq & 0xFFFFFFFF,
        )

    def receive(self, raw_frame: bytes) -> Tuple[List[WorkspaceMessage], Optional[bytes]]:
        """
        Processa quadro PT_WORKSPACE recebido.
        Retorna `(mensagens_entregues_em_ordem, frame_ack_opcional)`.
        """
        if not raw_frame or len(raw_frame) < WS_HEADER_SIZE:
            return [], None

        msg_type, flags, channel_id, msg_seq, peer_ack_seq = WS_HEADER_STRUCT.unpack(
            raw_frame[:WS_HEADER_SIZE]
        )
        payload = raw_frame[WS_HEADER_SIZE:]

        delivered: List[WorkspaceMessage] = []
        need_ack = False

        with self._lock:
            if peer_ack_seq > 0 and self._unacked:
                acked_keys = [k for k in self._unacked if k <= peer_ack_seq]
                for k in acked_keys:
                    del self._unacked[k]

            if flags & WS_FLAG_ACK_ONLY or msg_type == WsMsgType.ACK:
                return [], None

            if not (flags & WS_FLAG_RELIABLE):
                delivered.append(
                    WorkspaceMessage(
                        msg_type=msg_type,
                        payload=payload,
                        channel_id=channel_id,
                        msg_seq=msg_seq,
                        reliable=False,
                    )
                )
                return delivered, None

            need_ack = True
            if msg_seq < self._rx_expected_seq:
                ack_frame = WS_HEADER_STRUCT.pack(
                    int(WsMsgType.ACK),
                    WS_FLAG_ACK_ONLY,
                    0,
                    0,
                    self._highest_contiguous_rx & 0xFFFFFFFF,
                )
                return [], ack_frame

            if msg_seq == self._rx_expected_seq:
                delivered.append(
                    WorkspaceMessage(
                        msg_type=msg_type,
                        payload=payload,
                        channel_id=channel_id,
                        msg_seq=msg_seq,
                        reliable=True,
                    )
                )
                self._rx_expected_seq += 1
                while self._rx_expected_seq in self._rx_buffer:
                    nxt = self._rx_buffer.pop(self._rx_expected_seq)
                    delivered.append(nxt)
                    self._rx_expected_seq += 1
                self._highest_contiguous_rx = self._rx_expected_seq - 1
            elif (msg_seq - self._rx_expected_seq) < self._max_window:
                if msg_seq not in self._rx_buffer:
                    self._rx_buffer[msg_seq] = WorkspaceMessage(
                        msg_type=msg_type,
                        payload=payload,
                        channel_id=channel_id,
                        msg_seq=msg_seq,
                        reliable=True,
                    )

            ack_frame = (
                WS_HEADER_STRUCT.pack(
                    int(WsMsgType.ACK),
                    WS_FLAG_ACK_ONLY,
                    0,
                    0,
                    self._highest_contiguous_rx & 0xFFFFFFFF,
                )
                if need_ack
                else None
            )
            return delivered, ack_frame

    def poll_retransmits(
        self,
        now_mono: Optional[float] = None,
        rto_sec: float = 0.035,
        max_retries: int = 15,
    ) -> List[bytes]:
        now = now_mono if now_mono is not None else time.monotonic()
        retransmits: List[bytes] = []
        with self._lock:
            expired: List[int] = []
            ack_seq = self._highest_contiguous_rx
            for seq, item in self._unacked.items():
                eff_rto = rto_sec * min(4.0, 1.0 + 0.35 * item["retries"])
                if (now - item["sent_mono"]) >= eff_rto:
                    if item["retries"] >= max_retries:
                        expired.append(seq)
                        continue
                    item["retries"] += 1
                    item["sent_mono"] = now
                    hdr = WS_HEADER_STRUCT.pack(
                        item["msg_type"],
                        WS_FLAG_RELIABLE,
                        item["channel_id"],
                        seq & 0xFFFFFFFF,
                        ack_seq & 0xFFFFFFFF,
                    )
                    retransmits.append(hdr + item["payload"])
            for seq in expired:
                del self._unacked[seq]
        return retransmits
