# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Motor de Transmissao Modular em Thread (SenderWorker) — DA-V v4.6
Autor: Dante Ferraz (MonoTech)

Usa o DataPlaneSender unificado: Handshake PAKE (CPace-X25519), AEAD ChaCha20-Poly1305,
FEC sistematico GF(2^8), controle de congestionamento SQP+Salsify, MicroPacer e Audio TX.
"""

from __future__ import annotations

import logging
import select
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np

from src.dav.modules.capture.base import BaseCapturer
from src.dav.modules.codec.encoder import VideoEncoder
from src.dav.modules.remote_desktop.protocol import (
    EvType,
    InputEventPacket,
    pack_input_echo,
)
from src.dav.modules.remote_desktop.security_gate import SecurityGate, WorkspacePermissions
from src.dav.modules.remote_desktop.service import RemoteDesktopService
from src.dav.modules.remote_desktop.workspace_agent import WorkspaceAgent
from src.dav.modules.transport_p2p.blind_relay import wrap_relay_packet
from src.dav.modules.transport_p2p.candidates import is_lan_address
from src.dav.modules.transport_p2p.data_plane import DataPlaneSender
from src.dav.modules.transport_p2p.packetizer import MAGIC_ACK, MAGIC_PLI, MAGIC_SYN

logger = logging.getLogger("DAV.StreamEngine.Sender")


class SenderWorker:
    """Controlador de streaming ativo no lado transmissor sobre o Data Plane v4.6."""

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
        audio_capturer: Optional[Any] = None,
        audio_encoder: Optional[Any] = None,
        audio_enabled: bool = False,
        input_injector: Optional[Any] = None,
        security_gate: Optional[SecurityGate] = None,
        workspace_agent: Optional[WorkspaceAgent] = None,
        initial_permissions: Optional[Dict[str, bool]] = None,
        on_remote_event: Optional[Callable[[str, Any], None]] = None,
    ):
        self.sock = sock
        self.capturer = capturer
        self.encoder = encoder
        self.pin = pin
        self.clean_pin = pin.replace("-", "").replace(" ", "").strip()
        self.target_ip = target_ip
        self.target_port = target_port
        self._target_ep: Optional[Tuple[str, int]] = (
            (str(target_ip).strip(), int(target_port)) if target_ip else None
        )
        self.candidates = list(candidates or [])
        self.relay_addr = relay_addr
        self.on_route_locked = on_route_locked
        self.on_stats = on_stats
        self.on_remote_event = on_remote_event

        self.audio_capturer = audio_capturer
        self.audio_encoder = audio_encoder
        self._audio_muted = not bool(audio_enabled)

        try:
            self.sock.setblocking(False)
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
        self._ctrl_thread: Optional[threading.Thread] = None
        self._audio_thread: Optional[threading.Thread] = None
        self._ctrl_lock = threading.Lock()
        self._input_wake_evt = threading.Event()
        self._punch_locked = False
        self._use_relay = False
        self._is_streaming_active = bool(target_ip)
        self._frame_buffer = np.zeros((capturer.height, capturer.width, 4), dtype=np.uint8)
        self._last_pake_probe = 0.0
        self._last_frame_sent_mono = 0.0
        self._echo_counter = 0
        self._pair_started_mono = time.monotonic() if candidates else 0.0

        self.dp = DataPlaneSender(
            pin=pin,
            send_raw_fn=self._send_packet,
            initial_bitrate_kbps=encoder.bitrate_kbps,
            fps=capturer.fps,
        )

        init_perms = WorkspacePermissions.from_dict(initial_permissions or {})
        self.security_gate = security_gate or SecurityGate(initial_perms=init_perms)
        if input_injector is not None:
            self.input_injector = input_injector
        else:
            rd_svc = RemoteDesktopService()
            inj_res = rd_svc.create_injector()
            self.input_injector = inj_res.data
        if self.input_injector is not None and getattr(self.input_injector, "is_elevated", False):
            self.security_gate.update_permissions(admin_elevated=True)

        self.workspace_agent = workspace_agent or WorkspaceAgent(
            gate=self.security_gate,
            on_clipboard_rx=lambda txt: self._emit_remote("clipboard", txt),
            on_file_status=lambda st: self._emit_remote("file_status", st),
            send_wire_fn=lambda wf: self.dp.send_workspace_datagram(wf),
        )
        if self.workspace_agent._send_wire is None:
            self.workspace_agent.set_send_wire_fn(lambda wf: self.dp.send_workspace_datagram(wf))

    def start(self) -> None:
        self._running = True
        self.capturer.start()
        self._ctrl_thread = threading.Thread(target=self._control_rx_loop, daemon=True, name="DAV-Sender-CtrlRX")
        self._ctrl_thread.start()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="DAV-Sender-Loop")
        self._thread.start()
        if self.audio_capturer is not None and self.audio_encoder is not None:
            self._audio_thread = threading.Thread(target=self._audio_tx_loop, daemon=True, name="DAV-Sender-Audio")
            self._audio_thread.start()

    def stop(self) -> None:
        self._running = False
        try:
            self.sock.close()
        except Exception:
            pass
        if self._ctrl_thread and self._ctrl_thread.is_alive():
            self._ctrl_thread.join(timeout=0.3)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)
        if self._audio_thread and self._audio_thread.is_alive():
            self._audio_thread.join(timeout=0.4)
        try:
            self.workspace_agent.close()
        except Exception:
            pass
        if self.input_injector is not None:
            try:
                self.input_injector.close()
            except Exception:
                pass
        self.capturer.close()
        self.encoder.close()
        if self.audio_encoder is not None:
            try:
                self.audio_encoder.close()
            except Exception:
                pass
        if self.audio_capturer is not None:
            try:
                self.audio_capturer.close()
            except Exception:
                pass

    def set_audio_muted(self, muted: bool) -> None:
        self._audio_muted = bool(muted)

    def _emit_remote(self, kind: str, payload: Any) -> None:
        if self.on_remote_event is not None:
            try:
                self.on_remote_event(kind, payload)
            except Exception:
                pass

    def set_remote_permissions(self, **perms: bool) -> Dict[str, bool]:
        updated = self.security_gate.update_permissions(**perms)
        if not updated.allow_input and self.input_injector is not None:
            self.input_injector.release_all()
        if self.dp.pake.confirmed:
            self.workspace_agent.broadcast_permissions()
        snap = updated.to_dict()
        self._emit_remote("permissions", snap)
        return snap

    def panic_revoke_remote(self) -> Dict[str, bool]:
        updated = self.security_gate.panic_revoke_all()
        if self.input_injector is not None:
            self.input_injector.release_all()
        if self.dp.pake.confirmed:
            self.workspace_agent.broadcast_permissions()
        snap = updated.to_dict()
        self._emit_remote("permissions", snap)
        return snap

    def set_input_injector(self, new_injector: Any) -> None:
        old = self.input_injector
        self.input_injector = new_injector
        if old is not None and old is not new_injector:
            try:
                old.release_all()
            except Exception:
                pass
        is_elev = bool(new_injector is not None and getattr(new_injector, "is_elevated", False))
        self.set_remote_permissions(admin_elevated=is_elev)

    def send_clipboard_text(self, text: str) -> bool:
        if not self.security_gate.permissions.allow_clipboard or not self.dp.pake.confirmed:
            return False
        return bool(self.workspace_agent.build_clipboard_frames(text))

    def send_file(self, file_path: str) -> Optional[str]:
        if not self.security_gate.permissions.allow_files or not self.dp.pake.confirmed:
            return None
        tid, _ = self.workspace_agent.build_file_transfer_frames(file_path)
        return tid

    def update_target(self, new_ip: str, new_port: int) -> None:
        clean_ip = str(new_ip).strip()
        port_i = int(new_port)
        self.target_ip = clean_ip
        self.target_port = port_i
        self._target_ep = (clean_ip, port_i) if clean_ip else None
        self._use_relay = False
        self._punch_locked = False
        if clean_ip:
            self._is_streaming_active = True
            self._send_punch_burst()

    def request_keyframe(self) -> None:
        self.encoder.request_keyframe()

    def pair_peer(self, candidates: List[Tuple[str, int, str]], relay_info: Optional[Dict[str, Any]] = None) -> None:
        self.candidates = list(candidates)
        if relay_info and relay_info.get("host") and relay_info.get("port"):
            self.relay_addr = (str(relay_info["host"]), int(relay_info["port"]))
        self._pair_started_mono = time.monotonic()
        self._send_punch_burst()

    def _send_lan_upgrade_probe(self) -> None:
        syn = self.dp.build_pake_syn()
        for ip, port, _ in self.candidates:
            if is_lan_address(ip) or str(ip).startswith("100."):
                try:
                    self.sock.sendto(syn, (ip, port))
                except Exception:
                    pass
        self._last_pake_probe = time.monotonic()

    def _send_punch_burst(self) -> None:
        syn = self.dp.build_pake_syn()
        for ip, port, _ in self.candidates:
            try:
                self.sock.sendto(syn, (ip, port))
            except Exception:
                pass
        if self._use_relay and self.relay_addr:
            try:
                self.sock.sendto(wrap_relay_packet(self.clean_pin, b"S", syn), self.relay_addr)
            except Exception:
                pass
        self._last_pake_probe = time.monotonic()

    def _audio_tx_loop(self) -> None:
        while self._running:
            try:
                pcm = self.audio_capturer.read_frame(timeout=0.025)
                if pcm is None:
                    continue
                if self._audio_muted or not self._is_streaming_active or not self.dp.pake.confirmed:
                    continue
                use_lbrr = self.dp.sqp.loss_rate > 0.002
                enc_pkt = self.audio_encoder.encode(pcm, lbrr_active=use_lbrr)
                if enc_pkt:
                    self.dp.send_audio_frame(enc_pkt, is_lbrr=use_lbrr)
            except Exception:
                break

    def _run_loop(self) -> None:
        frame_interval = 1.0 / float(max(1, self.capturer.fps))
        t_target = time.perf_counter() + frame_interval
        total_frames = 0
        total_packets = 0
        total_bytes = 0
        last_stat_time = time.perf_counter()

        while self._running:
            self._poll_incoming_control()

            if not self.dp.pake.confirmed and (time.monotonic() - self._last_pake_probe >= 0.04):
                if self.target_ip:
                    self._send_packet(self.dp.build_pake_syn())
                    self._last_pake_probe = time.monotonic()
                elif self.candidates or self._use_relay:
                    self._send_punch_burst()
            elif (
                self.dp.pake.confirmed
                and self.candidates
                and (time.monotonic() - getattr(self, "_pair_started_mono", 0.0) <= 6.0)
                and (self._use_relay or not is_lan_address(self.target_ip))
                and (time.monotonic() - self._last_pake_probe >= 0.20)
            ):
                self._send_lan_upgrade_probe()

            if self.dp.pake.confirmed and self._is_streaming_active:
                if self.capturer.grab_into(self._frame_buffer):
                    payload = self.encoder.encode(self._frame_buffer)
                    if payload:
                        total_frames += 1
                        is_kf = self.encoder.last_frame_was_keyframe or (total_frames == 1)
                        pkts, f_bytes, _ = self.dp.send_video_frame(
                            payload,
                            is_keyframe=is_kf,
                            frame_interval_sec=frame_interval,
                            pir_mode=False,
                            stop_check=lambda: not self._running,
                        )
                        self._last_frame_sent_mono = time.perf_counter()
                        total_packets += pkts
                        total_bytes += f_bytes

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
                        "sqp_bps": int(self.dp.sqp.estimated_bps),
                        "fec_shards": self.dp.fec_shards_sent,
                        "pake_confirmed": self.dp.pake.confirmed,
                    })
                last_stat_time = now
                total_frames = 0
                total_bytes = 0

            slack = t_target - time.perf_counter()
            if slack > 0.002:
                woke = self._input_wake_evt.wait(timeout=slack - 0.001)
                if woke:
                    self._input_wake_evt.clear()
                    if (time.perf_counter() - self._last_frame_sent_mono) >= 0.0075:
                        t_target = time.perf_counter()
            while time.perf_counter() < t_target and not self._input_wake_evt.is_set():
                pass
            if self._input_wake_evt.is_set():
                self._input_wake_evt.clear()
                t_target = time.perf_counter() + frame_interval
            else:
                t_target = max(t_target + frame_interval, time.perf_counter())

    def _control_rx_loop(self) -> None:
        last_housekeeping = time.monotonic()
        while self._running:
            try:
                rlist, _, _ = select.select([self.sock], [], [], 0.002)
                if rlist or not self.dp.pake.confirmed:
                    self._poll_incoming_control()
                now_m = time.monotonic()
                if (now_m - last_housekeeping) >= 0.025:
                    last_housekeeping = now_m
                    if self.input_injector is not None:
                        self.input_injector.tick_watchdog(now_mono=now_m)
                    if self.dp.pake.confirmed:
                        for rf in self.workspace_agent.channel.poll_retransmits(now_mono=now_m):
                            self.dp.send_workspace_datagram(rf)
            except Exception:
                time.sleep(0.002)

    def _poll_incoming_control(self) -> None:
        if not self._ctrl_lock.acquire(blocking=False):
            return
        try:
            self._poll_incoming_control_unlocked()
        finally:
            self._ctrl_lock.release()

    def _poll_incoming_control_unlocked(self) -> None:
        while True:
            try:
                pkt, addr = self.sock.recvfrom(4096)
            except (BlockingIOError, OSError):
                break
            if not pkt:
                continue

            evt, reply_ack = self.dp.handle_incoming_packet(pkt)
            if evt in ("pake_confirmed", "pake_ack"):
                if not self._punch_locked or self._use_relay or (
                    self.target_ip and not is_lan_address(self.target_ip) and is_lan_address(addr[0])
                ):
                    new_ip, new_port = addr[0], int(addr[1])
                    self._target_ep = (new_ip, new_port)
                    self.target_ip, self.target_port = new_ip, new_port
                    self._punch_locked = True
                    self._use_relay = False
                    self._is_streaming_active = True
                    mode_tag = "LAN Direto" if is_lan_address(new_ip) else "WAN P2P Direto"
                    if self.on_route_locked:
                        self.on_route_locked(new_ip, new_port, mode_tag)
                if reply_ack is not None:
                    try:
                        self.sock.sendto(reply_ack, addr)
                    except Exception:
                        pass
                if evt == "pake_confirmed":
                    try:
                        self.encoder.request_keyframe(force=True)
                    except TypeError:
                        self.encoder.request_keyframe()
                    self.workspace_agent.broadcast_permissions()
                continue
            elif evt == "remote_input" and reply_ack is not None:
                in_pkt = InputEventPacket.unpack(reply_ack)
                if in_pkt is not None and self.security_gate.allow_input_packet(in_pkt):
                    if self.input_injector is not None:
                        self.input_injector.inject(in_pkt)
                    self._echo_counter += 1
                    if (
                        in_pkt.is_critical_transition
                        or in_pkt.ev_type == EvType.HEARTBEAT
                        or (self._echo_counter & 0x07) == 0
                    ) and in_pkt.client_ts_us > 0:
                        self.dp.send_workspace_datagram(pack_input_echo(in_pkt.client_ts_us))
                    if in_pkt.is_critical_transition or in_pkt.ev_type == EvType.WHEEL:
                        self._input_wake_evt.set()
                continue
            elif evt == "workspace_msg" and reply_ack is not None:
                self.workspace_agent.handle_incoming_wire(reply_ack, is_host=True)
                continue
            elif evt == "sqp_ack":
                continue

            if pkt.startswith(MAGIC_PLI):
                try:
                    self.encoder.request_keyframe(force=True)
                except TypeError:
                    self.encoder.request_keyframe()
            elif pkt in (b"DAV_RLY_ACK", b"DAV_RLY_PEER_READY"):
                if not self._punch_locked and self.relay_addr:
                    self._use_relay = True
                    self._is_streaming_active = True
                    self._send_punch_burst()
                    if self.on_route_locked:
                        self.on_route_locked(self.relay_addr[0], self.relay_addr[1], "Blind Relay UDP")
            elif pkt.startswith(MAGIC_SYN) or pkt.startswith(MAGIC_ACK):
                try:
                    self.sock.sendto(self.dp.build_pake_syn(), addr)
                except Exception:
                    pass

    def _send_packet(self, pkt: bytes) -> None:
        if self._use_relay and self.relay_addr:
            wrapped = wrap_relay_packet(self.clean_pin, b"S", pkt)
            try:
                self.sock.sendto(wrapped, self.relay_addr)
            except OSError:
                pass
            return

        ep = self._target_ep
        if ep:
            try:
                self.sock.sendto(pkt, ep)
            except OSError:
                pass
