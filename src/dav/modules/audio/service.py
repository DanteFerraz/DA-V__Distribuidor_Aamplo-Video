# -*- coding: utf-8 -*-
"""
Servico de Audio em Tempo Real (AudioService) — DA-V v4.5
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from typing import Optional

from src.dav.kernel.result import ServiceResult
from src.dav.modules.audio.capturer import BaseAudioCapturer, create_audio_capturer
from src.dav.modules.audio.codec_opus import OpusAudioDecoder, OpusAudioEncoder
from src.dav.modules.audio.jitter_asrc import AudioJitterAsrcBuffer


class AudioService:
    """Fachada para captura, compressao Opus low-delay e buffer ASRC."""

    def create_capturer(self, prefer_synthetic: bool = False) -> ServiceResult[BaseAudioCapturer]:
        try:
            cap = create_audio_capturer(prefer_synthetic=prefer_synthetic)
            return ServiceResult.ok(cap, code="AUDIO_CAPTURER_READY")
        except Exception as exc:
            return ServiceResult.fail(str(exc), code="AUDIO_CAPTURE_ERROR")

    def create_encoder(self, bitrate_bps: int = 96000, enable_lbrr: bool = True) -> ServiceResult[OpusAudioEncoder]:
        try:
            return ServiceResult.ok(
                OpusAudioEncoder(bitrate_bps=bitrate_bps, enable_lbrr_piggyback=enable_lbrr),
                code="AUDIO_ENCODER_READY",
            )
        except Exception as exc:
            return ServiceResult.fail(str(exc), code="AUDIO_ENCODE_ERROR")

    def create_decoder(self) -> ServiceResult[OpusAudioDecoder]:
        try:
            return ServiceResult.ok(OpusAudioDecoder(), code="AUDIO_DECODER_READY")
        except Exception as exc:
            return ServiceResult.fail(str(exc), code="AUDIO_DECODE_ERROR")

    def create_jitter_buffer(self) -> AudioJitterAsrcBuffer:
        return AudioJitterAsrcBuffer()
