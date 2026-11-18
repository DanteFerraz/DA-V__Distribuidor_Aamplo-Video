#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitoramento TUPA de Saude de Hardware e Processos — DA-V v4.6
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

HAS_TUPA = False
try:
    from tupã.collectors.network.network_collector import NetworkCollector
    from tupã.collectors.process.process_collector import ProcessCollector
    from tupã.collectors.system.cpu_collector import CPUCollector
    from tupã.collectors.system.memory_collector import MemoryCollector
    HAS_TUPA = True
except Exception:
    HAS_TUPA = False


@dataclass
class TupaMetricsSnapshot:
    cpu_global_percent: float
    cpu_cores_percent: List[float]
    ram_used_gb: float
    ram_total_gb: float
    ram_percent: float
    dav_gui_cpu_percent: float
    dav_gui_mem_mb: float
    dav_sender_cpu_percent: float
    dav_sender_mem_mb: float
    network_bytes_sent_sec: float
    network_bytes_recv_sec: float
    health_status: str
    health_alert: str
    timestamp: float


class TupaHealthChecker:
    """Coletor periodico de saude de CPU por nucleo, RAM, processos DA-V e I/O de rede."""

    def __init__(self, sample_interval_sec: float = 1.0):
        self._interval = sample_interval_sec
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callback = None
        self._latest_snapshot: Optional[TupaMetricsSnapshot] = None

        self._cpu_collector = None
        self._mem_collector = None
        self._proc_collector = None
        self._net_collector = None

        self._last_net_sent = 0
        self._last_net_recv = 0
        self._last_net_time = 0.0

        if HAS_TUPA:
            try:
                self._cpu_collector = CPUCollector("tupa_cpu", {})
                self._cpu_collector.initialize()
            except Exception:
                pass
            try:
                self._mem_collector = MemoryCollector("tupa_mem", {})
                self._mem_collector.initialize()
            except Exception:
                pass
            try:
                self._net_collector = NetworkCollector("tupa_net", {})
                self._net_collector.initialize()
            except Exception:
                pass

    def start(self, on_snapshot_callback=None):
        self._callback = on_snapshot_callback
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="TUPA-HealthChecker")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)

    def get_latest_snapshot(self) -> Optional[TupaMetricsSnapshot]:
        return self._latest_snapshot

    def _run_loop(self):
        import psutil
        while self._running:
            try:
                snapshot = self._collect_snapshot(psutil)
                self._latest_snapshot = snapshot
                if self._callback and snapshot:
                    self._callback(snapshot)
            except Exception:
                pass
            time.sleep(self._interval)

    def _collect_snapshot(self, psutil_mod) -> TupaMetricsSnapshot:
        try:
            cpu_global = float(psutil_mod.cpu_percent(interval=None))
            cpu_cores = [float(c) for c in psutil_mod.cpu_percent(interval=None, percpu=True)]
        except Exception:
            cpu_global = 0.0
            cpu_cores = [0.0] * 12

        ram_used_gb = 0.0
        ram_total_gb = 16.0
        ram_pct = 0.0
        try:
            mem = psutil_mod.virtual_memory()
            ram_used_gb = mem.used / (1024 ** 3)
            ram_total_gb = mem.total / (1024 ** 3)
            ram_pct = mem.percent
        except Exception:
            pass

        dav_gui_cpu = 0.0
        dav_gui_mem = 0.0
        dav_snd_cpu = 0.0
        dav_snd_mem = 0.0
        cur_pid = os.getpid()

        try:
            cur_proc = psutil_mod.Process(cur_pid)
            dav_gui_cpu = cur_proc.cpu_percent(interval=None)
            dav_gui_mem = cur_proc.memory_info().rss / (1024 * 1024)

            children = cur_proc.children(recursive=True)
            for child in children:
                try:
                    dav_snd_cpu += child.cpu_percent(interval=None)
                    dav_snd_mem += child.memory_info().rss / (1024 * 1024)
                except Exception:
                    pass
        except Exception:
            pass

        now = time.perf_counter()
        net_sent_sec = 0.0
        net_recv_sec = 0.0
        try:
            net_io = psutil_mod.net_io_counters()
            if self._last_net_time > 0:
                dt = now - self._last_net_time
                if dt > 0.001:
                    net_sent_sec = max(0.0, (net_io.bytes_sent - self._last_net_sent) / dt)
                    net_recv_sec = max(0.0, (net_io.bytes_recv - self._last_net_recv) / dt)
            self._last_net_sent = net_io.bytes_sent
            self._last_net_recv = net_io.bytes_recv
            self._last_net_time = now
        except Exception:
            pass

        health = "OTIMO"
        alert = "Sistema operando em condicoes ideais."
        if cpu_global > 85.0:
            health = "CRITICO"
            alert = "Uso global de CPU acima de 85%. Possivel contencao em threads de encode/decode."
        elif cpu_global > 65.0:
            health = "MODERADO"
            alert = "Carga de CPU moderada. Monitorando estabilidade da taxa de quadros."
        elif ram_pct > 85.0:
            health = "ALERTA"
            alert = "Consumo de memoria RAM do sistema elevado (> 85%)."

        return TupaMetricsSnapshot(
            cpu_global_percent=cpu_global,
            cpu_cores_percent=cpu_cores,
            ram_used_gb=ram_used_gb,
            ram_total_gb=ram_total_gb,
            ram_percent=ram_pct,
            dav_gui_cpu_percent=dav_gui_cpu,
            dav_gui_mem_mb=dav_gui_mem,
            dav_sender_cpu_percent=dav_snd_cpu,
            dav_sender_mem_mb=dav_snd_mem,
            network_bytes_sent_sec=net_sent_sec,
            network_bytes_recv_sec=net_recv_sec,
            health_status=health,
            health_alert=alert,
            timestamp=now,
        )
