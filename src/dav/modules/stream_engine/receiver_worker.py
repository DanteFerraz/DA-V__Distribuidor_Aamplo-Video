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

import collections
import logging
import socket
import threading
import time
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple
import numpy as np

from src.dav.modules.codec.base import BaseDecoder
from src.dav.modules.remote_desktop.protocol import (
    EvType,
    InputEventPacket,
    WsMsgType,
    unpack_input_echo,
)
from src.dav.modules.remote_desktop.security_gate import SecurityGate, WorkspacePermissions
from src.dav.modules.remote_desktop.workspace_agent import WorkspaceAgent
from src.dav.modules.telemetry.stage_probe import probe_send
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
        on_permissions_changed: Optional[Callable[[Dict[str, bool]], None]] = None,
        on_clipboard_rx: Optional[Callable[[str], None]] = None,
        on_file_status: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_shell_output: Optional[Callable[[str], None]] = None,
        on_input_echo: Optional[Callable[[float, float], None]] = None,
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
        self.on_permissions_changed = on_permissions_changed
        self.on_clipboard_rx = on_clipboard_rx
        self.on_file_status = on_file_status
        self.on_shell_output = on_shell_output
        self.on_input_echo = on_input_echo

        try:
            self.sock.settimeout(0.015)
        except Exception:
            pass
        try:
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0xB8)
        except Exception:
            pass
        if hasattr(socket, "SO_PRIORITY"):
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_PRIORITY, 6)
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
        self.peer_permissions = WorkspacePermissions()
        self.latest_input_rtt_ms: float = 0.0
        self.latest_input_to_photon_ms: float = 0.0
        self._last_input_sent_mono: float = 0.0
        self._last_buttons_mask: int = 0
        self._redundant_queue: Deque[Tuple[float, bytes]] = collections.deque(maxlen=32)

        self._ws_gate = SecurityGate(
            WorkspacePermissions(
                allow_input=True,
                allow_clipboard=True,
                allow_files=True,
                allow_shell=True,
            )
        )
        self.workspace_agent = WorkspaceAgent(
            gate=self._ws_gate,
            on_clipboard_rx=self.on_clipboard_rx,
            on_file_status=self.on_file_status,
            on_shell_output=self.on_shell_output,
            send_wire_fn=self.send_workspace_raw,
        )

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="DAV-Receiver-Loop")
        self._thread.start()

    def stop(self) -> None:
        if self._running and self.dp.pake.confirmed and self.peer_permissions.allow_input:
            try:
                rel_pkt = InputEventPacket(ev_type=EvType.RELEASE_ALL)
                dgram = self.dp.build_input_datagram(rel_pkt.pack())
                if dgram:
                    self._send_to_sender(dgram)
            except Exception:
                pass
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)
        try:
            self.workspace_agent.close()
        except Exception:
            pass
        if self.decoder is not None:
            try:
                self.decoder.close()
            except Exception:
                pass
        try:
            self.sock.close()
        except Exception:
            pass

    def send_remote_input(self, pkt: InputEventPacket) -> bool:
        """Empacota e envia evento PT_INPUT em < 0.1 ms no mesmo socket UDP."""
        if not self._running or not self.dp.pake.confirmed:
            return False
        if not self.peer_permissions.allow_input and pkt.ev_type != EvType.RELEASE_ALL:
            return False
        if pkt.client_ts_us <= 0:
            pkt.client_ts_us = int(time.perf_counter_ns() // 1000)
        raw_24b = pkt.pack()
        dgram = self.dp.build_input_datagram(raw_24b)
        if dgram is None:
            return False
        self._send_to_sender(dgram)
        self._last_input_sent_mono = time.monotonic()
        self._last_buttons_mask = int(pkt.buttons_mask)
        if pkt.is_critical_transition:
            self._redundant_queue.append((self._last_input_sent_mono + 0.002, raw_24b))
        return True

    def send_workspace_raw(self, ws_frame: bytes) -> bool:
        if not self._running or not self.dp.pake.confirmed or not ws_frame:
            return False
        dgram = self.dp.build_workspace_datagram(ws_frame)
        if dgram is None:
            return False
        self._send_to_sender(dgram)
        return True

    def send_clipboard_text(self, text: str) -> bool:
        if not self.peer_permissions.allow_clipboard or not self.dp.pake.confirmed:
            return False
        return bool(self.workspace_agent.build_clipboard_frames(text))

    def send_file(self, file_path: str) -> Optional[str]:
        if not self.peer_permissions.allow_files or not self.dp.pake.confirmed:
            return None
        tid, _ = self.workspace_agent.build_file_transfer_frames(file_path)
        return tid

    def send_shell_input(self, command_text: str) -> bool:
        if not self.peer_permissions.allow_shell or not self.dp.pake.confirmed:
            return False
        return self.workspace_agent.send_shell_input(command_text) is not None

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
        last_ws_housekeeping = 0.0
        last_input_hb = 0.0

        while self._running:
            mono_now = time.monotonic()
            # Envia copias redundantes de transicoes criticas (cliques/teclas) apos 2 ms
            while self._redundant_queue and mono_now >= self._redundant_queue[0][0]:
                _, raw_24b = self._redundant_queue.popleft()
                dup_dgram = self.dp.build_input_datagram(raw_24b)
                if dup_dgram:
                    self._send_to_sender(dup_dgram)

            if self.dp.pake.confirmed and (mono_now - last_ws_housekeeping >= 0.025):
                last_ws_housekeeping = mono_now
                for rf in self.workspace_agent.channel.poll_retransmits(now_mono=mono_now):
                    self.send_workspace_raw(rf)
                if (
                    self.peer_permissions.allow_input
                    and self._last_input_sent_mono > 0.0
                    and (mono_now - self._last_input_sent_mono) <= 3.0
                    and (mono_now - last_input_hb) >= 0.15
                ):
                    last_input_hb = mono_now
                    hb = InputEventPacket(
                        ev_type=EvType.HEARTBEAT,
                        buttons_mask=self._last_buttons_mask,
                        client_ts_us=int(time.perf_counter_ns() // 1000),
                    )
                    hb_dgram = self.dp.build_input_datagram(hb.pack())
                    if hb_dgram:
                        self._send_to_sender(hb_dgram)
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

            if ev["kind"] in ("video_frame", "audio_frame", "fragment", "workspace_msg") and not self._punch_locked:
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

            if kind == "workspace_msg" and ev["workspace_payload"]:
                delivered = self.workspace_agent.handle_incoming_wire(ev["workspace_payload"], is_host=False)
                for msg in delivered:
                    if msg.msg_type == WsMsgType.PERM_UPDATE:
                        p_dict = msg.decode_json() or {}
                        self.peer_permissions = WorkspacePermissions.from_dict(p_dict)
                        if self.on_permissions_changed:
                            self.on_permissions_changed(self.peer_permissions.to_dict())
                    elif msg.msg_type == WsMsgType.INPUT_ECHO:
                        echo_vals = unpack_input_echo(msg.payload)
                        if echo_vals is not None:
                            client_ts_us, _ = echo_vals
                            now_us = int(time.perf_counter_ns() // 1000)
                            rtt_ms = max(0.15, (now_us - client_ts_us) / 1000.0)
                            if rtt_ms < 2000.0:
                                if self.latest_input_rtt_ms <= 0.0:
                                    self.latest_input_rtt_ms = rtt_ms
                                else:
                                    self.latest_input_rtt_ms = 0.65 * self.latest_input_rtt_ms + 0.35 * rtt_ms
                                vid_owd = max(1.2, self.dp.latest_latency_ms or 1.8)
                                # Input-to-Photon = meia ida input + captura/encode/decode pipeline + volta video
                                itp_ms = (self.latest_input_rtt_ms * 0.5) + vid_owd + 6.2
                                self.latest_input_to_photon_ms = round(itp_ms, 2)
                                t_now_p = time.perf_counter()
                                probe_send(
                                    "input",
                                    t_now_p - (itp_ms / 1000.0),
                                    t_now_p,
                                    0,
                                    extra={"rtt_ms": round(self.latest_input_rtt_ms, 2)},
                                )
                                if self.on_input_echo:
                                    self.on_input_echo(
                                        round(self.latest_input_rtt_ms, 2),
                                        self.latest_input_to_photon_ms,
                                    )
                continue

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
                        "input_rtt_ms": round(self.latest_input_rtt_ms, 2),
                        "input_to_photon_ms": round(self.latest_input_to_photon_ms, 2),
                    })
                last_stat_time = now
                interval_frames = 0
                interval_bytes = 0
