# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Handshake PAKE (CPace-X25519) e Criptografia Autenticada ChaCha20-Poly1305 — DA-V
Autor: Dante Ferraz (MonoTech)

Substitui a derivacao estatica direta por PIN por troca efemera autenticada por senha
(CPace sobre Curve25519 / X25519 + HKDF-SHA256 + confirmacao mutua HMAC + AEAD RFC 8439
com cabecalho de 32 bytes autenticado como AAD e janela anti-replay de 64 pacotes).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
import threading
import time
from typing import Dict, Optional, Tuple

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC_PAKE_SYN = b"DAV_P2P_SYN2"  # 12B magic + 4B tag + 1B role + 16B nonce + 32B share = 65B
MAGIC_PAKE_ACK = b"DAV_P2P_ACK2"  # + 16B confirm_mac = 81B

_CURVE25519_P = (1 << 255) - 19
_CURVE25519_A = 486662
_ALL_ZERO_32 = b"\x00" * 32


def normalize_pin_str(pin: str) -> str:
    return str(pin or "").replace("-", "").replace(" ", "").strip()


def pin_tag(pin: str) -> bytes:
    """Identificador curto nao-reversivel de 4 bytes para roteamento multi-candidato."""
    clean = normalize_pin_str(pin).encode("utf-8")
    return hashlib.sha256(b"DAV-PIN-TAG-v5|" + clean).digest()[:4]


def map_pin_to_curve25519_u(pin: str) -> bytes:
    """
    Mapeia o PIN para uma coordenada u valida no subgrupo de ordem prima do Curve25519
    (o cofactor 8 e eliminado na multiplicacao pelo escalar clamped do X25519 RFC 7748).
    """
    clean = normalize_pin_str(pin)
    for ctr in range(256):
        digest = hashlib.sha512(f"DAV-CPACE-CURVE25519-v5|{clean}|{ctr}".encode("utf-8")).digest()
        u = int.from_bytes(digest[:32], "little") & ((1 << 255) - 1)
        if u <= 1:
            continue
        rhs = (pow(u, 3, _CURVE25519_P) + _CURVE25519_A * pow(u, 2, _CURVE25519_P) + u) % _CURVE25519_P
        if pow(rhs, (_CURVE25519_P - 1) // 2, _CURVE25519_P) == 1:
            return u.to_bytes(32, "little")
    raise RuntimeError("Falha ao mapear PIN para ponto Curve25519.")


class ReplayWindow:
    """Janela deslizante anti-replay O(1) baseada em mascara de bits."""

    def __init__(self, size: int = 256):
        self._size = max(1, int(size))
        self._mask_all = (1 << self._size) - 1
        self._highest: Optional[int] = None
        self._bitmap: int = 0

    def check_and_update(self, seq_num: int) -> bool:
        if seq_num < 0:
            return False
        if self._highest is None:
            self._highest = seq_num
            self._bitmap = 1
            return True
        if seq_num > self._highest:
            shift = seq_num - self._highest
            if shift >= self._size:
                self._bitmap = 1
            else:
                self._bitmap = ((self._bitmap << shift) | 1) & self._mask_all
            self._highest = seq_num
            return True
        diff = self._highest - seq_num
        if diff >= self._size:
            return False
        bit = 1 << diff
        if self._bitmap & bit:
            return False
        self._bitmap |= bit
        return True


class PacketCipher:
    """
    Motor AEAD ChaCha20-Poly1305 (RFC 8439) com chaves direcionais derivadas via PAKE,
    nonce de 96 bits livre de colisoes (salt_12 XOR (SSRC || FrameID || SeqNum)) e
    autenticacao integral do cabecalho de 32 bytes como AAD.
    """

    def __init__(
        self,
        enc_key: bytes,
        dec_key: bytes,
        enc_salt: bytes,
        dec_salt: bytes,
        replay_window_size: int = 256,
    ):
        if len(enc_key) != 32 or len(dec_key) != 32:
            raise ValueError("As chaves AEAD devem ter exatamente 32 bytes.")
        if len(enc_salt) != 12 or len(dec_salt) != 12:
            raise ValueError("Os salts AEAD devem ter exatamente 12 bytes.")
        self._enc = ChaCha20Poly1305(enc_key)
        self._dec = ChaCha20Poly1305(dec_key)
        self._enc_s0, self._enc_s1, self._enc_s2 = struct.unpack("!III", enc_salt)
        self._dec_s0, self._dec_s1, self._dec_s2 = struct.unpack("!III", dec_salt)
        self._replays: Dict[int, ReplayWindow] = {
            0: ReplayWindow(size=replay_window_size),  # Video + FEC
            2: ReplayWindow(size=128),                 # Audio
            3: ReplayWindow(size=128),                 # Control (SQP_ACK)
            4: ReplayWindow(size=512),                 # Remote Input (250 Hz + 2x transitions)
            5: ReplayWindow(size=256),                 # Workspace Channel (ARQ / Echo / PTY)
        }
        self._replay_window_size = int(replay_window_size)
        self._lock = threading.Lock()

    def _make_enc_nonce(self, ssrc: int, frame_id: int, seq_num: int, payload_type: int = 0) -> bytes:
        domain_ssrc = (ssrc ^ ((payload_type & 0xFF) << 24)) & 0xFFFFFFFF
        return struct.pack(
            "!III",
            self._enc_s0 ^ domain_ssrc,
            self._enc_s1 ^ (frame_id & 0xFFFFFFFF),
            self._enc_s2 ^ (seq_num & 0xFFFFFFFF),
        )

    def _make_dec_nonce(self, ssrc: int, frame_id: int, seq_num: int, payload_type: int = 0) -> bytes:
        domain_ssrc = (ssrc ^ ((payload_type & 0xFF) << 24)) & 0xFFFFFFFF
        return struct.pack(
            "!III",
            self._dec_s0 ^ domain_ssrc,
            self._dec_s1 ^ (frame_id & 0xFFFFFFFF),
            self._dec_s2 ^ (seq_num & 0xFFFFFFFF),
        )

    def seal_packet(
        self,
        header_bytes: bytes,
        plaintext: bytes,
        ssrc: int,
        frame_id: int,
        seq_num: int,
    ) -> bytes:
        pt_byte = header_bytes[1] if len(header_bytes) >= 2 else 0
        nonce = self._make_enc_nonce(ssrc, frame_id, seq_num, payload_type=pt_byte)
        ct_and_tag = self._enc.encrypt(nonce, plaintext, header_bytes)
        return header_bytes + ct_and_tag

    def open_packet(
        self,
        header_bytes: bytes,
        ct_and_tag: bytes,
        ssrc: int,
        frame_id: int,
        seq_num: int,
        enforce_replay: bool = True,
    ) -> Optional[bytes]:
        pt_byte = header_bytes[1] if len(header_bytes) >= 2 else 0
        nonce = self._make_dec_nonce(ssrc, frame_id, seq_num, payload_type=pt_byte)
        try:
            plaintext = self._dec.decrypt(nonce, ct_and_tag, header_bytes)
        except Exception:
            return None

        if enforce_replay:
            stream_key = 0 if pt_byte in (0, 1) else pt_byte
            with self._lock:
                rw = self._replays.get(stream_key)
                if rw is None:
                    rw = ReplayWindow(size=self._replay_window_size)
                    self._replays[stream_key] = rw
                if not rw.check_and_update(seq_num):
                    return None
        return plaintext


class PakeSession:
    """
    Maquina de estados PAKE (CPace sobre X25519) para canal UDP Single-Socket.
    Opera em 1 RTT sobre os proprios pacotes SYN2 / ACK2 de Hole-Punching sem expor o PIN.
    """

    def __init__(self, role: str, pin: str):
        if role not in ("S", "R"):
            raise ValueError("role deve ser 'S' (Sender) ou 'R' (Receiver).")
        self.role = role
        self.pin = normalize_pin_str(pin)
        self.tag = pin_tag(self.pin)

        self._g_bytes = map_pin_to_curve25519_u(self.pin)
        self._g_pub = X25519PublicKey.from_public_bytes(self._g_bytes)
        self._priv = X25519PrivateKey.generate()
        self.local_nonce = os.urandom(16)
        self.local_share = self._priv.exchange(self._g_pub)

        self.peer_nonce: Optional[bytes] = None
        self.peer_share: Optional[bytes] = None
        self._shared_z: Optional[bytes] = None
        self._derived: Optional[dict] = None
        self.confirmed: bool = False
        self.cipher: Optional[PacketCipher] = None
        self.confirmed_at_mono: float = 0.0
        self.last_valid_rx_mono: float = 0.0
        self._lock = threading.Lock()

    def mark_valid_rx(self, now_mono: Optional[float] = None) -> None:
        """Registra trafego AEAD autenticado valido para blindar a sessao contra SYN2 espurio."""
        ts = now_mono if now_mono is not None else time.monotonic()
        with self._lock:
            self.last_valid_rx_mono = ts
            if not self.confirmed:
                self.confirmed = True
                self.confirmed_at_mono = ts

    def build_syn(self) -> bytes:
        return MAGIC_PAKE_SYN + self.tag + self.role.encode("ascii") + self.local_nonce + self.local_share

    def build_ack(self) -> Optional[bytes]:
        with self._lock:
            if not self._derived:
                return None
            my_conf = self._derived["conf_tx"] if self.role == "S" else self._derived["conf_rx"]
            return (
                MAGIC_PAKE_ACK
                + self.tag
                + self.role.encode("ascii")
                + self.local_nonce
                + self.local_share
                + my_conf
            )

    def _derive_from_peer(self, peer_role: str, peer_nonce: bytes, peer_share: bytes) -> bool:
        if peer_share == _ALL_ZERO_32 or len(peer_share) != 32 or len(peer_nonce) != 16:
            return False
        try:
            peer_pub = X25519PublicKey.from_public_bytes(peer_share)
            z = self._priv.exchange(peer_pub)
        except Exception:
            return False
        if not z or z == _ALL_ZERO_32:
            return False

        if self.role == "S":
            tx_part = self.local_nonce + self.local_share
            rx_part = peer_nonce + peer_share
        else:
            tx_part = peer_nonce + peer_share
            rx_part = self.local_nonce + self.local_share

        transcript = b"DAV-CPACE-v5|" + tx_part + rx_part + self.tag
        pin_hash = hashlib.sha256(b"DAV-PIN-IKM-v5|" + self.pin.encode("utf-8")).digest()

        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=120,
            salt=b"DAV-HKDF-SALT-v5",
            info=transcript,
        )
        okm = hkdf.derive(z + pin_hash)
        key_tx = okm[0:32]
        key_rx = okm[32:64]
        salt_tx = okm[64:76]
        salt_rx = okm[76:88]
        conf_tx = okm[88:104]
        conf_rx = okm[104:120]

        self.peer_nonce = peer_nonce
        self.peer_share = peer_share
        self._shared_z = z
        self._derived = {
            "key_tx": key_tx,
            "key_rx": key_rx,
            "salt_tx": salt_tx,
            "salt_rx": salt_rx,
            "conf_tx": conf_tx,
            "conf_rx": conf_rx,
        }
        if self.role == "S":
            self.cipher = PacketCipher(key_tx, key_rx, salt_tx, salt_rx)
        else:
            self.cipher = PacketCipher(key_rx, key_tx, salt_rx, salt_tx)
        return True

    def process_control(self, data: bytes) -> Tuple[bool, Optional[bytes], bool]:
        """
        Processa pacote MAGIC_PAKE_SYN ou MAGIC_PAKE_ACK recebido do peer.
        Retorna (valido, ack_para_responder, recem_confirmado).
        """
        if not data:
            return False, None, False

        is_syn = data.startswith(MAGIC_PAKE_SYN) and len(data) == 65
        is_ack = data.startswith(MAGIC_PAKE_ACK) and len(data) == 81
        if not is_syn and not is_ack:
            return False, None, False

        hdr_len = len(MAGIC_PAKE_SYN)
        p_tag = data[hdr_len : hdr_len + 4]
        p_role = chr(data[hdr_len + 4])
        p_nonce = data[hdr_len + 5 : hdr_len + 21]
        p_share = data[hdr_len + 21 : hdr_len + 53]
        p_conf = data[hdr_len + 53 : hdr_len + 69] if is_ack else None

        if p_tag != self.tag or p_role not in ("S", "R") or p_role == self.role:
            return False, None, False

        with self._lock:
            if self.peer_nonce != p_nonce or self.peer_share != p_share or self._derived is None:
                # Blindagem contra SYN2/ACK2 espurios durante sessao ativa confirmada (ex: polls duplicados)
                if self.confirmed and self.peer_nonce is not None:
                    now_m = time.monotonic()
                    active_anchor = max(self.last_valid_rx_mono, self.confirmed_at_mono)
                    if (now_m - active_anchor) < 4.0:
                        return False, None, False
                if not self._derive_from_peer(p_role, p_nonce, p_share):
                    return False, None, False
                self.confirmed = False

            newly_confirmed = False
            if is_ack and p_conf is not None and self._derived is not None:
                expected_peer_conf = self._derived["conf_rx"] if self.role == "S" else self._derived["conf_tx"]
                if not hmac.compare_digest(p_conf, expected_peer_conf):
                    return False, None, False
                if not self.confirmed:
                    self.confirmed = True
                    now_m = time.monotonic()
                    self.confirmed_at_mono = now_m
                    self.last_valid_rx_mono = max(self.last_valid_rx_mono, now_m)
                    newly_confirmed = True

            my_conf = self._derived["conf_tx"] if self.role == "S" else self._derived["conf_rx"]
            reply_ack = (
                MAGIC_PAKE_ACK
                + self.tag
                + self.role.encode("ascii")
                + self.local_nonce
                + self.local_share
                + my_conf
            )
            return True, reply_ack, newly_confirmed
