# -*- coding: utf-8 -*-
"""
Manifesto do Modulo de Transporte P2P — DA-V v4.6
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.transport_p2p.blind_relay import normalize_pin, unwrap_relay_packet, wrap_relay_packet
from src.dav.modules.transport_p2p.candidates import build_peer_candidates, get_local_candidates
from src.dav.modules.transport_p2p.data_plane import DataPlaneReceiver, DataPlaneSender
from src.dav.modules.transport_p2p.lan_beacon import LanBeaconService, get_local_ip
from src.dav.modules.transport_p2p.packetizer import build_key_vector, pack_frame, unpack_header
from src.dav.modules.transport_p2p.service import TransportService
from src.dav.modules.transport_p2p.signaling_client import P2PChannelClient, find_available_port

MANIFEST = ModuleManifest(
    name="transport_p2p",
    version="4.6.0",
    description="STUN RFC 5389 Single-Socket, Hole-Punching concorrente, Data Plane PAKE/AEAD/FEC/SQP e Blind Relay",
    author="Dante Ferraz (MonoTech)",
    dependencies=[],
    enabled=True,
    service_factory=lambda: TransportService(),
    exports={
        "service": TransportService,
        "DataPlaneSender": DataPlaneSender,
        "DataPlaneReceiver": DataPlaneReceiver,
        "P2PChannelClient": P2PChannelClient,
        "LanBeaconService": LanBeaconService,
        "get_local_ip": get_local_ip,
        "find_available_port": find_available_port,
        "normalize_pin": normalize_pin,
        "pack_frame": pack_frame,
        "unpack_header": unpack_header,
        "build_key_vector": build_key_vector,
        "get_local_candidates": get_local_candidates,
        "build_peer_candidates": build_peer_candidates,
        "wrap_relay_packet": wrap_relay_packet,
        "unwrap_relay_packet": unwrap_relay_packet,
    },
)

manifest = MANIFEST
