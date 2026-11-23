# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
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
