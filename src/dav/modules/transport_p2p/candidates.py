# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Coleta e Priorizacao de Candidatos de Conexao P2P (ICE-Lite Dual-Stack IPv4/IPv6) — DA-V v5.2
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import socket
from typing import Dict, List, Optional, Tuple

from src.dav.modules.transport_p2p.dualstack import (
    canonicalize_ip,
    get_local_ipv6,
    is_global_ipv6,
    is_ipv6_address,
    is_lan_or_local_address,
    is_overlay_address,
)


def is_lan_address(ip_str: str) -> bool:
    """Verifica se o IP (IPv4 ou IPv6) pertence a sub-redes privadas LAN (RFC 1918/ULA) ou Loopback."""
    return is_lan_or_local_address(ip_str)


def get_local_candidates() -> List[str]:
    """Descobre enderecos IPv4 locais fisicos e IPv6 Global Unicast ativos da maquina."""
    local_ips: List[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_DGRAM):
            ip = canonicalize_ip(info[4][0])
            if not ip or ip in ("127.0.0.1", "::1") or ip.startswith("127.") or ip in local_ips:
                continue
            if is_ipv6_address(ip):
                if is_global_ipv6(ip) or is_overlay_address(ip):
                    local_ips.append(ip)
            else:
                if not any(ip.startswith(prefix) for prefix in ("172.17.", "172.18.", "192.168.56.", "169.254.")):
                    local_ips.append(ip)
    except Exception:
        pass

    # Garante rota de saida IPv4 primaria
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            routed_ip = canonicalize_ip(s.getsockname()[0])
            if routed_ip and routed_ip not in local_ips and not routed_ip.startswith("127."):
                local_ips.insert(0, routed_ip)
    except Exception:
        pass

    # Garante rota de saida IPv6 Global primaria (essencial para hosts IPv6-only e P2P sem CGNAT)
    v6_global = get_local_ipv6()
    if v6_global and v6_global not in local_ips:
        local_ips.append(v6_global)

    if not local_ips:
        local_ips.append("::1" if getattr(socket, "has_ipv6", False) else "127.0.0.1")

    return local_ips


def build_peer_candidates(peer_info: Dict[str, object], my_public_ip: Optional[str] = None) -> List[Tuple[str, int, str]]:
    """
    Constroi a lista ordenada de candidatos (Overlay -> LAN -> IPv6 Global -> WAN IPv4 -> Port Prediction)
    para o processo de Hole-Punching concorrente Dual-Stack.
    """
    candidates: List[Tuple[str, int, str]] = []
    seen = set()

    def _add(ip: str, port: int, mode: str) -> None:
        clean_ip = canonicalize_ip(ip)
        if not clean_ip or not port or clean_ip in ("0.0.0.0", "::"):
            return
        p_int = int(port)
        if p_int <= 0 or p_int > 65535:
            return
        key = (clean_ip, p_int)
        if key not in seen:
            seen.add(key)
            candidates.append((clean_ip, p_int, mode))

    peer_pub_ip = str(peer_info.get("public_ip") or "")
    peer_pub_port = int(peer_info.get("public_port") or 0)
    peer_pub_v6 = str(peer_info.get("public_ipv6") or "")
    peer_pub_v6_port = int(peer_info.get("public_ipv6_port") or peer_pub_port or peer_info.get("local_port") or 9000)
    peer_lan_ips = peer_info.get("lan_ips") or []
    if isinstance(peer_lan_ips, str):
        peer_lan_ips = [peer_lan_ips]
    peer_stream_port = int(peer_info.get("stream_port") or peer_info.get("local_port") or peer_pub_port or 9000)

    raw_cands = peer_info.get("candidates")
    if isinstance(raw_cands, list):
        for c in raw_cands:
            if isinstance(c, dict) and c.get("type") == "overlay":
                _add(str(c.get("ip") or ""), int(c.get("port") or peer_stream_port), "overlay")
        for c in raw_cands:
            if isinstance(c, dict) and c.get("type") == "lan":
                _add(str(c.get("ip") or ""), int(c.get("port") or peer_stream_port), "lan")
        for c in raw_cands:
            if isinstance(c, dict) and c.get("type") in ("ipv6", "wan-v6"):
                _add(str(c.get("ip") or ""), int(c.get("port") or peer_pub_v6_port), "ipv6")

    # 1. Candidatos Overlay / VPN privada (Tailscale IPv4 100.64/10 ou IPv6 fd7a::)
    for lip in peer_lan_ips:
        if is_overlay_address(str(lip)):
            _add(str(lip), peer_stream_port, "overlay")

    # 2. Candidatos LAN fisica direta
    for lip in peer_lan_ips:
        lip_s = str(lip)
        if not is_overlay_address(lip_s) and not lip_s.startswith("127.") and lip_s != "::1":
            mode = "ipv6" if is_global_ipv6(lip_s) else "lan"
            _add(lip_s, peer_stream_port, mode)

    # 3. Candidato IPv6 Global direto (sem CGNAT / sem traducao de portas)
    if peer_pub_v6 and is_global_ipv6(peer_pub_v6):
        _add(peer_pub_v6, peer_pub_v6_port, "ipv6")

    # 4. Candidato WAN reflexivo descoberto via STUN (IPv4 ou IPv6)
    if peer_pub_ip and peer_pub_port:
        pub_mode = "ipv6" if is_ipv6_address(peer_pub_ip) else "wan"
        _add(peer_pub_ip, peer_pub_port, pub_mode)

        # Predicao de portas adjacentes apenas para NAT IPv4 simetrico
        if not is_ipv6_address(peer_pub_ip) and peer_info.get("nat_type") == "symmetric":
            for delta in (+1, -1, +2, -2, +3):
                pred_port = peer_pub_port + delta
                if 1024 <= pred_port <= 65535:
                    _add(peer_pub_ip, pred_port, "wan-predicted")

    return candidates
