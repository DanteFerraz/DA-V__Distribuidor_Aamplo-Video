# -*- coding: utf-8 -*-
"""
Coleta e Priorização de Candidatos de Conexão P2P (ICE-Lite) — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import socket
from typing import Dict, List, Optional, Tuple


def is_lan_address(ip_str: str) -> bool:
    """Verifica se o IP informado pertence a sub-redes privadas RFC 1918 ou Loopback."""
    if not ip_str:
        return False
    parts = ip_str.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return False
    b0, b1 = int(parts[0]), int(parts[1])
    return (
        b0 == 127
        or b0 == 10
        or (b0 == 172 and 16 <= b1 <= 31)
        or (b0 == 192 and b1 == 168)
        or (b0 == 169 and b1 == 254)
    )


def get_local_candidates() -> List[str]:
    """Descobre os endereços IPv4 locais físicos válidos da máquina."""
    local_ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_DGRAM):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in local_ips:
                # Filtra pontes virtuais comuns que não roteiam entre hosts
                if not any(ip.startswith(prefix) for prefix in ("172.17.", "172.18.", "192.168.56.")):
                    local_ips.append(ip)
    except Exception:
        pass

    # Garante rota de saída primária
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            routed_ip = s.getsockname()[0]
            if routed_ip and routed_ip not in local_ips and not routed_ip.startswith("127."):
                local_ips.insert(0, routed_ip)
    except Exception:
        pass

    if not local_ips:
        local_ips.append("127.0.0.1")

    return local_ips


def build_peer_candidates(peer_info: Dict[str, object], my_public_ip: Optional[str] = None) -> List[Tuple[str, int, str]]:
    """
    Constrói a lista ordenada de candidatos (Overlay -> LAN -> WAN -> Port Prediction)
    para o processo de Hole-Punching concorrente.
    """
    candidates: List[Tuple[str, int, str]] = []
    seen = set()

    def _add(ip: str, port: int, mode: str):
        if not ip or not port:
            return
        key = (ip, int(port))
        if key not in seen:
            seen.add(key)
            candidates.append((ip, int(port), mode))

    peer_pub_ip = str(peer_info.get("public_ip") or "")
    peer_pub_port = int(peer_info.get("public_port") or 0)
    peer_lan_ips = peer_info.get("lan_ips") or []
    if isinstance(peer_lan_ips, str):
        peer_lan_ips = [peer_lan_ips]
    peer_stream_port = int(peer_info.get("stream_port") or peer_pub_port or 9000)

    # 1. Candidatos Overlay / VPN privada (ex: Tailscale 100.64.0.0/10)
    for lip in peer_lan_ips:
        if lip.startswith("100."):
            _add(lip, peer_stream_port, "overlay")

    # 2. Candidatos LAN física direta
    for lip in peer_lan_ips:
        if not lip.startswith("100.") and not lip.startswith("127."):
            _add(lip, peer_stream_port, "lan")

    # 3. Candidato WAN reflexivo descoberto via STUN
    if peer_pub_ip and peer_pub_port:
        _add(peer_pub_ip, peer_pub_port, "wan")

        # Predição de portas adjacentes para NAT com alocação sequencial
        if peer_info.get("nat_type") == "symmetric":
            for delta in (+1, -1, +2, -2, +3):
                pred_port = peer_pub_port + delta
                if 1024 <= pred_port <= 65535:
                    _add(peer_pub_ip, pred_port, "wan-predicted")

    return candidates

