# -*- coding: utf-8 -*-
"""
Módulo de Captura de Tela — Interface Base
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import numpy as np


class BaseCapturer(ABC):
    """Interface padrão para capturadores de tela de alta performance."""

    def __init__(self, width: int = 1920, height: int = 1080, fps: int = 60, monitor_index: int = 0):
        self.width = width
        self.height = height
        self.fps = max(1, fps)
        self.monitor_index = monitor_index
        self._is_running = False

    @abstractmethod
    def start(self) -> bool:
        """Inicializa o capturador e adquire permissões do sistema."""
        pass

    @abstractmethod
    def grab_into(self, dst_buffer: np.ndarray) -> bool:
        """
        Copia o quadro capturado mais recente no buffer fornecido em tempo < 1 ms.
        dst_buffer deve ter formato (height, width, 4) dtype=uint8 (BGRA/BGRx).
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Libera handles do compositor, buffers de GPU e threads."""
        pass

