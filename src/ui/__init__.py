# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
DA-V (Distribuidor Amplo de Vídeo) — Pacote de Interface Gráfica Desktop
Arquitetura moderna e modular em PySide6 / LGPLv3 com carregamento preguiçoso PEP 562.
"""

from __future__ import annotations

from typing import Any

__all__ = ["Theme", "EngineBridge", "DecodeWorker", "DavMainWindow"]


def __getattr__(name: str) -> Any:
    if name == "Theme":
        from src.ui.theme import Theme

        return Theme
    if name in ("EngineBridge", "DecodeWorker"):
        from src.ui import bridge

        return getattr(bridge, name)
    if name == "DavMainWindow":
        from src.ui.main_window import DavMainWindow

        return DavMainWindow
    raise AttributeError(f"module 'src.ui' has no attribute {name!r}")
