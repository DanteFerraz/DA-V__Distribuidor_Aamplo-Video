# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
MonoTech Core Kernel — Padrão de Resultados e DTOs (Data Transfer Objects)
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ServiceResult(Generic[T]):
    """
    Encapsulamento funcional de resultados de serviços e operações de mídia/rede.
    Elimina exceções descontroladas que derrubam pipelines de tempo real.
    """
    is_success: bool
    value: Optional[T] = None
    error: Optional[str] = None
    code: str = "OK"
    details: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, value: T, code: str = "OK", details: Optional[Dict[str, Any]] = None) -> ServiceResult[T]:
        return cls(is_success=True, value=value, error=None, code=code, details=details or {})

    @classmethod
    def fail(cls, error: str, code: str = "ERROR", details: Optional[Dict[str, Any]] = None) -> ServiceResult[T]:
        return cls(is_success=False, value=None, error=error, code=code, details=details or {})

    @property
    def is_error(self) -> bool:
        return not self.is_success

    @property
    def data(self) -> Optional[T]:
        """Alias ergonômico para self.value."""
        return self.value

    def unwrap(self) -> T:
        if self.is_error:
            raise ValueError(f"Tentativa de unwrap em ServiceResult com erro [{self.code}]: {self.error}")
        return self.value  # type: ignore[return-value]


@dataclass
class FrameDTO:
    """Representação neutra e tipada de um quadro de vídeo na pipeline."""
    data: Any  # bytes, memoryview ou np.ndarray
    width: int
    height: int
    timestamp_us: int
    is_keyframe: bool = False
    codec: str = "H264"
    frame_id: int = 0
    stride: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteDTO:
    """Representação de rota de rede e par de endpoints estabelecido."""
    remote_ip: str
    remote_port: int
    route_type: str  # 'LAN Direto', 'WAN P2P Direto', 'Blind Relay UDP'
    nat_type: str = "unknown"
    rtt_ms: float = 0.0
    is_relayed: bool = False


@dataclass
class TelemetryDTO:
    """Snapshot instantâneo de métricas operacionais para a UI e exportadores."""
    fps: float
    bitrate_mbps: float
    latency_ms: float
    frames_count: int = 0
    packets_count: int = 0
    frame_kb: int = 0
    jitter_ms: float = 0.0
    packet_loss_pct: float = 0.0
    route_mode: str = "P2P"
    mode: str = "P2P"
    details: str = ""
