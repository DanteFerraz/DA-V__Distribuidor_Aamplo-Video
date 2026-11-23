# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Codificador de Vídeo Unificado — NVENC GPU + libx264 Multi-Core AVX2 Sliced-Threads
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
import os
import time
from fractions import Fraction
from typing import Optional
import numpy as np

from src.dav.modules.codec.base import BaseEncoder, MAGIC_H264, MAGIC_HEVC, MAGIC_RAW

logger = logging.getLogger("DAV.Codec.Encoder")

HAS_AV = False
try:
    import av
    HAS_AV = True
except ImportError:
    pass

HAS_CV2 = False
try:
    import cv2
    HAS_CV2 = True
    cv2.setNumThreads(1)
except ImportError:
    pass


class VideoEncoder(BaseEncoder):
    """
    Codificador H.264/HEVC ultra-low latency com fallback transparente para CPU.
    Garante repetição de cabeçalhos SPS/PPS e escala em passe único C/AVX2.
    """

    def __init__(
        self,
        codec_type: str = "h264_nvenc",
        width: int = 1920,
        height: int = 1080,
        fps: int = 60,
        bitrate_kbps: int = 12000,
    ):
        self.requested_codec = codec_type.lower()
        self.codec_type = self.requested_codec
        self.active_backend_name = self.codec_type.upper()
        self.width = width
        self.height = height
        self.fps = max(1, fps)
        self.bitrate_kbps = bitrate_kbps

        self._av_codec = None
        self._wire_magic = MAGIC_H264
        self._current_quality = 75
        self._target_frame_bytes = int((bitrate_kbps * 1024 / 8) / self.fps)
        self._pir_active = False
        self._applied_bitrate_kbps = int(bitrate_kbps)
        self._last_bitrate_update_mono = time.monotonic()
        self._last_libx264_reopen_mono = 0.0
        self._frame_seq = 0
        self._force_next_idr = True
        self._last_idr_mono = 0.0
        self._vbv_clamp_active = False
        self.last_frame_was_keyframe = False

        self._init_encoder()

    def _init_encoder(self) -> None:
        if self.codec_type in ("raw", "jpeg"):
            self.active_backend_name = self.codec_type.upper()
            return

        if not HAS_AV:
            self.codec_type = "jpeg" if HAS_CV2 else "raw"
            self.active_backend_name = self.codec_type.upper()
            return

        maxrate_kbps = max(800, int(self.bitrate_kbps * 1.15))
        bufsize_kbps = max(1500, int(self.bitrate_kbps // 3))

        # 1. Tentativa primária: NVENC GPU (perfil p1 ULL fiel ao baseline de 1 ms)
        if self.codec_type in ("h264_nvenc", "hevc_nvenc"):
            try:
                ctx = av.CodecContext.create(self.codec_type, "w")
                ctx.width = self.width
                ctx.height = self.height
                ctx.pix_fmt = "yuv420p"
                ctx.time_base = Fraction(1, self.fps)
                ctx.bit_rate = self.bitrate_kbps * 1000
                ctx.max_b_frames = 0
                nv_opts = {
                    "preset": "p1",
                    "tune": "ull",
                    "zerolatency": "1",
                    "rc-lookahead": "0",
                    "surfaces": "2",
                    "delay": "0",
                    "rc": "cbr",
                    "b": f"{self.bitrate_kbps}k",
                    "g": str(self.fps * 3),
                    "forced-idr": "1",
                    "repeat-headers": "1",
                    "bf": "0",
                    "b_ref_mode": "disabled",
                }
                if self._vbv_clamp_active:
                    nv_opts["maxrate"] = f"{maxrate_kbps}k"
                    nv_opts["bufsize"] = f"{bufsize_kbps}k"
                ctx.options = nv_opts
                ctx.open()
                self._av_codec = ctx
                self._wire_magic = MAGIC_HEVC if self.codec_type == "hevc_nvenc" else MAGIC_H264
                self.active_backend_name = self.codec_type.upper()
                logger.info(f"[Codec] NVENC GPU ativo: {self.width}x{self.height} @ {self.fps} FPS ({self.bitrate_kbps}k).")
                return
            except Exception as exc:
                logger.warning(f"[Codec] {self.codec_type} indisponível ({exc}). Alternando para libx264...")

        # 2. Fallback universal: libx264 multi-core SIMD sem estrangulamento VBV por padrao
        cpu_threads = min(8, max(4, os.cpu_count() or 4))
        for sw_name in ("libx264", "h264"):
            try:
                ctx = av.CodecContext.create(sw_name, "w")
                ctx.width = self.width
                ctx.height = self.height
                ctx.pix_fmt = "yuv420p"
                ctx.time_base = Fraction(1, self.fps)
                ctx.bit_rate = self.bitrate_kbps * 1000
                ctx.max_b_frames = 0
                ctx.thread_count = cpu_threads
                x264_params = (
                    f"repeat-headers=1:keyint={self.fps * 2}:min-keyint=1:"
                    f"sliced-threads=1:threads={cpu_threads}:sync-lookahead=0:rc-lookahead=0"
                )
                sw_opts = {
                    "preset": "ultrafast",
                    "tune": "zerolatency",
                    "b": f"{self.bitrate_kbps}k",
                }
                if self._vbv_clamp_active:
                    sw_opts["maxrate"] = f"{maxrate_kbps}k"
                    sw_opts["bufsize"] = f"{bufsize_kbps}k"
                    x264_params += f":vbv-maxrate={maxrate_kbps}:vbv-bufsize={bufsize_kbps}"
                sw_opts["x264-params"] = x264_params
                ctx.options = sw_opts
                ctx.open()
                self._av_codec = ctx
                self.codec_type = "libx264"
                self._wire_magic = MAGIC_H264
                self.active_backend_name = "LIBX264_ULL"
                logger.info(f"[Codec] libx264 ativo: {self.width}x{self.height} @ {self.fps} FPS ({cpu_threads} threads).")
                return
            except Exception:
                continue

        # 3. Fallback final RAW
        self.codec_type = "raw"
        self.active_backend_name = "RAW"
        self._av_codec = None

    def request_keyframe(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or self._frame_seq == 0 or (now - self._last_idr_mono) >= 0.08:
            self._force_next_idr = True

    def update_rate_budget(self, bitrate_kbps: int, pir_mode: bool = False) -> None:
        """Acoplamento opcional de orcamento de taxa com histerese (>= 12% e >= 400 ms)."""
        clamped = max(400, min(50000, int(bitrate_kbps)))
        self._target_frame_bytes = int((clamped * 1024 / 8) / self.fps)
        self.bitrate_kbps = clamped
        self._pir_active = bool(pir_mode)
        if self._av_codec is None:
            return
        now = time.monotonic()
        delta = abs(clamped - self._applied_bitrate_kbps)
        threshold = max(400, int(self._applied_bitrate_kbps * 0.12))
        if delta >= threshold and (now - self._last_bitrate_update_mono) >= 0.40:
            try:
                self._vbv_clamp_active = True
                if (
                    self.codec_type == "libx264"
                    and delta >= max(800, int(self._applied_bitrate_kbps * 0.20))
                    and (now - self._last_libx264_reopen_mono) >= 1.20
                ):
                    self.close()
                    self._init_encoder()
                    self._last_libx264_reopen_mono = now
                if self._av_codec is not None:
                    self._av_codec.bit_rate = clamped * 1000
                self._applied_bitrate_kbps = clamped
                self._last_bitrate_update_mono = now
            except Exception:
                pass

    def encode(self, frame_bgra: np.ndarray) -> bytes:
        self._frame_seq += 1
        self.last_frame_was_keyframe = False

        if self._av_codec is not None:
            try:
                src_h, src_w = frame_bgra.shape[0], frame_bgra.shape[1]
                channels = frame_bgra.shape[2] if len(frame_bgra.shape) == 3 else 1
                needs_scale = (src_w != self.width) or (src_h != self.height)

                # Escala + conversão em passe único via C/AVX2
                if not needs_scale and HAS_CV2 and channels == 4:
                    yuv = cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2YUV_I420)
                    av_frame = av.VideoFrame.from_ndarray(yuv, format="yuv420p")
                elif not needs_scale and HAS_CV2 and channels == 3:
                    yuv = cv2.cvtColor(frame_bgra, cv2.COLOR_BGR2YUV_I420)
                    av_frame = av.VideoFrame.from_ndarray(yuv, format="yuv420p")
                elif channels == 4:
                    av_frame = av.VideoFrame.from_ndarray(frame_bgra, format="bgra").reformat(
                        width=self.width, height=self.height, format="yuv420p", interpolation=1
                    )
                else:
                    av_frame = av.VideoFrame.from_ndarray(frame_bgra, format="bgr24").reformat(
                        width=self.width, height=self.height, format="yuv420p", interpolation=1
                    )

                av_frame.pts = self._frame_seq
                if self._force_next_idr or self._frame_seq == 1:
                    av_frame.pict_type = 1  # AV_PICTURE_TYPE_I
                    self._force_next_idr = False
                    self._last_idr_mono = time.monotonic()
                    self.last_frame_was_keyframe = True

                packets = self._av_codec.encode(av_frame)
                if packets:
                    if any(getattr(p, "is_keyframe", False) for p in packets):
                        self.last_frame_was_keyframe = True
                        self._last_idr_mono = time.monotonic()
                    raw_nal = b"".join(bytes(p) for p in packets)
                    return self._wire_magic + raw_nal
            except Exception as exc:
                logger.error(f"[Codec] Erro ao codificar quadro: {exc}")

        if self.codec_type == "raw":
            self.last_frame_was_keyframe = True
            return MAGIC_RAW + frame_bgra.tobytes()

        if HAS_CV2:
            ok, enc = cv2.imencode(
                ".jpg",
                frame_bgra,
                [cv2.IMWRITE_JPEG_QUALITY, self._current_quality, cv2.IMWRITE_JPEG_OPTIMIZE, 0],
            )
            if ok:
                self.last_frame_was_keyframe = True
                payload = enc.tobytes()
                flen = len(payload)
                if flen > self._target_frame_bytes * 1.3 and self._current_quality > 45:
                    self._current_quality -= 1
                elif flen < self._target_frame_bytes * 0.8 and self._current_quality < 85:
                    self._current_quality += 1
                return payload

        return b""

    def close(self) -> None:
        if self._av_codec is not None:
            try:
                self._av_codec.encode(None)
            except Exception:
                pass
            self._av_codec = None


HybridEncoder = VideoEncoder

