# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Manifesto do Modulo de Audio — DA-V v4.6
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.audio.capturer import create_audio_capturer
from src.dav.modules.audio.codec_opus import OpusAudioDecoder, OpusAudioEncoder
from src.dav.modules.audio.jitter_asrc import AudioJitterAsrcBuffer
from src.dav.modules.audio.service import AudioService

MANIFEST = ModuleManifest(
    name="audio",
    version="4.6.0",
    description="Captura loopback WASAPI/PipeWire, Opus low-delay 10ms, LBRR e ASRC lip-sync",
    author="Dante Ferraz (MonoTech)",
    dependencies=["transport_p2p"],
    enabled=True,
    service_factory=lambda: AudioService(),
    exports={
        "service": AudioService,
        "create_audio_capturer": create_audio_capturer,
        "OpusAudioEncoder": OpusAudioEncoder,
        "OpusAudioDecoder": OpusAudioDecoder,
        "AudioJitterAsrcBuffer": AudioJitterAsrcBuffer,
    },
)

manifest = MANIFEST
