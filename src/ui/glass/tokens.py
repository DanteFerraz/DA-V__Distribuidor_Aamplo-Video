# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
DA-V Glass Design System - Tokens
Autor: Dante Ferraz (MonoTech)

Medidas extraidas das telas de referencia (1920x1080) em design/blocks_components/Telas.
Todas as dimensoes "design" sao em pixels de um canvas 1920x1080 e sao convertidas para a
janela real por um fator de escala (`ui_scale`).
"""

from __future__ import annotations

from typing import Tuple

# --- Geometria de referencia (canvas 1920x1080) ---------------------------------
REF_W, REF_H = 1920.0, 1080.0

# Card central de vidro (fracao da janela)
CARD_W_FRAC = 0.5656   # 1086 / 1920
CARD_H_FRAC = 0.5926   # 640 / 1080
CARD_DESIGN_W, CARD_DESIGN_H = 1086.0, 640.0

# Card amplo usado nas folhas de configuracao/telemetria
SHEET_FRAC = (0.13, 0.17, 0.74, 0.78)   # left, top, width, height

# Pilula de navegacao (px de design)
PILL_COLLAPSED = (168.0, 44.0, 14.0)    # largura, altura, margem superior
PILL_EXPANDED = (492.0, 96.0, 22.0)

# Controles dentro do card (px de design)
CONTROL_W = 640.0
INPUT_H = 57.0
BUTTON_H = 118.0

# Tipografia (px de design)
FONT_TITLE = 52
FONT_LABEL = 48
FONT_BUTTON = 46
FONT_INPUT = 38
FONT_HINT = 26
FONT_STATUS = 30

FONT_FAMILIES = ["Segoe UI Variable", "Segoe UI", "Inter", "Noto Sans", "Helvetica Neue", "Arial"]

# --- Paleta ---------------------------------------------------------------------
# Gradiente de fundo (posicao 0..1, cor RGB)
BACKGROUND_STOPS = [
    (0.00, (226, 253, 238)),
    (0.18, (214, 240, 231)),
    (0.38, (160, 205, 203)),
    (0.58, (108, 168, 178)),
    (0.78, (50, 125, 145)),
    (1.00, (9, 94, 120)),
]

WHITE = (255, 255, 255)
TEXT = (255, 255, 255)
TEXT_DIM = (232, 248, 246)
PILL_TINT = (120, 200, 185)
CARD_TEAL = (60, 135, 152)
DANGER = (255, 214, 214)
SUCCESS = (210, 255, 232)

# QSS de campos nativos usados dentro das folhas (config/telemetria)
SHEET_TEXT = "#f2fbfb"
SHEET_TEXT_DIM = "#cfe8e8"

# Sombreamento (Drop-Shadow para visibilidade e contraste sobre vidro e video)
ICON_SHADOW_RGBA = (8, 28, 38, 128)
ICON_SHADOW_OFFSET = (0.0, 2.0)
TEXT_SHADOW_RGBA = (6, 24, 34, 145)
TEXT_SHADOW_OFFSET = (0.0, 2.0)


def ui_scale(width: float, height: float) -> float:
    """Fator de escala da janela em relacao ao canvas de referencia 1920x1080."""
    return max(0.40, min(width / REF_W, height / REF_H))


def card_scale(width: float, height: float) -> float:
    """Fator de escala de um card em relacao ao card de referencia (1086x640)."""
    return max(0.38, min(width / CARD_DESIGN_W, height / CARD_DESIGN_H))


def px(design_px: float, scale: float, minimum: int = 1) -> int:
    """Converte um tamanho de design em pixels reais."""
    return max(minimum, int(round(design_px * scale)))


def rgba(color: Tuple[int, int, int], alpha: float) -> str:
    """Formata cor para QSS: rgba(r,g,b,a)."""
    return f"rgba({color[0]},{color[1]},{color[2]},{alpha:.3f})"

