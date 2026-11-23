# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Servico de Captura Unificado — Fabrica Multiplataforma
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import ctypes
import os
import sys
from typing import Any, Dict, List, Optional

from src.dav.kernel.result import ServiceResult
from src.dav.modules.capture.base import BaseCapturer
from src.dav.modules.capture.synthetic_capturer import SyntheticCapturer


def enumerate_system_monitors() -> List[Dict[str, Any]]:
    """Enumera os monitores conectados no sistema operacional (Win32 User32 / MSS) sem depender de UI."""
    monitors: List[Dict[str, Any]] = []

    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            class MONITORINFOEX(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_ulong),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", ctypes.c_ulong),
                    ("szDevice", ctypes.c_wchar * 32),
                ]

            def _enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
                info = MONITORINFOEX()
                info.cbSize = ctypes.sizeof(MONITORINFOEX)
                user32.GetMonitorInfoW(hMonitor, ctypes.byref(info))
                r = info.rcMonitor
                idx = len(monitors)
                monitors.append({
                    "index": idx,
                    "device": info.szDevice or f"Display-{idx + 1}",
                    "left": int(r.left),
                    "top": int(r.top),
                    "width": int(r.right - r.left),
                    "height": int(r.bottom - r.top),
                    "is_primary": bool(info.dwFlags & 1),
                })
                return True

            MONITORENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_long
            )
            user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_enum_proc), 0)
        except Exception:
            pass

    if not monitors:
        try:
            import mss
            factory = getattr(mss, "MSS", getattr(mss, "mss", None))
            if factory is not None:
                with factory() as sct:
                    for idx, m in enumerate(sct.monitors[1:]):
                        monitors.append({
                            "index": idx,
                            "device": f"Display-{idx + 1}",
                            "width": int(m["width"]),
                            "height": int(m["height"]),
                            "left": int(m["left"]),
                            "top": int(m["top"]),
                            "is_primary": (idx == 0),
                        })
        except Exception:
            pass

    if not monitors:
        monitors.append({
            "index": 0,
            "device": "Display-1",
            "width": 1920,
            "height": 1080,
            "left": 0,
            "top": 0,
            "is_primary": True,
        })

    return monitors


class CaptureService:
    """Fabrica e orquestrador de capturadores de tela."""

    @staticmethod
    def enumerate_monitors() -> List[Dict[str, Any]]:
        return enumerate_system_monitors()

    @staticmethod
    def create_capturer(
        width: int = 1920,
        height: int = 1080,
        fps: int = 60,
        monitor_index: int = 0,
        display_idx: Optional[int] = None,
        force_synthetic: bool = False,
    ) -> ServiceResult[BaseCapturer]:
        """Cria e retorna uma instancia pronta do capturador ideal para o host."""
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

        cap = SyntheticCapturer(width=width, height=height, fps=fps, monitor_index=idx)
        return ServiceResult.ok(cap, code="CAPTURER_FALLBACK")
