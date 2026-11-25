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
    WsMsgType,
    pack_input_echo,
)
from src.dav.modules.remote_desktop.security_gate import SecurityGate, WorkspacePermissions
from src.dav.modules.remote_desktop.service import RemoteDesktopService
from src.dav.modules.remote_desktop.workspace_agent import WorkspaceAgent
from src.dav.modules.transport_p2p.blind_relay import wrap_relay_packet
from src.dav.modules.transport_p2p.candidates import is_lan_address
from src.dav.modules.transport_p2p.crypto_pake import MAGIC_PAKE_ACK, MAGIC_PAKE_SYN
from src.dav.modules.transport_p2p.data_plane import DataPlaneSender
from src.dav.modules.transport_p2p.packetizer import MAGIC_ACK, MAGIC_PLI, MAGIC_SYN
from src.dav.modules.universal_input.gamepad_virtual_hub import VirtualGamepadHub
from src.dav.modules.universal_input.models import (
    ClientKeyboardProfileDTO,
    GamepadStateDTO,
    RumbleAckDTO,
    RumbleRequestDTO,
)

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
        self._extra_peers: Dict[bytes, Dict[str, Any]] = {}
        self._pending_extra_dp: Optional[DataPlaneSender] = None
        self.client_keyboard_profiles: Dict[str, Dict[str, str]] = {}

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

        self.gamepad_hub = VirtualGamepadHub(
            on_rumble_to_peer=self._send_rumble_to_peer,
            on_roster_changed=lambda roster: self._emit_remote("gamepad_roster", roster),
        )

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
            self.gamepad_hub.close()
        except Exception:
            pass
        for entry in list(self._extra_peers.values()):
            try:
                entry["ws_agent"].close()
            except Exception:
                pass
        self._extra_peers.clear()
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

    def has_any_confirmed_peer(self) -> bool:
        if self.dp.pake.confirmed:
            return True
        return any(e["dp"].pake.confirmed for e in self._extra_peers.values())

    def _send_to_addr(self, pkt: bytes, addr: Optional[Tuple[str, int]]) -> None:
        if not addr:
            return
        if self.relay_addr and addr == self.relay_addr:
            try:
                self.sock.sendto(wrap_relay_packet(self.clean_pin, b"S", pkt), self.relay_addr)
            except OSError:
                pass
            return
        try:
            self.sock.sendto(pkt, addr)
        except OSError:
            pass

    def _create_extra_peer_entry(self, peer_nonce: bytes, addr: Tuple[str, int], dp_inst: Optional[DataPlaneSender] = None) -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            "peer_id": f"peer:{peer_nonce.hex()[:12]}",
            "addr": (addr[0], int(addr[1])),
            "last_seen": time.monotonic(),
        }
        dp_obj = dp_inst or DataPlaneSender(
            pin=self.pin,
            send_raw_fn=lambda raw, ep=entry: self._send_to_addr(raw, ep["addr"]),
            initial_bitrate_kbps=self.encoder.bitrate_kbps,
            fps=self.capturer.fps,
        )
        dp_obj.pacer._send_fn = lambda raw, ep=entry: self._send_to_addr(raw, ep["addr"])
        ws_obj = WorkspaceAgent(
            gate=self.security_gate,
            on_clipboard_rx=lambda txt: self._emit_remote("clipboard", txt),
            on_file_status=lambda st: self._emit_remote("file_status", st),
            send_wire_fn=lambda wf, d=dp_obj: d.send_workspace_datagram(wf),
        )
        entry["dp"] = dp_obj
        entry["ws_agent"] = ws_obj
        return entry

    def _send_rumble_to_peer(self, peer_id: str, rumble_payload: bytes) -> None:
        if peer_id == "peer:primary":
            if self.dp.pake.confirmed:
                wf = self.workspace_agent.channel.send_unreliable(WsMsgType.GAMEPAD_RUMBLE, rumble_payload)
                self.dp.send_workspace_datagram(wf)
            return
        for entry in self._extra_peers.values():
            if entry["peer_id"] == peer_id and entry["dp"].pake.confirmed:
                wf = entry["ws_agent"].channel.send_unreliable(WsMsgType.GAMEPAD_RUMBLE, rumble_payload)
                entry["dp"].send_workspace_datagram(wf)
                return

    def _broadcast_permissions_all(self) -> None:
        if self.dp.pake.confirmed:
            self.workspace_agent.broadcast_permissions()
        for entry in self._extra_peers.values():
            if entry["dp"].pake.confirmed:
                entry["ws_agent"].broadcast_permissions()

    def trigger_gamepad_rumble_test(self, host_slot: Optional[int] = None) -> bool:
        dispatches = self.gamepad_hub.trigger_test_rumble(host_slot=host_slot)
        if host_slot is None and not dispatches:
            raw_req = RumbleRequestDTO(
                local_slot=0xFF,
                is_test_pulse=True,
                low_freq_u16=52000,
                high_freq_u16=38000,
                duration_ms=500,
            ).pack()
            sent_any = False
            if self.dp.pake.confirmed:
                self._send_rumble_to_peer("peer:primary", raw_req)
                sent_any = True
            for entry in self._extra_peers.values():
                if entry["dp"].pake.confirmed:
                    self._send_rumble_to_peer(entry["peer_id"], raw_req)
                    sent_any = True
            return sent_any
        return bool(dispatches)

    def set_remote_permissions(self, **perms: bool) -> Dict[str, bool]:
        updated = self.security_gate.update_permissions(**perms)
        if not updated.allow_input and self.input_injector is not None:
            self.input_injector.release_all()
        if not updated.allow_gamepad:
            self.gamepad_hub.release_all_neutral()
        self._broadcast_permissions_all()
        snap = updated.to_dict()
        self._emit_remote("permissions", snap)
        return snap

    def panic_revoke_remote(self) -> Dict[str, bool]:
        updated = self.security_gate.panic_revoke_all()
        if self.input_injector is not None:
            self.input_injector.release_all()
        self.gamepad_hub.release_all_neutral()
        self._broadcast_permissions_all()
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
        if relay_info and relay_info.get("host") and relay_info.get("port"):
            self.relay_addr = (str(relay_info["host"]), int(relay_info["port"]))
        if self.dp.pake.confirmed:
            self._pending_extra_dp = DataPlaneSender(
                pin=self.pin,
                send_raw_fn=lambda _raw: None,
                initial_bitrate_kbps=self.encoder.bitrate_kbps,
                fps=self.capturer.fps,
            )
            syn_ex = self._pending_extra_dp.build_pake_syn()
            for cip, cport, _ in candidates:
                self._send_to_addr(syn_ex, (cip, int(cport)))
            return
        self.candidates = list(candidates)
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
                if self._audio_muted or not self._is_streaming_active or not self.has_any_confirmed_peer():
                    continue
                use_lbrr = self.dp.sqp.loss_rate > 0.002
                enc_pkt = self.audio_encoder.encode(pcm, lbrr_active=use_lbrr)
                if enc_pkt:
                    if self.dp.pake.confirmed:
                        self.dp.send_audio_frame(enc_pkt, is_lbrr=use_lbrr)
                    for entry in self._extra_peers.values():
                        if entry["dp"].pake.confirmed:
                            entry["dp"].send_audio_frame(enc_pkt, is_lbrr=use_lbrr)
            except Exception:
                time.sleep(0.05)

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

            if self.has_any_confirmed_peer() and self._is_streaming_active:
                if self.capturer.grab_into(self._frame_buffer):
                    payload = self.encoder.encode(self._frame_buffer)
                    if payload:
                        total_frames += 1
                        is_kf = self.encoder.last_frame_was_keyframe or (total_frames == 1)
                        pkts = 0
                        f_bytes = 0
                        if self.dp.pake.confirmed:
                            p1, b1, _ = self.dp.send_video_frame(
                                payload,
                                is_keyframe=is_kf,
                                frame_interval_sec=frame_interval,
                                pir_mode=False,
                                stop_check=lambda: not self._running,
                            )
                            pkts += p1
                            f_bytes += b1
                        for entry in self._extra_peers.values():
                            if entry["dp"].pake.confirmed:
                                pe, be, _ = entry["dp"].send_video_frame(
                                    payload,
                                    is_keyframe=is_kf,
                                    frame_interval_sec=frame_interval,
                                    pir_mode=False,
                                    stop_check=lambda: not self._running,
                                )
                                pkts += pe
                                f_bytes += be
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
                    for entry in list(self._extra_peers.values()):
                        if entry["dp"].pake.confirmed:
                            for rf in entry["ws_agent"].channel.poll_retransmits(now_mono=now_m):
                                entry["dp"].send_workspace_datagram(rf)
            except Exception:
                time.sleep(0.002)

    def _poll_incoming_control(self) -> None:
        if not self._ctrl_lock.acquire(blocking=False):
            return
        try:
            self._poll_incoming_control_unlocked()
        finally:
            self._ctrl_lock.release()

    def _handle_host_ws_messages(self, peer_id: str, accepted_msgs: list) -> None:
        for msg in accepted_msgs:
            if msg.msg_type == WsMsgType.CLIENT_INPUT_PROFILE:
                d = msg.decode_json() or {}
                prof = ClientKeyboardProfileDTO.from_dict(d).to_dict()
                self.client_keyboard_profiles[peer_id] = prof
                self._emit_remote("client_kb_profile", {"peer_id": peer_id, **prof})
            elif msg.msg_type == WsMsgType.GAMEPAD_RUMBLE_ACK:
                ack = RumbleAckDTO.from_json_bytes(msg.payload)
                if ack is not None:
                    now_us = int(time.perf_counter_ns() // 1000)
                    rtt_ms = max(0.1, (now_us - ack.sent_ts_us) / 1000.0) if ack.sent_ts_us > 0 else 0.5
                    self._emit_remote(
                        "gamepad_rumble_ack",
                        {
                            "peer_id": peer_id,
                            "local_slot": ack.local_slot,
                            "ok": ack.ok,
                            "request_id": ack.request_id,
                            "rtt_ms": round(rtt_ms, 2),
                            "device_name": ack.device_name,
                            "backend": ack.backend,
                        },
                    )

    def _process_remote_input_bytes(self, peer_id: str, dp_ref: DataPlaneSender, raw_24b: bytes) -> None:
        in_pkt = InputEventPacket.unpack(raw_24b)
        if in_pkt is None or not self.security_gate.allow_input_packet(in_pkt):
            return
        if in_pkt.ev_type == EvType.GAMEPAD_STATE:
            gp_state = GamepadStateDTO.from_packet_fields(
                in_pkt.buttons_mask,
                in_pkt.modifiers_mask,
                in_pkt.x_val,
                in_pkt.y_val,
                in_pkt.key_or_wheel,
                in_pkt.client_ts_us,
            )
            self.gamepad_hub.handle_gamepad_state(peer_id, gp_state)
        else:
            if self.input_injector is not None:
                self.input_injector.inject(in_pkt)

        self._echo_counter += 1
        if (
            in_pkt.is_critical_transition
            or in_pkt.ev_type == EvType.HEARTBEAT
            or (self._echo_counter & 0x07) == 0
        ) and in_pkt.client_ts_us > 0:
            dp_ref.send_workspace_datagram(pack_input_echo(in_pkt.client_ts_us))
        if in_pkt.is_critical_transition or in_pkt.ev_type in (EvType.WHEEL, EvType.GAMEPAD_STATE):
            self._input_wake_evt.set()

    def _poll_incoming_control_unlocked(self) -> None:
        while True:
            try:
                pkt, addr = self.sock.recvfrom(4096)
            except (BlockingIOError, OSError):
                break
            if not pkt:
                continue

            is_pake_pkt = (
                (pkt.startswith(MAGIC_PAKE_SYN) and len(pkt) == 65)
                or (pkt.startswith(MAGIC_PAKE_ACK) and len(pkt) == 81)
            )
            if is_pake_pkt:
                p_nonce = pkt[17:33]
                is_primary_peer = (
                    not self.dp.pake.confirmed
                    or self.dp.pake.peer_nonce is None
                    or self.dp.pake.peer_nonce == p_nonce
                )
                if not is_primary_peer:
                    extra_entry = self._extra_peers.get(p_nonce)
                    if extra_entry is None and len(self._extra_peers) < 3:
                        dp_seed = self._pending_extra_dp
                        self._pending_extra_dp = None
                        extra_entry = self._create_extra_peer_entry(p_nonce, addr, dp_inst=dp_seed)
                        self._extra_peers[p_nonce] = extra_entry
                    if extra_entry is not None:
                        extra_entry["addr"] = (addr[0], int(addr[1]))
                        extra_entry["last_seen"] = time.monotonic()
                        ex_evt, ex_reply = extra_entry["dp"].handle_incoming_packet(pkt)
                        if ex_reply is not None:
                            self._send_to_addr(ex_reply, extra_entry["addr"])
                        if ex_evt == "pake_confirmed":
                            self._is_streaming_active = True
                            try:
                                self.encoder.request_keyframe(force=True)
                            except TypeError:
                                self.encoder.request_keyframe()
                            extra_entry["ws_agent"].broadcast_permissions()
                    continue

            handled_by_extra = False
            if not is_pake_pkt and self._extra_peers:
                for extra_entry in self._extra_peers.values():
                    if extra_entry["addr"] == addr:
                        ex_evt, ex_payload = extra_entry["dp"].handle_incoming_packet(pkt)
                        if ex_evt != "other":
                            extra_entry["last_seen"] = time.monotonic()
                            handled_by_extra = True
                            if ex_evt == "remote_input" and ex_payload is not None:
                                self._process_remote_input_bytes(extra_entry["peer_id"], extra_entry["dp"], ex_payload)
                            elif ex_evt == "workspace_msg" and ex_payload is not None:
                                msgs = extra_entry["ws_agent"].handle_incoming_wire(ex_payload, is_host=True)
                                self._handle_host_ws_messages(extra_entry["peer_id"], msgs)
                            break
            if handled_by_extra:
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
                self._process_remote_input_bytes("peer:primary", self.dp, reply_ack)
                continue
            elif evt == "workspace_msg" and reply_ack is not None:
                msgs = self.workspace_agent.handle_incoming_wire(reply_ack, is_host=True)
                self._handle_host_ws_messages("peer:primary", msgs)
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
