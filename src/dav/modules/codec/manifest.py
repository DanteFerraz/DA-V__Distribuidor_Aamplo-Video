# -*- coding: utf-8 -*-
"""
Manifesto do Módulo de Codec — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.codec.service import CodecService

MANIFEST = ModuleManifest(
    name="codec",
    version="4.0.0",
    description="Codificação NVENC GPU / libx264 Multi-Core AVX2 e decodificação PyAV Slice Low-Delay",
    author="Dante Ferraz (MonoTech)",
    dependencies=[],
    enabled=True,
    exports={
        "service": CodecService,
    },
)
