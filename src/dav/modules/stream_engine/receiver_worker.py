# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Motor de Recepcao Modular (ReceiverWorker) — DA-V v4.6
Autor: Dante Ferraz (MonoTech)

Usa o DataPlaneReceiver unificado: Handshake PAKE (CPace-X25519), AEAD ChaCha20-Poly1305,
FEC GF(2^8), retorno de feedback SQP e suporte a multiplexacao de audio PT_AUDIO.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np

from src.dav.modules.codec.base import BaseDecoder
from src.dav.modules.transport_p2p.blind_relay import unwrap_relay_packet, wrap_relay_packet
from src.dav.modules.transport_p2p.candidates import is_lan_address
from src.dav.modules.transport_p2p.data_plane import DataPlaneReceiver
from src.dav.modules.transport_p2p.packetizer import MAGIC_ACK, MAGIC_PLI, MAGIC_RLY, MAGIC_SYN

logger = logging.getLogger("DAV.StreamEngine.Receiver")


class ReceiverWorker:
    """Controlador de streaming ativo no lado receptor sobre DataPlaneReceiver."""

    def __init__(
        self,
        sock: socket.socket,
        decoder: Optional[BaseDecoder],
        pin: str,
        candidates: Optional[List[Tuple[str, int, str]]] = None,
        relay_addr: Optional[Tuple[str, int]] = None,
        on_frame: Optional[Callable[[np.ndarray], None]] = None,
        on_encoded_frame: Optional[Callable[[bytes, int, int, int, bool], None]] = None,
        on_audio: Optional[Callable[[int, int, bytes], None]] = None,
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
        self.on_encoded_frame = on_encoded_frame
        self.on_audio = on_audio
        self.on_route_locked = on_route_locked
        self.on_stats = on_stats

        try:
            self.sock.settimeout(0.05)
        except Exception:
            pass

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._punch_locked = False
        self._sender_addr: Optional[Tuple[str, int]] = (
            (self.candidates[0][0], self.candidates[0][1]) if self.candidates else None
        )
        self._use_relay = False
        self._last_pli_time = 0.0

        self.dp = DataPlaneReceiver(pin=pin)

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="DAV-Receiver-Loop")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)
        if self.decoder is not None:
            try:
                self.decoder.close()
            except Exception:
                pass
        try:
            self.sock.close()
        except Exception:
            pass

    def pair_peer(self, candidates: List[Tuple[str, int, str]], relay_info: Optional[Dict[str, Any]] = None) -> None:
        self.candidates = list(candidates)
        if relay_info and relay_info.get("host") and relay_info.get("port"):
            self.relay_addr = (str(relay_info["host"]), int(relay_info["port"]))
        self._send_punch_burst()

    def _send_to_sender(self, payload: bytes) -> None:
        if self._use_relay and self.relay_addr:
            try:
                self.sock.sendto(wrap_relay_packet(self.clean_pin, b"R", payload), self.relay_addr)
            except Exception:
                pass
        elif self._sender_addr:
            try:
                self.sock.sendto(payload, self._sender_addr)
            except Exception:
                pass

    def _send_punch_burst(self) -> None:
        syn = self.dp.build_pake_syn()
        for ip, port, _ in self.candidates:
            try:
                self.sock.sendto(syn, (ip, port))
            except Exception:
                pass

        if self.relay_addr and not self._punch_locked:
            hello = wrap_relay_packet(self.clean_pin, b"R", syn)
            try:
                self.sock.sendto(hello, self.relay_addr)
            except Exception:
                pass

    def _send_lan_upgrade_probe(self) -> None:
        """Envia sonda PAKE apenas aos candidatos LAN/Overlay para promover rota WAN -> LAN em quente."""
        syn = self.dp.build_pake_syn()
        for ip, port, _ in self.candidates:
            if is_lan_address(ip) or ip.startswith("100."):
                try:
                    self.sock.sendto(syn, (ip, port))
                except Exception:
                    pass

    def _request_pli(self) -> None:
        now = time.perf_counter()
        if now - self._last_pli_time < 0.15:
            return
        self._last_pli_time = now
        pli_msg = f"{MAGIC_PLI.decode('ascii')}:{self.clean_pin}".encode("ascii")
        self._send_to_sender(pli_msg)

    def _run_loop(self) -> None:
        interval_frames = 0
        cumulative_frames = 0
        total_packets = 0
        interval_bytes = 0
        last_stat_time = time.perf_counter()
        last_punch_burst = time.perf_counter()
        last_lan_upgrade_probe = 0.0
        last_sqp_ack_sent = 0.0
        awaiting_clean_idr = False
        awaiting_idr_since = 0.0
        start_mono = time.monotonic()
        last_relay_bind = 0.0

        while self._running:
            mono_now = time.monotonic()
            if (not self._punch_locked or not self.dp.pake.confirmed) and (
                time.perf_counter() - last_punch_burst >= 0.06
            ):
                self._send_punch_burst()
                last_punch_burst = time.perf_counter()
            elif (
                self.dp.pake.confirmed
                and (mono_now - start_mono <= 6.0)
                and (mono_now - last_lan_upgrade_probe >= 0.20)
                and (self._use_relay or (self._sender_addr and not is_lan_address(self._sender_addr[0])))
            ):
                self._send_lan_upgrade_probe()
                last_lan_upgrade_probe = mono_now

            if (
                not self.dp.pake.confirmed
                and self.relay_addr
                and (mono_now - start_mono >= 0.85)
                and (mono_now - last_relay_bind >= 0.30)
            ):
                try:
                    self.sock.sendto(wrap_relay_packet(self.clean_pin, b"R", b"BIND"), self.relay_addr)
                except Exception:
                    pass
                last_relay_bind = mono_now

            try:
                raw_pkt, addr = self.sock.recvfrom(65536)
            except socket.timeout:
                continue
            except (BlockingIOError, OSError):
                time.sleep(0.001)
                continue

            if not raw_pkt:
                continue

            total_packets += 1
            interval_bytes += len(raw_pkt)

            if raw_pkt.startswith(MAGIC_RLY):
                unwrapped = unwrap_relay_packet(raw_pkt)
                if unwrapped:
                    r_pin, _, payload = unwrapped
                    if r_pin == self.clean_pin:
                        if payload in (b"DAV_RLY_ACK", b"DAV_RLY_PEER_READY"):
                            if not self._punch_locked and self.relay_addr:
                                self._use_relay = True
                                self._punch_locked = True
                                self._send_to_sender(self.dp.build_pake_syn())
                                if self.on_route_locked:
                                    self.on_route_locked(self.relay_addr[0], self.relay_addr[1], "Blind Relay UDP")
                            continue
                        raw_pkt = payload

            if raw_pkt in (b"DAV_RLY_ACK", b"DAV_RLY_PEER_READY"):
                if not self._punch_locked and self.relay_addr:
                    self._use_relay = True
                    self._punch_locked = True
                    self._send_to_sender(self.dp.build_pake_syn())
                    if self.on_route_locked:
                        self.on_route_locked(self.relay_addr[0], self.relay_addr[1], "Blind Relay UDP")
                continue

            if raw_pkt.startswith(MAGIC_SYN) or raw_pkt.startswith(MAGIC_ACK):
                if not raw_pkt.startswith(b"DAV_P2P_SYN2") and not raw_pkt.startswith(b"DAV_P2P_ACK2"):
                    try:
                        self.sock.sendto(self.dp.build_pake_syn(), addr)
                    except Exception:
                        pass
                    continue

            ev = self.dp.process_packet(raw_pkt)
            kind = ev["kind"]

            if kind == "pake":
                if not self._punch_locked or self._use_relay or (
                    self._sender_addr and not is_lan_address(self._sender_addr[0]) and is_lan_address(addr[0])
                ):
                    if self.relay_addr and addr == self.relay_addr:
                        self._use_relay = True
                    else:
                        self._sender_addr = addr
                        self._use_relay = False
                    self._punch_locked = True
                    mode_tag = "Blind Relay UDP" if self._use_relay else (
                        "LAN Direto" if is_lan_address(addr[0]) else "WAN P2P Direto"
                    )
                    if self.on_route_locked:
                        self.on_route_locked(addr[0], addr[1], mode_tag)

                if ev["reply_pake"] is not None:
                    try:
                        if self._use_relay and self.relay_addr:
                            self.sock.sendto(wrap_relay_packet(self.clean_pin, b"R", ev["reply_pake"]), self.relay_addr)
                        else:
                            self.sock.sendto(ev["reply_pake"], addr)
                    except Exception:
                        pass
                continue

            if ev["kind"] in ("video_frame", "audio_frame", "fragment") and not self._punch_locked:
                if self.relay_addr and addr == self.relay_addr:
                    self._use_relay = True
                else:
                    self._sender_addr = addr
                    self._use_relay = False
                self._punch_locked = True

            if ev["sqp_ack_pkt"] is not None and (mono_now - last_sqp_ack_sent >= 0.045):
                self._send_to_sender(ev["sqp_ack_pkt"])
                last_sqp_ack_sent = mono_now

            if ev["need_pli"]:
                self._request_pli()

            if kind == "audio_frame" and ev["audio_payload"] and self.on_audio:
                self.on_audio(ev["audio_frame_id"], ev["tx_ts_us"], ev["audio_payload"])

            elif kind == "video_frame" and ev["frame_bytes"]:
                if ev["is_keyframe"]:
                    awaiting_clean_idr = False
                elif ev.get("ref_gap"):
                    awaiting_clean_idr = True
                    awaiting_idr_since = mono_now
                    self._request_pli()
                elif awaiting_clean_idr:
                    if (mono_now - awaiting_idr_since) < 0.45:
                        self._request_pli()
                    else:
                        awaiting_clean_idr = False

                if not awaiting_clean_idr:
                    if self.on_encoded_frame is not None:
                        interval_frames += 1
                        cumulative_frames += 1
                        self.on_encoded_frame(
                            ev["frame_bytes"],
                            1920,
                            1080,
                            ev["tx_ts_us"],
                            ev["is_keyframe"],
                        )
                    if self.decoder is not None:
                        decoded_frames = self.decoder.decode_all(ev["frame_bytes"])
                        if decoded_frames:
                            if self.on_encoded_frame is None:
                                interval_frames += len(decoded_frames)
                                cumulative_frames += len(decoded_frames)
                            if self.on_frame:
                                for f in decoded_frames:
                                    self.on_frame(f)

            now = time.perf_counter()
            if now - last_stat_time >= 0.5:
                dt = now - last_stat_time
                fps = interval_frames / dt if dt > 0 else 0.0
                mbps = (interval_bytes * 8.0) / (dt * 1_000_000.0) if dt > 0 else 0.0
                if self.on_stats:
                    self.on_stats({
                        "fps": round(fps, 1),
                        "bitrate_mbps": round(mbps, 2),
                        "latency_ms": round(self.dp.latest_latency_ms or 1.5, 2),
                        "frames_count": cumulative_frames,
                        "packets_count": total_packets,
                        "fec_recovered": self.dp.fec_recovered_frames,
                        "pake_confirmed": self.dp.pake.confirmed,
                    })
                last_stat_time = now
                interval_frames = 0
                interval_bytes = 0
