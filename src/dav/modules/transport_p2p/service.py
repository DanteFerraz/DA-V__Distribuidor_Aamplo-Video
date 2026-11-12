# -*- coding: utf-8 -*-
"""
Serviço de Transporte P2P — Fachada Unificada de Rede
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
import socket
import sys
from typing import Any, Dict, List, Optional, Tuple

from src.dav.modules.transport_p2p.stun import discover_socket_endpoint
from src.dav.modules.transport_p2p.candidates import get_local_candidates, build_peer_candidates, is_lan_address
from src.dav.modules.transport_p2p.blind_relay import wrap_relay_packet, unwrap_relay_packet
from src.dav.kernel.result import ServiceResult

logger = logging.getLogger("DAV.Transport.Service")


def disable_win_udp_connreset(sock: socket.socket) -> None:
    """Desativa WSAECONNRESET (WinError 10054) no Windows para evitar quebrar o loop UDP."""
    if sys.platform == "win32":
        try:
            SIO_UDP_CONNRESET = 0x9800000C
            sock.ioctl(SIO_UDP_CONNRESET, False)
        except Exception:
            pass


class TransportService:
    """Fachada para abertura de sockets, STUN RFC 5389 e preparação de rotas."""

    @classmethod
    def bind_udp_socket(cls, port: int = 0) -> ServiceResult[socket.socket]:
        """Alias conveniente para criação e vinculação de socket de mídia."""
        return cls.create_media_socket(bind_port=port)

    @staticmethod
    def create_media_socket(bind_port: int, rcvbuf_mb: int = 32, sndbuf_mb: int = 8) -> ServiceResult[socket.socket]:
        """Cria e configura o socket UDP de alta vazão com buffers de rede otimizados."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf_mb * 1024 * 1024)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, sndbuf_mb * 1024 * 1024)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            disable_win_udp_connreset(sock)

            try:
                sock.bind(("0.0.0.0", int(bind_port)))
            except OSError:
                # Se a porta estiver em uso, vincula em porta efêmera livre
                sock.bind(("0.0.0.0", 0))

            return ServiceResult.ok(sock, code="SOCKET_BOUND")
        except Exception as exc:
            return ServiceResult.fail(str(exc), code="SOCKET_BIND_ERROR")

    @staticmethod
    def discover_nat(bound_sock: socket.socket, rendezvous_host: str = "129.148.26.150") -> ServiceResult[Dict[str, Any]]:
        """Executa a descoberta STUN sobre o descritor já vinculado."""
        try:
            ep = discover_socket_endpoint(bound_sock, rendezvous_host=rendezvous_host)
            return ServiceResult.ok(ep, code="STUN_DISCOVERED")
        except Exception as exc:
            return ServiceResult.fail(str(exc), code="STUN_ERROR")
