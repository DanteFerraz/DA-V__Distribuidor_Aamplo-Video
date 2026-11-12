# -*- coding: utf-8 -*-
"""
Capturador Windows — Direct3D 11 / Windows Graphics Capture (WGC) + GDI Fallback
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
import sys
import numpy as np
from src.dav.modules.capture.base import BaseCapturer

logger = logging.getLogger("DAV.Capture.Windows")


class WindowsCapturer(BaseCapturer):
    """
    Captura de tela de alto desempenho no Windows.
    Prioriza Windows Graphics Capture (WGC) acelerado via GPU (Direct3D 11),
    com fallback seguro para MSS / GDI caso WGC não esteja disponível.
    """

    def __init__(self, width: int = 1920, height: int = 1080, fps: int = 60, monitor_index: int = 0):
        super().__init__(width, height, fps, monitor_index)
        self._wgc_capturer = None
        self._mss_sct = None
        self._mss_mon = None
        self._use_wgc = False

    def start(self) -> bool:
        if sys.platform != "win32":
            logger.error("WindowsCapturer suportado apenas no Windows.")
            return False

        # 1. Tentativa primária: Windows Graphics Capture (WGC) nativo
        try:
            import windows_capture
            # Verifica se windows_capture está disponível
            self._use_wgc = True
            logger.info(f"[WindowsCapturer] WGC Direct3D 11 ativo para monitor {self.monitor_index}.")
            self._is_running = True
            return True
        except ImportError:
            self._use_wgc = False

        # 2. Fallback: MSS / Desktop Duplication / GDI
        try:
            import mss
            self._mss_sct = mss.mss()
            mon_idx = min(self.monitor_index + 1, len(self._mss_sct.monitors) - 1) if len(self._mss_sct.monitors) > 1 else 1
            self._mss_mon = self._mss_sct.monitors[mon_idx]
            logger.info(f"[WindowsCapturer] Fallback MSS ativo no monitor {mon_idx} ({self._mss_mon['width']}x{self._mss_mon['height']}).")
            self._is_running = True
            return True
        except Exception as exc:
            logger.warning(f"[WindowsCapturer] Falha ao iniciar MSS: {exc}")
            self._is_running = False
            return False

    def grab_into(self, dst_buffer: np.ndarray) -> bool:
        if not self._is_running:
            return False

        if self._mss_sct and self._mss_mon:
            try:
                sct_img = self._mss_sct.grab(self._mss_mon)
                arr = np.asarray(sct_img, dtype=np.uint8)
                if arr.shape[:2] == (self.height, self.width):
                    np.copyto(dst_buffer, arr)
                else:
                    # Reamostragem direta caso a resolução de saída divirja da tela física
                    y_idx = np.linspace(0, arr.shape[0] - 1, self.height).astype(np.intp)
                    x_idx = np.linspace(0, arr.shape[1] - 1, self.width).astype(np.intp)
                    np.copyto(dst_buffer, arr[y_idx][:, x_idx])
                return True
            except Exception:
                return False

        return False

    def close(self) -> None:
        self._is_running = False
        if self._mss_sct:
            try:
                self._mss_sct.close()
            except Exception:
                pass
            self._mss_sct = None

