# -*- coding: utf-8 -*-
"""
Manifesto do Módulo de Apresentação — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.presentation.service import PresentationService

manifest = ModuleManifest(
    name="presentation",
    version="4.0.0",
    dependencies=["commercial", "telemetry"],
    service_factory=lambda: PresentationService(),
)

