# -*- coding: utf-8 -*-
"""
MonoTech Core Kernel — DA-V v4.0
Fornece infraestrutura agnóstica de transporte, registro dinâmico de módulos,
barramento de eventos assíncrono, buffers zero-copy e isolamento de falhas.
"""

from src.dav.kernel.result import ServiceResult, FrameDTO, RouteDTO, TelemetryDTO
from src.dav.kernel.registry import ModuleRegistry
from src.dav.kernel.event_bus import EventBus
from src.dav.kernel.buffer_pool import L1BufferPool
from src.dav.kernel.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from src.dav.kernel.config import ConfigEngine

__all__ = [
    "ServiceResult",
    "FrameDTO",
    "RouteDTO",
    "TelemetryDTO",
    "ModuleRegistry",
    "EventBus",
    "L1BufferPool",
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "ConfigEngine",
]
