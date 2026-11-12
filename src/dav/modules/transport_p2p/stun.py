# -*- coding: utf-8 -*-
"""
STUN RFC 5389 Single-Socket & NAT Mapping — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
import os
import random
import socket
import struct
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger("DAV.Transport.STUN")

STUN_BINDING_REQUEST = 0x0001
STUN_BINDING_RESPONSE = 0x0101
STUN_MAGIC_COOKIE = 0x2112A442
STUN_ATTR_MAPPED_ADDRESS = 0x0001
STUN_ATTR_XOR_MAPPED_ADDRESS = 0x0020


def discover_socket_endpoint(
    bound_sock: socket.socket,
    rendezvous_host: str = "129.148.26.150",
    stun_port: int = 19302,
    timeout: float = 0.85,
) -> Dict[str, object]:
    """
    Executa a descoberta STUN RFC 5389 diretamente no descritor de arquivo UDP já
    vinculado, preservando a alocação de porta na tabela NAT do roteador doméstico.
    """
    local_port = bound_sock.getsockname()[1]
    res: Dict[str, object] = {
        "local_port": local_port,
        "public_ip": None,
        "public_port": None,
        "nat_type": "unknown",
        "nat_symmetric": False,
        "rtt_ms": None,
    }

    # Servidores de consulta
    targets = [
        (rendezvous_host, 8768),
        ("stun.l.google.com", 19302),
        ("stun1.l.google.com", 19302),
    ]

    mapped_endpoints = []
    old_timeout = bound_sock.gettimeout()

    try:
        bound_sock.settimeout(timeout)
        for s_host, s_port in targets:
            try:
                ip_target = socket.gethostbyname(s_host)
            except Exception:
                continue

            trans_id = os.urandom(12)
            req = struct.pack("!HHI", STUN_BINDING_REQUEST, 0, STUN_MAGIC_COOKIE) + trans_id
            t0 = time.perf_counter()

            try:
                bound_sock.sendto(req, (ip_target, s_port))
                while True:
                    data, addr = bound_sock.recvfrom(2048)
                    if len(data) >= 20 and data[8:20] == trans_id:
                        rtt = (time.perf_counter() - t0) * 1000.0
                        ep = _parse_stun_response(data)
                        if ep:
                            mapped_endpoints.append((ep[0], ep[1], rtt))
                        break
            except (socket.timeout, OSError):
                continue

            if len(mapped_endpoints) >= 2:
                break
    finally:
        bound_sock.settimeout(old_timeout)

    if mapped_endpoints:
        primary_ip, primary_port, primary_rtt = mapped_endpoints[0]
        res["public_ip"] = primary_ip
        res["public_port"] = primary_port
        res["rtt_ms"] = round(primary_rtt, 2)

        if len(mapped_endpoints) >= 2:
            sec_ip, sec_port, _ = mapped_endpoints[1]
            if sec_ip == primary_ip and sec_port == primary_port:
                res["nat_type"] = "cone"
                res["nat_symmetric"] = False
            else:
                res["nat_type"] = "symmetric"
                res["nat_symmetric"] = True
        else:
            res["nat_type"] = "cone"

    return res


def send_stun_keepalive(sock: socket.socket, target_host: str = "stun.l.google.com", target_port: int = 19302) -> None:
    """Emite ping leve STUN para manter a tabela de tradução do roteador aberta em Standby."""
    try:
        ip = socket.gethostbyname(target_host)
        trans_id = os.urandom(12)
        req = struct.pack("!HHI", STUN_BINDING_REQUEST, 0, STUN_MAGIC_COOKIE) + trans_id
        sock.sendto(req, (ip, target_port))
    except Exception:
        pass


def _parse_stun_response(data: bytes) -> Optional[Tuple[str, int]]:
    """Extrai o IP público e porta de um pacote STUN Binding Response."""
    if len(data) < 20:
        return None

    msg_len = struct.unpack("!H", data[2:4])[0]
    idx = 20
    end = min(20 + msg_len, len(data))

    while idx + 4 <= end:
        attr_type, attr_len = struct.unpack("!HH", data[idx:idx+4])
        attr_data = data[idx+4 : idx+4+attr_len]
        idx += 4 + ((attr_len + 3) & ~3)

        if attr_type == STUN_ATTR_XOR_MAPPED_ADDRESS and len(attr_data) >= 8:
            family = attr_data[1]
            if family == 0x01:  # IPv4
                x_port = struct.unpack("!H", attr_data[2:4])[0]
                port = x_port ^ (STUN_MAGIC_COOKIE >> 16)
                x_ip = struct.unpack("!I", attr_data[4:8])[0]
                ip = socket.inet_ntoa(struct.pack("!I", x_ip ^ STUN_MAGIC_COOKIE))
                return ip, port

        elif attr_type == STUN_ATTR_MAPPED_ADDRESS and len(attr_data) >= 8:
            family = attr_data[1]
            if family == 0x01:
                port = struct.unpack("!H", attr_data[2:4])[0]
                ip = socket.inet_ntoa(attr_data[4:8])
                return ip, port

    return None
