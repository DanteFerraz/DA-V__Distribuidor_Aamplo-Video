# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Manifesto do Modulo Comercial e Governanca — DA-V v4.6
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.commercial.service import CommercialService

MANIFEST = ModuleManifest(
    name="commercial",
    version="4.6.0",
    description="Governanca MonoTech Community Edition 100% Free & Open Tech",
    author="Dante Ferraz (MonoTech)",
    dependencies=[],
    enabled=True,
    service_factory=lambda: CommercialService(),
    exports={
        "service": CommercialService,
    },
)

manifest = MANIFEST
