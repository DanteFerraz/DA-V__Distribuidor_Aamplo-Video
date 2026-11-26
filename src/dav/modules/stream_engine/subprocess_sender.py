# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Host de Transmissao em Subprocesso Isolado (GIL-Free Sender) — DA-V v4.6
Autor: Dante Ferraz (MonoTech)

Reside integralmente dentro da fatia `src.dav.modules.stream_engine`, consumindo
apenas as fatias `capture`, `codec`, `transport_p2p`, `audio` e `telemetry`.
"""

from __future__ import annotations

import collections
import ctypes
import json
import multiprocessing as mp
import os
import queue
import select
import socket
import sys
import threading
import time
from ctypes import wintypes
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.dav.modules.audio.capturer import create_audio_capturer
from src.dav.modules.audio.codec_opus import OpusAudioEncoder
from src.dav.modules.capture.service import enumerate_system_monitors
from src.dav.modules.capture.wayland_portal import WaylandPortalCapturer, is_wayland_session
from src.dav.modules.codec.encoder import VideoEncoder
from src.dav.modules.remote_desktop.injector_base import MonitorBounds
from src.dav.modules.remote_desktop.protocol import (
    EvType,
    InputEventPacket,
    WsMsgType,
    pack_input_echo,
)
from src.dav.modules.remote_desktop.security_gate import SecurityGate, WorkspacePermissions
from src.dav.modules.remote_desktop.service import RemoteDesktopService
from src.dav.modules.remote_desktop.workspace_agent import WorkspaceAgent
from src.dav.modules.telemetry.stage_probe import probe_init, probe_send as _probe_send
from src.dav.modules.transport_p2p.blind_relay import normalize_pin, unwrap_relay_packet, wrap_relay_packet
from src.dav.modules.transport_p2p.candidates import is_lan_address
from src.dav.modules.transport_p2p.crypto_pake import MAGIC_PAKE_ACK, MAGIC_PAKE_SYN
from src.dav.modules.transport_p2p.data_plane import DataPlaneSender
from src.dav.modules.transport_p2p.dualstack import (
    canonicalize_ip,
    create_dualstack_udp_socket,
    format_endpoint_display,
    format_url_host,
    is_ipv6_address,
    is_overlay_address,
    normalize_recv_addr,
    sendto_dualstack,
)
from src.dav.modules.transport_p2p.http_tunnel_relay import HttpTunnelRelayClient
from src.dav.modules.transport_p2p.packetizer import MAGIC_ACK, MAGIC_PLI, MAGIC_RLY, MAGIC_SYN
from src.dav.modules.universal_input.gamepad_virtual_hub import VirtualGamepadHub
from src.dav.modules.universal_input.models import (
    ClientKeyboardProfileDTO,
    GamepadStateDTO,
    RumbleAckDTO,
    RumbleRequestDTO,
)
from src.dav.modules.transport_p2p.service import disable_win_udp_connreset
from src.dav.modules.transport_p2p.signaling_client import (
    build_peer_candidates,
    discover_socket_endpoint,
    send_stun_keepalive,
)

try:
    import cv2
    cv2.setNumThreads(1)
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

try:
    from windows_capture import Frame, InternalCaptureControl, WindowsCapture
    _WGC_AVAILABLE = True
except ImportError:
    _WGC_AVAILABLE = False

THREAD_PRIORITY_TIME_CRITICAL = 15
THREAD_PRIORITY_HIGHEST = 2
HIGH_PRIORITY_CLASS = 0x00000080
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
PROCESS_ALL_ACCESS = 0x1F0FFF

k32 = None
if sys.platform == "win32":
    try:
        k32 = ctypes.windll.kernel32
        k32.GetCurrentThread.restype = wintypes.HANDLE
        k32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
        k32.SetThreadPriority.restype = wintypes.BOOL
        k32.SetThreadAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
        k32.SetThreadAffinityMask.restype = ctypes.c_size_t
        k32.GetCurrentProcessId.restype = wintypes.DWORD
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.SetPriorityClass.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass


def _elevate_process_priority(target_class: int = HIGH_PRIORITY_CLASS) -> None:
    if sys.platform == "win32" and k32 is not None:
        try:
            pid = k32.GetCurrentProcessId()
            h_proc = k32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
            if h_proc:
                k32.SetPriorityClass(h_proc, target_class)
                k32.CloseHandle(h_proc)
        except Exception:
            pass
    else:
        try:
            os.nice(-10)
        except Exception:
            pass


def _set_thread_perf(priority: int, core_affinity_mask: int) -> None:
    if sys.platform == "win32" and k32 is not None:
        try:
            h_thread = k32.GetCurrentThread()
            k32.SetThreadPriority(h_thread, priority)
            if core_affinity_mask > 0:
                k32.SetThreadAffinityMask(h_thread, core_affinity_mask)
        except Exception:
            pass
    elif hasattr(os, "sched_setaffinity") and core_affinity_mask > 0:
        try:
            cores = {i for i in range(64) if (core_affinity_mask & (1 << i))}
            if cores:
                os.sched_setaffinity(0, cores)
        except Exception:
            pass


class SenderTransportEndpoint:
    """
    Gerencia o descritor unico de socket UDP do Transmissor sobre o DataPlaneSender v4.6:
    - Realiza descoberta STUN RFC 5389 Single-Socket antes do loop nao-bloqueante.
    - Conduz Hole-Punching autenticado via PAKE (CPace-X25519) com forward secrecy.
    - Suporta fallback automatico para Blind Encrypted UDP Relay ('DAV_RLY1').
    - Recebe feedbacks SQP (gradiente OWD e perda) + pedidos PLI em tempo real.
    """

    def __init__(
        self,
        bind_port: int,
        initial_target_ip: str,
        initial_target_port: int,
        pin: str,
        is_streaming_active: threading.Event,
        cmd_queue: Optional["mp.Queue"] = None,
        evt_queue: Optional["mp.Queue"] = None,
        bitrate_kbps: int = 12000,
        fps: int = 60,
        audio_muted_evt: Optional[threading.Event] = None,
        monitor_bounds: Optional[MonitorBounds] = None,
        initial_permissions: Optional[Dict[str, bool]] = None,
        input_wake_evt: Optional[threading.Event] = None,
    ):
        self.clean_pin = normalize_pin(pin)
        self.target_ip = canonicalize_ip(str(initial_target_ip or "").strip()) if initial_target_ip else ""
        self.target_port = int(initial_target_port or bind_port or 9000)
        self._target_ep: Optional[Tuple[str, int]] = (
            (self.target_ip, self.target_port) if self.target_ip else None
        )
        self.is_streaming_active = is_streaming_active
        self.cmd_queue = cmd_queue
        self.evt_queue = evt_queue
        self.audio_muted_evt = audio_muted_evt
        self.input_wake_evt = input_wake_evt or threading.Event()
        self.monitor_bounds = monitor_bounds or MonitorBounds()

        self.candidates: List[Tuple[str, int, str]] = []
        self.relay_addr: Optional[Tuple[str, int]] = None
        self.relay_http_base_url: Optional[str] = None
        self.use_relay = False
        self.use_http_relay = False
        self._http_relay: Optional[HttpTunnelRelayClient] = None
        self._http_rx_queue: "collections.deque[bytes]" = collections.deque(maxlen=512)
        self.punch_locked = False
        self.punch_started_at = time.monotonic() if self.target_ip else 0.0
        self.last_punch_sent = 0.0
        self.last_lan_upgrade_sent = 0.0
        self.last_relay_bind = 0.0
        self.last_keepalive = time.monotonic()
        self._ctrl_lock = threading.Lock()
        self._active_encoder: Optional[VideoEncoder] = None
        self._echo_counter: int = 0
        self._elevating_lock = threading.Lock()
        self._elevating_in_progress = False

        self._pin_raw = pin
        self._bitrate_kbps = bitrate_kbps
        self._fps = fps
        self._extra_peers: Dict[bytes, Dict[str, Any]] = {}
        self._pending_extra_dp: Optional[DataPlaneSender] = None
        self._pending_extra_cands: List[Tuple[str, int, str]] = []
        self._pending_extra_started: float = 0.0
        self.client_keyboard_profiles: Dict[str, Dict[str, str]] = {}

        self.dp = DataPlaneSender(
            pin=pin,
            send_raw_fn=self.send_datagram,
            initial_bitrate_kbps=bitrate_kbps,
            fps=fps,
        )
        if self.target_ip:
            self.dp.set_target_mtu_for_ip(self.target_ip)

        self.rd_service = RemoteDesktopService()
        init_perms = WorkspacePermissions.from_dict(initial_permissions or {})
        self.security_gate = SecurityGate(initial_perms=init_perms)
        inj_res = self.rd_service.create_injector(bounds=self.monitor_bounds)
        self.input_injector = inj_res.data
        if self.input_injector is not None and getattr(self.input_injector, "is_elevated", False):
            self.security_gate.update_permissions(admin_elevated=True)

        self.workspace_agent = WorkspaceAgent(
            gate=self.security_gate,
            on_clipboard_rx=lambda txt: self._emit_event(("REMOTE_CLIPBOARD", txt)),
            on_file_status=lambda st: self._emit_event(("REMOTE_FILE_STATUS", st)),
            send_wire_fn=lambda wf: self.dp.send_workspace_datagram(wf),
        )
        self.gamepad_hub = VirtualGamepadHub(
            on_rumble_to_peer=self._send_rumble_to_peer,
            on_roster_changed=lambda roster: self._emit_event(("GAMEPAD_ROSTER", roster)),
        )

        desired_bind = int(bind_port or 9000)
        self.sock = create_dualstack_udp_socket(bind_port=desired_bind, rcvbuf_mb=8, sndbuf_mb=32)
        self.bound_port = int(self.sock.getsockname()[1])

        if self.evt_queue is not None and not self.target_ip:
            ep_info = discover_socket_endpoint(self.sock)
            try:
                self.evt_queue.put_nowait(("ENDPOINT_READY", ep_info))
            except Exception:
                pass
            bind_tag = "[::]" if self.sock.family == socket.AF_INET6 else "0.0.0.0"
            v6_extra = f" | IPv6: [{ep_info.get('public_ipv6')}]:{ep_info.get('public_ipv6_port')}" if ep_info.get("public_ipv6") else ""
            print(
                f"[Sender P2P] Socket UDP Dual-Stack vinculado em {bind_tag}:{self.bound_port} "
                f"| STUN Publico: {ep_info.get('public_ip')}:{ep_info.get('public_port')} ({ep_info.get('nat_type')}){v6_extra}"
            )
        else:
            print(f"[Sender] Socket UDP Dual-Stack ativo na porta local {self.bound_port}.")
            if self.evt_queue is not None:
                try:
                    self.evt_queue.put_nowait((
                        "ENDPOINT_READY",
                        {"local_port": self.bound_port, "public_port": self.bound_port, "nat_type": "direct"},
                    ))
                except Exception:
                    pass

        self.sock.setblocking(False)

    def _emit_event(self, payload: tuple):
        if self.evt_queue is not None:
            try:
                self.evt_queue.put_nowait(payload)
            except Exception:
                pass

    def attach_wayland_portal(self, portal_cap: WaylandPortalCapturer) -> None:
        """Conecta a ponte de injecao XDG RemoteDesktop caso o processo nao esteja usando uinput elevado."""
        if self.input_injector is not None and getattr(self.input_injector, "is_elevated", False):
            return
        res = self.rd_service.create_injector(
            bounds=self.monitor_bounds,
            wayland_cmd_fn=portal_cap.send_remote_input_cmd,
        )
        if res.is_success and res.data is not None:
            self.input_injector = res.data

    def _request_admin_async(self) -> None:
        with self._elevating_lock:
            if self._elevating_in_progress:
                return
            self._elevating_in_progress = True

        def _worker():
            try:
                res = self.rd_service.request_admin_elevation(bounds=self.monitor_bounds)
                if res.is_success and res.data is not None:
                    old = self.input_injector
                    self.input_injector = res.data
                    if old is not None and old is not res.data:
                        try:
                            old.release_all()
                        except Exception:
                            pass
                    snap = self.security_gate.update_permissions(admin_elevated=True).to_dict()
                    if self.dp.pake.confirmed:
                        self.workspace_agent.broadcast_permissions()
                    self._emit_event(("REMOTE_PERMS", snap))
                    self._emit_event((
                        "log",
                        "SUCCESS",
                        "[Area Remota] Privilegio Administrativo (UAC/Polkit) ativo para injecao global.",
                    ))
                else:
                    self._emit_event((
                        "log",
                        "WARN",
                        f"[Area Remota] Elevacao Admin nao concedida ({res.error}). Mantendo modo usuario.",
                    ))
            finally:
                with self._elevating_lock:
                    self._elevating_in_progress = False

        threading.Thread(target=_worker, daemon=True, name="DAV-Admin-Elevate").start()

    def has_any_confirmed_peer(self) -> bool:
        if self.dp.pake.confirmed:
            return True
        return any(e["dp"].pake.confirmed for e in self._extra_peers.values())

    def _send_to_addr(self, pkt: bytes, addr: Optional[Tuple[str, int]]) -> None:
        if not addr:
            return
        if self.relay_addr and addr == self.relay_addr:
            sendto_dualstack(self.sock, wrap_relay_packet(self.clean_pin, b"S", pkt), self.relay_addr[0], self.relay_addr[1])
            return
        sendto_dualstack(self.sock, pkt, addr[0], int(addr[1]))

    def _start_http_relay_if_needed(self) -> None:
        if self._http_relay is not None or not self.relay_http_base_url or not self.clean_pin:
            return

        def _on_http_pkt(raw_pkt: bytes) -> None:
            self._http_rx_queue.append(raw_pkt)

        def _on_http_conn() -> None:
            if not self.dp.pake.confirmed:
                self.use_http_relay = True
                self.is_streaming_active.set()
                if self._http_relay is not None:
                    self._http_relay.send_datagram(self.dp.build_pake_syn())
                host_label = self.relay_addr[0] if self.relay_addr else self.relay_http_base_url or "relay"
                port_label = self.relay_addr[1] if self.relay_addr else 80
                self._emit_event(("P2P_LOCKED", str(host_label), int(port_label), "Blind Relay HTTP"))

        self._http_relay = HttpTunnelRelayClient(
            base_url=self.relay_http_base_url,
            pin=self.clean_pin,
            role="S",
            on_packet_rx=_on_http_pkt,
            on_connected=_on_http_conn,
        )
        self._http_relay.start()

    def _stop_http_relay(self) -> None:
        if self._http_relay is not None:
            try:
                self._http_relay.stop()
            except Exception:
                pass
            self._http_relay = None
        self.use_http_relay = False

    def _create_extra_peer_entry(self, peer_nonce: bytes, addr: Tuple[str, int], dp_inst: Optional[DataPlaneSender] = None) -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            "peer_id": f"peer:{peer_nonce.hex()[:12]}",
            "addr": (addr[0], int(addr[1])),
            "last_seen": time.monotonic(),
        }
        dp_obj = dp_inst or DataPlaneSender(
            pin=self._pin_raw,
            send_raw_fn=lambda raw, ep=entry: self._send_to_addr(raw, ep["addr"]),
            initial_bitrate_kbps=self._bitrate_kbps,
            fps=self._fps,
        )
        dp_obj.pacer._send_fn = lambda raw, ep=entry: self._send_to_addr(raw, ep["addr"])
        ws_obj = WorkspaceAgent(
            gate=self.security_gate,
            on_clipboard_rx=lambda txt: self._emit_event(("REMOTE_CLIPBOARD", txt)),
            on_file_status=lambda st: self._emit_event(("REMOTE_FILE_STATUS", st)),
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

    def broadcast_audio_frame(self, encoded_audio: bytes, is_lbrr: bool = False) -> None:
        if self.dp.pake.confirmed:
            self.dp.send_audio_frame(encoded_audio, is_lbrr=is_lbrr)
        for entry in self._extra_peers.values():
            if entry["dp"].pake.confirmed:
                entry["dp"].send_audio_frame(encoded_audio, is_lbrr=is_lbrr)

    def broadcast_video_frame(
        self,
        compressed_payload: bytes,
        is_keyframe: bool,
        frame_interval_sec: float,
        stop_check: Optional[Any] = None,
    ) -> Tuple[int, int, int]:
        tot_pkts = 0
        tot_bytes = 0
        max_m = 0
        if self.dp.pake.confirmed:
            p, b, m = self.dp.send_video_frame(
                compressed_payload,
                is_keyframe=is_keyframe,
                frame_interval_sec=frame_interval_sec,
                pir_mode=False,
                stop_check=stop_check,
            )
            tot_pkts += p
            tot_bytes += b
            max_m = max(max_m, m)
        for entry in self._extra_peers.values():
            if entry["dp"].pake.confirmed:
                p, b, m = entry["dp"].send_video_frame(
                    compressed_payload,
                    is_keyframe=is_keyframe,
                    frame_interval_sec=frame_interval_sec,
                    pir_mode=False,
                    stop_check=stop_check,
                )
                tot_pkts += p
                tot_bytes += b
                max_m = max(max_m, m)
        return tot_pkts, tot_bytes, max_m

    def _handle_host_ws_messages(self, peer_id: str, accepted_msgs: list) -> None:
        for msg in accepted_msgs:
            if msg.msg_type == WsMsgType.PLI_REQ:
                if self._active_encoder is not None:
                    self._active_encoder.request_keyframe(force=False)
            elif msg.msg_type == WsMsgType.CLIENT_INPUT_PROFILE:
                d = msg.decode_json() or {}
                prof = ClientKeyboardProfileDTO.from_dict(d).to_dict()
                self.client_keyboard_profiles[peer_id] = prof
                self._emit_event(("CLIENT_KB_PROFILE", {"peer_id": peer_id, **prof}))
            elif msg.msg_type == WsMsgType.GAMEPAD_RUMBLE_ACK:
                ack = RumbleAckDTO.from_json_bytes(msg.payload)
                if ack is not None:
                    now_us = int(time.perf_counter_ns() // 1000)
                    rtt_ms = max(0.1, (now_us - ack.sent_ts_us) / 1000.0) if ack.sent_ts_us > 0 else 0.5
                    self._emit_event((
                        "GAMEPAD_RUMBLE_ACK",
                        {
                            "peer_id": peer_id,
                            "local_slot": ack.local_slot,
                            "ok": ack.ok,
                            "request_id": ack.request_id,
                            "rtt_ms": round(rtt_ms, 2),
                            "device_name": ack.device_name,
                            "backend": ack.backend,
                        },
                    ))

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
        if in_pkt.is_critical_transition:
            self.input_wake_evt.set()

    def tick_remote_housekeeping(self, now_mono: Optional[float] = None) -> None:
        now_m = now_mono if now_mono is not None else time.monotonic()
        if self.input_injector is not None:
            self.input_injector.tick_watchdog(now_mono=now_m)
        if self.dp.pake.confirmed:
            for rf in self.workspace_agent.channel.poll_retransmits(now_mono=now_m):
                self.dp.send_workspace_datagram(rf)
        for entry in list(self._extra_peers.values()):
            if entry["dp"].pake.confirmed:
                for rf in entry["ws_agent"].channel.poll_retransmits(now_mono=now_m):
                    entry["dp"].send_workspace_datagram(rf)

    def _send_punch_burst(self):
        syn_pkt = self.dp.build_pake_syn()
        for ip, port, _ in self.candidates:
            sendto_dualstack(self.sock, syn_pkt, ip, port)
        if self.target_ip and not self.use_relay and not self.use_http_relay:
            sendto_dualstack(self.sock, syn_pkt, self.target_ip, self.target_port)
        if self.use_relay and self.relay_addr:
            sendto_dualstack(self.sock, wrap_relay_packet(self.clean_pin, b"S", syn_pkt), self.relay_addr[0], self.relay_addr[1])
        if self.use_http_relay and self._http_relay is not None:
            self._http_relay.send_datagram(syn_pkt)
        self.last_punch_sent = time.monotonic()

    def _send_lan_upgrade_probe(self):
        syn_pkt = self.dp.build_pake_syn()
        for ip, port, mode in self.candidates:
            if self._is_lan_addr(ip) or is_overlay_address(ip) or mode == "ipv6":
                sendto_dualstack(self.sock, syn_pkt, ip, port)
        self.last_lan_upgrade_sent = time.monotonic()

    @staticmethod
    def _is_lan_addr(ip_str: str) -> bool:
        return is_lan_address(ip_str)

    def poll_control(self, encoder: Optional[VideoEncoder] = None):
        """Processa comandos IPC, handshake PAKE, feedbacks SQP, PLI e timers STUN."""
        if encoder is not None:
            self._active_encoder = encoder
        if not self._ctrl_lock.acquire(blocking=False):
            return
        try:
            self._poll_control_unlocked(encoder or self._active_encoder)
        finally:
            self._ctrl_lock.release()

    def _poll_control_unlocked(self, encoder: Optional[VideoEncoder] = None):
        if self.cmd_queue is not None:
            while True:
                try:
                    cmd = self.cmd_queue.get_nowait()
                except Exception:
                    break
                action = cmd[0]
                if action in ("UPDATE_TARGET", "START_STREAM"):
                    tip = canonicalize_ip(str(cmd[1]).strip())
                    tport = int(cmd[2])
                    self.target_ip = tip
                    self.target_port = tport
                    self._target_ep = (tip, tport) if tip else None
                    if tip:
                        self.dp.set_target_mtu_for_ip(tip)
                    self.use_relay = False
                    self._stop_http_relay()
                    self.punch_locked = False
                    self.punch_started_at = time.monotonic()
                    if tip:
                        self.is_streaming_active.set()
                        self._send_punch_burst()
                        print(f"[Sender] Destino direto configurado para {format_endpoint_display(tip, tport)}")
                elif action == "PAIR_PEER":
                    peer_dict = cmd[1] if len(cmd) > 1 and isinstance(cmd[1], dict) else {}
                    my_pub_ip = cmd[2] if len(cmd) > 2 else None
                    relay_dict = cmd[3] if len(cmd) > 3 and isinstance(cmd[3], dict) else peer_dict.get("_relay")
                    new_cands = build_peer_candidates(peer_dict, my_public_ip=my_pub_ip)
                    if relay_dict and relay_dict.get("host") and relay_dict.get("port"):
                        r_host = canonicalize_ip(str(relay_dict["host"]))
                        self.relay_addr = (r_host, int(relay_dict["port"]))
                        if relay_dict.get("http_base_url"):
                            self.relay_http_base_url = str(relay_dict["http_base_url"])
                        elif not self.relay_http_base_url:
                            self.relay_http_base_url = f"http://{format_url_host(r_host)}"

                    new_ep_set = {(ip, int(p)) for ip, p, _ in new_cands}
                    if self.dp.pake.confirmed:
                        # Idempotencia: ignora PAIR_PEER duplicado para o peer primario ou extra ja conectado!
                        known_eps = set()
                        if self._target_ep:
                            known_eps.add(self._target_ep)
                        for ip, p, _ in self.candidates:
                            known_eps.add((ip, int(p)))
                        for ex in self._extra_peers.values():
                            known_eps.add(ex["addr"])
                        if new_ep_set and (new_ep_set & known_eps):
                            continue
                        if (
                            self._pending_extra_dp is not None
                            and new_ep_set == {(ip, int(p)) for ip, p, _ in self._pending_extra_cands}
                            and (time.monotonic() - self._pending_extra_started) < 6.0
                        ):
                            continue
                        self._pending_extra_cands = new_cands
                        self._pending_extra_started = time.monotonic()
                        self._pending_extra_dp = DataPlaneSender(
                            pin=self._pin_raw,
                            send_raw_fn=lambda _raw: None,
                            initial_bitrate_kbps=self._bitrate_kbps,
                            fps=self._fps,
                        )
                        syn_extra = self._pending_extra_dp.build_pake_syn()
                        for cip, cport, _ in new_cands:
                            self._send_to_addr(syn_extra, (cip, int(cport)))
                        print(f"[Sender Multi-Peer] Sondando novo receptor adicional em {new_cands}")
                    else:
                        # Idempotencia antes da confirmacao: NAO reseta punch_started_at / use_relay se candidatos sao os mesmos!
                        cur_ep_set = {(ip, int(p)) for ip, p, _ in self.candidates}
                        if new_ep_set and new_ep_set == cur_ep_set and self.punch_started_at > 0.0 and (time.monotonic() - self.punch_started_at) < 12.0:
                            self._send_punch_burst()
                            continue
                        self.candidates = new_cands
                        self.use_relay = False
                        self._stop_http_relay()
                        self.punch_locked = False
                        self.punch_started_at = time.monotonic()
                        self.last_relay_bind = 0.0
                        self._send_punch_burst()
                        print(f"[Sender P2P] Hole-Punching PAKE concorrente para candidatos: {self.candidates}")
                elif action in ("REQUEST_KEYFRAME", "request_idr"):
                    if encoder is not None:
                        encoder.request_keyframe(force=True)
                elif action in ("PAUSE_STREAM", "STOP_STREAM"):
                    self.is_streaming_active.clear()
                    self.candidates.clear()
                    self._target_ep = None
                    self.target_ip = ""
                    self.use_relay = False
                    self.punch_locked = False
                    self.gamepad_hub.release_all_neutral()
                    print("[Sender] Transmissao em Standby (0% captura/encode).")
                elif action == "AUDIO_MUTE" and self.audio_muted_evt is not None:
                    if bool(cmd[1]):
                        self.audio_muted_evt.set()
                    else:
                        self.audio_muted_evt.clear()
                elif action == "SET_REMOTE_PERMS" and len(cmd) > 1 and isinstance(cmd[1], dict):
                    p_dict = dict(cmd[1])
                    p_dict.pop("admin_elevated", None)
                    updated = self.security_gate.update_permissions(**p_dict)
                    if not updated.allow_input and self.input_injector is not None:
                        self.input_injector.release_all()
                    if not updated.allow_gamepad:
                        self.gamepad_hub.release_all_neutral()
                    self._broadcast_permissions_all()
                    self._emit_event(("REMOTE_PERMS", updated.to_dict()))
                elif action == "PANIC_REVOKE_REMOTE":
                    updated = self.security_gate.panic_revoke_all()
                    if self.input_injector is not None:
                        self.input_injector.release_all()
                    self.gamepad_hub.release_all_neutral()
                    self._broadcast_permissions_all()
                    self._emit_event(("REMOTE_PERMS", updated.to_dict()))
                    self._emit_event(("log", "WARN", "[Seguranca] Controle remoto revogado imediatamente no Host."))
                elif action == "ELEVATE_REMOTE_ADMIN":
                    self._request_admin_async()
                elif action == "TEST_GAMEPAD_RUMBLE":
                    slot_arg = cmd[1] if len(cmd) > 1 else None
                    dispatches = self.gamepad_hub.trigger_test_rumble(host_slot=slot_arg)
                    if slot_arg is None and not dispatches:
                        raw_req = RumbleRequestDTO(
                            local_slot=0xFF,
                            is_test_pulse=True,
                            low_freq_u16=52000,
                            high_freq_u16=38000,
                            duration_ms=500,
                        ).pack()
                        if self.dp.pake.confirmed:
                            self._send_rumble_to_peer("peer:primary", raw_req)
                        for entry in self._extra_peers.values():
                            if entry["dp"].pake.confirmed:
                                self._send_rumble_to_peer(entry["peer_id"], raw_req)
                elif action == "SEND_CLIPBOARD" and len(cmd) > 1:
                    if self.security_gate.permissions.allow_clipboard and self.has_any_confirmed_peer():
                        self.workspace_agent.build_clipboard_frames(str(cmd[1]))
                        for entry in self._extra_peers.values():
                            if entry["dp"].pake.confirmed:
                                entry["ws_agent"].build_clipboard_frames(str(cmd[1]))
                elif action == "SEND_FILE" and len(cmd) > 1:
                    if self.security_gate.permissions.allow_files and self.has_any_confirmed_peer():
                        try:
                            self.workspace_agent.build_file_transfer_frames(str(cmd[1]))
                            for entry in self._extra_peers.values():
                                if entry["dp"].pake.confirmed:
                                    entry["ws_agent"].build_file_transfer_frames(str(cmd[1]))
                        except Exception as f_exc:
                            self._emit_event(("log", "WARN", f"[Arquivo P2P] Falha ao enviar: {f_exc}"))

        incoming_batch: List[Tuple[bytes, Tuple[str, int], bool]] = []
        while self._http_rx_queue:
            try:
                hpkt = self._http_rx_queue.popleft()
                r_ep = self.relay_addr or ("http-relay", 80)
                incoming_batch.append((hpkt, r_ep, True))
            except IndexError:
                break

        while True:
            try:
                raw_pkt, raw_addr = self.sock.recvfrom(4096)
            except (BlockingIOError, OSError):
                break
            if raw_pkt:
                norm_addr = normalize_recv_addr(raw_addr)
                if raw_pkt.startswith(MAGIC_RLY):
                    unwrapped = unwrap_relay_packet(raw_pkt)
                    if unwrapped and unwrapped[0] == self.clean_pin:
                        raw_pkt = unwrapped[2]
                incoming_batch.append((raw_pkt, norm_addr, False))

        for in_pkt, in_addr, from_http_relay in incoming_batch:
            if not in_pkt:
                continue

            # Roteamento PAKE multi-peer (distingue Peer 1 vs Peers adicionais 2..4 pelo nonce CPace de 16B)
            is_pake_pkt = (
                (in_pkt.startswith(MAGIC_PAKE_SYN) and len(in_pkt) == 65)
                or (in_pkt.startswith(MAGIC_PAKE_ACK) and len(in_pkt) == 81)
            )
            if is_pake_pkt:
                p_nonce = in_pkt[17:33]
                is_primary_peer = (
                    not self.dp.pake.confirmed
                    or self.dp.pake.peer_nonce is None
                    or self.dp.pake.peer_nonce == p_nonce
                )
                if not is_primary_peer:
                    # Se o pacote veio do mesmo IP:porta ja confirmado do peer primario, ignora SYN2 espurio
                    if self._target_ep and in_addr == self._target_ep:
                        continue
                    extra_entry = self._extra_peers.get(p_nonce)
                    if extra_entry is None and len(self._extra_peers) < 3:
                        dp_seed = self._pending_extra_dp
                        self._pending_extra_dp = None
                        extra_entry = self._create_extra_peer_entry(p_nonce, in_addr, dp_inst=dp_seed)
                        extra_entry["dp"].set_target_mtu_for_ip(in_addr[0])
                        self._extra_peers[p_nonce] = extra_entry
                    if extra_entry is not None:
                        extra_entry["addr"] = (in_addr[0], int(in_addr[1]))
                        extra_entry["last_seen"] = time.monotonic()
                        ex_evt, ex_reply = extra_entry["dp"].handle_incoming_packet(in_pkt)
                        if ex_reply is not None:
                            self._send_to_addr(ex_reply, extra_entry["addr"])
                        if ex_evt == "pake_confirmed":
                            self.is_streaming_active.set()
                            if encoder is not None:
                                encoder.request_keyframe(force=True)
                            extra_entry["ws_agent"].broadcast_permissions()
                            self._emit_event((
                                "log",
                                "SUCCESS",
                                f"[Multi-Peer] Cliente adicional conectado em {format_endpoint_display(in_addr[0], in_addr[1])}.",
                            ))
                    continue

            # Verifica primeiro se o datagrama cifrado pertence a um peer adicional conectado
            handled_by_extra = False
            if not is_pake_pkt and self._extra_peers:
                for extra_entry in self._extra_peers.values():
                    if extra_entry["addr"] == in_addr:
                        ex_evt, ex_payload = extra_entry["dp"].handle_incoming_packet(in_pkt)
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

            evt, reply_ack = self.dp.handle_incoming_packet(in_pkt)
            if evt in ("pake_confirmed", "pake_ack"):
                from_udp_relay = bool((not from_http_relay) and self.relay_addr and in_addr == self.relay_addr)
                from_any_relay = from_http_relay or from_udp_relay
                should_switch = (
                    not self.punch_locked
                    or ((self.use_relay or self.use_http_relay) and not from_any_relay)
                    or (not from_any_relay and not self._is_lan_addr(self.target_ip) and self._is_lan_addr(in_addr[0]))
                )
                if should_switch and not from_any_relay:
                    new_ip, new_port = in_addr[0], int(in_addr[1])
                    self._target_ep = (new_ip, new_port)
                    self.target_ip, self.target_port = new_ip, new_port
                    self.dp.set_target_mtu_for_ip(new_ip)
                    self.punch_locked = True
                    self.use_relay = False
                    self._stop_http_relay()
                    self.is_streaming_active.set()
                    if self._is_lan_addr(new_ip):
                        mode_tag = "LAN Direto"
                    elif is_ipv6_address(new_ip):
                        mode_tag = "IPv6 P2P Direto"
                    else:
                        mode_tag = "WAN P2P Direto"
                    print(f"[Sender PAKE] Tunel autenticado ({mode_tag}) -> {format_endpoint_display(new_ip, new_port)}")
                    self._emit_event(("P2P_LOCKED", new_ip, new_port, mode_tag))
                elif from_http_relay and not self.punch_locked:
                    self.use_http_relay = True
                    self.use_relay = False
                    self.punch_locked = True
                    self.is_streaming_active.set()
                elif from_udp_relay and not self.punch_locked:
                    self.use_relay = True
                    self.punch_locked = True
                    self.is_streaming_active.set()

                if reply_ack is not None:
                    if from_http_relay and self._http_relay is not None:
                        self._http_relay.send_datagram(reply_ack)
                    elif from_udp_relay and self.relay_addr:
                        sendto_dualstack(self.sock, wrap_relay_packet(self.clean_pin, b"S", reply_ack), self.relay_addr[0], self.relay_addr[1])
                    else:
                        sendto_dualstack(self.sock, reply_ack, in_addr[0], in_addr[1])

                if evt == "pake_confirmed":
                    if encoder is not None:
                        encoder.request_keyframe(force=True)
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

            if in_pkt.startswith(MAGIC_PLI):
                if encoder is not None:
                    encoder.request_keyframe(force=False)
            elif in_pkt in (b"DAV_RLY_ACK", b"DAV_RLY_PEER_READY"):
                if (not self.punch_locked or not self.dp.pake.confirmed) and self.relay_addr:
                    was_relay = self.use_relay
                    self.use_relay = True
                    self.is_streaming_active.set()
                    self._send_punch_burst()
                    if not was_relay:
                        print(f"[Sender P2P] Blind Encrypted UDP Relay ativo via {format_endpoint_display(self.relay_addr[0], self.relay_addr[1])}")
                        self._emit_event(("P2P_LOCKED", self.relay_addr[0], self.relay_addr[1], "Blind Relay UDP"))
            elif in_pkt.startswith(MAGIC_SYN) or in_pkt.startswith(MAGIC_ACK):
                syn_b = self.dp.build_pake_syn()
                if from_http_relay and self._http_relay is not None:
                    self._http_relay.send_datagram(syn_b)
                elif self.relay_addr and in_addr == self.relay_addr:
                    sendto_dualstack(self.sock, wrap_relay_packet(self.clean_pin, b"S", syn_b), self.relay_addr[0], self.relay_addr[1])
                else:
                    sendto_dualstack(self.sock, syn_b, in_addr[0], in_addr[1])

        now = time.monotonic()
        if not self.dp.pake.confirmed:
            if (self.candidates or self.target_ip or self.use_relay or self.use_http_relay) and (now - self.last_punch_sent >= 0.045):
                self._send_punch_burst()

            if self.candidates and not self.punch_locked:
                elapsed_punch = now - self.punch_started_at
                if elapsed_punch >= 0.85 and self.relay_addr and not self.use_relay and (now - self.last_relay_bind >= 0.3):
                    sendto_dualstack(self.sock, wrap_relay_packet(self.clean_pin, b"S", b"BIND"), self.relay_addr[0], self.relay_addr[1])
                    self.last_relay_bind = now
                if elapsed_punch >= 1.70 and not self.use_relay and not self.use_http_relay and self.relay_http_base_url:
                    self._start_http_relay_if_needed()
                if elapsed_punch >= 1.6 and not self.target_ip:
                    best_ip, best_port, best_mode = self.candidates[0]
                    self._target_ep = (best_ip, int(best_port))
                    self.target_ip, self.target_port = best_ip, best_port
                    self.dp.set_target_mtu_for_ip(best_ip)
                    self.is_streaming_active.set()
                    print(f"[Sender P2P] Sondando rota primaria PAKE ({best_mode}) para {format_endpoint_display(best_ip, best_port)}")
        elif (
            self.dp.pake.confirmed
            and self.candidates
            and self.punch_started_at > 0.0
            and (now - self.punch_started_at <= 6.0)
            and (self.use_relay or self.use_http_relay or not self._is_lan_addr(self.target_ip))
            and (now - self.last_lan_upgrade_sent >= 0.20)
        ):
            self._send_lan_upgrade_probe()
        elif not self.is_streaming_active.is_set() and (now - self.last_keepalive >= 15.0):
            send_stun_keepalive(self.sock)
            self.last_keepalive = now

    def send_datagram(self, pkt: bytes):
        if self.use_http_relay and self._http_relay is not None:
            self._http_relay.send_datagram(pkt)
            return

        use_rly = self.use_relay
        rly = self.relay_addr
        if use_rly and rly:
            wrapped = wrap_relay_packet(self.clean_pin, b"S", pkt)
            sendto_dualstack(self.sock, wrapped, rly[0], rly[1])
            return

        ep = self._target_ep
        if ep:
            if not sendto_dualstack(self.sock, pkt, ep[0], ep[1]):
                sendto_dualstack(self.sock, pkt, ep[0], ep[1])

    def close(self):
        self._stop_http_relay()
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
        self.rd_service.close()
        try:
            self.sock.close()
        except Exception:
            pass


def run_sender_subprocess(
    target_ip: str,
    target_port: int,
    pin: str,
    width: int,
    height: int,
    fps: int,
    bitrate_kbps: int,
    stats_queue: "mp.Queue",
    stop_event: "mp.Event",
    codec_type: str = "h264_nvenc",
    monitor_index: int = 0,
    cmd_queue: Optional["mp.Queue"] = None,
    evt_queue: Optional["mp.Queue"] = None,
    bind_port: Optional[int] = None,
    audio_enabled: bool = True,
    initial_permissions: Optional[Dict[str, bool]] = None,
):
    """Subprocesso dedicado de captura, compressao e envio UDP a 60 FPS."""
    if sys.platform == "win32":
        try:
            ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:
            pass
        try:
            _u32_sub = ctypes.windll.user32
            _u32_sub.SetProcessDPIAware()
            _h_desk_sub = _u32_sub.OpenDesktopW("Default", 0, False, 0x01FF)
            if _h_desk_sub:
                _u32_sub.SetThreadDesktop(_h_desk_sub)
        except Exception:
            pass

    try:
        probe_init()
    except Exception:
        pass

    _elevate_process_priority(ABOVE_NORMAL_PRIORITY_CLASS)

    is_win32 = sys.platform == "win32"
    user32 = ctypes.windll.user32 if is_win32 else None
    gdi32 = ctypes.windll.gdi32 if is_win32 else None

    if is_win32 and gdi32 and user32:
        gdi32.CreateDCW.restype = wintypes.HANDLE
        gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
        gdi32.CreateCompatibleDC.restype = wintypes.HANDLE
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HANDLE]
        gdi32.CreateDIBSection.restype = wintypes.HANDLE
        gdi32.CreateDIBSection.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
        ]
        gdi32.SelectObject.restype = wintypes.HANDLE
        gdi32.SelectObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        gdi32.BitBlt.restype = wintypes.BOOL
        gdi32.BitBlt.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HANDLE, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
        ]
        gdi32.DeleteObject.restype = wintypes.BOOL
        gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        gdi32.DeleteDC.restype = wintypes.BOOL
        gdi32.DeleteDC.argtypes = [wintypes.HANDLE]
        user32.GetDC.restype = wintypes.HANDLE
        user32.GetDC.argtypes = [wintypes.HWND]
        user32.ReleaseDC.restype = ctypes.c_int
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HANDLE]

    all_monitors = enumerate_system_monitors()
    target_mon = all_monitors[monitor_index] if 0 <= monitor_index < len(all_monitors) else all_monitors[0]
    src_x, src_y = target_mon["left"], target_mon["top"]
    src_w, src_h = target_mon["width"], target_mon["height"]

    total_frames_captured = 0
    total_frames_encoded = 0
    total_frames_sent = 0
    total_bytes_sent = 0
    total_packets_sent = 0
    latest_payload_kb = 32
    latest_lat_ms = 0.0
    active_codec_tag = codec_type.upper()

    is_streaming_active = threading.Event()
    if target_ip and str(target_ip).strip():
        is_streaming_active.set()
    audio_muted_evt = threading.Event()
    if not audio_enabled:
        audio_muted_evt.set()
    input_wake_evt = threading.Event()
    mon_bounds = MonitorBounds(left=src_x, top=src_y, width=src_w, height=src_h)

    effective_bind_port = int(bind_port if bind_port is not None else (target_port or 9000))

    transport = SenderTransportEndpoint(
        bind_port=effective_bind_port,
        initial_target_ip=target_ip,
        initial_target_port=target_port,
        pin=pin,
        is_streaming_active=is_streaming_active,
        cmd_queue=cmd_queue,
        evt_queue=evt_queue,
        bitrate_kbps=bitrate_kbps,
        fps=fps,
        audio_muted_evt=audio_muted_evt,
        monitor_bounds=mon_bounds,
        initial_permissions=initial_permissions,
        input_wake_evt=input_wake_evt,
    )

    _tel_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _tel_sock.setblocking(False)
    disable_win_udp_connreset(_tel_sock)

    use_wgc = False
    wgc_ctrl = None

    if _WGC_AVAILABLE and is_win32 and os.environ.get("DAV_HEADLESS_SYNTHETIC") != "1":
        try:
            wgc_mon_idx = (monitor_index + 1) if monitor_index is not None and monitor_index >= 0 else 1
            if wgc_mon_idx > len(all_monitors):
                wgc_mon_idx = 1

            shared_frame_buf = np.zeros((height, width, 4), dtype=np.uint8)
            local_enc_buf = np.zeros((height, width, 4), dtype=np.uint8)
            buf_lock = threading.Lock()
            has_first_frame = threading.Event()
            _t_latest_cap_start = time.perf_counter()
            _t_latest_cap_end = time.perf_counter()
            cap_id = 0

            capture = WindowsCapture(
                cursor_capture=True,
                draw_border=False,
                monitor_index=wgc_mon_idx,
            )

            @capture.event
            def on_frame_arrived(frame: Frame, ctrl: InternalCaptureControl):
                nonlocal cap_id, _t_latest_cap_start, _t_latest_cap_end, total_frames_captured
                if stop_event.is_set():
                    ctrl.stop()
                    return

                _t0 = time.perf_counter()
                if frame.width != width or frame.height != height:
                    if _HAS_CV2:
                        with buf_lock:
                            cv2.resize(
                                frame.frame_buffer, (width, height),
                                dst=shared_frame_buf, interpolation=cv2.INTER_LINEAR,
                            )
                else:
                    with buf_lock:
                        np.copyto(shared_frame_buf, frame.frame_buffer)
                _t1 = time.perf_counter()

                _t_latest_cap_start = _t0
                _t_latest_cap_end = _t1
                cap_id += 1
                total_frames_captured = cap_id
                has_first_frame.set()

            @capture.event
            def on_closed():
                pass

            wgc_ctrl = capture.start_free_threaded()
            use_wgc = True
            print(f"[Sender WGC] Captura Direct3D ativa no Monitor {wgc_mon_idx} ({src_w}x{src_h} -> {width}x{height} @ {fps} FPS).")
        except Exception as wgc_err:
            print(f"[Sender] WGC indisponivel ({wgc_err}); alternando para captura de contingencia.")
            use_wgc = False

    hdc_screen = None
    hdc_mems: list = []
    hbms: list = []
    NUM_BUFS = 6

    if not use_wgc:
        free_buffers: "queue.Queue[int]" = queue.Queue()
        for i in range(NUM_BUFS):
            free_buffers.put(i)
        ready_buffers: "queue.Queue[Tuple[int, int, float, float]]" = queue.Queue(maxsize=NUM_BUFS)

        if is_win32 and gdi32 and user32 and os.environ.get("DAV_HEADLESS_SYNTHETIC") != "1":
            hdc_screen = user32.GetDC(0)

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32),
                ]

            class BITMAPINFO(ctypes.Structure):
                _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]

            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0

            need_scale = (width != src_w or height != src_h)
            arrays = []
            for _ in range(NUM_BUFS):
                hdc_m = gdi32.CreateCompatibleDC(hdc_screen)
                p_b = ctypes.c_void_p()
                h_b = gdi32.CreateDIBSection(hdc_m, ctypes.byref(bmi), 0, ctypes.byref(p_b), None, 0)
                gdi32.SelectObject(hdc_m, h_b)
                arr = np.ctypeslib.as_array(
                    ctypes.cast(p_b, ctypes.POINTER(ctypes.c_uint8)), shape=(height, width, 4)
                )
                hdc_mems.append(hdc_m)
                hbms.append(h_b)
                arrays.append(arr)

            def _capture_worker():
                nonlocal total_frames_captured
                _set_thread_perf(THREAD_PRIORITY_TIME_CRITICAL, 0)
                try:
                    _u32_cap = ctypes.windll.user32
                    _h_desk_cap = _u32_cap.OpenDesktopW("Default", 0, False, 0x01FF)
                    if _h_desk_cap:
                        _u32_cap.SetThreadDesktop(_h_desk_cap)
                except Exception:
                    pass

                target_cadence_fps = (fps + 2.0) if fps >= 60 else float(fps)
                frame_interval = 1.0 / target_cadence_fps
                t_target = time.perf_counter() + frame_interval
                cap_id_gdi = 0

                while not stop_event.is_set():
                    if not is_streaming_active.is_set():
                        time.sleep(0.03)
                        t_target = time.perf_counter() + frame_interval
                        continue

                    try:
                        buf_idx = free_buffers.get(timeout=0.05)
                    except queue.Empty:
                        continue

                    _t_cap_start = time.perf_counter()
                    if need_scale:
                        gdi32.SetStretchBltMode(hdc_mems[buf_idx], 3)
                        gdi32.StretchBlt(
                            hdc_mems[buf_idx], 0, 0, width, height,
                            hdc_screen, src_x, src_y, src_w, src_h, 0x00CC0020,
                        )
                    else:
                        gdi32.BitBlt(
                            hdc_mems[buf_idx], 0, 0, width, height,
                            hdc_screen, src_x, src_y, 0x00CC0020,
                        )
                    _t_cap_end = time.perf_counter()

                    cap_id_gdi += 1
                    total_frames_captured = cap_id_gdi

                    if ready_buffers.qsize() >= 5:
                        try:
                            old_b, _, _, _ = ready_buffers.get_nowait()
                            free_buffers.put_nowait(old_b)
                        except Exception:
                            pass

                    ready_buffers.put((buf_idx, cap_id_gdi, _t_cap_start, _t_cap_end))

                    now = time.perf_counter()
                    slack = t_target - now
                    if slack > 0.003:
                        time.sleep(slack - 0.0015)
                    while time.perf_counter() < t_target:
                        pass
                    t_target = max(t_target + frame_interval, time.perf_counter())

        else:
            arrays = [np.zeros((height, width, 4), dtype=np.uint8) for _ in range(NUM_BUFS)]

            def _capture_worker():
                nonlocal total_frames_captured
                _set_thread_perf(0, 0)
                target_cadence_fps = (fps + 2.0) if fps >= 60 else float(fps)
                frame_interval = 1.0 / target_cadence_fps
                t_target = time.perf_counter() + frame_interval
                cap_id_linux = 0

                portal_cap = None
                sct = None
                mon_box = None
                cached_src_shape = None
                cached_y_idx = None
                cached_x_idx = None
                consecutive_black_mss = 0
                tried_portal_fallback = False

                is_synthetic = os.environ.get("DAV_HEADLESS_SYNTHETIC") == "1"

                if not is_synthetic:
                    if is_wayland_session():
                        tried_portal_fallback = True
                        if evt_queue is not None:
                            evt_queue.put((
                                "log",
                                "INFO",
                                "[Wayland] Sessao Wayland detectada — aguardando autorizacao no portal PipeWire...",
                            ))
                        candidate = WaylandPortalCapturer(width=width, height=height, fps=fps, enable_remote_desktop=True)
                        if candidate.start(wait_first_frame_timeout=60.0):
                            portal_cap = candidate
                            transport.attach_wayland_portal(portal_cap)
                            if cmd_queue is not None:
                                cmd_queue.put(("request_idr",))
                            if evt_queue is not None:
                                evt_queue.put((
                                    "log",
                                    "SUCCESS",
                                    f"[Wayland] Captura PipeWire ativa em {width}x{height} @ {fps} FPS.",
                                ))
                        else:
                            if evt_queue is not None:
                                evt_queue.put((
                                    "log",
                                    "WARN",
                                    f"[Wayland] Portal PipeWire indisponivel ({candidate.last_error}). Tentando fallback X11/MSS...",
                                ))

                    if portal_cap is None:
                        try:
                            import mss
                            sct = mss.mss()
                            mon_idx = min(monitor_index + 1, len(sct.monitors) - 1) if len(sct.monitors) > 1 else 1
                            mon_box = sct.monitors[mon_idx]
                        except Exception:
                            sct = None

                while not stop_event.is_set():
                    if not is_streaming_active.is_set():
                        time.sleep(0.03)
                        t_target = time.perf_counter() + frame_interval
                        continue

                    try:
                        buf_idx = free_buffers.get(timeout=0.05)
                    except queue.Empty:
                        continue

                    _t_cap_start = time.perf_counter()
                    captured = False

                    if portal_cap is not None:
                        captured = portal_cap.grab_into(arrays[buf_idx])
                    elif sct and mon_box:
                        try:
                            sct_img = sct.grab(mon_box)
                            arr_src = np.asarray(sct_img, dtype=np.uint8)
                            if arr_src.shape[0] != height or arr_src.shape[1] != width:
                                if _HAS_CV2:
                                    cv2.resize(
                                        arr_src,
                                        (width, height),
                                        dst=arrays[buf_idx],
                                        interpolation=cv2.INTER_NEAREST,
                                    )
                                else:
                                    if cached_src_shape != arr_src.shape[:2]:
                                        cached_src_shape = arr_src.shape[:2]
                                        cached_y_idx = np.linspace(0, arr_src.shape[0] - 1, height).astype(np.intp)
                                        cached_x_idx = np.linspace(0, arr_src.shape[1] - 1, width).astype(np.intp)
                                    np.copyto(arrays[buf_idx], arr_src[cached_y_idx][:, cached_x_idx])
                            else:
                                np.copyto(arrays[buf_idx], arr_src)
                            captured = True

                            if not tried_portal_fallback and cap_id_linux < 12:
                                if not np.any(arrays[buf_idx][::16, ::16, :3]):
                                    consecutive_black_mss += 1
                                    if consecutive_black_mss >= 8:
                                        tried_portal_fallback = True
                                        if evt_queue is not None:
                                            evt_queue.put((
                                                "log",
                                                "WARN",
                                                "[Captura Linux] XWayland bloqueou leitura X11. Migrando para PipeWire Portal...",
                                            ))
                                        candidate = WaylandPortalCapturer(width=width, height=height, fps=fps, enable_remote_desktop=True)
                                        if candidate.start(wait_first_frame_timeout=60.0):
                                            portal_cap = candidate
                                            transport.attach_wayland_portal(portal_cap)
                                            portal_cap.grab_into(arrays[buf_idx])
                                            if cmd_queue is not None:
                                                cmd_queue.put(("request_idr",))
                                            try:
                                                sct.close()
                                            except Exception:
                                                pass
                                            sct = None
                                else:
                                    consecutive_black_mss = 0
                        except Exception:
                            captured = False

                    if not captured:
                        arrays[buf_idx].fill(32)
                        arrays[buf_idx][:, :, 0] = (cap_id_linux * 5) % 255
                        arrays[buf_idx][:, :, 1] = 140
                        arrays[buf_idx][:, :, 2] = 220
                        arrays[buf_idx][:, :, 3] = 255

                    _t_cap_end = time.perf_counter()
                    cap_id_linux += 1
                    total_frames_captured = cap_id_linux

                    if ready_buffers.qsize() >= 5:
                        try:
                            old_b, _, _, _ = ready_buffers.get_nowait()
                            free_buffers.put_nowait(old_b)
                        except Exception:
                            pass

                    ready_buffers.put((buf_idx, cap_id_linux, _t_cap_start, _t_cap_end))

                    now = time.perf_counter()
                    slack = t_target - now
                    if slack > 0.003:
                        time.sleep(slack - 0.0015)
                    while time.perf_counter() < t_target:
                        pass
                    t_target = max(t_target + frame_interval, time.perf_counter())

                if portal_cap is not None:
                    portal_cap.close()
                if sct:
                    try:
                        sct.close()
                    except Exception:
                        pass

    def _encode_and_transmit_frame(
        frame_bgra: np.ndarray,
        t_cap_start: float,
        t_cap_end: float,
        encoder: VideoEncoder,
    ):
        nonlocal total_frames_encoded, total_frames_sent, total_bytes_sent, total_packets_sent, latest_payload_kb, latest_lat_ms

        if not transport.has_any_confirmed_peer():
            return

        frame_interval = 1.0 / float(max(1, fps))

        t_enc_start = time.perf_counter()
        payload = encoder.encode(frame_bgra)
        t_enc_end = time.perf_counter()

        if not payload:
            return

        total_frames_encoded += 1
        frame_id = total_frames_encoded
        latest_payload_kb = max(1, len(payload) // 1024)
        is_keyframe = encoder.last_frame_was_keyframe or (frame_id == 1)

        t_send_start = time.perf_counter()
        pkts_sent, frame_sent_bytes, _ = transport.broadcast_video_frame(
            payload,
            is_keyframe=is_keyframe,
            frame_interval_sec=frame_interval,
            stop_check=stop_event.is_set,
        )
        t_send_end = time.perf_counter()

        total_packets_sent += pkts_sent
        total_frames_sent += 1
        total_bytes_sent += frame_sent_bytes
        latest_lat_ms = (t_send_end - t_cap_start) * 1000.0

        if _probe_send is not None and frame_id % 3 == 0:
            _probe_send("capture", t_cap_start, t_cap_end, frame_id)
            _probe_send("encode", t_enc_start, t_enc_end, frame_id)
            _probe_send("send", t_send_start, t_send_end, frame_id)
            _probe_send("e2e", t_cap_start, t_send_end, frame_id)

    def _encode_send_worker_wgc():
        nonlocal active_codec_tag
        _set_thread_perf(THREAD_PRIORITY_HIGHEST, 0)

        encoder = VideoEncoder(
            codec_type=codec_type, width=width, height=height,
            fps=fps, bitrate_kbps=bitrate_kbps,
        )
        active_codec_tag = encoder.active_backend_name

        t_wait_deadline = time.monotonic() + 2.0
        while not stop_event.is_set() and not has_first_frame.is_set() and time.monotonic() < t_wait_deadline:
            transport.poll_control(encoder)
            has_first_frame.wait(timeout=0.05)
        frame_interval = 1.0 / float(max(1, fps))
        min_frame_spacing = frame_interval * 0.96
        t_target = time.perf_counter() + frame_interval
        last_encode_t = 0.0
        last_encoded_cap_id = -1

        while not stop_event.is_set():
            transport.poll_control(encoder)

            if not is_streaming_active.is_set() or not transport.has_any_confirmed_peer():
                time.sleep(0.01)
                t_target = time.perf_counter() + frame_interval
                continue

            with buf_lock:
                np.copyto(local_enc_buf, shared_frame_buf)
                cur_cap_id = cap_id

            last_encode_t = time.perf_counter()
            last_encoded_cap_id = cur_cap_id
            _encode_and_transmit_frame(
                local_enc_buf,
                _t_latest_cap_start,
                _t_latest_cap_end,
                encoder,
            )

            now = time.perf_counter()
            min_next_t = last_encode_t + min_frame_spacing
            effective_target = max(t_target, min_next_t)
            slack = effective_target - now
            if slack > 0.002:
                woke = input_wake_evt.wait(timeout=slack - 0.001)
                if woke:
                    input_wake_evt.clear()
                    # Permite despertar adiantado apenas se ja houve novo quadro WGC e respeita teto de FPS
                    if cap_id != last_encoded_cap_id and time.perf_counter() >= min_next_t:
                        effective_target = time.perf_counter()
            while time.perf_counter() < effective_target:
                pass
            input_wake_evt.clear()
            t_target = max(t_target + frame_interval, last_encode_t + frame_interval, time.perf_counter())

        encoder.close()

    def _encode_send_worker_buffered():
        nonlocal active_codec_tag
        _set_thread_perf(THREAD_PRIORITY_HIGHEST, 0)

        encoder = VideoEncoder(
            codec_type=codec_type, width=width, height=height,
            fps=fps, bitrate_kbps=bitrate_kbps,
        )
        active_codec_tag = encoder.active_backend_name

        while not stop_event.is_set() or not ready_buffers.empty():
            transport.poll_control(encoder)

            if not is_streaming_active.is_set() or not transport.has_any_confirmed_peer():
                time.sleep(0.01)
                continue

            try:
                buf_idx, _, t_cap_start, t_cap_end = ready_buffers.get(timeout=0.03)
            except queue.Empty:
                continue

            while not ready_buffers.empty():
                try:
                    newer = ready_buffers.get_nowait()
                    free_buffers.put_nowait(buf_idx)
                    buf_idx, _, t_cap_start, t_cap_end = newer
                except queue.Empty:
                    break

            frame_view = arrays[buf_idx]
            _encode_and_transmit_frame(
                frame_view,
                t_cap_start,
                t_cap_end,
                encoder,
            )
            free_buffers.put(buf_idx)

        encoder.close()

    def _audio_tx_worker():
        while not stop_event.is_set():
            audio_cap = None
            audio_enc = None
            try:
                audio_cap = create_audio_capturer()
                audio_enc = OpusAudioEncoder(bitrate_bps=96000, enable_lbrr_piggyback=True)
                while not stop_event.is_set():
                    pcm = audio_cap.read_frame(timeout=0.025)
                    if pcm is None:
                        continue
                    if audio_muted_evt.is_set() or not is_streaming_active.is_set() or not transport.has_any_confirmed_peer():
                        continue
                    use_lbrr = transport.dp.sqp.loss_rate > 0.005
                    enc_pkt = audio_enc.encode(pcm, lbrr_active=use_lbrr)
                    if enc_pkt:
                        transport.broadcast_audio_frame(enc_pkt, is_lbrr=use_lbrr)
            except Exception as exc:
                print(f"[Audio TX] Reiniciando captura apos falha transitoria ({exc}).")
                time.sleep(0.35)
            finally:
                if audio_enc is not None:
                    try:
                        audio_enc.close()
                    except Exception:
                        pass
                if audio_cap is not None:
                    try:
                        audio_cap.close()
                    except Exception:
                        pass

    def _control_rx_worker():
        _set_thread_perf(THREAD_PRIORITY_TIME_CRITICAL, 0)
        last_hk = time.monotonic()
        while not stop_event.is_set():
            try:
                rlist, _, _ = select.select([transport.sock], [], [], 0.002)
                if (
                    rlist
                    or transport._http_rx_queue
                    or not transport.dp.pake.confirmed
                    or (cmd_queue is not None and not cmd_queue.empty())
                ):
                    transport.poll_control()
                now_hk = time.monotonic()
                if (now_hk - last_hk) >= 0.025:
                    last_hk = now_hk
                    transport.tick_remote_housekeeping(now_mono=now_hk)
            except Exception:
                time.sleep(0.002)

    t_ctrl = threading.Thread(target=_control_rx_worker, daemon=True, name="DAV-Control-RX")
    t_ctrl.start()

    t_audio = threading.Thread(target=_audio_tx_worker, daemon=True, name="DAV-Audio-TX")
    t_audio.start()

    if use_wgc:
        t_capture = None
        t_encode = threading.Thread(target=_encode_send_worker_wgc, daemon=True, name="DAV-EncodeSend-WGC")
        t_encode.start()
    else:
        cap_tag = "GDI" if is_win32 else "X11"
        t_capture = threading.Thread(target=_capture_worker, daemon=True, name=f"DAV-Capture-{cap_tag}")
        t_encode = threading.Thread(target=_encode_send_worker_buffered, daemon=True, name=f"DAV-EncodeSend-{cap_tag}")
        t_capture.start()
        t_encode.start()

    last_stat_t = time.perf_counter()
    last_stat_frames = 0
    last_stat_bytes = 0

    while not stop_event.is_set():
        time.sleep(0.1)
        stat_now = time.perf_counter()
        if stat_now - last_stat_t >= 0.5:
            elapsed = stat_now - last_stat_t
            d_frames = total_frames_sent - last_stat_frames
            d_bytes = total_bytes_sent - last_stat_bytes
            cur_fps = d_frames / elapsed if elapsed > 0 else 0.0
            cur_mbps = (d_bytes * 8.0) / (elapsed * 1_000_000.0) if elapsed > 0 else 0.0
            backend_label = "WGC" if use_wgc else ("GDI" if is_win32 else "X11")
            codec_label = f"{active_codec_tag}[{backend_label}]"

            try:
                stats_queue.put_nowait((
                    total_frames_sent,
                    cur_fps,
                    cur_mbps,
                    total_packets_sent,
                    codec_label,
                    latest_payload_kb,
                ))
            except Exception:
                pass

            try:
                _tel_msg = json.dumps({
                    "role": "tx",
                    "fps": round(cur_fps, 2),
                    "mbps": round(cur_mbps, 2),
                    "lat": round(latest_lat_ms, 2),
                    "frames": total_frames_sent,
                    "packets": total_packets_sent,
                }).encode("utf-8")
                _tel_sock.sendto(_tel_msg, ("127.0.0.1", 19901))
            except Exception:
                pass

            last_stat_t = stat_now
            last_stat_frames = total_frames_sent
            last_stat_bytes = total_bytes_sent

    t_ctrl.join(timeout=0.3)
    t_audio.join(timeout=0.5)
    if use_wgc and wgc_ctrl is not None:
        try:
            wgc_ctrl.stop()
            wgc_ctrl.wait()
        except Exception:
            pass
        t_encode.join(timeout=1.0)
    else:
        if t_capture:
            t_capture.join(timeout=0.5)
        t_encode.join(timeout=1.0)
        if is_win32 and gdi32 and user32:
            for h_b in hbms:
                gdi32.DeleteObject(h_b)
            for hdc_m in hdc_mems:
                gdi32.DeleteDC(hdc_m)
            if hdc_screen:
                user32.ReleaseDC(0, hdc_screen)

    transport.close()

    try:
        _tel_sock.close()
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass


_sender_subprocess = run_sender_subprocess
