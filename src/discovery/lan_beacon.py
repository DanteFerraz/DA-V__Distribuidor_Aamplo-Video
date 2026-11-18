# -*- coding: utf-8 -*-
"""
Shim de Compatibilidade — Redireciona para `src.dav.modules.transport_p2p.lan_beacon`.
Autor: Dante Ferraz (MonoTech)
"""

from src.dav.modules.transport_p2p.lan_beacon import (
    BEACON_MAGIC,
    BEACON_PORT,
    LanBeaconService,
    PING_MAGIC,
    PONG_MAGIC,
    get_all_active_ipv4_interfaces,
    get_local_ip,
)

__all__ = [
    "BEACON_PORT",
    "BEACON_MAGIC",
    "PING_MAGIC",
    "PONG_MAGIC",
    "get_all_active_ipv4_interfaces",
    "get_local_ip",
    "LanBeaconService",
]
