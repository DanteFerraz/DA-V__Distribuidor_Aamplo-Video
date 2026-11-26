# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
STUN RFC 5389 Single-Socket Dual-Stack (IPv4 0x01 + IPv6 0x02) & NAT Mapping — DA-V v5.2
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
import os
import socket
import struct
import time
from typing import Dict, List, Optional, Tuple

from src.dav.modules.transport_p2p.dualstack import (
    canonicalize_ip,
    format_sendto_addr,
    is_ipv6_address,
    sendto_dualstack,
)

logger = logging.getLogger("DAV.Transport.STUN")

STUN_BINDING_REQUEST = 0x0001
STUN_BINDING_RESPONSE = 0x0101
STUN_MAGIC_COOKIE = 0x2112A442
STUN_ATTR_MAPPED_ADDRESS = 0x0001
STUN_ATTR_XOR_MAPPED_ADDRESS = 0x0020


def parse_stun_response(data: bytes, trans_id: Optional[bytes] = None) -> Optional[Tuple[str, int]]:
    """
    Extrai (ip, porta) de um pacote STUN Binding Response (RFC 5389),
    suportando tanto IPv4 (`family == 0x01`) quanto IPv6 (`family == 0x02`, 128 bits XOR).
    """
    if len(data) < 20:
        return None
    msg_type, msg_len = struct.unpack("!HH", data[0:4])
    if msg_type != STUN_BINDING_RESPONSE:
        return None
    if trans_id is not None and data[8:20] != trans_id:
        return None

    pkt_trans_id = data[8:20]
    xor_mask_v6 = struct.pack("!I", STUN_MAGIC_COOKIE) + pkt_trans_id

    idx = 20
    end = min(20 + msg_len, len(data))

    while idx + 4 <= end:
        attr_type, attr_len = struct.unpack("!HH", data[idx : idx + 4])
        attr_data = data[idx + 4 : idx + 4 + attr_len]
        idx += 4 + ((attr_len + 3) & ~3)

        if attr_type == STUN_ATTR_XOR_MAPPED_ADDRESS and len(attr_data) >= 8:
            family = attr_data[1]
            x_port = struct.unpack("!H", attr_data[2:4])[0]
            port = x_port ^ (STUN_MAGIC_COOKIE >> 16)
            if family == 0x01 and len(attr_data) >= 8:
                x_ip = struct.unpack("!I", attr_data[4:8])[0]
                ip = socket.inet_ntop(socket.AF_INET, struct.pack("!I", x_ip ^ STUN_MAGIC_COOKIE))
                return ip, int(port)
            if family == 0x02 and len(attr_data) >= 20:
                x_bytes = attr_data[4:20]
                raw_v6 = bytes(b ^ m for b, m in zip(x_bytes, xor_mask_v6))
                ip = canonicalize_ip(socket.inet_ntop(socket.AF_INET6, raw_v6))
                return ip, int(port)

        elif attr_type == STUN_ATTR_MAPPED_ADDRESS and len(attr_data) >= 8:
            family = attr_data[1]
            port = struct.unpack("!H", attr_data[2:4])[0]
            if family == 0x01 and len(attr_data) >= 8:
                ip = socket.inet_ntop(socket.AF_INET, attr_data[4:8])
                return ip, int(port)
            if family == 0x02 and len(attr_data) >= 20:
                ip = canonicalize_ip(socket.inet_ntop(socket.AF_INET6, attr_data[4:20]))
                return ip, int(port)

    return None


# Alias privado mantido para compatibilidade com importadores internos/testes
_parse_stun_response = parse_stun_response


def _resolve_stun_target(host: str, port: int, family: int) -> Optional[str]:
    try:
        infos = socket.getaddrinfo(host, port, family, socket.SOCK_DGRAM)
        if infos:
            return canonicalize_ip(str(infos[0][4][0]))
    except OSError:
        return None
    return None


def _probe_single_stun(
    bound_sock: socket.socket,
    target_ip: str,
    target_port: int,
    timeout: float,
) -> Optional[Tuple[str, int, float]]:
    dst = format_sendto_addr(bound_sock, target_ip, target_port)
    if dst is None:
        return None
    trans_id = os.urandom(12)
    req = struct.pack("!HHI", STUN_BINDING_REQUEST, 0, STUN_MAGIC_COOKIE) + trans_id
    t0 = time.perf_counter()
    deadline = time.monotonic() + timeout
    try:
        bound_sock.sendto(req, dst)
        while time.monotonic() < deadline:
            data, _ = bound_sock.recvfrom(2048)
            if len(data) >= 20 and data[8:20] == trans_id:
                rtt = (time.perf_counter() - t0) * 1000.0
                ep = parse_stun_response(data, trans_id=trans_id)
                if ep:
                    return ep[0], ep[1], rtt
                break
    except (socket.timeout, OSError):
        return None
    return None


def discover_socket_endpoint(
    bound_sock: socket.socket,
    rendezvous_host: str = "129.148.26.150",
    stun_port: int = 19302,
    timeout: float = 0.85,
) -> Dict[str, object]:
    """
    Executa descoberta STUN RFC 5389 Dual-Stack (IPv4 + IPv6) diretamente no descritor UDP
    ja vinculado, preservando a alocacao de porta no roteador/firewall.
    """
    local_port = int(bound_sock.getsockname()[1])
    res: Dict[str, object] = {
        "local_port": local_port,
        "public_ip": None,
        "public_port": None,
        "public_ipv6": None,
        "public_ipv6_port": None,
        "nat_type": "unknown",
        "nat_symmetric": False,
        "rtt_ms": None,
    }

    targets_v4: List[Tuple[str, int]] = [
        ("stun.l.google.com", 19302),
        ("stun.cloudflare.com", 3478),
        ("stun1.l.google.com", 19302),
    ]
    targets_v6: List[Tuple[str, int]] = [
        ("stun.l.google.com", 19302),
        ("stun.cloudflare.com", 3478),
    ]

    mapped_v4: List[Tuple[str, int, float]] = []
    mapped_v6: List[Tuple[str, int, float]] = []
    old_timeout = bound_sock.gettimeout()

    try:
        bound_sock.settimeout(timeout)

        # 1. Sondas IPv4 (deteccao de NAT Cone vs Simetrico)
        for s_host, s_port in targets_v4:
            ip_target = _resolve_stun_target(s_host, s_port, socket.AF_INET)
            if not ip_target:
                continue
            hit = _probe_single_stun(bound_sock, ip_target, s_port, timeout)
            if hit:
                mapped_v4.append(hit)
            if len(mapped_v4) >= 2:
                break

        # 2. Sondas IPv6 (quando socket for AF_INET6 Dual-Stack)
        if bound_sock.family == socket.AF_INET6:
            for s_host, s_port in targets_v6:
                ip6_target = _resolve_stun_target(s_host, s_port, socket.AF_INET6)
                if not ip6_target:
                    continue
                hit6 = _probe_single_stun(bound_sock, ip6_target, s_port, min(0.65, timeout))
                if hit6 and is_ipv6_address(hit6[0]):
                    mapped_v6.append(hit6)
                    break
    finally:
        try:
            bound_sock.settimeout(old_timeout)
        except Exception:
            pass

    if mapped_v6:
        res["public_ipv6"] = mapped_v6[0][0]
        res["public_ipv6_port"] = mapped_v6[0][1]

    if mapped_v4:
        primary_ip, primary_port, primary_rtt = mapped_v4[0]
        res["public_ip"] = primary_ip
        res["public_port"] = primary_port
        res["rtt_ms"] = round(primary_rtt, 2)

        if len(mapped_v4) >= 2:
            sec_ip, sec_port, _ = mapped_v4[1]
            if sec_ip == primary_ip and sec_port == primary_port:
                res["nat_type"] = "cone"
                res["nat_symmetric"] = False
            else:
                res["nat_type"] = "symmetric"
                res["nat_symmetric"] = True
        else:
            res["nat_type"] = "cone"
    elif mapped_v6:
        # Host IPv6-Only: promove IPv6 global descoberto como endpoint publico primario
        res["public_ip"] = mapped_v6[0][0]
        res["public_port"] = mapped_v6[0][1]
        res["rtt_ms"] = round(mapped_v6[0][2], 2)
        res["nat_type"] = "ipv6-direct"
        res["nat_symmetric"] = False

    return res


def send_stun_keepalive(sock: socket.socket, target_host: str = "stun.l.google.com", target_port: int = 19302) -> None:
    """Emite ping leve STUN Dual-Stack para manter a tabela NAT/SPI aberta em Standby."""
    try:
        trans_id = os.urandom(12)
        req = struct.pack("!HHI", STUN_BINDING_REQUEST, 0, STUN_MAGIC_COOKIE) + trans_id
        sendto_dualstack(sock, req, target_host, target_port)
    except Exception:
        pass
