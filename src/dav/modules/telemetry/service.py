# -*- coding: utf-8 -*-
"""
Serviço de Telemetria e Observabilidade TUPÃ/SDE — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.dav.kernel.event_bus import EventBus
from src.dav.kernel.result import TelemetryDTO
from src.dav.modules.telemetry.tupa_probes import TupaNetworkProbe
from src.dav.modules.telemetry.sde_exporter import SDETelemetryExporter

logger = logging.getLogger("DAV.Telemetry.Service")


class TelemetryService:
    """
    Coordena métricas em tempo real, cálculos estatísticos e integração
    com os ecossistemas TUPÃ e SDE.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        probe: Optional[TupaNetworkProbe] = None,
        exporter: Optional[SDETelemetryExporter] = None,
    ):
        self.bus = event_bus or EventBus.get_instance()
        self.probe = probe or TupaNetworkProbe()
        self.exporter = exporter or SDETelemetryExporter()
        self._current_stats: Dict[str, Any] = {
            "fps": 0.0,
            "bitrate_mbps": 0.0,
            "latency_ms": 0.0,
            "packets_count": 0,
            "frames_count": 0,
        }

        # Inscreve-se nas estatísticas do StreamEngine
        self.bus.subscribe("stream.stats", self._on_stream_stats)

    def _on_stream_stats(self, stats: Dict[str, Any]) -> None:
        if not isinstance(stats, dict):
            return
        self._current_stats.update(stats)
        self.probe.record_stats(
            fps=float(stats.get("fps", 0.0)),
            bitrate_mbps=float(stats.get("bitrate_mbps", 0.0)),
        )

    def get_telemetry_snapshot(self) -> TelemetryDTO:
        """Gera DTO padronizado de telemetria para o HUD e painel TUPÃ."""
        snap = self.probe.get_snapshot()
        return TelemetryDTO(
            fps=self._current_stats.get("fps", snap.fps),
            bitrate_mbps=self._current_stats.get("bitrate_mbps", 0.0),
            latency_ms=self._current_stats.get("latency_ms", snap.latency_ms),
            jitter_ms=snap.jitter_ms,
            packet_loss_pct=snap.packet_loss_pct,
            route_mode=self._current_stats.get("route_mode", "P2P"),
        )

    def push_to_sde_hub(self) -> None:
        """Exporta métricas de forma não-bloqueante ao SDE."""
        dto = self.get_telemetry_snapshot()
        payload = {
            "app": "DA-V",
            "version": "4.0.0",
            "fps": dto.fps,
            "bitrate_mbps": dto.bitrate_mbps,
            "latency_ms": dto.latency_ms,
            "jitter_ms": dto.jitter_ms,
        }
        self.exporter.export_metric(payload)

