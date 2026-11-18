# -*- coding: utf-8 -*-
"""
Servico de Transporte P2P — Fachada Unificada de Rede, Sinalizacao, Beacon e Data Plane
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
import socket
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.dav.kernel.result import ServiceResult
from src.dav.modules.transport_p2p.blind_relay import normalize_pin, unwrap_relay_packet, wrap_relay_packet
from src.dav.modules.transport_p2p.candidates import is_lan_address
from src.dav.modules.transport_p2p.data_plane import DataPlaneReceiver, DataPlaneSender
from src.dav.modules.transport_p2p.lan_beacon import LanBeaconService, get_local_ip
from src.dav.modules.transport_p2p.signaling_client import (
    DEFAULT_HTTP_PORT,
    DEFAULT_RENDEZVOUS_HOST,
    DEFAULT_STUN_PORT,
    P2PChannelClient,
    build_peer_candidates,
    discover_socket_endpoint,
    find_available_port,
    get_local_candidates,
)

logger = logging.getLogger("DAV.Transport.Service")


def disable_win_udp_connreset(sock: socket.socket) -> None:
    """Desativa WSAECONNRESET (WinError 10054) no Windows para evitar quebrar o loop UDP."""
    if sys.platform == "win32" and hasattr(sock, "ioctl"):
        try:
            SIO_UDP_CONNRESET = 0x9800000C
            sock.ioctl(SIO_UDP_CONNRESET, False)
        except Exception:
            pass


class TransportService:
    """Fachada para abertura de sockets, STUN RFC 5389, Sinalizacao P2P, Beacon LAN e Data Plane."""

    @classmethod
    def bind_udp_socket(cls, port: int = 0) -> ServiceResult[socket.socket]:
        """Alias conveniente para criacao e vinculacao de socket de midia."""
        return cls.create_media_socket(bind_port=port)

    @staticmethod
    def create_media_socket(bind_port: int, rcvbuf_mb: int = 32, sndbuf_mb: int = 8) -> ServiceResult[socket.socket]:
        """Cria e configura o socket UDP de alta vazao com buffers de rede otimizados."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf_mb * 1024 * 1024)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, sndbuf_mb * 1024 * 1024)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            disable_win_udp_connreset(sock)

            try:
                sock.bind(("0.0.0.0", int(bind_port)))
            except OSError:
                sock.bind(("0.0.0.0", 0))

            return ServiceResult.ok(sock, code="SOCKET_BOUND")
        except Exception as exc:
            return ServiceResult.fail(str(exc), code="SOCKET_BIND_ERROR")

    @staticmethod
    def discover_nat(
        bound_sock: socket.socket,
        rendezvous_host: str = DEFAULT_RENDEZVOUS_HOST,
        stun_port: int = DEFAULT_STUN_PORT,
    ) -> ServiceResult[Dict[str, Any]]:
        """Executa a descoberta STUN sobre o descritor ja vinculado."""
        try:
            ep = discover_socket_endpoint(bound_sock, rendezvous_host=rendezvous_host, stun_port=stun_port)
            return ServiceResult.ok(ep, code="STUN_DISCOVERED")
        except Exception as exc:
            return ServiceResult.fail(str(exc), code="STUN_ERROR")

    @staticmethod
    def create_data_plane_sender(
        pin: str,
        send_raw_fn: Callable[[bytes], None],
        initial_bitrate_kbps: int = 12000,
        fps: int = 60,
    ) -> DataPlaneSender:
        return DataPlaneSender(
            pin=pin,
            send_raw_fn=send_raw_fn,
            initial_bitrate_kbps=initial_bitrate_kbps,
            fps=fps,
        )

    @staticmethod
    def create_data_plane_receiver(pin: str) -> DataPlaneReceiver:
        return DataPlaneReceiver(pin=pin)

    @staticmethod
    def create_signaling_client(
        rendezvous_host: str = DEFAULT_RENDEZVOUS_HOST,
        http_port: int = DEFAULT_HTTP_PORT,
        stun_port: int = DEFAULT_STUN_PORT,
    ) -> P2PChannelClient:
        return P2PChannelClient(
            rendezvous_host=rendezvous_host,
            http_port=http_port,
            stun_port=stun_port,
        )

    @staticmethod
    def create_lan_beacon(node_name: str, stream_port: int = 9000, pin: str = "123456") -> LanBeaconService:
        return LanBeaconService(node_name=node_name, stream_port=stream_port, pin=pin)

    @staticmethod
    def get_local_ip() -> str:
        return get_local_ip()

    @staticmethod
    def find_available_port(start_port: int = 9000, max_tries: int = 20) -> int:
        return find_available_port(start_port=start_port, max_tries=max_tries)

    @staticmethod
    def normalize_pin(pin: str) -> str:
        return normalize_pin(pin)

    @staticmethod
    def build_peer_candidates(peer_info: Dict[str, Any], my_public_ip: Optional[str] = None) -> List[Tuple[str, int, str]]:
        return build_peer_candidates(peer_info, my_public_ip=my_public_ip)
