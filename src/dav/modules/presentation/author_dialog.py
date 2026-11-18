# -*- coding: utf-8 -*-
"""
Diálogo "Sobre o Autor & Tecnologias" — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.ui.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, Qt, QFont
)
from src.ui.theme import Theme
from src.dav.modules.commercial.author_showcase import get_author_showcase
from src.dav.modules.commercial.edition_policy import COMMUNITY_CAPABILITIES


class AuthorShowcaseDialog(QDialog):
    """
    Diálogo institucional apresentando a autoria de Dante Ferraz, a arquitetura
    MonoTech e o ecossistema autoral 100% gratuito e aberto.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sobre o Autor & Tecnologias — DA-V")
        self.setFixedSize(560, 520)
        self.setModal(True)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {Theme.SYS["bg_canvas"]};
                color: {Theme.SYS["text_primary"]};
                font-family: 'Segoe UI', Inter, sans-serif;
            }}
            QLabel {{
                color: {Theme.SYS["text_primary"]};
            }}
        """)
        self._init_ui()

    def _init_ui(self):
        meta = get_author_showcase()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # ── Cabeçalho com Badge ──
        header_layout = QHBoxLayout()
        lbl_badge = QLabel("MONOTECH OPEN-TECH")
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
        lbl_title.setStyleSheet("font-size: 20px; font-weight: 800; margin-top: 4px;")
        layout.addWidget(lbl_title)

        lbl_author = QLabel(f"Autor & Arquiteto Principal: <b>{meta['author_name']}</b> ({meta['organization']})")
        lbl_author.setStyleSheet(f"font-size: 14px; color: {Theme.SYS['text_accent']};")
        layout.addWidget(lbl_author)

        # ── Filosofia / Missão ──
        box_mission = QFrame()
        box_mission.setStyleSheet(f"""
            QFrame {{
                background-color: {Theme.SYS["bg_surface"]};
                border: 1px solid {Theme.SYS["border_subtle"]};
                border-radius: 8px;
                padding: 12px;
            }}
        """)
        m_layout = QVBoxLayout(box_mission)
        m_layout.setContentsMargins(12, 10, 12, 10)
        lbl_m_title = QLabel("Edição 100% Gratuita & Aberta")
        lbl_m_title.setStyleSheet(f"font-weight: 700; color: {Theme.SYS['status_success']}; font-size: 13px;")
        lbl_m_desc = QLabel(
            "Esta aplicação é disponibilizada gratuitamente para democratizar o acesso a streaming de "
            "ultra-baixa latência e alto desempenho (até 4K 120 FPS sem paywalls ou limites de sessão)."
        )
        lbl_m_desc.setWordWrap(True)
        lbl_m_desc.setStyleSheet(f"color: {Theme.SYS['text_secondary']}; font-size: 12px; margin-top: 4px;")
        m_layout.addWidget(lbl_m_title)
        m_layout.addWidget(lbl_m_desc)
        layout.addWidget(box_mission)

        # ── Ecossistema Autoral ──
        lbl_eco = QLabel("Ecossistema Tecnológico Dante Ferraz:")
        lbl_eco.setStyleSheet("font-weight: 700; font-size: 13px; margin-top: 6px;")
        layout.addWidget(lbl_eco)

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
        eco_layout.setSpacing(6)

        for proj in meta["ecosystem"]:
            lbl_item = QLabel(f"• <b>{proj['name']}</b>: {proj['desc']}")
            lbl_item.setStyleSheet(f"font-size: 11px; color: {Theme.SYS['text_secondary']};")
            eco_layout.addWidget(lbl_item)
        layout.addWidget(box_eco)

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
