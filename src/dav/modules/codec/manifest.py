# -*- coding: utf-8 -*-
"""
Manifesto do Modulo de Codec — DA-V v4.6
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.codec.decoder import VideoDecoder
from src.dav.modules.codec.encoder import VideoEncoder
from src.dav.modules.codec.service import CodecService

MANIFEST = ModuleManifest(
    name="codec",
    version="4.6.0",
    description="Codificacao NVENC GPU / libx264 Multi-Core AVX2 e decodificacao PyAV Slice Low-Delay",
    author="Dante Ferraz (MonoTech)",
    dependencies=[],
    enabled=True,
    service_factory=lambda: CodecService(),
    exports={
        "service": CodecService,
        "VideoEncoder": VideoEncoder,
        "VideoDecoder": VideoDecoder,
    },
)

manifest = MANIFEST
