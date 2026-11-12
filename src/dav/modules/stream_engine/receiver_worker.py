# -*- coding: utf-8 -*-
"""
Motor de Recepção (ReceiverWorker) — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import collections
import logging
import socket
import struct
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np

from src.dav.modules.codec.base import BaseDecoder
from src.dav.modules.transport_p2p.packetizer import (
    DAV_HEADER_SIZE,
    DAV_POLY1305_TAG,
    MAGIC_SYN,
    MAGIC_ACK,
    MAGIC_PLI,
    MAGIC_RLY,
    build_key_vector,
    unpack_header,
)
from src.dav.modules.transport_p2p.blind_relay import unwrap_relay_packet, wrap_relay_packet
from src.dav.modules.transport_p2p.candidates import is_lan_address

logger = logging.getLogger("DAV.StreamEngine.Receiver")


class ReceiverWorker:
    """
    Controlador de streaming ativo no lado receptor.
    Efetua Hole-Punching STUN/LAN, remontagem de datagramas, decodificação
    em tempo real, solicitação de IDR sob perda (PLI) e cálculo de telemetria.
    """

    def __init__(
        self,
        sock: socket.socket,
        decoder: BaseDecoder,
        pin: str,
        candidates: Optional[List[Tuple[str, int, str]]] = None,
        relay_addr: Optional[Tuple[str, int]] = None,
        on_frame: Optional[Callable[[np.ndarray], None]] = None,
        on_route_locked: Optional[Callable[[str, int, str], None]] = None,
        on_stats: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.sock = sock
        self.decoder = decoder
        self.pin = pin
        self.clean_pin = pin.replace("-", "").replace(" ", "").strip()
        self.candidates = list(candidates or [])
        self.relay_addr = relay_addr
        self.on_frame = on_frame
        self.on_route_locked = on_route_locked
        self.on_stats = on_stats

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._key_vector = build_key_vector(pin)
        self._punch_locked = False
        self._sender_addr: Optional[Tuple[str, int]] = None
        self._use_relay = False
        self._has_seen_keyframe = False

        # Remontagem de quadros: frame_id -> {frags: {idx: bytes}, tot: int, is_kf: bool, ts: float}
        self._frame_assembler: Dict[int, Dict[str, Any]] = collections.OrderedDict()
        self._max_buffered_frames = 30
        self._last_pli_time = 0.0

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="DAV-Receiver-Loop")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)
        self.decoder.close()

    def pair_peer(self, candidates: List[Tuple[str, int, str]], relay_info: Optional[Dict[str, Any]] = None) -> None:
        """Configura candidatos remotos para Hole-Punching."""
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

        if self.relay_addr and not self._punch_locked:
            hello = wrap_relay_packet(self.clean_pin, b"R", b"DAV_RLY_HELLO")
            try:
                self.sock.sendto(hello, self.relay_addr)
            except Exception:
                pass

    def _request_pli(self) -> None:
        """Emite sinal PLI ao transmissor solicitando IDR imediato."""
        now = time.perf_counter()
        if now - self._last_pli_time < 0.2:
            return  # Rate-limit a cada 200ms
        self._last_pli_time = now

        pli_msg = f"{MAGIC_PLI.decode('ascii')}:{self.clean_pin}".encode("ascii")
        if self._use_relay and self.relay_addr:
            wrapped = wrap_relay_packet(self.clean_pin, b"R", pli_msg)
            try:
                self.sock.sendto(wrapped, self.relay_addr)
            except Exception:
                pass
        elif self._sender_addr:
            try:
                self.sock.sendto(pli_msg, self._sender_addr)
            except Exception:
                pass

    def _run_loop(self) -> None:
        total_frames = 0
        total_packets = 0
        total_bytes = 0
        recent_latency = 0.0
        last_stat_time = time.perf_counter()
        last_punch_burst = time.perf_counter()

        while self._running:
            # Envio periódico de SYN enquanto rota não estiver travada
            if not self._punch_locked and (time.perf_counter() - last_punch_burst >= 0.25):
                self._send_punch_burst()
                last_punch_burst = time.perf_counter()

            try:
                raw_pkt, addr = self.sock.recvfrom(65536)
            except (BlockingIOError, OSError):
                time.sleep(0.001)
                continue

            if not raw_pkt:
                continue

            total_packets += 1
            total_bytes += len(raw_pkt)

            # 1. Trata Blind Relay
            if raw_pkt.startswith(MAGIC_RLY):
                unwrapped = unwrap_relay_packet(raw_pkt)
                if unwrapped:
                    r_pin, role, payload = unwrapped
                    if r_pin == self.clean_pin:
                        if payload in (b"DAV_RLY_ACK", b"DAV_RLY_PEER_READY"):
                            if not self._punch_locked:
                                self._use_relay = True
                                self._punch_locked = True
                                if self.on_route_locked and self.relay_addr:
                                    self.on_route_locked(self.relay_addr[0], self.relay_addr[1], "Blind Relay UDP")
                            continue
                        # Payload é um pacote DA-V reencaminhado
                        raw_pkt = payload

            # 2. Trata Sinalização de Hole-Punching
            if raw_pkt.startswith(MAGIC_SYN):
                ack = f"{MAGIC_ACK.decode('ascii')}:{self.clean_pin}".encode("ascii")
                try:
                    self.sock.sendto(ack, addr)
                except Exception:
                    pass
                if not self._punch_locked or (self._use_relay) or (not is_lan_address(self._sender_addr[0] if self._sender_addr else "") and is_lan_address(addr[0])):
                    self._sender_addr = addr
                    self._punch_locked = True
                    self._use_relay = False
                    mode_tag = "LAN Direto" if is_lan_address(addr[0]) else "WAN P2P Direto"
                    logger.info(f"[Receiver] Rota travada com transmissor: {addr[0]}:{addr[1]} ({mode_tag})")
                    if self.on_route_locked:
                        self.on_route_locked(addr[0], addr[1], mode_tag)
                continue

            elif raw_pkt.startswith(MAGIC_ACK):
                if not self._punch_locked or (self._use_relay):
                    self._sender_addr = addr
                    self._punch_locked = True
                    self._use_relay = False
                    mode_tag = "LAN Direto" if is_lan_address(addr[0]) else "WAN P2P Direto"
                    logger.info(f"[Receiver] ACK recebido, rota travada: {addr[0]}:{addr[1]} ({mode_tag})")
                    if self.on_route_locked:
                        self.on_route_locked(addr[0], addr[1], mode_tag)
                continue

            # 3. Trata Datagrama de Vídeo DA-V
            hdr = unpack_header(raw_pkt)
            if not hdr:
                continue

            # Se ainda não travou rota, aproveita o primeiro pacote de vídeo para travar
            if not self._punch_locked and not self._use_relay:
                self._sender_addr = addr
                self._punch_locked = True
                mode_tag = "LAN Direto" if is_lan_address(addr[0]) else "WAN P2P Direto"
                if self.on_route_locked:
                    self.on_route_locked(addr[0], addr[1], mode_tag)

            # Cálculo de latência fim-a-fim
            if hdr.timestamp_us > 0:
                now_us = int(time.time_ns() // 1000)
                lat = (now_us - hdr.timestamp_us) / 1000.0
                if 0.0 < lat < 2000.0:
                    recent_latency = round(lat, 2)

            # Se for quadro P e ainda não tivermos visto keyframe, pede IDR imediatamente
            if not hdr.is_keyframe and not self._has_seen_keyframe:
                self._request_pli()
                continue

            # Extração do chunk cifrado
            chunk_data = raw_pkt[DAV_HEADER_SIZE : DAV_HEADER_SIZE + hdr.payload_len]

            # Inserção no buffer de montagem do quadro
            frame_id = hdr.frame_id
            if frame_id not in self._frame_assembler:
                self._frame_assembler[frame_id] = {
                    "frags": {},
                    "tot": hdr.frag_tot,
                    "is_kf": hdr.is_keyframe,
                    "is_enc": hdr.is_encrypted,
                    "ts": time.perf_counter(),
                }

            entry = self._frame_assembler[frame_id]
            entry["frags"][hdr.frag_idx] = chunk_data

            # Limpeza de quadros velhos não completados
            while len(self._frame_assembler) > self._max_buffered_frames:
                old_fid, _ = self._frame_assembler.popitem(last=False)
                # Perda detectada -> solicita PLI
                self._request_pli()

            # Se todos os fragmentos chegaram, remonta o payload
            if len(entry["frags"]) == entry["tot"]:
                del self._frame_assembler[frame_id]
                sorted_chunks = [entry["frags"][i] for i in range(entry["tot"])]
                enc_payload = b"".join(sorted_chunks)

                # Decriptografia SIMD em bloco único
                if entry["is_enc"] and len(enc_payload) > 0:
                    payload_arr = np.frombuffer(enc_payload, dtype=np.uint8)
                    key_sub = self._key_vector[: len(enc_payload)]
                    dec_payload = np.bitwise_xor(payload_arr, key_sub).tobytes()
                else:
                    dec_payload = enc_payload

                # Decodificação
                decoded_frames = self.decoder.decode_all(dec_payload)
                if decoded_frames:
                    self._has_seen_keyframe = True
                    total_frames += len(decoded_frames)
                    if self.on_frame:
                        for f in decoded_frames:
                            self.on_frame(f)

            # Estatísticas periódicas (a cada 500ms)
            now = time.perf_counter()
            if now - last_stat_time >= 0.5:
                dt = now - last_stat_time
                fps = total_frames / dt if dt > 0 else 0.0
                mbps = (total_bytes * 8.0) / (dt * 1_000_000.0) if dt > 0 else 0.0
                if self.on_stats:
                    self.on_stats({
                        "fps": round(fps, 1),
                        "bitrate_mbps": round(mbps, 2),
                        "latency_ms": recent_latency,
                        "frames_count": total_frames,
                        "packets_count": total_packets,
                    })
                last_stat_time = now
                total_frames = 0
                total_bytes = 0
