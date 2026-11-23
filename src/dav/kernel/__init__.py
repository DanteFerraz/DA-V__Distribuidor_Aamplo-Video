# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
MonoTech Core Kernel — DA-V v4.0
Fornece infraestrutura agnóstica de transporte, registro dinâmico de módulos,
barramento de eventos assíncrono, buffers zero-copy e isolamento de falhas.
"""

from src.dav.kernel.result import ServiceResult, FrameDTO, RouteDTO, TelemetryDTO
from src.dav.kernel.registry import ModuleManifest, ModuleRegistry
from src.dav.kernel.event_bus import EventBus
from src.dav.kernel.buffer_pool import L1BufferPool
from src.dav.kernel.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from src.dav.kernel.config import ConfigEngine
from src.dav.kernel.contracts import (
    EVENT_AUDIO_FRAME_RX,
    EVENT_LAN_PEERS_UPDATED,
    EVENT_LOG_MESSAGE,
    EVENT_STREAM_ROUTE_LOCKED,
    EVENT_STREAM_STATS,
    EVENT_STREAM_STOPPED,
    EVENT_TUPA_SNAPSHOT,
    EVENT_VIDEO_FRAME_RX,
    IAudioService,
    ICaptureService,
    ICodecService,
    IStreamEngineService,
    ITelemetryService,
    ITransportService,
)

__all__ = [
    "ServiceResult",
    "FrameDTO",
    "RouteDTO",
    "TelemetryDTO",
    "ModuleManifest",
    "ModuleRegistry",
    "EventBus",
    "L1BufferPool",
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "ConfigEngine",
    "EVENT_VIDEO_FRAME_RX",
    "EVENT_AUDIO_FRAME_RX",
    "EVENT_STREAM_ROUTE_LOCKED",
    "EVENT_STREAM_STATS",
    "EVENT_STREAM_STOPPED",
    "EVENT_LAN_PEERS_UPDATED",
    "EVENT_TUPA_SNAPSHOT",
    "EVENT_LOG_MESSAGE",
    "ICaptureService",
    "ICodecService",
    "ITransportService",
    "IAudioService",
    "IStreamEngineService",
    "ITelemetryService",
]

