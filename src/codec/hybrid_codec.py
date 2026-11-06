#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Motor Híbrido de Codificação e Decodificação de Vídeo — DA-V v2.0
Autor: Dante Ferraz (MonoTech)

Orquestra a compressão e descompressão em tempo real com foco estrito em latência
sub-frame (< 5 ms no encode). Prioriza aceleradores dedicados em silício (NVIDIA NVENC)
e degrada de forma transparente para libx264 (ultrafast / zerolatency) via PyAV quando
executado em máquinas Linux ou Windows sem GPU dedicada, eliminando dependência rígida
de OpenCV ou drivers proprietários.
"""

import os
from fractions import Fraction
from typing import Optional
import numpy as np

HAS_AV = False
try:
    import av
    HAS_AV = True
except ImportError:
    HAS_AV = False

HAS_CV2 = False
try:
    import cv2
    HAS_CV2 = True
    cv2.setNumThreads(1)
except ImportError:
    HAS_CV2 = False

# Identificadores de payload na rede (9 bytes prefixados ao fluxo comprimido)
MAGIC_H264 = b"DAV_H264:"
MAGIC_HEVC = b"DAV_HEVC:"
MAGIC_RAW = b"DAV_RAW_:"


class HybridEncoder:
    """
    Codificador unificado de baixa latência com cascata automática de fallback:
    1. Hardware GPU (h264_nvenc / hevc_nvenc) com repetição de cabeçalhos SPS/PPS.
    2. Software CPU SIMD (libx264 ultrafast + zerolatency) multiplataforma via FFmpeg/PyAV.
    3. JPEG adaptativo (OpenCV/libjpeg-turbo) ou quadro cru (RAW BGRA).
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
        self._frame_seq = 0
        self._force_next_idr = True
        self.last_frame_was_keyframe = False

        self._init_encoder()

    def _init_encoder(self):
        if self.codec_type in ("raw", "jpeg"):
            self.active_backend_name = self.codec_type.upper()
            return

        if not HAS_AV:
            self.codec_type = "jpeg" if HAS_CV2 else "raw"
            self.active_backend_name = self.codec_type.upper()
            return

        # 1. Tentativa primária: Aceleração dedicada NVIDIA NVENC
        if self.codec_type in ("h264_nvenc", "hevc_nvenc"):
            try:
                ctx = av.CodecContext.create(self.codec_type, "w")
                ctx.width = self.width
                ctx.height = self.height
                ctx.pix_fmt = "yuv420p"
                ctx.time_base = Fraction(1, self.fps)
                ctx.max_b_frames = 0
                ctx.options = {
                    "preset": "p1",
                    "tune": "ull",
                    "zerolatency": "1",
                    "rc-lookahead": "0",
                    "surfaces": "2",
                    "delay": "0",
                    "rc": "cbr",
                    "b": f"{self.bitrate_kbps}k",
                    "g": str(self.fps * 3),       # IDR periódico a cada 3s para resiliência WAN
                    "forced-idr": "1",            # Permite disparo sob demanda via PLI / Handshake P2P
                    "repeat-headers": "1",        # Emite SPS/PPS em todo IDR para sincronia imediata
                    "bf": "0",
                    "b_ref_mode": "disabled",
                }
                ctx.open()
                self._av_codec = ctx
                self._wire_magic = MAGIC_HEVC if self.codec_type == "hevc_nvenc" else MAGIC_H264
                self.active_backend_name = self.codec_type.upper()
                print(f"[Codec] Encoder de hardware {self.active_backend_name} ativo ({self.width}x{self.height} @ {self.fps} FPS).")
                return
            except Exception as nv_err:
                print(f"[Codec] {self.codec_type} indisponível neste host ({nv_err}). Alternando para libx264 ultrafast...")

        # 2. Fallback universal H.264 por CPU SIMD (essencial para Linux sem GPU NVIDIA)
        cpu_threads = min(8, max(4, os.cpu_count() or 4))
        for sw_name in ("libx264", "h264"):
            try:
                ctx = av.CodecContext.create(sw_name, "w")
                ctx.width = self.width
                ctx.height = self.height
                ctx.pix_fmt = "yuv420p"
                ctx.time_base = Fraction(1, self.fps)
                ctx.max_b_frames = 0
                ctx.thread_count = cpu_threads
                ctx.options = {
                    "preset": "ultrafast",
                    "tune": "zerolatency",
                    "b": f"{self.bitrate_kbps}k",
                    "x264-params": (
                        f"repeat-headers=1:keyint={self.fps * 2}:min-keyint=1:"
                        f"sliced-threads=1:threads={cpu_threads}:sync-lookahead=0:rc-lookahead=0"
                    ),
                }
                ctx.open()
                self._av_codec = ctx
                self.codec_type = "libx264"
                self._wire_magic = MAGIC_H264
                self.active_backend_name = "LIBX264_ULL"
                print(f"[Codec] Encoder {self.active_backend_name} ativo ({self.width}x{self.height} @ {self.fps} FPS, {cpu_threads} threads).")
                return
            except Exception:
                continue

        # 3. Último recurso: JPEG SIMD ou RAW
        self.codec_type = "jpeg" if HAS_CV2 else "raw"
        self.active_backend_name = self.codec_type.upper()
        self._av_codec = None
        print(f"[Codec] Operando em modo de contingência: {self.active_backend_name}.")

    def request_keyframe(self):
        """Solicita emissão imediata de um quadro IDR + SPS/PPS no próximo ciclo de encode."""
        self._force_next_idr = True

    def encode(self, np_bgra: np.ndarray) -> bytes:
        """Comprime um quadro BGRA/BGR em bytes prontos para fragmentação na rede."""
        self._frame_seq += 1
        self.last_frame_was_keyframe = False

        if self._av_codec is not None:
            try:
                src_h, src_w = np_bgra.shape[0], np_bgra.shape[1]
                channels = np_bgra.shape[2] if len(np_bgra.shape) == 3 else 1
                needs_scale = (src_w != self.width) or (src_h != self.height)

                if not needs_scale and HAS_CV2 and channels == 4:
                    yuv = cv2.cvtColor(np_bgra, cv2.COLOR_BGRA2YUV_I420)
                    frame = av.VideoFrame.from_ndarray(yuv, format="yuv420p")
                elif not needs_scale and HAS_CV2 and channels == 3:
                    yuv = cv2.cvtColor(np_bgra, cv2.COLOR_BGR2YUV_I420)
                    frame = av.VideoFrame.from_ndarray(yuv, format="yuv420p")
                elif channels == 4:
                    frame = av.VideoFrame.from_ndarray(np_bgra, format="bgra").reformat(
                        width=self.width, height=self.height, format="yuv420p", interpolation=1
                    )
                else:
                    frame = av.VideoFrame.from_ndarray(np_bgra, format="bgr24").reformat(
                        width=self.width, height=self.height, format="yuv420p", interpolation=1
                    )

                frame.pts = self._frame_seq
                if self._force_next_idr or self._frame_seq == 1:
                    frame.pict_type = 1  # AV_PICTURE_TYPE_I (força IDR + SPS/PPS imediato)
                    self._force_next_idr = False
                    self.last_frame_was_keyframe = True

                packets = self._av_codec.encode(frame)
                if packets:
                    if any(getattr(p, "is_keyframe", False) for p in packets):
                        self.last_frame_was_keyframe = True
                    raw_nal = b"".join(bytes(p) for p in packets)
                    return self._wire_magic + raw_nal
            except Exception:
                pass

        if self.codec_type == "raw":
            self.last_frame_was_keyframe = True
            return MAGIC_RAW + np_bgra.tobytes()

        if HAS_CV2:
            ok, enc = cv2.imencode(
                ".jpg",
                np_bgra,
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

    def close(self):
        if self._av_codec is not None:
            try:
                self._av_codec.encode(None)
            except Exception:
                pass
            self._av_codec = None


class HybridDecoder:
    """Decodificador de baixa latência com detecção automática do formato de fluxo."""

    def __init__(self):
        self._h264_dec = None
        self._hevc_dec = None

    def _get_h264_decoder(self):
        if self._h264_dec is None and HAS_AV:
            try:
                dec = av.CodecContext.create("h264", "r")
                dec.thread_type = "SLICE"
                dec.thread_count = 4
                dec.options = {"flags": "low_delay"}
                dec.open()
                self._h264_dec = dec
                print("[Codec] Decodificador H.264 Slice Low-Delay inicializado (4 threads).")
            except Exception as err:
                print(f"[Codec] Erro ao abrir decodificador H.264: {err}")
        return self._h264_dec

    def _get_hevc_decoder(self):
        if self._hevc_dec is None and HAS_AV:
            try:
                dec = av.CodecContext.create("hevc", "r")
                dec.thread_type = "SLICE"
                dec.thread_count = 4
                dec.options = {"flags": "low_delay"}
                dec.open()
                self._hevc_dec = dec
                print("[Codec] Decodificador HEVC Slice Low-Delay inicializado (4 threads).")
            except Exception as err:
                print(f"[Codec] Erro ao abrir decodificador HEVC: {err}")
        return self._hevc_dec

    def _convert_frame_to_bgr(self, frame) -> np.ndarray:
        """Converte AVFrame decodificado para matriz BGR24 contígua pronta para QImage."""
        try:
            return frame.to_ndarray(format="bgr24")
        except Exception:
            pass
        if HAS_CV2:
            try:
                fmt = frame.format.name
                if fmt == "yuv420p":
                    return cv2.cvtColor(frame.to_ndarray(), cv2.COLOR_YUV2BGR_I420)
                if fmt == "nv12":
                    return cv2.cvtColor(frame.to_ndarray(), cv2.COLOR_YUV2BGR_NV12)
            except Exception:
                pass
        return frame.to_ndarray()

    def decode_all(self, payload: bytes, width: int = 1920, height: int = 1080) -> list:
        """Decodifica todos os quadros contidos no pacote remontado."""
        if not payload:
            return []

        if payload.startswith(MAGIC_H264):
            dec = self._get_h264_decoder()
            if dec:
                try:
                    frames = dec.decode(av.Packet(payload[len(MAGIC_H264):]))
                    return [self._convert_frame_to_bgr(f) for f in frames]
                except Exception:
                    return []
            return []

        if payload.startswith(MAGIC_HEVC):
            dec = self._get_hevc_decoder()
            if dec:
                try:
                    frames = dec.decode(av.Packet(payload[len(MAGIC_HEVC):]))
                    return [self._convert_frame_to_bgr(f) for f in frames]
                except Exception:
                    return []
            return []

        if payload.startswith(MAGIC_RAW):
            raw = payload[len(MAGIC_RAW):]
            if len(raw) == width * height * 4:
                return [np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 4))[:, :, :3]]
            return []

        if payload.startswith(b"\xff\xd8") and HAS_CV2:
            arr = np.frombuffer(payload, dtype=np.uint8)
            res = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            return [res] if res is not None else []

        if len(payload) == width * height * 4:
            return [np.frombuffer(payload, dtype=np.uint8).reshape((height, width, 4))[:, :, :3]]

        return []

    def decode(self, payload: bytes, width: int = 1920, height: int = 1080) -> Optional[np.ndarray]:
        frames = self.decode_all(payload, width, height)
        return frames[-1] if frames else None
