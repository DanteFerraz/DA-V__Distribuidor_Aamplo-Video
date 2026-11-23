# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Fatia Vertical de Transporte P2P (PAKE + AEAD + FEC GF(2^8) + SQP + Salsify + Sinalizacao) — DA-V v4.6
Autor: Dante Ferraz (MonoTech)
"""

from src.dav.modules.transport_p2p.blind_relay import (
    MAGIC_RLY1,
    normalize_pin,
    unwrap_relay_packet,
    wrap_relay_packet,
)
from src.dav.modules.transport_p2p.candidates import (
    build_peer_candidates,
    get_local_candidates,
    is_lan_address,
)
from src.dav.modules.transport_p2p.crypto_pake import (
    MAGIC_PAKE_ACK,
    MAGIC_PAKE_SYN,
    PacketCipher,
    PakeSession,
    ReplayWindow,
)
from src.dav.modules.transport_p2p.data_plane import DataPlaneReceiver, DataPlaneSender
from src.dav.modules.transport_p2p.fec_engine import AdaptiveFecPolicy, FecDecoder, FecEncoder
from src.dav.modules.transport_p2p.lan_beacon import LanBeaconService, get_local_ip
from src.dav.modules.transport_p2p.packetizer import (
    DAV_DEFAULT_MTU,
    DAV_HEADER_SIZE,
    DAV_SSRC,
    FLAG_AEAD_CHACHA20,
    FLAG_AUDIO_LBRR,
    FLAG_ENCRYPTED,
    FLAG_FEC,
    FLAG_KEYFRAME,
    FLAG_LAST_FRAG,
    FLAG_PIR,
    MAGIC_ACK,
    MAGIC_PLI,
    MAGIC_SYN,
    PT_AUDIO,
    PT_CONTROL,
    PT_FEC,
    PT_VIDEO,
    HeaderData,
    build_key_vector,
    pack_datagram,
    pack_frame,
    split_chunks,
    unpack_and_decrypt,
    unpack_header,
)

PacketHeaderData = HeaderData
from src.dav.modules.transport_p2p.service import TransportService, disable_win_udp_connreset
from src.dav.modules.transport_p2p.signaling_client import (
    DEFAULT_HTTP_PORT,
    DEFAULT_RENDEZVOUS_HOST,
    DEFAULT_STUN_PORT,
    P2PChannelClient,
    discover_socket_endpoint,
    find_available_port,
    send_stun_keepalive,
)
from src.dav.modules.transport_p2p.sqp_controller import (
    FrameBudget,
    MicroPacer,
    SqpAckData,
    SqpReceiverTracker,
    SqpSenderController,
)

__all__ = [
    "MAGIC_RLY1",
    "normalize_pin",
    "wrap_relay_packet",
    "unwrap_relay_packet",
    "is_lan_address",
    "get_local_candidates",
    "build_peer_candidates",
    "MAGIC_PAKE_SYN",
    "MAGIC_PAKE_ACK",
    "PakeSession",
    "PacketCipher",
    "ReplayWindow",
    "DataPlaneSender",
    "DataPlaneReceiver",
    "FecEncoder",
    "FecDecoder",
    "AdaptiveFecPolicy",
    "LanBeaconService",
    "get_local_ip",
    "P2PChannelClient",
    "find_available_port",
    "discover_socket_endpoint",
    "send_stun_keepalive",
    "DEFAULT_RENDEZVOUS_HOST",
    "DEFAULT_HTTP_PORT",
    "DEFAULT_STUN_PORT",
    "DAV_HEADER_SIZE",
    "DAV_DEFAULT_MTU",
    "DAV_SSRC",
    "PT_VIDEO",
    "PT_FEC",
    "PT_AUDIO",
    "PT_CONTROL",
    "FLAG_KEYFRAME",
    "FLAG_LAST_FRAG",
    "FLAG_FEC",
    "FLAG_ENCRYPTED",
    "FLAG_AEAD_CHACHA20",
    "FLAG_AUDIO_LBRR",
    "FLAG_PIR",
    "MAGIC_PLI",
    "MAGIC_SYN",
    "MAGIC_ACK",
    "HeaderData",
    "PacketHeaderData",
    "build_key_vector",
    "split_chunks",
    "pack_datagram",
    "pack_frame",
    "unpack_header",
    "unpack_and_decrypt",
    "FrameBudget",
    "SqpAckData",
    "SqpReceiverTracker",
    "SqpSenderController",
    "MicroPacer",
    "TransportService",
    "disable_win_udp_connreset",
]
