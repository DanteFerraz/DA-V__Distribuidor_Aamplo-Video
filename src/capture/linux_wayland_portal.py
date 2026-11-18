# -*- coding: utf-8 -*-
"""
Shim de Compatibilidade — Redireciona para `src.dav.modules.capture.wayland_portal`.
Autor: Dante Ferraz (MonoTech)
"""

from src.dav.modules.capture.wayland_portal import (
    WaylandPortalCapturer,
    _PORTAL_HELPER_CODE,
    _build_clean_host_env,
    is_wayland_session,
)

__all__ = [
    "WaylandPortalCapturer",
    "_PORTAL_HELPER_CODE",
    "_build_clean_host_env",
    "is_wayland_session",
]
