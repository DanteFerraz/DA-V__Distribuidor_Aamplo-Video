# -*- coding: utf-8 -*-
"""
Serviço de Codec — Fábrica e Fachada Unificada
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from typing import Optional
from src.dav.modules.codec.encoder import VideoEncoder
from src.dav.modules.codec.decoder import VideoDecoder
from src.dav.kernel.result import ServiceResult


class CodecService:
    """Fábrica de encoders e decoders de vídeo de alta fidelidade."""

    @staticmethod
    def create_encoder(
        codec_type: str = "h264_nvenc",
        width: int = 1920,
        height: int = 1080,
        fps: int = 60,
        bitrate_kbps: int = 12000,
    ) -> ServiceResult[VideoEncoder]:
        try:
            enc = VideoEncoder(
                codec_type=codec_type,
                width=width,
                height=height,
                fps=fps,
                bitrate_kbps=bitrate_kbps,
            )
            return ServiceResult.ok(enc, code="ENCODER_READY")
        except Exception as exc:
            return ServiceResult.fail(str(exc), code="ENCODER_INIT_ERROR")

    @staticmethod
    def create_decoder() -> ServiceResult[VideoDecoder]:
        try:
            dec = VideoDecoder()
            return ServiceResult.ok(dec, code="DECODER_READY")
        except Exception as exc:
            return ServiceResult.fail(str(exc), code="DECODER_INIT_ERROR")

