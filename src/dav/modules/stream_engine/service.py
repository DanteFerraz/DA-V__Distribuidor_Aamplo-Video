# -*- coding: utf-8 -*-
"""
Serviço do Motor de Streaming (StreamEngineService) — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np

from src.dav.kernel.result import ServiceResult
from src.dav.kernel.event_bus import EventBus
from src.dav.modules.capture.service import CaptureService
from src.dav.modules.codec.service import CodecService
from src.dav.modules.transport_p2p.service import TransportService
from src.dav.modules.stream_engine.sender_worker import SenderWorker
from src.dav.modules.stream_engine.receiver_worker import ReceiverWorker

logger = logging.getLogger("DAV.StreamEngine.Service")

EVENT_STREAM_ROUTE_LOCKED = "stream.route_locked"
EVENT_STREAM_FRAME_RECEIVED = "stream.frame_received"
EVENT_STREAM_STATS = "stream.stats"
EVENT_STREAM_STOPPED = "stream.stopped"


class StreamEngineService:
    """
    Serviço orquestrador de alto nível para sessões de streaming DA-V.
    Gerencia instâncias ativas de SenderWorker e ReceiverWorker conectando
    captura, codec e transporte ao EventBus do sistema.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        capture_service: Optional[CaptureService] = None,
        codec_service: Optional[CodecService] = None,
        transport_service: Optional[TransportService] = None,
    ):
        self.bus = event_bus or EventBus.get_instance()
        self.capture_service = capture_service or CaptureService()
        self.codec_service = codec_service or CodecService()
        self.transport_service = transport_service or TransportService()

        self._sender: Optional[SenderWorker] = None
        self._receiver: Optional[ReceiverWorker] = None
        self._current_role: Optional[str] = None  # "sender" | "receiver"
        self._active_route: Optional[Dict[str, Any]] = None
        self._latest_stats: Dict[str, Any] = {}

    @property
    def is_transmitting(self) -> bool:
        return self._sender is not None and self._sender._running

    @property
    def is_receiving(self) -> bool:
        return self._receiver is not None and self._receiver._running

    def start_transmission(
        self,
        pin: str,
        display_idx: int = 1,
        width: int = 1920,
        height: int = 1080,
        fps: int = 60,
        bitrate_kbps: int = 12000,
        target_ip: str = "",
        target_port: int = 9000,
        port: int = 9000,
        candidates: Optional[List[Tuple[str, int, str]]] = None,
        relay_addr: Optional[Tuple[str, int]] = None,
    ) -> ServiceResult[Dict[str, Any]]:
        """Inicia uma sessão de transmissão (Sender)."""
        if self.is_transmitting or self.is_receiving:
            self.stop_all()

        # 1. Obtenção do socket UDP
        sock_res = self.transport_service.bind_udp_socket(port=port)
        if not sock_res.is_success or sock_res.data is None:
            return ServiceResult.fail(f"Falha ao vincular porta UDP de streaming: {sock_res.error}")
        sock = sock_res.data

        # 2. Criação do capturador
        cap_res = self.capture_service.create_capturer(
            display_idx=display_idx, width=width, height=height, fps=fps
        )
        if not cap_res.is_success or cap_res.data is None:
            sock.close()
            return ServiceResult.fail(f"Falha ao instanciar capturador: {cap_res.error}")
        capturer = cap_res.data

        # 3. Criação do encoder de vídeo
        enc_res = self.codec_service.create_encoder(
            width=width, height=height, fps=fps, bitrate_kbps=bitrate_kbps
        )
        if not enc_res.is_success or enc_res.data is None:
            capturer.close()
            sock.close()
            return ServiceResult.fail(f"Falha ao instanciar encoder de vídeo: {enc_res.error}")
        encoder = enc_res.data

        def _on_route_locked(ip: str, p: int, mode_tag: str) -> None:
            self._active_route = {"ip": ip, "port": p, "mode": mode_tag}
            self.bus.publish(EVENT_STREAM_ROUTE_LOCKED, self._active_route)

        def _on_stats(stats: Dict[str, Any]) -> None:
            self._latest_stats = stats
            self.bus.publish(EVENT_STREAM_STATS, stats)

        # 4. Inicialização do SenderWorker
        sender = SenderWorker(
            sock=sock,
            capturer=capturer,
            encoder=encoder,
            pin=pin,
            target_ip=target_ip,
            target_port=target_port,
            candidates=candidates,
            relay_addr=relay_addr,
            on_route_locked=_on_route_locked,
            on_stats=_on_stats,
        )
        sender.start()
        self._sender = sender
        self._current_role = "sender"

        logger.info(f"[StreamEngine] Transmissor iniciado com sucesso (PIN: {pin}, porta: {port})")
        return ServiceResult.ok({
            "role": "sender",
            "pin": pin,
            "port": port,
            "resolution": f"{width}x{height}",
            "fps": fps,
        })

    def start_reception(
        self,
        pin: str,
        port: int = 9000,
        candidates: Optional[List[Tuple[str, int, str]]] = None,
        relay_addr: Optional[Tuple[str, int]] = None,
        on_frame_callback: Optional[Callable[[np.ndarray], None]] = None,
    ) -> ServiceResult[Dict[str, Any]]:
        """Inicia uma sessão de recepção (Receiver)."""
        if self.is_transmitting or self.is_receiving:
            self.stop_all()

        # 1. Obtenção do socket UDP
        sock_res = self.transport_service.bind_udp_socket(port=port)
        if not sock_res.is_success or sock_res.data is None:
            return ServiceResult.fail(f"Falha ao vincular porta UDP de streaming: {sock_res.error}")
        sock = sock_res.data

        # 2. Criação do decoder
        dec_res = self.codec_service.create_decoder()
        if not dec_res.is_success or dec_res.data is None:
            sock.close()
            return ServiceResult.fail(f"Falha ao instanciar decoder: {dec_res.error}")
        decoder = dec_res.data

        def _on_frame(frame: np.ndarray) -> None:
            if on_frame_callback:
                on_frame_callback(frame)
            self.bus.publish(EVENT_STREAM_FRAME_RECEIVED, frame)

        def _on_route_locked(ip: str, p: int, mode_tag: str) -> None:
            self._active_route = {"ip": ip, "port": p, "mode": mode_tag}
            self.bus.publish(EVENT_STREAM_ROUTE_LOCKED, self._active_route)

        def _on_stats(stats: Dict[str, Any]) -> None:
            self._latest_stats = stats
            self.bus.publish(EVENT_STREAM_STATS, stats)

        # 3. Inicialização do ReceiverWorker
        receiver = ReceiverWorker(
            sock=sock,
            decoder=decoder,
            pin=pin,
            candidates=candidates,
            relay_addr=relay_addr,
            on_frame=_on_frame,
            on_route_locked=_on_route_locked,
            on_stats=_on_stats,
        )
        receiver.start()
        self._receiver = receiver
        self._current_role = "receiver"

        logger.info(f"[StreamEngine] Receptor iniciado com sucesso (PIN: {pin}, porta: {port})")
        return ServiceResult.ok({
            "role": "receiver",
            "pin": pin,
            "port": port,
        })

    def pair_peer(self, candidates: List[Tuple[str, int, str]], relay_info: Optional[Dict[str, Any]] = None) -> ServiceResult[bool]:
        """Injeta candidatos de Hole-Punching na sessão ativa."""
        if self._sender:
            self._sender.pair_peer(candidates, relay_info)
            return ServiceResult.ok(True)
        if self._receiver:
            self._receiver.pair_peer(candidates, relay_info)
            return ServiceResult.ok(True)
        return ServiceResult.fail("Nenhuma sessão de streaming ativa para parear.")

    def stop_all(self) -> ServiceResult[bool]:
        """Encerra com segurança qualquer transmissão ou recepção ativa."""
        if self._sender:
            try:
                self._sender.stop()
            except Exception as exc:
                logger.error(f"[StreamEngine] Erro ao parar SenderWorker: {exc}")
            self._sender = None

        if self._receiver:
            try:
                self._receiver.stop()
            except Exception as exc:
                logger.error(f"[StreamEngine] Erro ao parar ReceiverWorker: {exc}")
            self._receiver = None

        self._current_role = None
        self._active_route = None
        self.bus.publish(EVENT_STREAM_STOPPED, True)
        return ServiceResult.ok(True)

    def get_status(self) -> Dict[str, Any]:
        """Retorna o estado operacional e estatísticas da sessão de streaming."""
        return {
            "active_role": self._current_role,
            "is_transmitting": self.is_transmitting,
            "is_receiving": self.is_receiving,
            "route": self._active_route,
            "latest_stats": self._latest_stats,
        }

