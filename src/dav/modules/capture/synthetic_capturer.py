# -*- coding: utf-8 -*-
"""
Capturador Sintético de Alta Fidelidade (Headless / CI / Testes)
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import time
import numpy as np
from src.dav.modules.capture.base import BaseCapturer


class SyntheticCapturer(BaseCapturer):
    """
    Gera padrões de teste coloridos com relógio dinâmico e gradientes,
    permitindo testar o pipeline completo de 60 FPS sem servidor gráfico.
    """

    def __init__(self, width: int = 1920, height: int = 1080, fps: int = 60, monitor_index: int = 0):
        super().__init__(width, height, fps, monitor_index)
        self._frame_seq = 0

    def start(self) -> bool:
        self._is_running = True
        return True

    def grab_into(self, dst_buffer: np.ndarray) -> bool:
        if not self._is_running:
            return False
        self._frame_seq += 1
        seq = self._frame_seq

        # Fundo dinâmico com variação de cor determinística
        dst_buffer.fill(32)
        dst_buffer[:, :, 0] = (seq * 4) % 255   # B
        dst_buffer[:, :, 1] = 128                # G
        dst_buffer[:, :, 2] = (seq * 7) % 255   # R
        dst_buffer[:, :, 3] = 255                # A

        # Marca um bloco móvel para simular movimento de tela a 60 FPS
        bx = (seq * 8) % max(1, self.width - 120)
        by = (seq * 5) % max(1, self.height - 120)
        dst_buffer[by : by + 100, bx : bx + 100, :3] = 250

        return True

    def close(self) -> None:
        self._is_running = False

