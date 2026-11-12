# -*- coding: utf-8 -*-
"""
Motor de Transmissão (SenderWorker) — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np

from src.dav.modules.capture.base import BaseCapturer
from src.dav.modules.codec.encoder import VideoEncoder
from src.dav.modules.transport_p2p.packetizer import (
    pack_frame,
    build_key_vector,
    MAGIC_SYN,
    MAGIC_ACK,
    MAGIC_PLI,
)
from src.dav.modules.transport_p2p.blind_relay import wrap_relay_packet
from src.dav.modules.transport_p2p.candidates import is_lan_address

logger = logging.getLogger("DAV.StreamEngine.Sender")


class SenderWorker:
    """
    Controlador de streaming ativo no lado transmissor.
    Executa a cadência estável de 60 FPS, gerenciamento de IDR sob demanda (PLI),
    Hole-Punching concorrente e chaveamento transparente para Blind Relay.
    """

    def __init__(
        self,
        sock: socket.socket,
        capturer: BaseCapturer,
        encoder: VideoEncoder,
        pin: str,
        target_ip: str = "",
        target_port: int = 9000,
        candidates: Optional[List[Tuple[str, int, str]]] = None,
        relay_addr: Optional[Tuple[str, int]] = None,
        on_route_locked: Optional[Callable[[str, int, str], None]] = None,
        on_stats: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.sock = sock
        self.capturer = capturer
        self.encoder = encoder
        self.pin = pin
        self.clean_pin = pin.replace("-", "").replace(" ", "").strip()
        self.target_ip = target_ip
        self.target_port = target_port
        self.candidates = list(candidates or [])
        self.relay_addr = relay_addr
        self.on_route_locked = on_route_locked
        self.on_stats = on_stats

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._key_vector = build_key_vector(pin)
        self._punch_locked = False
        self._use_relay = False
        self._is_streaming_active = bool(target_ip)
        self._frame_buffer = np.zeros((capturer.height, capturer.width, 4), dtype=np.uint8)

    def start(self) -> None:
        self._running = True
        self.capturer.start()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="DAV-Sender-Loop")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)
        self.capturer.close()
        self.encoder.close()

    def pair_peer(self, candidates: List[Tuple[str, int, str]], relay_info: Optional[Dict[str, Any]] = None) -> None:
        """Injeta candidatos recebidos do sinalizador para início do Hole-Punching."""
        self.candidates = list(candidates)
        if relay_info and relay_info.get("host") and relay_info.get("port"):
            self.relay_addr = (str(relay_info["host"]), int(relay_info["port"]))
        self._send_punch_burst()

    def _send_punch_burst(self) -> None:
        syn = f"{MAGIC_SYN.decode('ascii')}:{self.clean_pin}".encode("ascii")
        for ip, port, _ in self.candidates:
            try:
                self.sock.sendto(syn, (ip, port))
            except Exception:
                pass

    def _run_loop(self) -> None:
        frame_interval = 1.0 / float(max(1, self.capturer.fps))
        t_target = time.perf_counter() + frame_interval
        total_frames = 0
        total_packets = 0
        total_bytes = 0
        last_stat_time = time.perf_counter()
        seq_num = 0

        while self._running:
            # 1. Checagem de pacotes de controle UDP de entrada (não-bloqueante)
            self._poll_incoming_control()

            # 2. Captura do quadro
            if self.capturer.grab_into(self._frame_buffer):
                # 3. Codificação de vídeo
                payload = self.encoder.encode(self._frame_buffer)
                if payload and self._is_streaming_active:
                    total_frames += 1
                    is_kf = self.encoder.last_frame_was_keyframe or (total_frames == 1)

                    # 4. Criptografia e fragmentação em datagramas
                    packets, seq_num = pack_frame(
                        payload,
                        frame_id=total_frames,
                        is_keyframe=is_kf,
                        key_vector=self._key_vector,
                        start_seq=seq_num,
                    )

                    # 5. Envio dos datagramas
                    frame_bytes = 0
                    for pkt in packets:
                        self._send_packet(pkt)
                        total_packets += 1
                        frame_bytes += len(pkt)
                    total_bytes += frame_bytes

            # 6. Cálculo de estatísticas periódicas
            now = time.perf_counter()
            if now - last_stat_time >= 0.5:
                dt = now - last_stat_time
                fps = total_frames / dt if dt > 0 else 0.0
                mbps = (total_bytes * 8.0) / (dt * 1_000_000.0) if dt > 0 else 0.0
                if self.on_stats:
                    self.on_stats({
                        "fps": round(fps, 1),
                        "bitrate_mbps": round(mbps, 2),
                        "frames_count": total_frames,
                        "packets_count": total_packets,
                    })
                last_stat_time = now
                total_frames = 0
                total_bytes = 0

            # 7. Cadência precisa
            slack = t_target - time.perf_counter()
            if slack > 0.003:
                time.sleep(slack - 0.0015)
            while time.perf_counter() < t_target:
                pass
            t_target = max(t_target + frame_interval, time.perf_counter())

    def _poll_incoming_control(self) -> None:
        while True:
            try:
                pkt, addr = self.sock.recvfrom(2048)
            except (BlockingIOError, OSError):
                break
            if not pkt:
                continue

            if pkt.startswith(MAGIC_SYN) or pkt.startswith(MAGIC_ACK):
                if not self._punch_locked or self._use_relay or (not is_lan_address(self.target_ip) and is_lan_address(addr[0])):
                    self.target_ip, self.target_port = addr[0], int(addr[1])
                    self._punch_locked = True
                    self._use_relay = False
                    self._is_streaming_active = True
                    self.encoder.request_keyframe()
                    mode_tag = "LAN Direto" if is_lan_address(self.target_ip) else "WAN P2P Direto"
                    logger.info(f"[Sender] Rota confirmada: {self.target_ip}:{self.target_port} ({mode_tag})")
                    if self.on_route_locked:
                        self.on_route_locked(self.target_ip, self.target_port, mode_tag)

            elif pkt.startswith(MAGIC_PLI):
                self.encoder.request_keyframe()

            elif pkt in (b"DAV_RLY_ACK", b"DAV_RLY_PEER_READY"):
                if not self._punch_locked and self.relay_addr:
                    self._use_relay = True
                    self._is_streaming_active = True
                    self.encoder.request_keyframe()
                    if self.on_route_locked:
                        self.on_route_locked(self.relay_addr[0], self.relay_addr[1], "Blind Relay UDP")

    def _send_packet(self, pkt: bytes) -> None:
        if self._use_relay and self.relay_addr:
            wrapped = wrap_relay_packet(self.clean_pin, b"S", pkt)
            try:
                self.sock.sendto(wrapped, self.relay_addr)
            except OSError:
                pass
            return

        if self.target_ip:
            try:
                self.sock.sendto(pkt, (self.target_ip, self.target_port))
            except OSError:
                pass

