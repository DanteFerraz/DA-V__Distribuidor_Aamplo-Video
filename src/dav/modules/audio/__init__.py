# -*- coding: utf-8 -*-
"""
Fatia Vertical de Audio em Tempo Real (Ultra-Baixa Latencia) — DA-V v4.5
Autor: Dante Ferraz (MonoTech)
"""

from src.dav.modules.audio.capturer import (
    AUDIO_CHANNELS,
    AUDIO_FRAME_BYTES,
    AUDIO_FRAME_SAMPLES,
    AUDIO_SAMPLE_RATE,
    BaseAudioCapturer,
    SyntheticAudioCapturer,
    create_audio_capturer,
    resample_to_48k_stereo_s16,
)
from src.dav.modules.audio.codec_opus import (
    OpusAudioDecoder,
    OpusAudioEncoder,
)
from src.dav.modules.audio.jitter_asrc import AudioJitterAsrcBuffer
from src.dav.modules.audio.service import AudioService

__all__ = [
    "AUDIO_SAMPLE_RATE",
    "AUDIO_CHANNELS",
    "AUDIO_FRAME_SAMPLES",
    "AUDIO_FRAME_BYTES",
    "BaseAudioCapturer",
    "SyntheticAudioCapturer",
    "create_audio_capturer",
    "resample_to_48k_stereo_s16",
    "OpusAudioEncoder",
    "OpusAudioDecoder",
    "AudioJitterAsrcBuffer",
    "AudioService",
]
