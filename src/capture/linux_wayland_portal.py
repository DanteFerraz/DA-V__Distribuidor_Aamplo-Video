# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
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
