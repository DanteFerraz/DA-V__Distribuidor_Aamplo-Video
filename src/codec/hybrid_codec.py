# -*- coding: utf-8 -*-
"""
Shim de Compatibilidade — Redireciona para `src.dav.modules.codec`.
Autor: Dante Ferraz (MonoTech)
"""

from src.dav.modules.codec.base import MAGIC_H264, MAGIC_HEVC, MAGIC_RAW
from src.dav.modules.codec.decoder import HAS_AV, HAS_CV2, HybridDecoder, VideoDecoder
from src.dav.modules.codec.encoder import HybridEncoder, VideoEncoder

__all__ = [
    "MAGIC_H264",
    "MAGIC_HEVC",
    "MAGIC_RAW",
    "HAS_AV",
    "HAS_CV2",
    "HybridEncoder",
    "HybridDecoder",
    "VideoEncoder",
    "VideoDecoder",
]
