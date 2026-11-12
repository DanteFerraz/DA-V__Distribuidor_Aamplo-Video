# -*- coding: utf-8 -*-
"""
Manifesto do Módulo StreamEngine — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.stream_engine.service import StreamEngineService

manifest = ModuleManifest(
    name="stream_engine",
    version="4.0.0",
    dependencies=["capture", "codec", "transport_p2p"],
    service_factory=lambda: StreamEngineService(),
)

