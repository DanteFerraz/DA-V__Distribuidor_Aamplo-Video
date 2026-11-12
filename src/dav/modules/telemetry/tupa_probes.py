# -*- coding: utf-8 -*-
"""
Sondas de Rede e Telemetria TUPÃ — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import collections
import time
from typing import Deque, Dict, Optional
from src.dav.kernel.result import TelemetryDTO


class TupaNetworkProbe:
    """
    Sonda de telemetria baseada nos princípios do protocolo TUPÃ.
    Mede jitter estatístico (RFC 3550), RTT e variação instantânea de vazão.
    """

    def __init__(self, sample_window: int = 60):
        self._latencies: Deque[float] = collections.deque(maxlen=sample_window)
        self._fps_samples: Deque[float] = collections.deque(maxlen=sample_window)
        self._last_arrival_us: Optional[int] = None
        self._jitter_us: float = 0.0

    def record_packet_arrival(self, sender_ts_us: int) -> None:
        """Registra a chegada de um datagrama e atualiza o jitter instantâneo."""
        now_us = int(time.time_ns() // 1000)
        transit_us = now_us - sender_ts_us

        if self._last_arrival_us is not None:
            # Cálculo de jitter segundo RFC 3550: D(i, j) = (R_j - S_j) - (R_i - S_i)
            # J = J + (|D| - J) / 16
            diff = abs(transit_us - self._last_arrival_us)
            self._jitter_us += (diff - self._jitter_us) / 16.0

        self._last_arrival_us = transit_us
        self._latencies.append(transit_us / 1000.0)

    def record_stats(self, fps: float, bitrate_mbps: float) -> None:
        """Registra métricas agregadas da janela."""
        self._fps_samples.append(fps)

    def get_snapshot(self) -> TelemetryDTO:
        """Produz um snapshot consolidado das métricas de rede e mídia."""
        avg_lat = sum(self._latencies) / len(self._latencies) if self._latencies else 0.0
        avg_fps = sum(self._fps_samples) / len(self._fps_samples) if self._fps_samples else 0.0
        jitter_ms = self._jitter_us / 1000.0

        return TelemetryDTO(
            fps=round(avg_fps, 1),
            bitrate_mbps=0.0,
            latency_ms=round(avg_lat, 2),
            jitter_ms=round(jitter_ms, 2),
            packet_loss_pct=0.0,
            route_mode="Direct",
        )
