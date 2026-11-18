# -*- coding: utf-8 -*-
"""
Shim de Compatibilidade — Redireciona para `src.dav.modules.transport_p2p.signaling_client`.
Autor: Dante Ferraz (MonoTech)
"""

from src.dav.modules.transport_p2p.signaling_client import (
    DEFAULT_HTTP_PORT,
    DEFAULT_RENDEZVOUS_HOST,
    DEFAULT_STUN_PORT,
    MAGIC_ACK,
    MAGIC_PLI,
    MAGIC_RELAY_HDR,
    MAGIC_SYN,
    P2PChannelClient,
    PUBLIC_STUN_SERVERS,
    STUN_MAGIC_COOKIE,
    _classify_private_ip,
    build_peer_candidates,
    discover_socket_endpoint,
    find_available_port,
    get_local_candidates,
    get_local_ip,
    normalize_pin,
    query_rfc5389_stun,
    send_stun_keepalive,
    wrap_relay_packet,
)

__all__ = [
    "DEFAULT_RENDEZVOUS_HOST",
    "DEFAULT_HTTP_PORT",
    "DEFAULT_STUN_PORT",
    "MAGIC_SYN",
    "MAGIC_ACK",
    "MAGIC_PLI",
    "MAGIC_RELAY_HDR",
    "STUN_MAGIC_COOKIE",
    "PUBLIC_STUN_SERVERS",
    "normalize_pin",
    "wrap_relay_packet",
    "get_local_ip",
    "find_available_port",
    "_classify_private_ip",
    "get_local_candidates",
    "query_rfc5389_stun",
    "send_stun_keepalive",
    "discover_socket_endpoint",
    "build_peer_candidates",
    "P2PChannelClient",
]
