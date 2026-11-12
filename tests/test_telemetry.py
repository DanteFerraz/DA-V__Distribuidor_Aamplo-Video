# -*- coding: utf-8 -*-
"""
Testes Unitários do Módulo de Telemetria — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

import time
import pytest

from src.dav.kernel.circuit_breaker import CircuitBreaker
from src.dav.kernel.event_bus import EventBus
from src.dav.modules.telemetry.tupa_probes import TupaNetworkProbe
from src.dav.modules.telemetry.sde_exporter import SDETelemetryExporter
from src.dav.modules.telemetry.service import TelemetryService


def test_tupa_network_probe_jitter_calculation():
    probe = TupaNetworkProbe(sample_window=10)

    # Simula 5 pacotes com chegadas variáveis
    t0_us = int(time.time_ns() // 1000) - 20000
    probe.record_packet_arrival(t0_us)

    t1_us = int(time.time_ns() // 1000) - 25000
    probe.record_packet_arrival(t1_us)

    probe.record_stats(fps=59.8, bitrate_mbps=8.5)
    snapshot = probe.get_snapshot()

    assert snapshot.fps == 59.8
    assert snapshot.jitter_ms >= 0.0


def test_sde_exporter_circuit_breaker_resilience():
    # Aponta para endpoint inexistente com breaker de teste rápido
    breaker = CircuitBreaker("TestSDE", failure_threshold=2, recovery_timeout=0.05)
    exporter = SDETelemetryExporter(endpoint_url="http://127.0.0.1:59999/unreachable", circuit_breaker=breaker)

    # 1ª tentativa falha
    res1 = exporter.export_metric({"ping": 1})
    assert res1.is_error

    # 2ª tentativa falha -> atinge o limite
    res2 = exporter.export_metric({"ping": 2})
    assert res2.is_error

    # 3ª tentativa é bloqueada imediatamente pelo CircuitBreaker sem fazer requisição HTTP
    res3 = exporter.export_metric({"ping": 3})
    assert res3.is_error
    assert res3.code == "CIRCUIT_OPEN"


def test_telemetry_service_bus_event_integration():
    bus = EventBus.get_instance()
    service = TelemetryService(event_bus=bus)

    # Publica evento de estatísticas
    bus.publish("stream.stats", {
        "fps": 60.0,
        "bitrate_mbps": 12.5,
        "latency_ms": 3.4,
        "packets_count": 500,
        "frames_count": 60,
    })

    snap = service.get_telemetry_snapshot()
    assert snap.fps == 60.0
    assert snap.bitrate_mbps == 12.5
    assert snap.latency_ms == 3.4
