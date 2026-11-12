# -*- coding: utf-8 -*-
"""
Manifesto do Módulo Comercial e Governança — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.commercial.service import CommercialService

manifest = ModuleManifest(
    name="commercial",
    version="4.0.0",
    dependencies=[],
    service_factory=lambda: CommercialService(),
)
