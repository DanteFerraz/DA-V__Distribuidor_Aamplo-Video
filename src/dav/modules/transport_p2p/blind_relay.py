# -*- coding: utf-8 -*-
"""
Blind Encrypted UDP Relay (DAV_RLY1) — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

MAGIC_RLY1 = b"DAV_RLY1"


def normalize_pin(pin: str) -> str:
    """Remove hifens e espacos do PIN para comparacao canonica."""
    return str(pin or "").replace("-", "").replace(" ", "").strip()


def wrap_relay_packet(pin: str, role: bytes, payload: bytes) -> bytes:
    """
    Encapsula o datagrama cifrado no envelope de 17 bytes para o Gateway Blind Relay.
      00..07: 'DAV_RLY1' (8 bytes)
      08..15: PIN tag normalizado (8 bytes)
      16    : 'S' (Sender) ou 'R' (Receiver)
      17..  : Payload cifrado end-to-end
    """
    clean_pin = normalize_pin(pin)
    pin_tag = clean_pin.encode("ascii", errors="ignore")[:8].ljust(8, b"\x00")
    role_b = role[:1] if role else b"S"
    return MAGIC_RLY1 + pin_tag + role_b + payload


def unwrap_relay_packet(data: bytes) -> tuple[str, bytes, bytes] | None:
    """Extrai (clean_pin, role, payload) do envelope do Blind Relay."""
    if len(data) < 17 or not data.startswith(MAGIC_RLY1):
        return None
    pin_tag = data[8:16].decode("ascii", errors="ignore").rstrip("\x00")
    role = data[16:17]
    payload = data[17:]
    return pin_tag, role, payload

