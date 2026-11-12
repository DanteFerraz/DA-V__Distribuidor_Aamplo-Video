# -*- coding: utf-8 -*-
"""
Serviço de Captura Unificado — Fábrica Multiplataforma
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional
from src.dav.modules.capture.base import BaseCapturer
from src.dav.modules.capture.synthetic_capturer import SyntheticCapturer
from src.dav.kernel.result import ServiceResult


def enumerate_system_monitors() -> List[Dict[str, Any]]:
    """Enumera os monitores conectados no sistema operacional de forma agnóstica."""
    monitors: List[Dict[str, Any]] = []

    # Tentativa via MSS
    try:
        import mss
        factory = getattr(mss, "MSS", getattr(mss, "mss", None))
        if factory is not None:
            with factory() as sct:
                for idx, m in enumerate(sct.monitors[1:]):
                    monitors.append({
                        "index": idx,
                        "width": int(m["width"]),
                        "height": int(m["height"]),
                        "left": int(m["left"]),
                        "top": int(m["top"]),
                        "is_primary": (idx == 0),
                    })
    except Exception:
        pass

    if not monitors:
        # Fallback padrão seguro
        monitors.append({
            "index": 0,
            "width": 1920,
            "height": 1080,
            "left": 0,
            "top": 0,
            "is_primary": True,
        })

    return monitors


class CaptureService:
    """Fábrica e orquestrador de capturadores de tela."""

    @staticmethod
    def create_capturer(
        width: int = 1920,
        height: int = 1080,
        fps: int = 60,
        monitor_index: int = 0,
        display_idx: Optional[int] = None,
        force_synthetic: bool = False,
    ) -> ServiceResult[BaseCapturer]:
        """Cria e retorna uma instância pronta do capturador ideal para o host."""
        idx = display_idx if display_idx is not None else monitor_index
        if force_synthetic or os.environ.get("DAV_HEADLESS_SYNTHETIC") == "1":
            cap = SyntheticCapturer(width=width, height=height, fps=fps, monitor_index=idx)
            return ServiceResult.ok(cap, code="CAPTURER_SYNTHETIC")

        if sys.platform == "win32":
            from src.dav.modules.capture.windows_capturer import WindowsCapturer
            cap = WindowsCapturer(width=width, height=height, fps=fps, monitor_index=idx)
            return ServiceResult.ok(cap, code="CAPTURER_WINDOWS")

        if sys.platform.startswith("linux"):
            from src.dav.modules.capture.linux_capturer import LinuxCapturer
            cap = LinuxCapturer(width=width, height=height, fps=fps, monitor_index=idx)
            return ServiceResult.ok(cap, code="CAPTURER_LINUX")

        # Fallback universal
        cap = SyntheticCapturer(width=width, height=height, fps=fps, monitor_index=idx)
        return ServiceResult.ok(cap, code="CAPTURER_SYNTHETIC_FALLBACK")
