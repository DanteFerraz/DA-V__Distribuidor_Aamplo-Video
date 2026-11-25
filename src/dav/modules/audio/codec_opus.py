# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Codificador / Decodificador de Audio Opus Low-Delay + Piggyback LBRR — DA-V v4.5
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
import struct
from typing import List, Optional, Tuple
import numpy as np

from src.dav.modules.audio.capturer import (
    AUDIO_CHANNELS,
    AUDIO_FRAME_SAMPLES,
    AUDIO_SAMPLE_RATE,
)

logger = logging.getLogger("DAV.Audio.Codec")

AUDIO_CODEC_OPUS = 1
AUDIO_CODEC_PCM16 = 2

AUDIO_FLAG_SILENCE = 0x80
AUDIO_FLAG_LBRR_PIGGY = 0x40

# 2 bytes meta: codec_and_flags (B), rate_and_ch (B)
AUDIO_META_FORMAT = "!BB"
AUDIO_META_SIZE = 2


class OpusAudioEncoder:
    """
    Codificador Opus 48 kHz Estereo em blocos de 10 ms (lowdelay) com fallback PCM16.
    Suporta piggyback do quadro comprimido anterior para recuperacao de perda em 0-RTT.
    """

    def __init__(self, bitrate_bps: int = 96000, enable_lbrr_piggyback: bool = True):
        self.bitrate_bps = max(24000, min(256000, int(bitrate_bps)))
        self.enable_lbrr_piggyback = bool(enable_lbrr_piggyback)
        self._codec_ctx = None
        self._codec_id = AUDIO_CODEC_PCM16
        self._pts = 0
        self._prev_encoded_chunk: Optional[bytes] = None
        self._init_codec()

    def _init_codec(self) -> None:
        try:
            import av

            ctx = av.CodecContext.create("libopus", "w")
            ctx.sample_rate = AUDIO_SAMPLE_RATE
            ctx.layout = "stereo"
            ctx.format = "s16"
            ctx.bit_rate = self.bitrate_bps
            for opts in (
                {"application": "lowdelay", "frame_duration": "10", "fec": "1", "packet_loss": "5"},
                {"application": "lowdelay", "frame_duration": "10"},
            ):
                try:
                    ctx.options = opts
                    ctx.open()
                    self._codec_ctx = ctx
                    self._codec_id = AUDIO_CODEC_OPUS
                    logger.info(f"[Audio] Encoder libopus lowdelay ativo ({self.bitrate_bps // 1000} kbps).")
                    return
                except Exception:
                    continue
        except Exception as exc:
            logger.debug(f"[Audio] libopus indisponivel ({exc}); usando PCM16.")
        self._codec_id = AUDIO_CODEC_PCM16

    def encode(self, pcm_s16: np.ndarray, lbrr_active: Optional[bool] = None) -> bytes:
        """
        Recebe array int16 shape (480, 2) e retorna payload binario pronto para PT_AUDIO.
        """
        import av

        arr = np.asarray(pcm_s16, dtype=np.int16)
        if arr.ndim == 1:
            arr = arr.reshape(-1, AUDIO_CHANNELS)
        if arr.shape[0] < AUDIO_FRAME_SAMPLES:
            pad = np.zeros((AUDIO_FRAME_SAMPLES - arr.shape[0], AUDIO_CHANNELS), dtype=np.int16)
            arr = np.vstack((arr, pad))
        elif arr.shape[0] > AUDIO_FRAME_SAMPLES:
            arr = arr[:AUDIO_FRAME_SAMPLES]

        is_silence = bool(np.max(np.abs(arr)) <= 2)
        cur_bytes = b""

        if is_silence:
            cur_bytes = b"\x00"
        elif self._codec_ctx is not None:
            try:
                packed = np.ascontiguousarray(arr).reshape(1, -1)
                af = av.AudioFrame.from_ndarray(packed, format="s16", layout="stereo")
                af.sample_rate = AUDIO_SAMPLE_RATE
                af.pts = self._pts
                self._pts += AUDIO_FRAME_SAMPLES
                pkts = self._codec_ctx.encode(af)
                if pkts:
                    cur_bytes = bytes(pkts[0])
            except Exception:
                cur_bytes = arr.tobytes()
                self._codec_id = AUDIO_CODEC_PCM16
        else:
            cur_bytes = arr.tobytes()

        use_lbrr = self.enable_lbrr_piggyback if lbrr_active is None else bool(lbrr_active)
        flags_byte = (AUDIO_FLAG_SILENCE if is_silence else 0) | (
            AUDIO_FLAG_LBRR_PIGGY if (use_lbrr and self._prev_encoded_chunk and not is_silence) else 0
        )
        codec_meta = (self._codec_id & 0x0F) | flags_byte
        rate_meta = 0x24  # 48 kHz (code 4), 2ch (code 2)
        hdr = struct.pack(AUDIO_META_FORMAT, codec_meta, rate_meta)

        if flags_byte & AUDIO_FLAG_LBRR_PIGGY:
            prev_b = self._prev_encoded_chunk or b""
            out = hdr + struct.pack("!H", len(prev_b)) + prev_b + cur_bytes
        else:
            out = hdr + cur_bytes

        self._prev_encoded_chunk = None if is_silence else cur_bytes
        return out

    def close(self) -> None:
        if self._codec_ctx is not None:
            try:
                self._codec_ctx.encode(None)
            except Exception:
                pass
            self._codec_ctx = None


class OpusAudioDecoder:
    """Decodificador Opus / PCM16 com suporte a recuperacao LBRR piggyback e PLC."""

    def __init__(self):
        self._codec_ctx = None
        self._opus_unavailable = False
        self._last_good_frame = np.zeros((AUDIO_FRAME_SAMPLES, AUDIO_CHANNELS), dtype=np.int16)
        self._init_codec()

    def _init_codec(self) -> None:
        if self._opus_unavailable:
            return
        try:
            import av

            dec = av.CodecContext.create("libopus", "r")
            dec.sample_rate = AUDIO_SAMPLE_RATE
            dec.layout = "stereo"
            dec.open()
            self._codec_ctx = dec
        except Exception:
            self._codec_ctx = None
            self._opus_unavailable = True

    def ensure_open(self) -> None:
        """Garante que o contexto libopus esteja aberto apos um ciclo stop() -> start()."""
        if self._codec_ctx is None and not self._opus_unavailable:
            self._init_codec()

    def _decode_chunk(self, codec_id: int, chunk: bytes, is_silence: bool) -> np.ndarray:
        if is_silence or not chunk:
            return np.zeros((AUDIO_FRAME_SAMPLES, AUDIO_CHANNELS), dtype=np.int16)

        if codec_id == AUDIO_CODEC_PCM16:
            arr = np.frombuffer(chunk, dtype=np.int16)
            usable = (len(arr) // AUDIO_CHANNELS) * AUDIO_CHANNELS
            out = arr[:usable].reshape(-1, AUDIO_CHANNELS).copy()
            self._last_good_frame = out
            return out

        if codec_id == AUDIO_CODEC_OPUS:
            if self._codec_ctx is None:
                self.ensure_open()
        if codec_id == AUDIO_CODEC_OPUS and self._codec_ctx is not None:
            try:
                import av

                frames = self._codec_ctx.decode(av.Packet(chunk))
                if frames:
                    parts = []
                    for f in frames:
                        nd = f.to_ndarray()
                        # fltp (channels, samples) ou s16 (1, samples*2)
                        if nd.dtype in (np.float32, np.float64):
                            if nd.ndim == 2 and nd.shape[0] == AUDIO_CHANNELS:
                                nd = nd.T
                            nd_i16 = np.clip(nd * 32767.0, -32768.0, 32767.0).astype(np.int16)
                        else:
                            nd_i16 = nd.reshape(-1, AUDIO_CHANNELS).astype(np.int16, copy=False)
                        parts.append(nd_i16)
                    out = np.vstack(parts) if len(parts) > 1 else parts[0]
                    self._last_good_frame = out
                    return out
            except Exception:
                pass
        return self.conceal_loss()

    def decode_payload(self, payload: bytes, need_prev_recovery: bool = False) -> Tuple[Optional[np.ndarray], np.ndarray]:
        """
        Decodifica o payload `PT_AUDIO`. Se `need_prev_recovery=True` e o pacote contiver
        piggyback LBRR do quadro anterior, retorna `(recovered_prev_pcm, current_pcm)`.
        """
        if len(payload) < AUDIO_META_SIZE:
            return None, self.conceal_loss()

        codec_meta, _ = struct.unpack(AUDIO_META_FORMAT, payload[:AUDIO_META_SIZE])
        codec_id = codec_meta & 0x0F
        is_silence = bool(codec_meta & AUDIO_FLAG_SILENCE)
        has_lbrr = bool(codec_meta & AUDIO_FLAG_LBRR_PIGGY)
        body = payload[AUDIO_META_SIZE:]

        recovered_prev: Optional[np.ndarray] = None
        if has_lbrr and len(body) >= 2:
            prev_len = struct.unpack("!H", body[:2])[0]
            if 2 + prev_len <= len(body):
                prev_chunk = body[2 : 2 + prev_len]
                cur_chunk = body[2 + prev_len :]
                if need_prev_recovery and prev_chunk:
                    recovered_prev = self._decode_chunk(codec_id, prev_chunk, False)
                cur_pcm = self._decode_chunk(codec_id, cur_chunk, is_silence)
                return recovered_prev, cur_pcm

        cur_pcm = self._decode_chunk(codec_id, body, is_silence)
        return None, cur_pcm

    def conceal_loss(self) -> np.ndarray:
        """Atenua suavemente o ultimo quadro valido (PLC fallback) para evitar cliques."""
        faded = (self._last_good_frame.astype(np.float32) * 0.65).astype(np.int16)
        self._last_good_frame = faded
        return faded

    def close(self) -> None:
        self._codec_ctx = None
