# -*- coding: utf-8 -*-
"""
DA-V Glass Design System - QSS das folhas (configuracoes / telemetria)
Autor: Dante Ferraz (MonoTech)

Os paineis tecnicos (TUPA, dispositivos LAN, registros, parametros) usam widgets nativos do
Qt. Este QSS os reveste de vidro: campos translucidos com borda branca, texto claro e
barras de rolagem finas. E aplicado apenas dentro das folhas, sem afetar as telas principais.
"""

from __future__ import annotations

from src.ui.glass import tokens as T

_FAMILIES = ",".join(f"'{f}'" if " " in f else f for f in T.FONT_FAMILIES)


def sheet_qss(scale: float = 1.0) -> str:
    fs = max(12, int(round(19 * scale)))        # tipografia técnica limpa (13px em 1280px)
    fs_small = max(11, int(round(16 * scale)))
    radius = max(8, int(round(14 * scale)))
    btn_radius = max(7, min(12, int(round(11 * scale))))
    pad_v = max(3, int(round(6 * scale)))
    pad_h = max(8, int(round(12 * scale)))
    bw = max(1, int(round(1.6 * scale)))
    txt, dim = T.SHEET_TEXT, T.SHEET_TEXT_DIM
    return f"""
    QWidget {{ background: transparent; color: {txt}; font-family: {_FAMILIES}; font-size: {fs}px; }}
    QLabel {{ background: transparent; color: {txt}; border: none; }}
    QToolTip {{ background: rgb(12,70,90); color: #ffffff; border: 1px solid rgba(255,255,255,0.7); padding: 4px 8px; }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: rgba(255,255,255,0.12);
        border: {bw}px solid rgba(255,255,255,0.76);
        border-radius: {radius}px;
        padding: {pad_v}px {pad_h}px;
        color: #ffffff;
        selection-background-color: rgba(255,255,255,0.35);
        min-height: {max(18, int(round(24 * scale)))}px;
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ background: rgba(255,255,255,0.20); border-color: #ffffff; }}
    QComboBox::drop-down {{ border: none; width: {max(18, int(round(28 * scale)))}px; }}
    QComboBox QAbstractItemView {{
        background: rgb(14,74,94); color: #ffffff; border: 1px solid rgba(255,255,255,0.7);
        selection-background-color: rgba(255,255,255,0.28); outline: none;
    }}
    QSpinBox::up-button, QSpinBox::down-button {{ width: {max(14, int(round(22 * scale)))}px; border: none; background: transparent; }}

    QPushButton {{
        background: rgba(255,255,255,0.12);
        border: {bw}px solid rgba(255,255,255,0.85);
        border-radius: {btn_radius}px;
        padding: {pad_v}px {pad_h + 4}px;
        color: #ffffff; font-weight: 600;
        min-height: {max(20, int(round(26 * scale)))}px;
    }}
    QPushButton:hover {{ background: rgba(255,255,255,0.24); }}
    QPushButton:pressed {{ background: rgba(255,255,255,0.32); }}
    QPushButton:disabled {{ color: rgba(255,255,255,0.45); border-color: rgba(255,255,255,0.35); }}
    QPushButton#stopBtn {{ background: rgba(255,120,120,0.28); border-color: rgba(255,214,214,0.95); }}

    QCheckBox {{ spacing: 10px; background: transparent; }}
    QCheckBox::indicator {{ width: {max(14, int(round(18 * scale)))}px; height: {max(14, int(round(18 * scale)))}px;
        border: {bw}px solid rgba(255,255,255,0.85); border-radius: 5px; background: rgba(255,255,255,0.10); }}
    QCheckBox::indicator:checked {{ background: rgba(134, 239, 172, 0.88); border-color: #ffffff; }}

    QGroupBox {{
        background: rgba(255,255,255,0.06);
        border: {bw}px solid rgba(255,255,255,0.45);
        border-radius: {radius}px;
        margin-top: {max(12, int(round(18 * scale)))}px;
        padding: {max(10, int(round(16 * scale)))}px {max(8, int(round(12 * scale)))}px {max(8, int(round(10 * scale)))}px {max(8, int(round(12 * scale)))}px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: {pad_h}px;
        padding: 1px 8px;
        color: {dim};
        background: rgba(8, 52, 70, 0.84);
        border-radius: 6px;
    }}

    QTextEdit, QPlainTextEdit {{
        background: rgba(2,26,36,0.55);
        border: {bw}px solid rgba(255,255,255,0.45);
        border-radius: {radius}px; padding: 8px; color: {txt};
        font-family: Consolas, 'Cascadia Mono', 'DejaVu Sans Mono', monospace; font-size: {fs_small}px;
    }}

    QTableWidget {{
        background: rgba(2,26,36,0.45);
        border: {bw}px solid rgba(255,255,255,0.45);
        border-radius: {radius}px; gridline-color: rgba(255,255,255,0.18); color: {txt};
        alternate-background-color: rgba(255,255,255,0.05);
        selection-background-color: rgba(255,255,255,0.22);
    }}
    QHeaderView::section {{ background: rgba(255,255,255,0.14); color: {txt}; border: none; padding: 6px 10px; font-weight: 600; }}

    QProgressBar {{ background: rgba(255,255,255,0.14); border: none; border-radius: 6px; text-align: center; color: {txt}; }}
    QProgressBar::chunk {{ background: rgba(255,255,255,0.78); border-radius: 6px; }}

    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.50); border-radius: 4px; min-height: 36px; }}
    QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.78); }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: rgba(255,255,255,0.50); border-radius: 4px; min-width: 36px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
    """

