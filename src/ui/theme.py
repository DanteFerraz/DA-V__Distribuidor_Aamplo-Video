# -*- coding: utf-8 -*-
"""
DA-V UI Design System & Tokens (Multi-tier Tokenization)
Adere estritamente às diretrizes da skill ui-engineering-antigravity-skill.

Camadas:
1. Reference Tokens (ref): Cores brutas e primitivos
2. System Tokens (sys): Papeis funcionais e semânticos (superfície, acento, status)
3. Component Tokens (comp) & QSS: Estilos aplicados aos componentes Qt
"""

class Theme:
    # ── 1. REFERENCE TOKENS (Paleta Bruta) ──────────────────────────────────
    REF = {
        # Neutros Escuros (Obsidian / Slate)
        "neutral_950": "#070a0f",
        "neutral_900": "#0b0f19",
        "neutral_850": "#0f1523",
        "neutral_800": "#151d30",
        "neutral_750": "#1c263d",
        "neutral_700": "#24324f",
        "neutral_600": "#3b4d71",
        "neutral_500": "#64748b",
        "neutral_400": "#94a3b8",
        "neutral_300": "#cbd5e1",
        "neutral_200": "#e2e8f0",
        "neutral_100": "#f1f5f9",
        "neutral_50":  "#f8fafc",

        # Cores de Acento & Status
        "cyan_400":    "#38bdf8",
        "cyan_500":    "#0ea5e9",
        "cyan_600":    "#0284c7",
        "emerald_400": "#34d399",
        "emerald_500": "#10b981",
        "emerald_600": "#059669",
        "amber_400":   "#fbbf24",
        "amber_500":   "#f59e0b",
        "rose_400":    "#f87171",
        "rose_500":    "#ef4444",
        "rose_600":    "#dc2626",
        "violet_400":  "#a78bfa",
        "violet_500":  "#8b5cf6",
        "indigo_500":  "#6366f1",
    }

    # ── 2. SYSTEM TOKENS (Papeis Semânticos) ────────────────────────────────
    SYS = {
        # Superfícies
        "bg_canvas":            REF["neutral_950"],
        "bg_surface":           REF["neutral_900"],
        "bg_surface_card":      REF["neutral_850"],
        "bg_surface_elevated":  REF["neutral_800"],
        "bg_surface_hover":     REF["neutral_750"],

        # Bordas e Linhas de Separação
        "border_subtle":        REF["neutral_800"],
        "border_medium":        REF["neutral_700"],
        "border_active":        REF["cyan_500"],
        "border_focus":         REF["cyan_400"],

        # Textos
        "text_primary":         REF["neutral_50"],
        "text_secondary":       REF["neutral_300"],
        "text_muted":           REF["neutral_500"],
        "text_accent":          REF["cyan_400"],

        # Ações & Status
        "accent_primary":       REF["cyan_500"],
        "accent_primary_hover": REF["cyan_400"],
        "accent_primary_active":REF["cyan_600"],
        "status_success":       REF["emerald_500"],
        "status_success_bg":    "#06281e",
        "status_warning":       REF["amber_500"],
        "status_warning_bg":    "#2e1804",
        "status_danger":        REF["rose_500"],
        "status_danger_hover":  REF["rose_600"],
        "status_danger_bg":     "#2a0a0f",
        "status_info":          REF["violet_400"],
    }

    # ── 3. ESPAÇAMENTO E GEOMETRIA (Múltiplos de 4pt / 8pt) ─────────────────
    SPACE_XXS = 2
    SPACE_XS  = 4
    SPACE_SM  = 8
    SPACE_MD  = 12
    SPACE_LG  = 16
    SPACE_XL  = 24
    SPACE_2XL = 32

    RADIUS_SM = 4
    RADIUS_MD = 6
    RADIUS_LG = 10
    RADIUS_XL = 14

    @classmethod
    def get_qss(cls) -> str:
        """Gera a folha de estilos global do DA-V com Dark Theme profissional."""
        s = cls.SYS
        return f"""
        /* ── Estilos Globais da Janela ── */
        QMainWindow {{
            background-color: {s["bg_canvas"]};
            color: {s["text_primary"]};
            font-family: 'Segoe UI', Arial, sans-serif;
        }}

        QWidget {{
            color: {s["text_primary"]};
            background-color: transparent;
            font-family: 'Segoe UI', Arial, sans-serif;
            font-size: 13px;
        }}

        /* ── Scrollbars Finos e Estilizados ── */
        QScrollBar:vertical {{
            border: none;
            background: {s["bg_surface"]};
            width: 8px;
            margin: 0px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: {s["border_medium"]};
            min-height: 24px;
            border-radius: 4px;
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
            height: 8px;
            margin: 0px;
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal {{
            background: {s["border_medium"]};
            min-width: 24px;
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {s["accent_primary"]};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}

        /* ── GroupBox / Cards ── */
        QGroupBox {{
            font-weight: 700;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border: 1px solid {s["border_subtle"]};
            border-radius: {cls.RADIUS_MD}px;
            margin-top: 14px;
            padding-top: 18px;
            background-color: {s["bg_surface_card"]};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 6px;
            color: {s["text_accent"]};
            background-color: {s["bg_surface_card"]};
            border-radius: 3px;
        }}

        /* ── Campos de Entrada (Inputs, SpinBox, Combo) ── */
        QLineEdit, QSpinBox, QComboBox {{
            background-color: {s["bg_canvas"]};
            border: 1px solid {s["border_subtle"]};
            border-radius: {cls.RADIUS_MD}px;
            padding: 7px 12px;
            color: {s["text_primary"]};
            font-size: 13px;
            min-height: 20px;
            selection-background-color: {s["accent_primary"]};
        }}
        QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{
            border: 1px solid {s["border_medium"]};
        }}
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
            border: 1px solid {s["border_focus"]};
            background-color: #0c121e;
        }}
        QLineEdit:read-only {{
            color: {s["text_secondary"]};
            background-color: {s["bg_surface"]};
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

        /* ── Botões Primários, Secundários e de Ação ── */
        QPushButton {{
            background-color: {s["accent_primary"]};
            color: #070a0f;
            font-weight: 700;
            border-radius: {cls.RADIUS_MD}px;
            padding: 8px 18px;
            font-size: 13px;
            border: none;
            outline: none;
            min-height: 20px;
        }}
        QPushButton:hover {{
            background-color: {s["accent_primary_hover"]};
        }}
        QPushButton:pressed {{
            background-color: {s["accent_primary_active"]};
        }}
        QPushButton:disabled {{
            background-color: {s["bg_surface_elevated"]};
            color: {s["text_muted"]};
        }}

        QPushButton#secondaryBtn {{
            background-color: {s["bg_surface_elevated"]};
            color: {s["text_secondary"]};
            border: 1px solid {s["border_subtle"]};
            font-weight: 600;
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
            font-weight: 700;
        }}
        QPushButton#stopBtn:hover {{
            background-color: {s["status_danger_hover"]};
        }}

        QPushButton#ghostBtn {{
            background-color: transparent;
            color: {s["text_secondary"]};
            border: none;
            padding: 4px 8px;
        }}
        QPushButton#ghostBtn:hover {{
            color: {s["text_accent"]};
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
            width: 18px;
            height: 18px;
            border-radius: 4px;
            border: 1px solid {s["border_medium"]};
            background-color: {s["bg_canvas"]};
        }}
        QCheckBox::indicator:hover {{
            border-color: {s["accent_primary"]};
        }}
        QCheckBox::indicator:checked {{
            background-color: {s["accent_primary"]};
            border: 1px solid {s["accent_primary"]};
        }}

        /* ── Tabelas de Dados ── */
        QTableWidget {{
            background-color: {s["bg_canvas"]};
            border: 1px solid {s["border_subtle"]};
            border-radius: {cls.RADIUS_MD}px;
            gridline-color: {s["border_subtle"]};
            color: {s["text_primary"]};
            selection-background-color: {s["bg_surface_hover"]};
            selection-color: {s["text_primary"]};
        }}
        QHeaderView::section {{
            background-color: {s["bg_surface_card"]};
            color: {s["text_muted"]};
            padding: 10px 12px;
            font-weight: 700;
            font-size: 11px;
            text-transform: uppercase;
            border: none;
            border-bottom: 1px solid {s["border_subtle"]};
        }}

        /* ── Terminal / Console de Logs ── */
        QTextEdit {{
            background-color: {s["bg_canvas"]};
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
            background-color: {s["bg_canvas"]};
            text-align: center;
            color: {s["text_primary"]};
            font-size: 10px;
            font-weight: bold;
        }}
        QProgressBar::chunk {{
            background-color: {s["accent_primary"]};
            border-radius: 4px;
        }}
        """

    build_stylesheet = get_qss
