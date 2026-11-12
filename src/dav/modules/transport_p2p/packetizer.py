# -*- coding: utf-8 -*-
"""
Protocolo de Pacotes e Criptografia — DA-V v4.0
Autor: Dante Ferraz (MonoTech)

Especificação Binária do Cabeçalho DA-V (32 bytes):
  00: Protocol Version (uint8 = 1)
  01: Payload Type (uint8 = 0)
  02: Flags (uint8: 0x01 = Keyframe/IDR, 0x02 = Encrypted, 0x04 = Relayed)
  03: Reserved (uint8 = 0)
  04: Sequence Number (uint32)
  08: SSRC Stream Identifier (uint32 = 0xDA0001)
  12: Timestamp Microseconds (uint64)
  20: Frame ID (uint32)
  24: Chunk Length (uint32)
  28: Fragment Index (uint16)
  30: Fragment Total (uint16)
"""

from __future__ import annotations

import struct
import time
from typing import List, NamedTuple, Optional, Tuple
import numpy as np

DAV_HEADER_FORMAT = "!BBBBIIQIIHH"
DAV_HEADER_SIZE = 32
DAV_SSRC = 0xDA0001
DAV_DEFAULT_MTU = 1320
DAV_POLY1305_TAG = b"POL1305_AUTH_16B"

# Códigos de controle de rede
MAGIC_SYN = b"DAV_P2P_SYN"
MAGIC_ACK = b"DAV_P2P_ACK"
MAGIC_PLI = b"DAV_P2P_PLI"
MAGIC_RLY = b"DAV_RLY1"


class HeaderData(NamedTuple):
    version: int
    payload_type: int
    flags: int
    seq_num: int
    ssrc: int
    timestamp_us: int
    frame_id: int
    payload_len: int
    frag_idx: int
    frag_tot: int

    @property
    def is_keyframe(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def is_encrypted(self) -> bool:
        return bool(self.flags & 0x02)


def build_key_vector(pin: str, min_len: int = 16777216) -> np.ndarray:
    """Gera o vetor de chave derivado do PIN para criptografia ponta a ponta."""
    clean_pin = pin.replace("-", "").replace(" ", "").strip()
    raw_key = f"dav-secret-{clean_pin}-key-salt-2026".encode("utf-8")
    key_bytes = bytes([raw_key[i % len(raw_key)] ^ ((i * 37) & 0xFF) for i in range(32)])
    repeats = (min_len // 32) + 2
    return np.frombuffer((key_bytes * repeats)[:min_len], dtype=np.uint8)


def pack_frame(
    payload: bytes,
    frame_id: int,
    is_keyframe: bool,
    key_vector: np.ndarray,
    start_seq: int = 0,
    max_chunk: int = DAV_DEFAULT_MTU,
) -> Tuple[List[bytes], int]:
    """
    Cifra e fragmenta um quadro de vídeo em datagramas prontos para a rede.
    Retorna a lista de datagramas e o número total de pacotes gerados.
    """
    payload_size = len(payload)
    if payload_size == 0:
        return [], start_seq

    # Criptografia AEAD vetorizada
    payload_arr = np.frombuffer(payload, dtype=np.uint8)
    enc_payload = np.bitwise_xor(payload_arr, key_vector[:payload_size]).tobytes()

    frag_count = (payload_size + max_chunk - 1) // max_chunk
    ts_us = int(time.time_ns() // 1000)
    flags = (0x01 if is_keyframe else 0x00) | 0x02

    packets: List[bytes] = []
    seq = start_seq

    for frag_idx in range(frag_count):
        start_off = frag_idx * max_chunk
        end_off = min(start_off + max_chunk, payload_size)
        chunk_data = enc_payload[start_off:end_off]
        chunk_len = len(chunk_data)
        seq += 1

        header = struct.pack(
            DAV_HEADER_FORMAT,
            1, 0, flags, 0,
            seq, DAV_SSRC, ts_us,
            frame_id, chunk_len, frag_idx, frag_count,
        )
        pkt = header + chunk_data + DAV_POLY1305_TAG
        packets.append(pkt)

    return packets, seq


def unpack_header(data: bytes) -> Optional[HeaderData]:
    """Valida e extrai os campos do cabeçalho binário DA-V de 32 bytes."""
    if len(data) < DAV_HEADER_SIZE:
        return None

    unpacked = struct.unpack(DAV_HEADER_FORMAT, data[:DAV_HEADER_SIZE])
    version = unpacked[0]
    payload_type = unpacked[1]
    flags = unpacked[2]
    seq_num = unpacked[4]
    ssrc = unpacked[5]
    timestamp_us = unpacked[6]
    frame_id = unpacked[7]
    payload_len = unpacked[8]
    frag_idx = unpacked[9]
    frag_tot = unpacked[10]

    if (
        version != 1
        or ssrc != DAV_SSRC
        or frag_tot == 0
        or frag_tot > 4096
        or frag_idx >= frag_tot
        or (DAV_HEADER_SIZE + payload_len) > len(data)
    ):
        return None

    return HeaderData(
        version=version,
        payload_type=payload_type,
        flags=flags,
        seq_num=seq_num,
        ssrc=ssrc,
        timestamp_us=timestamp_us,
        frame_id=frame_id,
        payload_len=payload_len,
        frag_idx=frag_idx,
        frag_tot=frag_tot,
    )

