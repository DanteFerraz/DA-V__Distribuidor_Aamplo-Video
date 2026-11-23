# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
DA-V UI Design System & Tokens — Blocks.so Modern Enterprise Architecture
Inspirado na biblioteca Blocks.so / shadcn/ui com suporte nativo a Modos Claro e Escuro
e contraste em Azul MonoTech (#0066FF).
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from typing import Dict


class Theme:
    """
    Sistema de Design multi-camadas (Reference -> System -> Component Tokens)
    com suporte dinâmico a temas Dark (Obsidian/Zinc) e Light (Clean Slate/White).
    """

    current_mode: str = "dark"

    # ── 1. REFERENCE TOKENS (Paleta Bruta) ──────────────────────────────────
    REF = {
        # Neutros Escuros (Blocks.so Zinc Dark)
        "zinc_950": "#09090b",
        "zinc_900": "#121215",
        "zinc_850": "#18181b",
        "zinc_800": "#202024",
        "zinc_750": "#27272a",
        "zinc_700": "#3f3f46",
        "zinc_600": "#52525b",
        "zinc_500": "#71717a",
        "zinc_400": "#a1a1aa",
        "zinc_300": "#d4d4d8",
        "zinc_200": "#e4e4e7",
        "zinc_100": "#f4f4f5",
        "zinc_50":  "#fafafa",

        # Neutros Claros (Blocks.so Slate/White Light)
        "slate_50":  "#f8fafc",
        "slate_100": "#f1f5f9",
        "slate_200": "#e2e8f0",
        "slate_300": "#cbd5e1",
        "slate_400": "#94a3b8",
        "slate_500": "#64748b",
        "slate_600": "#475569",
        "slate_700": "#334155",
        "slate_800": "#1e293b",
        "slate_900": "#0f172a",
        "slate_950": "#020617",
        "pure_white": "#ffffff",

        # Azul MonoTech (Cor Canônica de Acento e Contraste)
        "monotech_blue_400": "#38bdf8",
        "monotech_blue_500": "#0066FF",  # Azul MonoTech Primário
        "monotech_blue_600": "#0052cc",  # Azul MonoTech Hover Light
        "monotech_blue_700": "#003d99",  # Azul MonoTech Active
        "monotech_blue_light": "#2575fc",# Azul MonoTech Hover Dark
        "monotech_blue_glow":  "#0066ff33",

        # Status Semânticos
        "emerald_500": "#10b981",
        "emerald_600": "#059669",
        "amber_500":   "#f59e0b",
        "amber_600":   "#d97706",
        "rose_500":    "#ef4444",
        "rose_600":    "#dc2626",
        "violet_500":  "#8b5cf6",
    }

    # ── 2. SYSTEM TOKENS: TEMA ESCURO (Blocks.so Zinc Dark) ──────────────────
    DARK_SYS: Dict[str, str] = {
        # Superfícies
        "bg_canvas":            REF["zinc_950"],
        "bg_surface":           REF["zinc_900"],
        "bg_surface_card":      REF["zinc_850"],
        "bg_surface_elevated":  REF["zinc_800"],
        "bg_surface_hover":     REF["zinc_750"],

        # Bordas
        "border_subtle":        REF["zinc_750"],
        "border_medium":        REF["zinc_700"],
        "border_active":        REF["monotech_blue_500"],
        "border_focus":         REF["monotech_blue_500"],

        # Textos
        "text_primary":         REF["zinc_100"],
        "text_secondary":       REF["zinc_400"],
        "text_muted":           REF["zinc_500"],
        "text_accent":          REF["monotech_blue_400"],

        # Azul MonoTech
        "accent_primary":       REF["monotech_blue_500"],
        "accent_primary_hover": REF["monotech_blue_light"],
        "accent_primary_active":REF["monotech_blue_700"],
        "accent_badge_bg":      "#002266",

        # Status
        "status_success":       REF["emerald_500"],
        "status_success_bg":    "#06281e",
        "status_warning":       REF["amber_500"],
        "status_warning_bg":    "#2e1804",
        "status_danger":        REF["rose_500"],
        "status_danger_hover":  REF["rose_600"],
        "status_danger_bg":     "#2a0a0f",
        "status_info":          REF["monotech_blue_400"],
    }

    # ── 3. SYSTEM TOKENS: TEMA CLARO (Blocks.so Slate Light) ─────────────────
    LIGHT_SYS: Dict[str, str] = {
        # Superfícies
        "bg_canvas":            REF["slate_50"],
        "bg_surface":           REF["pure_white"],
        "bg_surface_card":      REF["pure_white"],
        "bg_surface_elevated":  REF["slate_100"],
        "bg_surface_hover":     REF["slate_200"],

        # Bordas
        "border_subtle":        REF["slate_200"],
        "border_medium":        REF["slate_300"],
        "border_active":        REF["monotech_blue_500"],
        "border_focus":         REF["monotech_blue_500"],

        # Textos
        "text_primary":         REF["slate_900"],
        "text_secondary":       REF["slate_600"],
        "text_muted":           REF["slate_400"],
        "text_accent":          REF["monotech_blue_500"],

        # Azul MonoTech
        "accent_primary":       REF["monotech_blue_500"],
        "accent_primary_hover": REF["monotech_blue_600"],
        "accent_primary_active":REF["monotech_blue_700"],
        "accent_badge_bg":      "#e6f0ff",

        # Status
        "status_success":       REF["emerald_600"],
        "status_success_bg":    "#ecfdf5",
        "status_warning":       REF["amber_600"],
        "status_warning_bg":    "#fffbeb",
        "status_danger":        REF["rose_600"],
        "status_danger_hover":  "#b91c1c",
        "status_danger_bg":     "#fef2f2",
        "status_info":          REF["monotech_blue_600"],
    }

    # SYS aponta dinamicamente para os tokens ativos
    SYS: Dict[str, str] = DARK_SYS.copy()

    # Espaçamento e Geometria (Escala 4pt / 8pt)
    SPACE_XXS = 2
    SPACE_XS  = 4
    SPACE_SM  = 8
    SPACE_MD  = 12
    SPACE_LG  = 16
    SPACE_XL  = 24
    SPACE_2XL = 32

    RADIUS_SM = 4
    RADIUS_MD = 6
    RADIUS_LG = 8
    RADIUS_XL = 12

    @classmethod
    def set_theme(cls, mode: str = "dark") -> str:
        """Comuta o tema ativo ('dark' ou 'light') e atualiza os tokens semânticos."""
        if mode.lower() == "light":
            cls.current_mode = "light"
            cls.SYS.clear()
            cls.SYS.update(cls.LIGHT_SYS)
        else:
            cls.current_mode = "dark"
            cls.SYS.clear()
            cls.SYS.update(cls.DARK_SYS)
        return cls.current_mode

    @classmethod
    def toggle_theme(cls) -> str:
        """Alterna entre os modos Claro e Escuro."""
        new_mode = "light" if cls.current_mode == "dark" else "dark"
        return cls.set_theme(new_mode)

    @classmethod
    def get_qss(cls) -> str:
        """Gera a folha de estilos global Qt aderente ao design Blocks.so."""
        s = cls.SYS
        is_dark = (cls.current_mode == "dark")
        input_bg = s["bg_canvas"] if is_dark else "#ffffff"
        btn_txt_primary = "#ffffff"

        return f"""
        /* ── Estilos Globais da Janela (Blocks.so) ── */
        QMainWindow {{
            background-color: {s["bg_canvas"]};
            color: {s["text_primary"]};
            font-family: 'Segoe UI', Inter, -apple-system, sans-serif;
        }}

        QWidget {{
            color: {s["text_primary"]};
            background-color: transparent;
            font-family: 'Segoe UI', Inter, -apple-system, sans-serif;
            font-size: 13px;
        }}

        /* ── Scrollbars Finos e Estilizados ── */
        QScrollBar:vertical {{
            border: none;
            background: {s["bg_surface"]};
            width: 7px;
            margin: 0px;
            border-radius: 3px;
        }}
        QScrollBar::handle:vertical {{
            background: {s["border_medium"]};
            min-height: 24px;
            border-radius: 3px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {s["accent_primary"]};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar:horizontal {{
            border: none;
            background: {s["bg_surface"]};
            height: 7px;
            margin: 0px;
            border-radius: 3px;
        }}
        QScrollBar::handle:horizontal {{
            background: {s["border_medium"]};
            min-width: 24px;
            border-radius: 3px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {s["accent_primary"]};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}

        /* ── GroupBox / Cards Blocks.so ── */
        QGroupBox {{
            font-weight: 700;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            border: 1px solid {s["border_subtle"]};
            border-radius: {cls.RADIUS_LG}px;
            margin-top: 14px;
            padding-top: 18px;
            background-color: {s["bg_surface_card"]};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 8px;
            color: {s["text_accent"]};
            background-color: {s["bg_surface_card"]};
            border-radius: 4px;
        }}

        /* ── Campos de Entrada (Inputs, SpinBox, Combo) ── */
        QLineEdit, QSpinBox, QComboBox {{
            background-color: {input_bg};
            border: 1px solid {s["border_subtle"]};
            border-radius: {cls.RADIUS_MD}px;
            padding: 7px 12px;
            color: {s["text_primary"]};
            font-size: 13px;
            min-height: 20px;
            selection-background-color: {s["accent_primary"]};
            selection-color: #ffffff;
        }}
        QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{
            border: 1px solid {s["border_medium"]};
        }}
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
            border: 1px solid {s["border_focus"]};
            background-color: {input_bg};
        }}
        QLineEdit:read-only {{
            color: {s["text_secondary"]};
            background-color: {s["bg_surface_elevated"]};
        }}

        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 24px;
            border-left: 1px solid {s["border_subtle"]};
        }}
        QComboBox QAbstractItemView {{
            background-color: {s["bg_surface_card"]};
            border: 1px solid {s["border_medium"]};
            border-radius: 6px;
            color: {s["text_primary"]};
            selection-background-color: {s["bg_surface_hover"]};
            selection-color: {s["accent_primary"]};
            padding: 4px;
        }}

        /* ── Botões Blocks.so com Azul MonoTech ── */
        QPushButton {{
            background-color: {s["accent_primary"]};
            color: {btn_txt_primary};
            font-weight: 600;
            border-radius: {cls.RADIUS_MD}px;
            padding: 8px 18px;
            font-size: 13px;
            border: 1px solid {s["accent_primary"]};
            outline: none;
            min-height: 20px;
        }}
        QPushButton:hover {{
            background-color: {s["accent_primary_hover"]};
            border-color: {s["accent_primary_hover"]};
        }}
        QPushButton:pressed {{
            background-color: {s["accent_primary_active"]};
            border-color: {s["accent_primary_active"]};
        }}
        QPushButton:disabled {{
            background-color: {s["bg_surface_elevated"]};
            color: {s["text_muted"]};
            border-color: {s["border_subtle"]};
        }}

        QPushButton#secondaryBtn {{
            background-color: {s["bg_surface_elevated"]};
            color: {s["text_primary"]};
            border: 1px solid {s["border_subtle"]};
            font-weight: 500;
        }}
        QPushButton#secondaryBtn:hover {{
            background-color: {s["bg_surface_hover"]};
            color: {s["text_primary"]};
            border-color: {s["border_medium"]};
        }}
        QPushButton#secondaryBtn:pressed {{
            background-color: {s["border_subtle"]};
        }}

        QPushButton#stopBtn {{
            background-color: {s["status_danger"]};
            color: #ffffff;
            font-weight: 600;
            border: 1px solid {s["status_danger"]};
        }}
        QPushButton#stopBtn:hover {{
            background-color: {s["status_danger_hover"]};
            border-color: {s["status_danger_hover"]};
        }}

        QPushButton#ghostBtn {{
            background-color: transparent;
            color: {s["text_secondary"]};
            border: none;
            padding: 6px 10px;
        }}
        QPushButton#ghostBtn:hover {{
            color: {s["text_primary"]};
            background-color: {s["bg_surface_hover"]};
            border-radius: {cls.RADIUS_SM}px;
        }}

        /* ── Checkboxes ── */
        QCheckBox {{
            color: {s["text_secondary"]};
            font-size: 13px;
            spacing: 8px;
        }}
        QCheckBox:hover {{
            color: {s["text_primary"]};
        }}
        QCheckBox::indicator {{
            width: 17px;
            height: 17px;
            border-radius: 4px;
            border: 1px solid {s["border_medium"]};
            background-color: {input_bg};
        }}
        QCheckBox::indicator:hover {{
            border-color: {s["accent_primary"]};
        }}
        QCheckBox::indicator:checked {{
            background-color: {s["accent_primary"]};
            border: 1px solid {s["accent_primary"]};
        }}

        /* ── Tabelas de Dados (Blocks.so Table) ── */
        QTableWidget {{
            background-color: {s["bg_surface_card"]};
            border: 1px solid {s["border_subtle"]};
            border-radius: {cls.RADIUS_MD}px;
            gridline-color: {s["border_subtle"]};
            color: {s["text_primary"]};
            selection-background-color: {s["bg_surface_hover"]};
            selection-color: {s["text_primary"]};
        }}
        QHeaderView::section {{
            background-color: {s["bg_surface_elevated"]};
            color: {s["text_muted"]};
            padding: 10px 12px;
            font-weight: 700;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border: none;
            border-bottom: 1px solid {s["border_subtle"]};
        }}

        /* ── Terminal / Console de Logs ── */
        QTextEdit {{
            background-color: {input_bg};
            border: 1px solid {s["border_subtle"]};
            border-radius: {cls.RADIUS_MD}px;
            color: {s["text_secondary"]};
            font-family: 'Consolas', 'Cascadia Code', monospace;
            font-size: 12px;
            padding: 8px;
        }}

        /* ── Progress Bars ── */
        QProgressBar {{
            border-radius: 4px;
            background-color: {s["bg_surface_elevated"]};
            border: 1px solid {s["border_subtle"]};
            text-align: center;
            color: {s["text_primary"]};
            font-size: 10px;
            font-weight: bold;
        }}
        QProgressBar::chunk {{
            background-color: {s["accent_primary"]};
            border-radius: 3px;
        }}
        """

    build_stylesheet = get_qss
