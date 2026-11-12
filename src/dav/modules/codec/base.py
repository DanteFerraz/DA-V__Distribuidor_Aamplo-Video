# -*- coding: utf-8 -*-
"""
Módulo de Codec — Interfaces Base
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional
import numpy as np


# Identificadores de formato na rede (prefixo de 9 bytes)
MAGIC_H264 = b"DAV_H264:"
MAGIC_HEVC = b"DAV_HEVC:"
MAGIC_RAW = b"DAV_RAW_:"


class BaseEncoder(ABC):
    """Interface abstrata para codificadores de vídeo."""

    @abstractmethod
    def encode(self, frame_bgra: np.ndarray) -> bytes:
        """Codifica o quadro de entrada em bytes prontos para transmissão."""
        pass

    @abstractmethod
    def request_keyframe(self) -> None:
        """Solicita a emissão imediata de um IDR + SPS/PPS no próximo quadro."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Encerra e libera o contexto do encoder."""
        pass


class BaseDecoder(ABC):
    """Interface abstrata para decodificadores de vídeo."""

    @abstractmethod
    def decode_all(self, payload: bytes, width: int = 1920, height: int = 1080) -> List[np.ndarray]:
        """Decodifica todos os quadros contidos no payload remontado em BGR contíguo."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Encerra e libera o contexto do decoder."""
        pass
