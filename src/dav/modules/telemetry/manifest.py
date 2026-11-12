# -*- coding: utf-8 -*-
"""
Manifesto do Módulo de Telemetria — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.telemetry.service import TelemetryService

manifest = ModuleManifest(
    name="telemetry",
    version="4.0.0",
    dependencies=[],
    service_factory=lambda: TelemetryService(),
)
