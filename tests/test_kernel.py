# -*- coding: utf-8 -*-
"""
Testes Unitários do MonoTech Core Kernel — DA-V v4.0
Valida ServiceResult, ModuleRegistry, EventBus, L1BufferPool, CircuitBreaker e ConfigEngine.
"""

import time
import numpy as np
import pytest

from src.dav.kernel.result import ServiceResult, FrameDTO, RouteDTO, TelemetryDTO
from src.dav.kernel.registry import ModuleRegistry, ModuleManifest
from src.dav.kernel.event_bus import EventBus
from src.dav.kernel.buffer_pool import L1BufferPool
from src.dav.kernel.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState
from src.dav.kernel.config import ConfigEngine


def test_service_result_functional_flow():
    ok_res = ServiceResult.ok("frame_rendered", code="RENDER_OK")
    assert ok_res.is_success is True
    assert ok_res.is_error is False
    assert ok_res.unwrap() == "frame_rendered"
    assert ok_res.code == "RENDER_OK"

    fail_res = ServiceResult.fail("Connection lost", code="NET_DROPPED", details={"peer": "127.0.0.1"})
    assert fail_res.is_success is False
    assert fail_res.is_error is True
    assert fail_res.error == "Connection lost"
    assert fail_res.details["peer"] == "127.0.0.1"

    with pytest.raises(ValueError) as exc_info:
        fail_res.unwrap()
    assert "NET_DROPPED" in str(exc_info.value)


def test_module_registry_lifecycle():
    reg = ModuleRegistry()
    events = []

    m1 = ModuleManifest(
        name="capture",
        version="1.0.0",
        on_startup=lambda k: events.append("capture_started"),
        on_shutdown=lambda k: events.append("capture_stopped"),
    )
    m2 = ModuleManifest(
        name="stream",
        version="1.0.0",
        dependencies=["capture"],
        on_startup=lambda k: events.append("stream_started"),
        on_shutdown=lambda k: events.append("stream_stopped"),
    )

    reg.register(m2)
    reg.register(m1)

    assert reg.is_registered("capture")
    assert reg.is_registered("stream")

    reg.startup_all()
    # Ordem respeitando dependências: capture antes de stream
    assert events == ["capture_started", "stream_started"]

    reg.shutdown_all()
    # Ordem reversa: stream antes de capture
    assert events == ["capture_started", "stream_started", "stream_stopped", "capture_stopped"]


def test_event_bus_sync_and_async():
    bus = EventBus(max_workers=2)
    sync_msgs = []
    async_msgs = []

    bus.subscribe("telemetry.stats", lambda data: sync_msgs.append(data), is_async=False)
    bus.subscribe("telemetry.stats", lambda data: async_msgs.append(data), is_async=True)

    bus.publish("telemetry.stats", {"fps": 60.0})

    # Sync foi executado imediatamente
    assert len(sync_msgs) == 1
    assert sync_msgs[0]["fps"] == 60.0

    # Aguarda pool assíncrono
    time.sleep(0.08)
    assert len(async_msgs) == 1
    assert async_msgs[0]["fps"] == 60.0

    bus.shutdown(wait=True)


def test_l1_buffer_pool_slot_management():
    pool = L1BufferPool(num_slots=2, width=640, height=360, channels=4)
    slot0 = pool.acquire(timeout=0.05)
    slot1 = pool.acquire(timeout=0.05)
    assert slot0 is not None
    assert slot1 is not None

    # Pool esgotado
    slot2 = pool.acquire(timeout=0.01)
    assert slot2 is None

    # Devolve slot0 e adquire novamente
    buf = pool.get_slot(slot0)
    assert buf.shape == (360, 640, 4)
    buf[0, 0, 0] = 42

    pool.release(slot0)
    slot_reacquired = pool.acquire(timeout=0.05)
    assert slot_reacquired == slot0
    assert pool.get_slot(slot_reacquired)[0, 0, 0] == 42

    pool.close()


def test_circuit_breaker_state_machine():
    cb = CircuitBreaker("test-relay", failure_threshold=2, recovery_timeout=0.05)
    assert cb.state == CircuitState.CLOSED

    # Falha 1: ainda CLOSED
    cb.record_failure(ValueError("timeout"))
    assert cb.state == CircuitState.CLOSED

    # Falha 2: atinge limiar, transiciona para OPEN
    cb.record_failure(ValueError("refused"))
    assert cb.state == CircuitState.OPEN

    # Chamada protegida deve falhar imediatamente
    with pytest.raises(CircuitBreakerOpenError):
        cb.call(lambda: "never_called")

    # Aguarda tempo de recuperação -> HALF_OPEN
    time.sleep(0.06)
    assert cb.state == CircuitState.HALF_OPEN

    # Sucesso em HALF_OPEN restaura para CLOSED
    res = cb.call(lambda: "recovered")
    assert res == "recovered"
    assert cb.state == CircuitState.CLOSED


def test_config_engine_defaults():
    cfg = ConfigEngine()
    d = cfg.to_dict()
    assert "video" in d
    assert "network" in d
    assert "commercial" in d
    assert cfg.video.fps in (30, 60)
    assert cfg.commercial.edition == "Community"
