# -*- coding: utf-8 -*-
"""
Manifesto do Módulo de Transporte P2P — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.transport_p2p.service import TransportService
from src.dav.modules.transport_p2p.packetizer import pack_frame, unpack_header, build_key_vector
from src.dav.modules.transport_p2p.candidates import get_local_candidates, build_peer_candidates
from src.dav.modules.transport_p2p.blind_relay import wrap_relay_packet, unwrap_relay_packet

MANIFEST = ModuleManifest(
    name="transport_p2p",
    version="4.0.0",
    description="STUN RFC 5389 Single-Socket, Hole-Punching concorrente e Blind Encrypted UDP Relay",
    author="Dante Ferraz (MonoTech)",
    dependencies=[],
    enabled=True,
    exports={
        "service": TransportService,
        "pack_frame": pack_frame,
        "unpack_header": unpack_header,
        "build_key_vector": build_key_vector,
        "get_local_candidates": get_local_candidates,
        "build_peer_candidates": build_peer_candidates,
        "wrap_relay_packet": wrap_relay_packet,
        "unwrap_relay_packet": unwrap_relay_packet,
    },
)
