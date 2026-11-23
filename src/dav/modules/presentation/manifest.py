# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Manifesto do Modulo de Apresentacao — DA-V v4.6
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.presentation.service import PresentationService

MANIFEST = ModuleManifest(
    name="presentation",
    version="4.6.0",
    description="Apresentacao institucional MonoTech e vitrine de tecnologias autorais",
    author="Dante Ferraz (MonoTech)",
    dependencies=["commercial", "telemetry"],
    enabled=True,
    service_factory=lambda: PresentationService(),
    exports={
        "service": PresentationService,
    },
)

manifest = MANIFEST
