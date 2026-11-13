# -*- coding: utf-8 -*-
"""
DA-V Glass Design System - Sistema de design "vidro" (v4.1)
Autor: Dante Ferraz (MonoTech)

Camadas, de baixo para cima:
  tokens   -> medidas e cores extraidas das telas de referencia
  paint    -> desenho puro (fundo, card, pilula) com cache de pixmaps
  icons    -> icones vetoriais (QPainterPath)
  widgets  -> GlassCard, GlassButton, GlassLineEdit, GlassSegmented...
  nav_pill -> pilula flutuante de navegacao
  qss      -> reveste widgets nativos dentro das folhas tecnicas
"""

from src.ui.glass import tokens
from src.ui.glass.nav_pill import FloatingNavPill
from src.ui.glass.sheets import BaseOverlaySheet, SettingsSheet, StatsSheet
from src.ui.glass.views import (
    SenderHomePage,
    ViewerConnectingPage,
    ViewerIdlePage,
    parse_access_input,
)
from src.ui.glass.widgets import (
    CardPage, GlassButton, GlassCard, GlassLabel, GlassLineEdit, GlassScrollArea, GlassSegmented,
    GlassSpacer,
)

__all__ = [
    "tokens", "FloatingNavPill", "BaseOverlaySheet", "SettingsSheet", "StatsSheet",
    "SenderHomePage", "ViewerConnectingPage", "ViewerIdlePage", "parse_access_input",
    "CardPage", "GlassButton", "GlassCard", "GlassLabel", "GlassLineEdit",
    "GlassScrollArea", "GlassSegmented", "GlassSpacer",
]
