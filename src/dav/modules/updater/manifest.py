# -*- coding: utf-8 -*-
"""
Manifesto do Módulo de Atualizações — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.updater.service import UpdaterService

manifest = ModuleManifest(
    name="updater",
    version="4.0.0",
    dependencies=[],
    service_factory=lambda: UpdaterService(),
)
