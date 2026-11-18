# -*- coding: utf-8 -*-
"""
Manifesto do Modulo de Captura — DA-V v4.6
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.capture.service import CaptureService, enumerate_system_monitors

MANIFEST = ModuleManifest(
    name="capture",
    version="4.6.0",
    description="Captura de tela Direct3D 11 / WGC no Windows, Wayland PipeWire e X11 no Linux",
    author="Dante Ferraz (MonoTech)",
    dependencies=[],
    enabled=True,
    service_factory=lambda: CaptureService(),
    exports={
        "service": CaptureService,
        "enumerate_monitors": enumerate_system_monitors,
    },
)

manifest = MANIFEST
