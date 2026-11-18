# -*- coding: utf-8 -*-
"""
Manifesto do Modulo de Atualizacoes — DA-V v4.6
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav import __version__ as _DAV_VERSION
from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.updater.service import UpdaterService

MANIFEST = ModuleManifest(
    name="updater",
    version=_DAV_VERSION,
    description="Verificacao assincrona de releases e instalacao com consentimento do usuario",
    author="Dante Ferraz (MonoTech)",
    dependencies=[],
    enabled=True,
    service_factory=lambda: UpdaterService(),
    exports={
        "service": UpdaterService,
    },
)

manifest = MANIFEST
