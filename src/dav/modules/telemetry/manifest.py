# -*- coding: utf-8 -*-
"""
Manifesto do Modulo de Telemetria — DA-V v4.6
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.telemetry.diagnostic_packager import DiagnosticPackager
from src.dav.modules.telemetry.sde_exporter import SDETelemetryExporter
from src.dav.modules.telemetry.service import TelemetryService
from src.dav.modules.telemetry.stage_probe import StageProbeServer, probe_init, probe_send
from src.dav.modules.telemetry.tupa_checker import TupaHealthChecker, TupaMetricsSnapshot
from src.dav.modules.telemetry.tupa_probes import TupaNetworkProbe

MANIFEST = ModuleManifest(
    name="telemetry",
    version="4.6.0",
    description="Telemetria TUPA por nucleo, StageProbe de latencia, exportador SDE e empacotador de diagnostico",
    author="Dante Ferraz (MonoTech)",
    dependencies=[],
    enabled=True,
    service_factory=lambda: TelemetryService(),
    exports={
        "service": TelemetryService,
        "TupaHealthChecker": TupaHealthChecker,
        "TupaMetricsSnapshot": TupaMetricsSnapshot,
        "TupaNetworkProbe": TupaNetworkProbe,
        "SDETelemetryExporter": SDETelemetryExporter,
        "DiagnosticPackager": DiagnosticPackager,
        "StageProbeServer": StageProbeServer,
        "probe_init": probe_init,
        "probe_send": probe_send,
    },
)

manifest = MANIFEST
