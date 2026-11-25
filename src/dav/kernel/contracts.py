# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
MonoTech Core Kernel — Contratos Formais de Fatia e Topicos de Eventos (v4.6)
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import socket
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from src.dav.kernel.result import ServiceResult, TelemetryDTO

# Topicos canonicos do EventBus
EVENT_VIDEO_FRAME_RX = "stream.frame_received"
EVENT_AUDIO_FRAME_RX = "stream.audio_received"
EVENT_STREAM_ROUTE_LOCKED = "stream.route_locked"
EVENT_STREAM_STATS = "stream.stats"
EVENT_STREAM_STOPPED = "stream.stopped"
EVENT_LAN_PEERS_UPDATED = "discovery.peers_updated"
EVENT_TUPA_SNAPSHOT = "telemetry.tupa_snapshot"
EVENT_LOG_MESSAGE = "system.log_message"
EVENT_REMOTE_PERM_CHANGED = "remote.permissions_changed"
EVENT_REMOTE_CLIPBOARD = "remote.clipboard_synced"
EVENT_REMOTE_FILE_STATUS = "remote.file_transfer_status"
EVENT_REMOTE_SHELL_OUTPUT = "remote.shell_output"
EVENT_REMOTE_INPUT_METRICS = "remote.input_metrics"
EVENT_GAMEPAD_ROSTER_CHANGED = "input.gamepad_roster_changed"
EVENT_GAMEPAD_RUMBLE_ACK = "input.gamepad_rumble_ack"
EVENT_CLIENT_KEYBOARD_PROFILE = "input.client_keyboard_profile"


@runtime_checkable
class ICaptureService(Protocol):
    def create_capturer(
        self,
        width: int = 1920,
        height: int = 1080,
        fps: int = 60,
        monitor_index: int = 0,
        display_idx: Optional[int] = None,
        force_synthetic: bool = False,
    ) -> ServiceResult[Any]: ...

    def enumerate_monitors(self) -> List[Dict[str, Any]]: ...


@runtime_checkable
class ICodecService(Protocol):
    def create_encoder(
        self,
        codec_type: str = "h264_nvenc",
        width: int = 1920,
        height: int = 1080,
        fps: int = 60,
        bitrate_kbps: int = 12000,
    ) -> ServiceResult[Any]: ...

    def create_decoder(self) -> ServiceResult[Any]: ...


@runtime_checkable
class ITransportService(Protocol):
    def bind_udp_socket(self, port: int = 0) -> ServiceResult[socket.socket]: ...
    def discover_nat(self, bound_sock: socket.socket, rendezvous_host: str = "129.148.26.150") -> ServiceResult[Dict[str, Any]]: ...
    def create_data_plane_sender(self, pin: str, send_raw_fn: Callable[[bytes], None], initial_bitrate_kbps: int = 12000, fps: int = 60) -> Any: ...
    def create_data_plane_receiver(self, pin: str) -> Any: ...
    def create_signaling_client(self, rendezvous_host: Optional[str] = None) -> Any: ...
    def create_lan_beacon(self, node_name: str, stream_port: int = 9000, pin: str = "123456") -> Any: ...


@runtime_checkable
class IAudioService(Protocol):
    def create_capturer(self, prefer_synthetic: bool = False) -> ServiceResult[Any]: ...
    def create_encoder(self, bitrate_bps: int = 96000, enable_lbrr: bool = True) -> ServiceResult[Any]: ...
    def create_decoder(self) -> ServiceResult[Any]: ...
    def create_jitter_buffer(self) -> Any: ...


@runtime_checkable
class IStreamEngineService(Protocol):
    @property
    def is_transmitting(self) -> bool: ...

    @property
    def is_receiving(self) -> bool: ...

    def start_transmission(self, **kwargs: Any) -> ServiceResult[Dict[str, Any]]: ...
    def start_reception(self, **kwargs: Any) -> ServiceResult[Dict[str, Any]]: ...
    def stop_all(self) -> ServiceResult[bool]: ...
    def get_status(self) -> Dict[str, Any]: ...


@runtime_checkable
class ITelemetryService(Protocol):
    def get_telemetry_snapshot(self) -> TelemetryDTO: ...
    def push_to_sde_hub(self) -> None: ...
    def create_tupa_checker(self, sample_interval_sec: float = 1.0) -> Any: ...
    def probe_send(self, stage: str, t_start: float, t_end: float, frame_id: int = 0, extra: Optional[Dict[str, Any]] = None) -> None: ...


@runtime_checkable
class IRemoteDesktopService(Protocol):
    def create_injector(
        self,
        force_synthetic: bool = False,
        prefer_elevated: bool = False,
    ) -> ServiceResult[Any]: ...
    def create_security_gate(self, **initial_perms: bool) -> Any: ...
    def create_workspace_agent(
        self,
        gate: Any,
        download_dir: Optional[str] = None,
    ) -> Any: ...
    def translate_qt_key(
        self,
        qt_key: int,
        native_scancode: int = 0,
        native_vk: int = 0,
    ) -> int: ...
    def is_admin_elevated(self) -> bool: ...
    def request_admin_elevation(self) -> ServiceResult[Any]: ...


@runtime_checkable
class IUniversalInputService(Protocol):
    def detect_client_keyboard_profile(self) -> ServiceResult[Any]: ...
    def create_keyboard_translator(self) -> Any: ...
    def create_keyboard_reproducer(self) -> Any: ...
    def create_gamepad_capturer(
        self,
        on_state_packet: Optional[Callable[[Any], None]] = None,
        prefer_synthetic: bool = False,
    ) -> ServiceResult[Any]: ...
    def create_virtual_gamepad_hub(
        self,
        on_rumble_to_peer: Optional[Callable[[str, bytes], None]] = None,
        force_synthetic: bool = False,
    ) -> ServiceResult[Any]: ...
