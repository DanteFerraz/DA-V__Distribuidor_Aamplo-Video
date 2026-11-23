# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Capturador Linux Unificado — Wayland (PipeWire Portal) & X11 (MIT-SHM / MSS)
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
import os
import sys
import numpy as np
from src.dav.modules.capture.base import BaseCapturer

logger = logging.getLogger("DAV.Capture.Linux")


class LinuxCapturer(BaseCapturer):
    """
    Capturador nativo para ambientes Linux modernos.
    Detecta Wayland (GNOME / KDE / Hyprland) e inicializa o XDG Desktop Portal + PipeWire.
    Em sessões X11 ou contingência, opera via XShm/MSS com sentinela anti-XWayland.
    """

    def __init__(self, width: int = 1920, height: int = 1080, fps: int = 60, monitor_index: int = 0):
        super().__init__(width, height, fps, monitor_index)
        self._portal_cap = None
        self._sct = None
        self._mon_box = None
        self._consecutive_black = 0
        self._tried_portal = False

    def start(self) -> bool:
        if sys.platform == "win32":
            logger.error("LinuxCapturer não é suportado no Windows.")
            return False

        from src.dav.modules.capture.wayland_portal import WaylandPortalCapturer, is_wayland_session

        if is_wayland_session():
            self._tried_portal = True
            logger.info("[LinuxCapturer] Sessão Wayland detectada. Negociando XDG Desktop Portal / PipeWire...")
            portal = WaylandPortalCapturer(width=self.width, height=self.height, fps=self.fps)
            if portal.start(wait_first_frame_timeout=45.0):
                self._portal_cap = portal
                self._is_running = True
                logger.info("[LinuxCapturer] Captura PipeWire autorizada e ativa.")
                return True
            else:
                logger.warning(f"[LinuxCapturer] PipeWire recusado/falhou ({portal.last_error}). Tentando X11...")

        # Fallback X11
        try:
            import mss
            self._sct = mss.mss()
            mon_idx = min(self.monitor_index + 1, len(self._sct.monitors) - 1) if len(self._sct.monitors) > 1 else 1
            self._mon_box = self._sct.monitors[mon_idx]
            self._is_running = True
            return True
        except Exception as exc:
            logger.error(f"[LinuxCapturer] Falha no fallback X11: {exc}")
            return False

    def grab_into(self, dst_buffer: np.ndarray) -> bool:
        if not self._is_running:
            return False

        if self._portal_cap is not None:
            return self._portal_cap.grab_into(dst_buffer)

        if self._sct and self._mon_box:
            try:
                sct_img = self._sct.grab(self._mon_box)
                arr = np.asarray(sct_img, dtype=np.uint8)
                if arr.shape[:2] == (self.height, self.width):
                    np.copyto(dst_buffer, arr)
                else:
                    y_idx = np.linspace(0, arr.shape[0] - 1, self.height).astype(np.intp)
                    x_idx = np.linspace(0, arr.shape[1] - 1, self.width).astype(np.intp)
                    np.copyto(dst_buffer, arr[y_idx][:, x_idx])

                # Sentinela anti-XWayland: detecta se X11 está devolvendo tela preta silenciosa
                if not self._tried_portal:
                    if not np.any(dst_buffer[::16, ::16, :3]):
                        self._consecutive_black += 1
                        if self._consecutive_black >= 8:
                            self._tried_portal = True
                            logger.warning("[LinuxCapturer] Tela preta detectada no XWayland. Migrando a quente para PipeWire...")
                            from src.dav.modules.capture.wayland_portal import WaylandPortalCapturer
                            candidate = WaylandPortalCapturer(width=self.width, height=self.height, fps=self.fps)
                            if candidate.start(wait_first_frame_timeout=45.0):
                                self._portal_cap = candidate
                                self._portal_cap.grab_into(dst_buffer)
                                try:
                                    self._sct.close()
                                except Exception:
                                    pass
                                self._sct = None
                    else:
                        self._consecutive_black = 0
                return True
            except Exception:
                return False

        return False

    def close(self) -> None:
        self._is_running = False
        if self._portal_cap is not None:
            self._portal_cap.close()
            self._portal_cap = None
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None

