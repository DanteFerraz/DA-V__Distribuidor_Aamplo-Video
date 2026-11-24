# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
DA-V Glass Design System - Sistema de design "vidro" (v5.0)
Autor: Dante Ferraz (MonoTech)

Camadas, de baixo para cima:
  tokens          -> medidas e cores extraidas das telas de referencia
  paint           -> desenho puro (fundo, card, pilula) com cache de pixmaps
  icons           -> icones vetoriais (QPainterPath)
  widgets         -> GlassCard, GlassButton, GlassLineEdit, GlassToggleSwitch...
  nav_pill        -> pilula flutuante de navegacao
  qss             -> reveste widgets nativos dentro das folhas tecnicas
  installer_shell -> shell Glassmorphism compartilhado pelos instaladores Windows e Linux

Usa carregamento preguicoso (`__getattr__` PEP 562) para `views` e `sheets` a fim de que
o binario standalone `--onefile` do instalador importe apenas os primitivos leves de UI.
"""

from __future__ import annotations

from typing import Any

from src.ui.glass import icons, paint, qss, tokens
from src.ui.glass.widgets import (
    CardPage,
    GlassButton,
    GlassCard,
    GlassLabel,
    GlassLineEdit,
    GlassScrollArea,
    GlassSegmented,
    GlassSpacer,
    GlassToggleSwitch,
    VideoOverlayControls,
)

__all__ = [
    "tokens",
    "paint",
    "icons",
    "qss",
    "FloatingNavPill",
    "BaseOverlaySheet",
    "SettingsSheet",
    "StatsSheet",
    "RemoteWorkspaceView",
    "SenderHomePage",
    "ViewerConnectingPage",
    "ViewerIdlePage",
    "parse_access_input",
    "CardPage",
    "GlassButton",
    "GlassCard",
    "GlassLabel",
    "GlassLineEdit",
    "GlassScrollArea",
    "GlassSegmented",
    "GlassSpacer",
    "GlassToggleSwitch",
    "VideoOverlayControls",
    "DavGlassInstallerDialog",
]


def __getattr__(name: str) -> Any:
    if name == "FloatingNavPill":
        from src.ui.glass.nav_pill import FloatingNavPill

        return FloatingNavPill
    if name in ("BaseOverlaySheet", "SettingsSheet", "StatsSheet", "RemoteWorkspaceView"):
        from src.ui.glass import sheets

        return getattr(sheets, name)
    if name in ("SenderHomePage", "ViewerConnectingPage", "ViewerIdlePage", "parse_access_input"):
        from src.ui.glass import views

        return getattr(views, name)
    if name == "DavGlassInstallerDialog":
        from src.ui.glass.installer_shell import DavGlassInstallerDialog

        return DavGlassInstallerDialog
    raise AttributeError(f"module 'src.ui.glass' has no attribute {name!r}")
