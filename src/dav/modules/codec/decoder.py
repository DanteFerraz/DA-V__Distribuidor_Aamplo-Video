# -*- coding: utf-8 -*-
"""
Decodificador de Vídeo Unificado — PyAV H.264 / HEVC Slice Low-Delay
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
from typing import List, Optional
import numpy as np

from src.dav.modules.codec.base import BaseDecoder, MAGIC_H264, MAGIC_HEVC, MAGIC_RAW

logger = logging.getLogger("DAV.Codec.Decoder")

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
except ImportError:
    pass


class VideoDecoder(BaseDecoder):
    """
    Decodificador de baixa latência com garantia estrita de buffers C-contíguos
    para compatibilidade com qualquer resolução e renderização direta em QImage.
    """

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
                logger.info("[Codec] Decodificador H.264 Slice Low-Delay inicializado.")
            except Exception as exc:
                logger.error(f"[Codec] Falha ao abrir decodificador H.264: {exc}")
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
                logger.info("[Codec] Decodificador HEVC Slice Low-Delay inicializado.")
            except Exception as exc:
                logger.error(f"[Codec] Falha ao abrir decodificador HEVC: {exc}")
        return self._hevc_dec

    def _convert_frame_to_bgr(self, frame) -> np.ndarray:
        """Converte AVFrame decodificado para matriz BGR24 C-contígua pronta para QImage."""
        arr = None
        try:
            arr = frame.to_ndarray(format="bgr24")
        except Exception:
            if HAS_CV2:
                try:
                    fmt = frame.format.name
                    if fmt == "yuv420p":
                        arr = cv2.cvtColor(frame.to_ndarray(), cv2.COLOR_YUV2BGR_I420)
                    elif fmt == "nv12":
                        arr = cv2.cvtColor(frame.to_ndarray(), cv2.COLOR_YUV2BGR_NV12)
                except Exception:
                    arr = None
            if arr is None:
                arr = frame.to_ndarray()

        # Proteção contra non-contiguous strides em resoluções como 1366x768
        if arr is not None and not arr.flags["C_CONTIGUOUS"]:
            arr = np.ascontiguousarray(arr)
        return arr

    def decode_all(self, payload: bytes, width: int = 1920, height: int = 1080) -> List[np.ndarray]:
        if not payload:
            return []

        if payload.startswith(MAGIC_H264):
            dec = self._get_h264_decoder()
            if dec:
                try:
                    frames = dec.decode(av.Packet(payload[len(MAGIC_H264):]))
                    return [self._convert_frame_to_bgr(f) for f in frames if f is not None]
                except Exception as exc:
                    logger.debug(f"[Codec] Erro no decode H.264: {exc}")
                    return []
            return []

        if payload.startswith(MAGIC_HEVC):
            dec = self._get_hevc_decoder()
            if dec:
                try:
                    frames = dec.decode(av.Packet(payload[len(MAGIC_HEVC):]))
                    return [self._convert_frame_to_bgr(f) for f in frames if f is not None]
                except Exception as exc:
                    logger.debug(f"[Codec] Erro no decode HEVC: {exc}")
                    return []
            return []

        if payload.startswith(MAGIC_RAW):
            raw = payload[len(MAGIC_RAW):]
            if len(raw) == width * height * 4:
                arr = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 4))[:, :, :3]
                if not arr.flags["C_CONTIGUOUS"]:
                    arr = np.ascontiguousarray(arr)
                return [arr]
            return []

        if payload.startswith(b"\xff\xd8") and HAS_CV2:
            arr = np.frombuffer(payload, dtype=np.uint8)
            res = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            return [res] if res is not None else []

        return []

    def close(self) -> None:
        self._h264_dec = None
        self._hevc_dec = None

