# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Servico Unificado do Motor de Streaming (StreamEngineService) — DA-V v4.6
Autor: Dante Ferraz (MonoTech)

Orquestrador canonico de alto nivel que unifica:
1. API de fatia reativa (`start_transmission`, `start_reception`, `pair_peer`, `stop_all`, `EventBus`);
2. API desktop/CLI multiprocesso GIL-free (`start_sender`, `start_receiver`, `prepare_receiver_socket`,
   `wait_sender_endpoint`, `pair_sender_peer`, `set_sender_audio_muted`, `stop`) anteriormente duplicada
   em `scripts/dav_client.py`.
"""

from __future__ import annotations

import ctypes
import logging
import multiprocessing as mp
import os
import socket
import threading
from ctypes import (
    CFUNCTYPE,
    POINTER,
    Structure,
    c_char_p,
    c_float,
    c_int,
    c_size_t,
    c_uint16,
    c_uint32,
    c_uint64,
    c_void_p,
)
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from src.dav.kernel.contracts import (
    EVENT_AUDIO_FRAME_RX,
    EVENT_CLIENT_KEYBOARD_PROFILE,
    EVENT_GAMEPAD_ROSTER_CHANGED,
    EVENT_GAMEPAD_RUMBLE_ACK,
    EVENT_REMOTE_CLIPBOARD,
    EVENT_REMOTE_FILE_STATUS,
    EVENT_REMOTE_INPUT_METRICS,
    EVENT_REMOTE_PERM_CHANGED,
    EVENT_REMOTE_SHELL_OUTPUT,
    EVENT_STREAM_ROUTE_LOCKED,
    EVENT_STREAM_STATS,
    EVENT_STREAM_STOPPED,
    EVENT_VIDEO_FRAME_RX,
)
from src.dav.kernel.event_bus import EventBus
from src.dav.kernel.result import ServiceResult
from src.dav.modules.audio.service import AudioService
from src.dav.modules.capture.service import CaptureService
from src.dav.modules.codec.service import CodecService
from src.dav.modules.remote_desktop.elevation import is_process_elevated
from src.dav.modules.remote_desktop.security_gate import WorkspacePermissions
from src.dav.modules.remote_desktop.service import RemoteDesktopService
from src.dav.modules.stream_engine.receiver_worker import ReceiverWorker
from src.dav.modules.stream_engine.sender_worker import SenderWorker
from src.dav.modules.stream_engine.subprocess_sender import run_sender_subprocess
from src.dav.modules.transport_p2p.service import TransportService
from src.dav.modules.universal_input.service import UniversalInputService
from src.dav.modules.transport_p2p.signaling_client import (
    DEFAULT_RENDEZVOUS_HOST,
    DEFAULT_STUN_PORT,
    build_peer_candidates,
    discover_socket_endpoint,
)

logger = logging.getLogger("DAV.StreamEngine.Service")

EVENT_STREAM_FRAME_RECEIVED = EVENT_VIDEO_FRAME_RX


class DavFrameData(Structure):
    _fields_ = [
        ("rgba_data", POINTER(ctypes.c_uint8)),
        ("data_size", c_size_t),
        ("width", c_uint32),
        ("height", c_uint32),
        ("timestamp_us", c_uint64),
        ("is_keyframe", c_int),
    ]


class DavTelemetry(Structure):
    _fields_ = [
        ("fps", c_float),
        ("bitrate_mbps", c_float),
        ("latency_ms", c_float),
        ("packet_loss_rate", c_float),
        ("packets_sent", c_uint64),
        ("packets_received", c_uint64),
        ("frames_captured", c_uint64),
        ("frames_encoded", c_uint64),
        ("frames_decoded", c_uint64),
        ("frames_rendered", c_uint64),
        ("fec_recovered", c_uint32),
        ("pli_requests", c_uint32),
    ]


DavFrameReadyCallback = CFUNCTYPE(None, POINTER(DavFrameData), c_void_p)
DavTelemetryCallback = CFUNCTYPE(None, POINTER(DavTelemetry), c_void_p)


class StreamEngineService:
    """
    Servico orquestrador unico para sessoes de streaming DA-V (v4.6).
    Conecta `CaptureService`, `CodecService`, `TransportService` e `AudioService`
    ao `EventBus` e a camada de apresentacao desktop.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        capture_service: Optional[CaptureService] = None,
        codec_service: Optional[CodecService] = None,
        transport_service: Optional[TransportService] = None,
        audio_service: Optional[AudioService] = None,
    ):
        self.bus = event_bus or EventBus.get_instance()
        self.capture_service = capture_service or CaptureService()
        self.codec_service = codec_service or CodecService()
        self.transport_service = transport_service or TransportService()
        self.audio_service = audio_service or AudioService()
        self.remote_desktop_service = RemoteDesktopService()
        self.universal_input_service = UniversalInputService()

        self._sender: Optional[SenderWorker] = None
        self._receiver: Optional[ReceiverWorker] = None
        self._current_role: Optional[str] = None
        self._active_route: Optional[Dict[str, Any]] = None
        self._latest_stats: Dict[str, Any] = {}
        self._remote_perms = WorkspacePermissions(admin_elevated=is_process_elevated())
        self._peer_remote_perms = WorkspacePermissions()
        self._client_gamepad_enabled: bool = False
        self._host_gamepad_roster: List[Dict[str, Any]] = []

        # Estado de subprocesso TX e socket preparado RX (fluxo desktop GIL-free)
        self._dll = None
        self._is_native = False
        self._fallback_running = False
        self._fallback_threads: List[threading.Thread] = []
        self._sender_process: Optional[mp.Process] = None
        self._sender_stop_event: Optional[Any] = None
        self._sender_stats_queue: Optional[Any] = None
        self._sender_cmd_queue: Optional[Any] = None
        self._sender_evt_queue: Optional[Any] = None
        self._sender_endpoint_info: Optional[Dict[str, object]] = None
        self._sender_endpoint_ready = threading.Event()
        self._prepared_recv_sock: Optional[socket.socket] = None

        self._user_frame_callback: Optional[Callable] = None
        self._user_telemetry_callback: Optional[Callable] = None
        self._user_audio_callback: Optional[Callable] = None
        self._user_sender_stats_callback: Optional[Callable] = None
        self._user_p2p_event_callback: Optional[Callable] = None
        self._user_log_callback: Optional[Callable] = None

        self._try_load_native_library()

    def _try_load_native_library(self) -> None:
        if os.environ.get("DAV_USE_NATIVE_CORE") != "1":
            return

        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        possible_paths = [
            os.path.join(base_dir, "build", "Release", "dav_core.dll"),
            os.path.join(base_dir, "build", "dav_core.dll"),
            os.path.join(base_dir, "build", "libdav_core.so"),
            "dav_core.dll",
            "libdav_core.so",
        ]
        for p in possible_paths:
            if os.path.exists(p):
                try:
                    self._dll = ctypes.CDLL(os.path.abspath(p))
                    self._setup_c_signatures()
                    self._is_native = True
                    logger.info(f"[StreamEngine] Biblioteca C-ABI carregada: {p}")
                    return
                except Exception as exc:
                    logger.warning(f"[StreamEngine] Falha ao carregar {p}: {exc}")

    def _setup_c_signatures(self) -> None:
        if not self._dll:
            return
        self._dll.dav_init.argtypes = [c_char_p]
        self._dll.dav_init.restype = c_int
        self._dll.dav_start_sender.argtypes = [c_char_p, c_uint16, c_char_p, c_uint32, c_uint32, c_uint32]
        self._dll.dav_start_sender.restype = c_int
        self._dll.dav_start_receiver.argtypes = [
            c_uint16, c_char_p, DavFrameReadyCallback, DavTelemetryCallback, c_void_p
        ]
        self._dll.dav_start_receiver.restype = c_int
        self._dll.dav_stop.argtypes = []
        self._dll.dav_stop.restype = None
        self._dll.dav_request_keyframe.argtypes = []
        self._dll.dav_request_keyframe.restype = None
        self._dll.dav_get_telemetry.argtypes = [POINTER(DavTelemetry)]
        self._dll.dav_get_telemetry.restype = c_int
        self._dll.dav_get_version.argtypes = []
        self._dll.dav_get_version.restype = c_char_p
        self._dll.dav_init(None)

    @property
    def is_native_backend(self) -> bool:
        return self._is_native

    @property
    def is_transmitting(self) -> bool:
        return (self._sender is not None and self._sender._running) or (
            self._sender_process is not None and self._sender_process.is_alive()
        )

    @property
    def is_receiving(self) -> bool:
        return self._receiver is not None and self._receiver._running

    # =========================================================================
    # 1. API Reativa de Fatia (`ServiceResult` + `EventBus`)
    # =========================================================================

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
        codec_type: str = "h264_nvenc",
        audio_enabled: bool = False,
        input_injector: Optional[Any] = None,
        initial_permissions: Optional[Dict[str, bool]] = None,
    ) -> ServiceResult[Dict[str, Any]]:
        """Inicia uma sessao de transmissao em thread via `SenderWorker`."""
        if self.is_transmitting or self.is_receiving:
            self.stop_all()

        sock_res = self.transport_service.bind_udp_socket(port=port)
        if not sock_res.is_success or sock_res.data is None:
            return ServiceResult.fail(f"Falha ao vincular porta UDP de streaming: {sock_res.error}")
        sock = sock_res.data

        cap_res = self.capture_service.create_capturer(
            display_idx=display_idx, width=width, height=height, fps=fps
        )
        if not cap_res.is_success or cap_res.data is None:
            sock.close()
            return ServiceResult.fail(f"Falha ao instanciar capturador: {cap_res.error}")
        capturer = cap_res.data

        enc_res = self.codec_service.create_encoder(
            codec_type=codec_type, width=width, height=height, fps=fps, bitrate_kbps=bitrate_kbps
        )
        if not enc_res.is_success or enc_res.data is None:
            capturer.close()
            sock.close()
            return ServiceResult.fail(f"Falha ao instanciar encoder de video: {enc_res.error}")
        encoder = enc_res.data

        audio_cap = None
        audio_enc = None
        if audio_enabled:
            ac_res = self.audio_service.create_capturer()
            ae_res = self.audio_service.create_encoder()
            if ac_res.is_success and ae_res.is_success:
                audio_cap = ac_res.data
                audio_enc = ae_res.data

        def _on_route_locked(ip: str, p: int, mode_tag: str) -> None:
            self._active_route = {"ip": ip, "port": p, "mode": mode_tag}
            self.bus.publish(EVENT_STREAM_ROUTE_LOCKED, self._active_route)

        def _on_stats(stats: Dict[str, Any]) -> None:
            self._latest_stats = stats
            self.bus.publish(EVENT_STREAM_STATS, stats)

        def _on_remote_evt(kind: str, payload: Any) -> None:
            if kind == "permissions":
                self.bus.publish(EVENT_REMOTE_PERM_CHANGED, payload)
            elif kind == "clipboard":
                self.bus.publish(EVENT_REMOTE_CLIPBOARD, payload)
            elif kind == "file_status":
                self.bus.publish(EVENT_REMOTE_FILE_STATUS, payload)
            elif kind == "gamepad_roster":
                self._host_gamepad_roster = list(payload or [])
                self.bus.publish(EVENT_GAMEPAD_ROSTER_CHANGED, self._host_gamepad_roster)
            elif kind == "gamepad_rumble_ack":
                self.bus.publish(EVENT_GAMEPAD_RUMBLE_ACK, payload)
            elif kind == "client_kb_profile":
                self.bus.publish(EVENT_CLIENT_KEYBOARD_PROFILE, payload)

        eff_perms = initial_permissions if initial_permissions is not None else self._remote_perms.to_dict()
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
            audio_capturer=audio_cap,
            audio_encoder=audio_enc,
            audio_enabled=audio_enabled,
            input_injector=input_injector,
            initial_permissions=eff_perms,
            on_remote_event=_on_remote_evt,
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
        on_audio_callback: Optional[Callable[[int, int, bytes], None]] = None,
    ) -> ServiceResult[Dict[str, Any]]:
        """Inicia uma sessao de recepcao via `ReceiverWorker`."""
        if self.is_transmitting or self.is_receiving:
            self.stop_all()

        sock_res = self.transport_service.bind_udp_socket(port=port)
        if not sock_res.is_success or sock_res.data is None:
            return ServiceResult.fail(f"Falha ao vincular porta UDP de streaming: {sock_res.error}")
        sock = sock_res.data

        dec_res = self.codec_service.create_decoder()
        if not dec_res.is_success or dec_res.data is None:
            sock.close()
            return ServiceResult.fail(f"Falha ao instanciar decoder: {dec_res.error}")
        decoder = dec_res.data

        def _on_frame(frame: np.ndarray) -> None:
            if on_frame_callback:
                on_frame_callback(frame)
            self.bus.publish(EVENT_VIDEO_FRAME_RX, frame)

        def _on_audio(audio_fid: int, tx_ts_us: int, audio_payload: bytes) -> None:
            if on_audio_callback:
                on_audio_callback(audio_fid, tx_ts_us, audio_payload)
            self.bus.publish(EVENT_AUDIO_FRAME_RX, {
                "frame_id": audio_fid,
                "timestamp_us": tx_ts_us,
                "payload": audio_payload,
            })

        def _on_route_locked(ip: str, p: int, mode_tag: str) -> None:
            self._active_route = {"ip": ip, "port": p, "mode": mode_tag}
            self.bus.publish(EVENT_STREAM_ROUTE_LOCKED, self._active_route)

        def _on_stats(stats: Dict[str, Any]) -> None:
            self._latest_stats = stats
            self.bus.publish(EVENT_STREAM_STATS, stats)

        def _on_perm_rx(perms_dict: Dict[str, bool]) -> None:
            self._peer_remote_perms = WorkspacePermissions.from_dict(perms_dict)
            self.bus.publish(EVENT_REMOTE_PERM_CHANGED, perms_dict)

        def _on_clip_rx(txt: str) -> None:
            self.bus.publish(EVENT_REMOTE_CLIPBOARD, txt)

        def _on_file_rx(st: Dict[str, Any]) -> None:
            self.bus.publish(EVENT_REMOTE_FILE_STATUS, st)

        def _on_shell_rx(out: str) -> None:
            self.bus.publish(EVENT_REMOTE_SHELL_OUTPUT, out)

        def _on_echo_rx(rtt_ms: float, itp_ms: float) -> None:
            self.bus.publish(
                EVENT_REMOTE_INPUT_METRICS,
                {"input_rtt_ms": rtt_ms, "input_to_photon_ms": itp_ms},
            )

        receiver = ReceiverWorker(
            sock=sock,
            decoder=decoder,
            pin=pin,
            candidates=candidates,
            relay_addr=relay_addr,
            on_frame=_on_frame,
            on_audio=_on_audio,
            on_route_locked=_on_route_locked,
            on_stats=_on_stats,
            on_permissions_changed=_on_perm_rx,
            on_clipboard_rx=_on_clip_rx,
            on_file_status=_on_file_rx,
            on_shell_output=_on_shell_rx,
            on_input_echo=_on_echo_rx,
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
        """Injeta candidatos de Hole-Punching na sessao ativa."""
        if self._sender:
            self._sender.pair_peer(candidates, relay_info)
            return ServiceResult.ok(True)
        if self._receiver:
            self._receiver.pair_peer(candidates, relay_info)
            return ServiceResult.ok(True)
        return ServiceResult.fail("Nenhuma sessao de streaming ativa para parear.")

    def stop_all(self) -> ServiceResult[bool]:
        """Encerra com seguranca qualquer transmissao ou recepcao ativa."""
        self.stop()
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
        return {
            "active_role": self._current_role,
            "is_transmitting": self.is_transmitting,
            "is_receiving": self.is_receiving,
            "route": self._active_route,
            "latest_stats": self._latest_stats,
        }

    # =========================================================================
    # 2. API Desktop / Subprocesso GIL-Free e Single-Socket STUN
    # =========================================================================

    def start_sender(
        self,
        target_ip: str,
        target_port: int,
        pin: str,
        width: int = 1920,
        height: int = 1080,
        fps: int = 60,
        bitrate_kbps: int = 12000,
        on_sender_stats: Optional[Callable] = None,
        codec_type: str = "h264_nvenc",
        monitor_index: int = 0,
        bind_port: Optional[int] = None,
        on_p2p_event: Optional[Callable] = None,
        on_log: Optional[Callable] = None,
        audio_enabled: bool = True,
    ) -> bool:
        self._user_sender_stats_callback = on_sender_stats or (lambda *a: None)
        self._user_p2p_event_callback = on_p2p_event
        self._user_log_callback = on_log
        self._sender_endpoint_info = None
        self._sender_endpoint_ready.clear()

        if self._is_native and self._dll:
            res = self._dll.dav_start_sender(
                target_ip.encode("utf-8"),
                target_port,
                pin.encode("utf-8"),
                width,
                height,
                fps,
            )
            return res == 0

        target_fps = fps if fps > 0 else 60
        ctx = mp.get_context("spawn")
        self._sender_stats_queue = ctx.Queue(maxsize=16)
        self._sender_cmd_queue = ctx.Queue(maxsize=64)
        self._sender_evt_queue = ctx.Queue(maxsize=64)
        self._sender_stop_event = ctx.Event()

        self._sender_process = ctx.Process(
            target=run_sender_subprocess,
            name="DAV-Sender-Engine",
            daemon=True,
            args=(
                target_ip,
                target_port,
                pin,
                width,
                height,
                target_fps,
                bitrate_kbps,
                self._sender_stats_queue,
                self._sender_stop_event,
                codec_type,
                monitor_index,
                self._sender_cmd_queue,
                self._sender_evt_queue,
                bind_port,
                audio_enabled,
                self._remote_perms.to_dict(),
            ),
        )
        self._sender_process.start()
        self._fallback_running = True
        self._current_role = "sender"

        def _stats_poller():
            while self._fallback_running:
                try:
                    item = self._sender_stats_queue.get(timeout=0.12)
                    frames_sent, cur_fps, cur_mbps, packets_sent, quality, frame_kb = item
                    self._latest_stats = {
                        "fps": round(cur_fps, 1),
                        "bitrate_mbps": round(cur_mbps, 2),
                        "frames_count": frames_sent,
                        "packets_count": packets_sent,
                    }
                    self.bus.publish(EVENT_STREAM_STATS, self._latest_stats)
                    if self._user_sender_stats_callback:
                        try:
                            self._user_sender_stats_callback(
                                frames_sent, cur_fps, cur_mbps, packets_sent, quality, frame_kb
                            )
                        except TypeError:
                            self._user_sender_stats_callback(frames_sent, cur_fps, cur_mbps, packets_sent)
                except Exception:
                    pass

        def _evt_poller():
            while self._fallback_running:
                try:
                    evt = self._sender_evt_queue.get(timeout=0.15)
                    if not evt:
                        continue
                    if evt[0] == "ENDPOINT_READY":
                        self._sender_endpoint_info = evt[1]
                        self._sender_endpoint_ready.set()
                    elif evt[0] == "P2P_LOCKED":
                        self._active_route = {"ip": evt[1], "port": evt[2], "mode": evt[3]}
                        self.bus.publish(EVENT_STREAM_ROUTE_LOCKED, self._active_route)
                        if self._user_p2p_event_callback:
                            self._user_p2p_event_callback(evt[1], evt[2], evt[3])
                    elif evt[0] == "REMOTE_PERMS":
                        self._remote_perms = WorkspacePermissions.from_dict(evt[1])
                        self.bus.publish(EVENT_REMOTE_PERM_CHANGED, evt[1])
                    elif evt[0] == "REMOTE_CLIPBOARD":
                        self.bus.publish(EVENT_REMOTE_CLIPBOARD, evt[1])
                    elif evt[0] == "REMOTE_FILE_STATUS":
                        self.bus.publish(EVENT_REMOTE_FILE_STATUS, evt[1])
                    elif evt[0] == "GAMEPAD_ROSTER":
                        self._host_gamepad_roster = list(evt[1] or [])
                        self.bus.publish(EVENT_GAMEPAD_ROSTER_CHANGED, self._host_gamepad_roster)
                    elif evt[0] == "GAMEPAD_RUMBLE_ACK":
                        self.bus.publish(EVENT_GAMEPAD_RUMBLE_ACK, evt[1])
                    elif evt[0] == "CLIENT_KB_PROFILE":
                        self.bus.publish(EVENT_CLIENT_KEYBOARD_PROFILE, evt[1])
                    elif evt[0] == "log":
                        if self._user_log_callback:
                            try:
                                self._user_log_callback(evt[1], evt[2])
                            except Exception:
                                pass
                except Exception:
                    pass

        t_stats = threading.Thread(target=_stats_poller, daemon=True, name="DAV-Sender-Stats")
        t_evts = threading.Thread(target=_evt_poller, daemon=True, name="DAV-Sender-Events")
        self._fallback_threads = [t_stats, t_evts]
        t_stats.start()
        t_evts.start()
        return True

    def set_sender_audio_muted(self, muted: bool) -> None:
        if self._sender is not None:
            self._sender.set_audio_muted(muted)
        if self._sender_cmd_queue is not None:
            try:
                self._sender_cmd_queue.put(("AUDIO_MUTE", bool(muted)))
            except Exception:
                pass

    def wait_sender_endpoint(self, timeout: float = 2.8) -> Optional[Dict[str, object]]:
        self._sender_endpoint_ready.wait(timeout=timeout)
        return self._sender_endpoint_info

    def pair_sender_peer(
        self,
        peer_info: dict,
        my_public_ip: Optional[str] = None,
        relay_info: Optional[dict] = None,
    ) -> None:
        if self._sender is not None:
            cands = build_peer_candidates(peer_info, my_public_ip=my_public_ip)
            self._sender.pair_peer(cands, relay_info=relay_info or peer_info.get("_relay"))
        if self._sender_cmd_queue is not None:
            try:
                self._sender_cmd_queue.put(("PAIR_PEER", peer_info, my_public_ip, relay_info))
            except Exception:
                pass

    def update_sender_target(self, new_ip: str, new_port: int) -> None:
        if self._sender is not None:
            self._sender.update_target(new_ip, new_port)
        if self._sender_cmd_queue is not None:
            try:
                self._sender_cmd_queue.put(("UPDATE_TARGET", str(new_ip), int(new_port)))
            except Exception:
                pass

    def pause_sender(self) -> None:
        if self._sender_cmd_queue is not None:
            try:
                self._sender_cmd_queue.put(("PAUSE_STREAM",))
            except Exception:
                pass

    def resume_sender(self, ip: str, port: int) -> None:
        if self._sender_cmd_queue is not None:
            try:
                self._sender_cmd_queue.put(("START_STREAM", str(ip), int(port)))
            except Exception:
                pass

    def request_keyframe(self) -> None:
        if self._is_native and self._dll:
            self._dll.dav_request_keyframe()
        elif self._sender is not None:
            self._sender.request_keyframe()
        elif self._sender_cmd_queue is not None:
            try:
                self._sender_cmd_queue.put(("REQUEST_KEYFRAME",))
            except Exception:
                pass

    def request_receiver_pli(self) -> None:
        """Aciona pedido imediato de IDR limpo no Receptor ativo (usado pelo DecodeWorker em Zero-Ghosting)."""
        if self._receiver is not None:
            try:
                self._receiver.request_pli(force=True)
            except Exception:
                pass

    def prepare_receiver_socket(
        self,
        bind_port: int,
        rendezvous_host: str = DEFAULT_RENDEZVOUS_HOST,
        stun_port: int = DEFAULT_STUN_PORT,
    ) -> Dict[str, object]:
        self._close_prepared_recv_sock()
        sock_res = self.transport_service.create_media_socket(bind_port=bind_port, rcvbuf_mb=32, sndbuf_mb=8)
        if not sock_res.is_success or sock_res.data is None:
            return {"local_port": bind_port}
        self._prepared_recv_sock = sock_res.data
        return discover_socket_endpoint(self._prepared_recv_sock, rendezvous_host=rendezvous_host, stun_port=stun_port)

    def _close_prepared_recv_sock(self) -> None:
        if self._prepared_recv_sock is not None:
            try:
                self._prepared_recv_sock.close()
            except Exception:
                pass
            self._prepared_recv_sock = None

    def start_receiver(
        self,
        bind_port: int,
        pin: str,
        on_frame_ready: Callable,
        on_telemetry: Optional[Callable] = None,
        target_peer: Optional[Tuple[str, int]] = None,
        peer_info: Optional[dict] = None,
        my_public_ip: Optional[str] = None,
        relay_info: Optional[dict] = None,
        on_p2p_status: Optional[Callable] = None,
        on_audio_ready: Optional[Callable[[int, int, bytes], None]] = None,
    ) -> bool:
        self._user_frame_callback = on_frame_ready
        self._user_telemetry_callback = on_telemetry
        self._user_audio_callback = on_audio_ready

        if self._is_native and self._dll:
            def _native_frame_bridge(frame_ptr, user_data):
                if frame_ptr and self._user_frame_callback:
                    f = frame_ptr.contents
                    buf = ctypes.string_at(f.rgba_data, f.data_size)
                    self._user_frame_callback(buf, f.width, f.height, f.timestamp_us, bool(f.is_keyframe))

            def _native_telemetry_bridge(telem_ptr, user_data):
                if telem_ptr and self._user_telemetry_callback:
                    t = telem_ptr.contents
                    self._user_telemetry_callback(
                        t.fps, t.bitrate_mbps, t.latency_ms,
                        t.packets_received, t.frames_rendered,
                    )

            self._frame_cb_native = DavFrameReadyCallback(_native_frame_bridge)
            self._telemetry_cb_native = DavTelemetryCallback(_native_telemetry_bridge)
            res = self._dll.dav_start_receiver(
                bind_port,
                pin.encode("utf-8"),
                self._frame_cb_native,
                self._telemetry_cb_native,
                None,
            )
            return res == 0

        sock = self._prepared_recv_sock
        self._prepared_recv_sock = None
        if sock is None:
            sock_res = self.transport_service.create_media_socket(bind_port=bind_port, rcvbuf_mb=32, sndbuf_mb=8)
            if not sock_res.is_success or sock_res.data is None:
                return False
            sock = sock_res.data
        sock.settimeout(0.05)

        candidates = build_peer_candidates(peer_info, my_public_ip=my_public_ip) if peer_info else []
        if not candidates and target_peer:
            candidates = [(str(target_peer[0]), int(target_peer[1]), "direct")]

        relay_addr: Optional[Tuple[str, int]] = None
        relay_http_url: Optional[str] = None
        if relay_info and relay_info.get("host") and relay_info.get("port"):
            relay_addr = (str(relay_info["host"]), int(relay_info["port"]))
            if relay_info.get("http_base_url"):
                relay_http_url = str(relay_info["http_base_url"])

        def _on_route_locked(ip: str, p: int, mode_tag: str) -> None:
            self._active_route = {"ip": ip, "port": p, "mode": mode_tag}
            self.bus.publish(EVENT_STREAM_ROUTE_LOCKED, self._active_route)
            if on_p2p_status:
                on_p2p_status(ip, p, mode_tag)

        def _on_stats(stats: Dict[str, Any]) -> None:
            self._latest_stats = stats
            self.bus.publish(EVENT_STREAM_STATS, stats)
            if self._user_telemetry_callback:
                self._user_telemetry_callback(
                    float(stats.get("fps", 0.0)),
                    float(stats.get("bitrate_mbps", 0.0)),
                    float(stats.get("latency_ms", 1.5)),
                    int(stats.get("packets_count", 0)),
                    int(stats.get("frames_count", 0)),
                )

        def _on_audio(audio_fid: int, tx_ts_us: int, audio_payload: bytes) -> None:
            if on_audio_ready:
                on_audio_ready(audio_fid, tx_ts_us, audio_payload)
            self.bus.publish(EVENT_AUDIO_FRAME_RX, {
                "frame_id": audio_fid,
                "timestamp_us": tx_ts_us,
                "payload": audio_payload,
            })

        def _on_perm_desk(perms_dict: Dict[str, bool]) -> None:
            self._peer_remote_perms = WorkspacePermissions.from_dict(perms_dict)
            self.bus.publish(EVENT_REMOTE_PERM_CHANGED, perms_dict)

        def _on_clip_desk(txt: str) -> None:
            self.bus.publish(EVENT_REMOTE_CLIPBOARD, txt)

        def _on_file_desk(st: Dict[str, Any]) -> None:
            self.bus.publish(EVENT_REMOTE_FILE_STATUS, st)

        def _on_shell_desk(out: str) -> None:
            self.bus.publish(EVENT_REMOTE_SHELL_OUTPUT, out)

        def _on_echo_desk(rtt_ms: float, itp_ms: float) -> None:
            self.bus.publish(
                EVENT_REMOTE_INPUT_METRICS,
                {"input_rtt_ms": rtt_ms, "input_to_photon_ms": itp_ms},
            )

        self._peer_remote_perms = WorkspacePermissions()
        receiver = ReceiverWorker(
            sock=sock,
            decoder=None,
            pin=pin,
            candidates=candidates,
            relay_addr=relay_addr,
            relay_http_base_url=relay_http_url,
            on_encoded_frame=on_frame_ready,
            on_audio=_on_audio,
            on_route_locked=_on_route_locked,
            on_stats=_on_stats,
            on_permissions_changed=_on_perm_desk,
            on_clipboard_rx=_on_clip_desk,
            on_file_status=_on_file_desk,
            on_shell_output=_on_shell_desk,
            on_input_echo=_on_echo_desk,
        )
        receiver.set_gamepad_enabled(self._client_gamepad_enabled)
        receiver.start()
        self._receiver = receiver
        self._fallback_running = True
        self._current_role = "receiver"
        return True

    def set_remote_permissions(self, **perms: bool) -> Dict[str, bool]:
        for k in (
            "allow_input",
            "allow_gamepad",
            "allow_clipboard",
            "allow_files",
            "allow_shell",
            "admin_elevated",
        ):
            if k in perms and perms[k] is not None:
                setattr(self._remote_perms, k, bool(perms[k]))
        snap = self._remote_perms.to_dict()
        if self._sender is not None:
            snap = self._sender.set_remote_permissions(**snap)
        if self._sender_cmd_queue is not None:
            try:
                self._sender_cmd_queue.put_nowait(("SET_REMOTE_PERMS", snap))
            except Exception:
                pass
        self.bus.publish(EVENT_REMOTE_PERM_CHANGED, snap)
        return snap

    def get_remote_permissions(self) -> Dict[str, bool]:
        return self._remote_perms.to_dict()

    def get_peer_remote_permissions(self) -> Dict[str, bool]:
        return self._peer_remote_perms.to_dict()

    def panic_revoke_remote(self) -> Dict[str, bool]:
        self._remote_perms.allow_input = False
        self._remote_perms.allow_gamepad = False
        self._remote_perms.allow_clipboard = False
        self._remote_perms.allow_files = False
        self._remote_perms.allow_shell = False
        snap = self._remote_perms.to_dict()
        if self._sender is not None:
            snap = self._sender.panic_revoke_remote()
        if self._sender_cmd_queue is not None:
            try:
                self._sender_cmd_queue.put_nowait(("PANIC_REVOKE_REMOTE",))
            except Exception:
                pass
        self.bus.publish(EVENT_REMOTE_PERM_CHANGED, snap)
        return snap

    def set_client_gamepad_enabled(self, enabled: bool) -> bool:
        self._client_gamepad_enabled = bool(enabled)
        if self._receiver is not None:
            return self._receiver.set_gamepad_enabled(self._client_gamepad_enabled)
        return self._client_gamepad_enabled

    @property
    def is_client_gamepad_enabled(self) -> bool:
        if self._receiver is not None:
            return self._receiver.is_gamepad_enabled
        return self._client_gamepad_enabled

    def get_host_gamepad_roster(self) -> List[Dict[str, Any]]:
        if self._sender is not None:
            return self._sender.gamepad_hub.get_roster_snapshot()
        return list(self._host_gamepad_roster)

    def get_local_gamepads(self) -> List[Dict[str, Any]]:
        if self._receiver is not None and self._receiver.gamepad_capturer is not None:
            states = self._receiver.gamepad_capturer.get_local_controllers()
        else:
            states = []
        return [
            {
                "local_slot": st.local_slot,
                "kind": int(st.kind),
                "kind_label": st.kind.display_label,
                "device_name": st.device_name or st.kind.display_label,
                "connected": st.connected,
                "buttons_mask": st.buttons_mask,
                "lt_u8": st.lt_u8,
                "rt_u8": st.rt_u8,
                "lx_i16": st.lx_i16,
                "ly_i16": st.ly_i16,
                "rx_i16": st.rx_i16,
                "ry_i16": st.ry_i16,
            }
            for st in states
        ]

    def trigger_remote_gamepad_rumble_test(self, host_slot: Optional[int] = None) -> bool:
        if self._sender is not None:
            return self._sender.trigger_gamepad_rumble_test(host_slot=host_slot)
        if self._sender_cmd_queue is not None and self._sender_process is not None and self._sender_process.is_alive():
            try:
                self._sender_cmd_queue.put_nowait(("TEST_GAMEPAD_RUMBLE", host_slot))
                return True
            except Exception:
                return False
        return False

    def test_local_gamepad_rumble(self, local_slot: int = 0xFF) -> Tuple[bool, str]:
        if self._receiver is not None and self._receiver.gamepad_capturer is not None:
            return self._receiver.gamepad_capturer.trigger_rumble(local_slot=local_slot)
        cap_res = self.universal_input_service.create_gamepad_capturer()
        if not cap_res.is_success or cap_res.data is None:
            return False, cap_res.error or "Capturador indisponivel"
        cap = cap_res.data
        try:
            cap.backend.poll_states()
            return cap.trigger_rumble(local_slot=local_slot)
        finally:
            cap.close()

    def is_remote_admin_elevated(self) -> bool:
        return bool(self._remote_perms.admin_elevated or self.remote_desktop_service.is_admin_elevated())

    def request_remote_admin_elevation(
        self,
        launcher_fn: Optional[Callable] = None,
    ) -> ServiceResult[bool]:
        if self._sender_cmd_queue is not None and self._sender_process is not None and self._sender_process.is_alive():
            try:
                self._sender_cmd_queue.put_nowait(("ELEVATE_REMOTE_ADMIN",))
                return ServiceResult.ok(True)
            except Exception as exc:
                return ServiceResult.fail(str(exc))

        res = self.remote_desktop_service.request_admin_elevation(launcher_fn=launcher_fn)
        if not res.is_success or res.data is None:
            return ServiceResult.fail(res.error or "Elevacao cancelada.")
        self._remote_perms.admin_elevated = True
        if self._sender is not None:
            self._sender.set_input_injector(res.data)
        self.bus.publish(EVENT_REMOTE_PERM_CHANGED, self._remote_perms.to_dict())
        return ServiceResult.ok(True)

    def send_remote_input(self, pkt: Any) -> bool:
        if self._receiver is not None:
            return self._receiver.send_remote_input(pkt)
        return False

    def send_clipboard_text(self, text: str) -> bool:
        if self._receiver is not None:
            return self._receiver.send_clipboard_text(text)
        if self._sender is not None:
            return self._sender.send_clipboard_text(text)
        if self._sender_cmd_queue is not None and self._remote_perms.allow_clipboard:
            try:
                self._sender_cmd_queue.put_nowait(("SEND_CLIPBOARD", str(text)))
                return True
            except Exception:
                return False
        return False

    def send_file(self, file_path: str) -> Optional[str]:
        if self._receiver is not None:
            return self._receiver.send_file(file_path)
        if self._sender is not None:
            return self._sender.send_file(file_path)
        if self._sender_cmd_queue is not None and self._remote_perms.allow_files:
            try:
                self._sender_cmd_queue.put_nowait(("SEND_FILE", str(file_path)))
                return "queued"
            except Exception:
                return None
        return None

    def send_shell_input(self, command_text: str) -> bool:
        if self._receiver is not None:
            return self._receiver.send_shell_input(command_text)
        return False

    def stop(self) -> None:
        self._close_prepared_recv_sock()
        self._sender_endpoint_ready.clear()
        self._sender_endpoint_info = None
        self._active_route = None
        self._current_role = None
        if self._is_native and self._dll:
            self._dll.dav_stop()
            return

        self._fallback_running = False
        if self._sender_stop_event is not None:
            try:
                self._sender_stop_event.set()
            except Exception:
                pass
        if self._sender_process is not None:
            try:
                self._sender_process.join(timeout=0.6)
                if self._sender_process.is_alive():
                    self._sender_process.terminate()
                    self._sender_process.join(timeout=0.8)
                if self._sender_process.is_alive():
                    self._sender_process.kill()
                    self._sender_process.join(timeout=0.3)
            except Exception:
                pass
            self._sender_process = None
        self._sender_stop_event = None
        self._sender_cmd_queue = None
        self._sender_evt_queue = None
        self._sender_stats_queue = None

        if self._receiver is not None:
            try:
                self._receiver.stop()
            except Exception:
                pass
            self._receiver = None

        for t in self._fallback_threads:
            if t.is_alive():
                t.join(timeout=0.35)
        self._fallback_threads.clear()


DavCoreEngine = StreamEngineService
