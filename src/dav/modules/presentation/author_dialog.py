# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Diálogo "Sobre o Autor & Tecnologias" (Appropriate Legal Notices - GNU AGPLv3 Seção 5(d) & 7(b)) — DA-V
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.ui.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTabWidget, QTextEdit, QWidget, Qt, QFont
)
from src.ui.theme import Theme
from src.dav.modules.commercial.author_showcase import get_author_showcase
from src.dav.modules.commercial.license_verifier import LicenseVerifier


class AuthorShowcaseDialog(QDialog):
    """
    Diálogo institucional apresentando os Avisos Legais Apropriados (Seção 5(d)
    e Seção 7(b) da GNU AGPLv3): autoria de Dante Ferraz (MonoTech), arquivo
    NOTICE obrigatório e licenças de componentes de terceiros.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sobre o Autor & Tecnologias — DA-V")
        self.setFixedSize(620, 560)
        self.setModal(True)
        self._verifier = LicenseVerifier()
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {Theme.SYS["bg_canvas"]};
                color: {Theme.SYS["text_primary"]};
                font-family: 'Segoe UI', Inter, sans-serif;
            }}
            QLabel {{
                color: {Theme.SYS["text_primary"]};
            }}
            QTabWidget::pane {{
                border: 1px solid {Theme.SYS["border_subtle"]};
                background-color: {Theme.SYS["bg_surface"]};
                border-radius: 6px;
            }}
            QTabBar::tab {{
                background-color: {Theme.SYS["bg_surface_elevated"]};
                color: {Theme.SYS["text_secondary"]};
                padding: 8px 14px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: 600;
                font-size: 12px;
            }}
            QTabBar::tab:selected {{
                background-color: {Theme.SYS["accent_primary"]};
                color: #070a0f;
                font-weight: 700;
            }}
            QTextEdit {{
                background-color: {Theme.SYS["bg_canvas"]};
                color: {Theme.SYS["text_secondary"]};
                border: 1px solid {Theme.SYS["border_subtle"]};
                border-radius: 6px;
                padding: 10px;
                font-family: Consolas, 'JetBrains Mono', monospace;
                font-size: 11px;
            }}
        """)
        self._init_ui()

    def _init_ui(self):
        meta = get_author_showcase()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # ── Cabeçalho com Badge SPDX ──
        header_layout = QHBoxLayout()
        lbl_badge = QLabel(f"MONOTECH OPEN-TECH · {meta['license_spdx']}")
        lbl_badge.setStyleSheet(f"""
            background: {Theme.SYS["accent_primary"]};
            color: #070a0f;
            font-weight: 800;
            font-size: 11px;
            padding: 4px 10px;
            border-radius: 4px;
        """)
        header_layout.addWidget(lbl_badge)
        header_layout.addStretch()

        from src.dav import __version__ as _dav_ver
        lbl_ver = QLabel(f"DA-V v{_dav_ver}")
        lbl_ver.setStyleSheet(f"color: {Theme.SYS['text_muted']}; font-weight: 600; font-size: 12px;")
        header_layout.addWidget(lbl_ver)
        layout.addLayout(header_layout)

        # ── Título & Autor ──
        lbl_title = QLabel("Distribuidor Amplo de Vídeo")
        lbl_title.setStyleSheet("font-size: 20px; font-weight: 800; margin-top: 2px;")
        layout.addWidget(lbl_title)

        lbl_author = QLabel(
            f"Autor & Arquiteto Principal: <b>{meta['author_name']}</b> ({meta['organization']}) · "
            f"<span style='font-size:11px;'>{meta['copyright_notice']}</span>"
        )
        lbl_author.setStyleSheet(f"font-size: 13px; color: {Theme.SYS['text_accent']};")
        layout.addWidget(lbl_author)

        # ── Abas: Autoria, NOTICE (Seção 7) e Licenças de Terceiros ──
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_tab_author(meta), "Autoria & Ecossistema")
        self.tabs.addTab(self._build_tab_notice(meta), "Licença & NOTICE (Seção 7)")
        self.tabs.addTab(self._build_tab_third_party(), "Licenças de Terceiros")
        layout.addWidget(self.tabs, 1)

        # ── Botão Fechar ──
        btn_close = QPushButton("Fechar", self)
        btn_close.setFixedHeight(36)
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.SYS["accent_primary"]};
                color: #070a0f;
                font-weight: 700;
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {Theme.SYS["accent_primary_hover"]};
            }}
        """)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def _build_tab_author(self, meta: dict) -> QWidget:
        tab = QWidget()
        t_lay = QVBoxLayout(tab)
        t_lay.setContentsMargins(14, 14, 14, 14)
        t_lay.setSpacing(12)

        box_mission = QFrame()
        box_mission.setStyleSheet(f"""
            QFrame {{
                background-color: {Theme.SYS["bg_canvas"]};
                border: 1px solid {Theme.SYS["border_subtle"]};
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        m_layout = QVBoxLayout(box_mission)
        m_layout.setContentsMargins(10, 8, 10, 8)
        lbl_m_title = QLabel("Edição 100% Gratuita & Aberta (GNU AGPLv3 + Seção 7)")
        lbl_m_title.setStyleSheet(f"font-weight: 700; color: {Theme.SYS['status_success']}; font-size: 13px;")
        lbl_m_desc = QLabel(
            "Esta aplicação é disponibilizada 100% gratuitamente e sem chaves de ativação para "
            "democratizar o acesso a streaming P2P de ultra-baixa latência (até 4K 120 FPS). "
            f"{meta['section7_summary']}"
        )
        lbl_m_desc.setWordWrap(True)
        lbl_m_desc.setStyleSheet(f"color: {Theme.SYS['text_secondary']}; font-size: 12px; margin-top: 4px;")
        m_layout.addWidget(lbl_m_title)
        m_layout.addWidget(lbl_m_desc)
        t_lay.addWidget(box_mission)

        lbl_eco = QLabel("Ecossistema Tecnológico Dante Ferraz:")
        lbl_eco.setStyleSheet("font-weight: 700; font-size: 13px;")
        t_lay.addWidget(lbl_eco)

        box_eco = QFrame()
        box_eco.setStyleSheet(f"""
            QFrame {{
                background-color: {Theme.SYS["bg_surface_elevated"]};
                border-radius: 6px;
                padding: 8px;
            }}
        """)
        eco_layout = QVBoxLayout(box_eco)
        eco_layout.setContentsMargins(10, 8, 10, 8)
        eco_layout.setSpacing(5)
        for proj in meta["ecosystem"]:
            lbl_item = QLabel(f"• <b>{proj['name']}</b>: {proj['desc']}")
            lbl_item.setStyleSheet(f"font-size: 11px; color: {Theme.SYS['text_secondary']};")
            eco_layout.addWidget(lbl_item)
        t_lay.addWidget(box_eco)
        t_lay.addStretch(1)
        return tab

    def _build_tab_notice(self, meta: dict) -> QWidget:
        tab = QWidget()
        t_lay = QVBoxLayout(tab)
        t_lay.setContentsMargins(12, 12, 12, 12)
        t_lay.setSpacing(8)

        lbl_info = QLabel(f"<b>{meta['license_name']}</b>")
        lbl_info.setWordWrap(True)
        lbl_info.setStyleSheet(f"font-size: 12px; color: {Theme.SYS['text_primary']};")
        t_lay.addWidget(lbl_info)

        self.txt_notice = QTextEdit(tab)
        self.txt_notice.setReadOnly(True)
        self.txt_notice.setPlainText(self._verifier.get_notice_text())
        t_lay.addWidget(self.txt_notice, 1)
        return tab

    def _build_tab_third_party(self) -> QWidget:
        tab = QWidget()
        t_lay = QVBoxLayout(tab)
        t_lay.setContentsMargins(12, 12, 12, 12)
        t_lay.setSpacing(8)

        lbl_info = QLabel("Componentes de código aberto utilizados (PySide6/Qt6, FFmpeg, x264, KCP, OpenSSL):")
        lbl_info.setWordWrap(True)
        lbl_info.setStyleSheet(f"font-size: 12px; color: {Theme.SYS['text_primary']};")
        t_lay.addWidget(lbl_info)

        self.txt_third_party = QTextEdit(tab)
        self.txt_third_party.setReadOnly(True)
        self.txt_third_party.setPlainText(self._verifier.get_third_party_notices())
        t_lay.addWidget(self.txt_third_party, 1)
        return tab
