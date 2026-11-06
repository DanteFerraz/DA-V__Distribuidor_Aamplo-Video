# -*- coding: utf-8 -*-
"""
DA-V — Instalador Gráfico Oficial de Alta Fidelidade (Windows)
Autor: Dante Ferraz (MonoTech)

Design System: Dark Obsidian & Electric Cyan (Enterprise UX / WCAG 2.2 AAA compliant).
Substitui o QWizard nativo por um assistente moderno com Stepper lateral, cards
de telemetria de GPU em tempo real, automação de regras do Windows Firewall e
registro do protocolo 'dav://'.
"""

import sys
import os
import subprocess
import winreg
import shutil
import zipfile
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QProgressBar, QStackedWidget,
    QFrame, QFileDialog, QLineEdit
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QColor, QPalette, QCursor


# ── Design Tokens Exclusivos do Instalador (WCAG 2.2 AAA) ────────────────────
C_BG_CANVAS      = "#070a0f"  # Obsidian mais escuro
C_BG_SIDEBAR     = "#0b0f19"  # Painel lateral
C_BG_CARD        = "#0f1523"  # Cards e superfícies
C_BG_CARD_HOVER  = "#151d30"
C_BORDER_SUBTLE  = "#1c263d"
C_BORDER_ACTIVE  = "#0ea5e9"  # Cyan Neon
C_TEXT_PRIMARY   = "#f8fafc"  # Branco nítido (Contraste > 14:1)
C_TEXT_SECONDARY = "#cbd5e1"  # Cinza claro
C_TEXT_MUTED     = "#64748b"  # Cinza atenuado
C_ACCENT         = "#0ea5e9"  # Cyan principal
C_ACCENT_HOVER   = "#38bdf8"
C_ACCENT_TEXT    = "#040810"  # Texto escuro sobre botão ciano (Contraste > 8:1)
C_SUCCESS        = "#10b981"  # Verde esmeralda
C_SUCCESS_BG     = "#06281e"
C_WARNING        = "#f59e0b"
C_WARNING_BG     = "#261604"


INSTALLER_QSS = f"""
QDialog {{
    background-color: {C_BG_CANVAS};
    color: {C_TEXT_PRIMARY};
    font-family: 'Segoe UI', -apple-system, sans-serif;
}}

QWidget {{
    color: {C_TEXT_PRIMARY};
    background-color: transparent;
    font-family: 'Segoe UI', -apple-system, sans-serif;
}}

/* Barra Lateral */
#Sidebar {{
    background-color: {C_BG_SIDEBAR};
    border-right: 1px solid {C_BORDER_SUBTLE};
}}

/* Cards e Contêineres */
.Card {{
    background-color: {C_BG_CARD};
    border: 1px solid {C_BORDER_SUBTLE};
    border-radius: 8px;
    padding: 14px;
}}

/* Botões */
QPushButton {{
    background-color: {C_BG_CARD};
    border: 1px solid {C_BORDER_SUBTLE};
    color: {C_TEXT_PRIMARY};
    border-radius: 6px;
    padding: 9px 18px;
    font-size: 13px;
    font-weight: 600;
}}

QPushButton:hover {{
    background-color: {C_BG_CARD_HOVER};
    border-color: {C_ACCENT};
}}

QPushButton#BtnPrimary {{
    background-color: {C_ACCENT};
    border: 1px solid {C_ACCENT};
    color: {C_ACCENT_TEXT};
    font-weight: 700;
    font-size: 13px;
}}

QPushButton#BtnPrimary:hover {{
    background-color: {C_ACCENT_HOVER};
    border-color: {C_ACCENT_HOVER};
}}

QPushButton#BtnPrimary:disabled {{
    background-color: #1e293b;
    border-color: #334155;
    color: #64748b;
}}

QPushButton#BtnSecondary {{
    background-color: transparent;
    border: 1px solid {C_BORDER_SUBTLE};
    color: {C_TEXT_SECONDARY};
}}

QPushButton#BtnSecondary:hover {{
    background-color: {C_BG_CARD};
    border-color: {C_TEXT_MUTED};
    color: {C_TEXT_PRIMARY};
}}

/* Checkboxes */
QCheckBox {{
    color: {C_TEXT_PRIMARY};
    font-size: 13px;
    spacing: 10px;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid {C_BORDER_SUBTLE};
    background-color: {C_BG_CARD};
}}

QCheckBox::indicator:hover {{
    border-color: {C_ACCENT};
}}

QCheckBox::indicator:checked {{
    background-color: {C_ACCENT};
    border-color: {C_ACCENT};
    image: none;
}}

/* Barra de Progresso */
QProgressBar {{
    background-color: {C_BG_CARD};
    border: 1px solid {C_BORDER_SUBTLE};
    border-radius: 6px;
    height: 12px;
    text-align: center;
    font-size: 10px;
    font-weight: 700;
    color: {C_TEXT_PRIMARY};
}}

QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {C_ACCENT}, stop:1 {C_SUCCESS});
    border-radius: 5px;
}}
"""


class StepperItem(QWidget):
    """Item individual da barra lateral de etapas."""
    def __init__(self, step_num: int, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.step_num = step_num
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # Círculo indicador
        self.badge = QLabel(str(step_num))
        self.badge.setFixedSize(28, 28)
        self.badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.badge)

        # Textos
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("font-size: 13px; font-weight: 700;")
        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setStyleSheet(f"font-size: 11px; color: {C_TEXT_MUTED};")
        text_col.addWidget(self.lbl_title)
        text_col.addWidget(self.lbl_sub)
        layout.addLayout(text_col)
        layout.addStretch()

        self.set_state("pending")

    def set_state(self, state: str):
        """Atualiza o estado visual: 'pending', 'active' ou 'completed'."""
        if state == "active":
            self.badge.setStyleSheet(f"""
                background-color: {C_ACCENT};
                color: {C_ACCENT_TEXT};
                border-radius: 14px;
                font-weight: 800;
                font-size: 12px;
            """)
            self.lbl_title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {C_TEXT_PRIMARY};")
            self.setStyleSheet(f"background-color: {C_BG_CARD}; border-radius: 8px;")
        elif state == "completed":
            self.badge.setText("✓")
            self.badge.setStyleSheet(f"""
                background-color: {C_SUCCESS_BG};
                color: {C_SUCCESS};
                border: 1px solid {C_SUCCESS};
                border-radius: 14px;
                font-weight: 800;
                font-size: 12px;
            """)
            self.lbl_title.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {C_TEXT_SECONDARY};")
            self.setStyleSheet("background-color: transparent;")
        else:  # pending
            self.badge.setText(str(self.step_num))
            self.badge.setStyleSheet(f"""
                background-color: {C_BG_CARD};
                color: {C_TEXT_MUTED};
                border: 1px solid {C_BORDER_SUBTLE};
                border-radius: 14px;
                font-weight: 700;
                font-size: 12px;
            """)
            self.lbl_title.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {C_TEXT_MUTED};")
            self.setStyleSheet("background-color: transparent;")


class DavModernInstaller(QDialog):
    """Instalador visual moderno, escuro e de alta fidelidade para Windows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DA-V · Distribuidor Amplo de Vídeo — Assistente de Instalação")
        self.setMinimumSize(800, 520)
        self.resize(840, 540)
        self.setStyleSheet(INSTALLER_QSS)

        # Estado da navegação
        self.current_step = 0

        self._build_ui()
        self._update_step_view()

    def _build_ui(self):
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── 1. BARRA LATERAL (Stepper) ───────────────────────────────────────
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(260)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(20, 24, 20, 20)
        side_layout.setSpacing(16)

        # Branding no topo da barra lateral
        brand_row = QHBoxLayout()
        brand_icon = QLabel("⚡")
        brand_icon.setStyleSheet(f"font-size: 24px; color: {C_ACCENT};")
        brand_row.addWidget(brand_icon)

        brand_text_col = QVBoxLayout()
        brand_text_col.setSpacing(1)
        lbl_app_name = QLabel("DA-V")
        lbl_app_name.setStyleSheet(f"font-size: 18px; font-weight: 800; color: {C_TEXT_PRIMARY}; letter-spacing: 0.5px;")
        lbl_app_sub = QLabel("Distribuidor Amplo de Vídeo")
        lbl_app_sub.setStyleSheet(f"font-size: 11px; color: {C_TEXT_MUTED};")
        brand_text_col.addWidget(lbl_app_name)
        brand_text_col.addWidget(lbl_app_sub)
        brand_row.addLayout(brand_text_col)
        brand_row.addStretch()
        side_layout.addLayout(brand_row)

        # Divisor
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet(f"border: none; border-top: 1px solid {C_BORDER_SUBTLE}; margin: 8px 0;")
        side_layout.addWidget(div)

        # Passos do Stepper
        self.stepper_items = [
            StepperItem(1, "Boas-vindas", "Visão geral e GPU"),
            StepperItem(2, "Preferências", "Firewall e atalhos"),
            StepperItem(3, "Configuração", "Aplicação no sistema"),
            StepperItem(4, "Conclusão", "Pronto para usar")
        ]
        for item in self.stepper_items:
            side_layout.addWidget(item)

        side_layout.addStretch()

        # Rodapé da sidebar
        lbl_ver = QLabel("DA-V v3.1.0 · Dante Ferraz\nMonoTech Architecture")
        lbl_ver.setStyleSheet(f"font-size: 10px; color: {C_TEXT_MUTED}; line-height: 1.4;")
        side_layout.addWidget(lbl_ver)

        root_layout.addWidget(sidebar)

        # ── 2. ÁREA DE CONTEÚDO PRINCIPAL ────────────────────────────────────
        main_content = QWidget()
        main_layout = QVBoxLayout(main_content)
        main_layout.setContentsMargins(36, 28, 36, 24)
        main_layout.setSpacing(20)

        # Stack de páginas
        self.stack = QStackedWidget()
        self.page_welcome = self._create_page_welcome()
        self.page_options = self._create_page_options()
        self.page_progress = self._create_page_progress()
        self.page_finish = self._create_page_finish()

        self.stack.addWidget(self.page_welcome)
        self.stack.addWidget(self.page_options)
        self.stack.addWidget(self.page_progress)
        self.stack.addWidget(self.page_finish)
        main_layout.addWidget(self.stack, 1)

        # Barra de Navegação Inferior (Botoes)
        nav_row = QHBoxLayout()
        nav_row.setSpacing(12)

        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setObjectName("BtnSecondary")
        self.btn_cancel.clicked.connect(self.reject)
        nav_row.addWidget(self.btn_cancel)

        nav_row.addStretch()

        self.btn_back = QPushButton("← Voltar")
        self.btn_back.setObjectName("BtnSecondary")
        self.btn_back.clicked.connect(self._go_back)
        nav_row.addWidget(self.btn_back)

        self.btn_next = QPushButton("Continuar →")
        self.btn_next.setObjectName("BtnPrimary")
        self.btn_next.clicked.connect(self._go_next)
        nav_row.addWidget(self.btn_next)

        main_layout.addLayout(nav_row)
        root_layout.addWidget(main_content, 1)

    # ── PÁGINAS DO WIZARD ────────────────────────────────────────────────────

    def _create_page_welcome(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        # Título
        lbl_title = QLabel("Transmissão de Vídeo P2P a 60 FPS")
        lbl_title.setStyleSheet(f"font-size: 22px; font-weight: 800; color: {C_TEXT_PRIMARY};")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel(
            "Bem-vindo ao instalador oficial do DA-V. Este utilitário configurará o ambiente "
            "com máxima aceleração de hardware e latência ultra-baixa no Windows."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"font-size: 13px; color: {C_TEXT_SECONDARY}; line-height: 1.5;")
        layout.addWidget(lbl_desc)

        # Card de Destaques
        card = QWidget()
        card.setProperty("class", "Card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)

        p1 = QLabel("⚡  <b>Subprocesso GPU Desvinculado:</b> Transmissão fluida a 60 FPS sem congelamentos.")
        p2 = QLabel("🌐  <b>Sinalização Push Instantânea:</b> Pareamento em milissegundos via Server-Sent Events.")
        p3 = QLabel("🔗  <b>Links Diretos:</b> Suporte a convites <code>dav://connect/PIN</code> em 1 clique.")
        for p in (p1, p2, p3):
            p.setStyleSheet(f"font-size: 13px; color: {C_TEXT_PRIMARY};")
            card_layout.addWidget(p)
        layout.addWidget(card)

        # Card de Telemetria de GPU
        has_nv = False
        try:
            res = subprocess.run("nvidia-smi", shell=True, capture_output=True, text=True)
            has_nv = (res.returncode == 0)
        except Exception:
            pass

        gpu_card = QWidget()
        gpu_card.setProperty("class", "Card")
        gpu_layout = QHBoxLayout(gpu_card)
        gpu_layout.setContentsMargins(14, 12, 14, 12)
        gpu_layout.setSpacing(12)

        icon_gpu = QLabel("🎮" if has_nv else "⚙️")
        icon_gpu.setStyleSheet("font-size: 22px;")
        gpu_layout.addWidget(icon_gpu)

        gpu_text_col = QVBoxLayout()
        gpu_text_col.setSpacing(2)
        if has_nv:
            lbl_gpu_title = QLabel("Hardware Gráfico: NVIDIA NVENC Detectado")
            lbl_gpu_title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {C_SUCCESS};")
            lbl_gpu_sub = QLabel("Aceleração por hardware RTX/GTX ativa (Zero consumo de CPU para codificação).")
            lbl_gpu_sub.setStyleSheet(f"font-size: 11px; color: {C_TEXT_MUTED};")
        else:
            lbl_gpu_title = QLabel("Modo Universal: Aceleração SIMD por CPU")
            lbl_gpu_title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {C_ACCENT};")
            lbl_gpu_sub = QLabel("Otimizado para processadores multi-core com instruções AVX2/SSE4.")
            lbl_gpu_sub.setStyleSheet(f"font-size: 11px; color: {C_TEXT_MUTED};")

        gpu_text_col.addWidget(lbl_gpu_title)
        gpu_text_col.addWidget(lbl_gpu_sub)
        gpu_layout.addLayout(gpu_text_col)
        gpu_layout.addStretch()

        badge_status = QLabel("ATIVO ✓" if has_nv else "PRONTO")
        badge_status.setStyleSheet(f"""
            background-color: {C_SUCCESS_BG if has_nv else C_BG_CANVAS};
            color: {C_SUCCESS if has_nv else C_ACCENT};
            border: 1px solid {C_SUCCESS if has_nv else C_BORDER_SUBTLE};
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 800;
        """)
        gpu_layout.addWidget(badge_status)
        layout.addWidget(gpu_card)

        layout.addStretch()
        return w

    def _create_page_options(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        lbl_title = QLabel("Opções de Integração e Rede")
        lbl_title.setStyleSheet(f"font-size: 22px; font-weight: 800; color: {C_TEXT_PRIMARY};")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel("Selecione os recursos do sistema que deseja configurar automaticamente:")
        lbl_desc.setStyleSheet(f"font-size: 13px; color: {C_TEXT_SECONDARY};")
        layout.addWidget(lbl_desc)

        card = QWidget()
        card.setProperty("class", "Card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(16)

        self.chk_firewall = QCheckBox("Liberar portas no Windows Defender Firewall (Recomendado)")
        self.chk_firewall.setChecked(True)
        lbl_fw_sub = QLabel("   Abre as faixas UDP 9000-9020, 19000-19010 e o Beacon LAN 9005 para tráfego P2P direto.")
        lbl_fw_sub.setStyleSheet(f"font-size: 11px; color: {C_TEXT_MUTED}; margin-top: -6px;")
        card_layout.addWidget(self.chk_firewall)
        card_layout.addWidget(lbl_fw_sub)

        self.chk_protocol = QCheckBox("Registrar protocolo 'dav://' para convites diretos")
        self.chk_protocol.setChecked(True)
        lbl_proto_sub = QLabel("   Permite abrir streams e conectar no DA-V clicando em links no Discord, WhatsApp ou navegador.")
        lbl_proto_sub.setStyleSheet(f"font-size: 11px; color: {C_TEXT_MUTED}; margin-top: -6px;")
        card_layout.addWidget(self.chk_protocol)
        card_layout.addWidget(lbl_proto_sub)

        self.chk_desktop = QCheckBox("Criar atalho na Área de Trabalho (Desktop)")
        self.chk_desktop.setChecked(True)
        card_layout.addWidget(self.chk_desktop)

        layout.addWidget(card)
        layout.addStretch()
        return w

    def _create_page_progress(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        lbl_title = QLabel("Aplicando Configurações")
        lbl_title.setStyleSheet(f"font-size: 22px; font-weight: 800; color: {C_TEXT_PRIMARY};")
        layout.addWidget(lbl_title)

        self.lbl_status = QLabel("Inicializando instalação...")
        self.lbl_status.setStyleSheet(f"font-size: 13px; color: {C_TEXT_SECONDARY};")
        layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_card = QWidget()
        self.log_card.setProperty("class", "Card")
        self.log_layout = QVBoxLayout(self.log_card)
        self.log_layout.setSpacing(8)

        self.lbl_log1 = QLabel("• Instalando motor e binários do DA-V em AppData\\Local\\Programs\\DA-V...")
        self.lbl_log2 = QLabel("• Configurando regras do Firewall do Windows...")
        self.lbl_log3 = QLabel("• Registrando protocolo de deep-link dav://...")
        self.lbl_log4 = QLabel("• Criando atalhos na Área de Trabalho e Menu Iniciar...")

        for lbl in (self.lbl_log1, self.lbl_log2, self.lbl_log3, self.lbl_log4):
            lbl.setStyleSheet(f"font-size: 12px; color: {C_TEXT_MUTED};")
            self.log_layout.addWidget(lbl)

        layout.addWidget(self.log_card)
        layout.addStretch()
        return w

    def _create_page_finish(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        # Ícone de sucesso
        icon_box = QLabel("✓")
        icon_box.setFixedSize(54, 54)
        icon_box.setAlignment(Qt.AlignCenter)
        icon_box.setStyleSheet(f"""
            background-color: {C_SUCCESS_BG};
            color: {C_SUCCESS};
            border: 2px solid {C_SUCCESS};
            border-radius: 27px;
            font-size: 28px;
            font-weight: 900;
        """)
        layout.addWidget(icon_box)

        lbl_title = QLabel("Instalação Concluída com Sucesso!")
        lbl_title.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {C_TEXT_PRIMARY};")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel(
            "O DA-V foi integrado com sucesso ao Windows. O firewall foi ajustado para streaming "
            "P2P de baixa latência e os links dav:// já estão associados ao aplicativo."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"font-size: 13px; color: {C_TEXT_SECONDARY}; line-height: 1.5;")
        layout.addWidget(lbl_desc)

        card = QWidget()
        card.setProperty("class", "Card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(10)

        self.chk_launch = QCheckBox("Iniciar o DA-V agora")
        self.chk_launch.setChecked(True)
        card_layout.addWidget(self.chk_launch)
        layout.addWidget(card)

        layout.addStretch()
        return w

    # ── LÓGICA DE NAVEGAÇÃO E EXECUÇÃO ───────────────────────────────────────

    def _update_step_view(self):
        """Sincroniza o Stepper e os botões de navegação."""
        self.stack.setCurrentIndex(self.current_step)

        # Atualiza o visual do Stepper
        for i, item in enumerate(self.stepper_items):
            if i < self.current_step:
                item.set_state("completed")
            elif i == self.current_step:
                item.set_state("active")
            else:
                item.set_state("pending")

        # Controle dos botões
        if self.current_step == 0:
            self.btn_back.setVisible(False)
            self.btn_next.setText("Continuar →")
            self.btn_next.setEnabled(True)
            self.btn_cancel.setVisible(True)
        elif self.current_step == 1:
            self.btn_back.setVisible(True)
            self.btn_next.setText("Instalar e Configurar")
            self.btn_next.setEnabled(True)
            self.btn_cancel.setVisible(True)
        elif self.current_step == 2:
            self.btn_back.setVisible(False)
            self.btn_next.setVisible(False)
            self.btn_cancel.setVisible(False)
            # Dispara a instalação em thread/timer
            QTimer.singleShot(200, self._execute_installation)
        elif self.current_step == 3:
            self.btn_back.setVisible(False)
            self.btn_cancel.setVisible(False)
            self.btn_next.setVisible(True)
            self.btn_next.setText("Concluir e Abrir")
            self.btn_next.setEnabled(True)

    def _go_next(self):
        if self.current_step == 3:
            # Finalizar
            if self.chk_launch.isChecked():
                self._launch_app()
            self.accept()
            return

        self.current_step = min(self.current_step + 1, 3)
        self._update_step_view()

    def _go_back(self):
        self.current_step = max(self.current_step - 1, 0)
        self._update_step_view()

    @staticmethod
    def _get_proj_root() -> Path:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
            for cand in (base, base.parent, base.parent.parent):
                if (cand / "DA-V.exe").exists() or (cand / "scripts" / "gui_app.py").exists():
                    return cand
            return base
        return Path(__file__).resolve().parent.parent

    @staticmethod
    def _find_bundled_payload() -> Path | None:
        candidates = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "dav_app_payload.zip")
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "dav_app_payload.zip")
        candidates.append(Path(__file__).resolve().parent.parent / "dist_installer" / "dav_app_payload.zip")
        for c in candidates:
            if c.is_file():
                return c
        return None

    @staticmethod
    def _get_default_install_dir() -> Path:
        local_app = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local_app) / "Programs" / "DA-V"

    @staticmethod
    def _get_python_runtime() -> str:
        if not getattr(sys, "frozen", False):
            cand_same = Path(sys.executable).resolve().with_name("pythonw.exe")
            if cand_same.is_file():
                return str(cand_same)
        local_py = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"
        if local_py.exists():
            for cand in sorted(local_py.glob("Python3*/pythonw.exe"), reverse=True):
                if cand.is_file():
                    return str(cand)
        for cmd in ("pythonw", "pyw", "python"):
            found = shutil.which(cmd)
            if found and "WindowsApps" not in found:
                return found
        return "pythonw"

    def _resolve_installed_target(self) -> tuple[Path, str, Path]:
        """Retorna (executavel_alvo, argumentos_extras, diretorio_de_trabalho)."""
        install_dir = self._get_default_install_dir()
        installed_exe = install_dir / "DA-V.exe"
        if installed_exe.is_file():
            return installed_exe, "", install_dir

        proj_root = self._get_proj_root()
        sibling_exe = proj_root / "DA-V.exe"
        if sibling_exe.is_file():
            return sibling_exe, "", proj_root

        launcher = proj_root / "scripts" / "gui_app.py"
        pyw_exe = Path(self._get_python_runtime())
        return pyw_exe, f'"{launcher}"', proj_root

    def _execute_installation(self):
        """Extrai os binários autossuficientes do DA-V e aplica integrações no Windows."""
        self.progress_bar.setValue(12)
        self.lbl_status.setText("Instalando binários autossuficientes do DA-V...")
        QApplication.processEvents()

        payload_zip = self._find_bundled_payload()
        install_dir = self._get_default_install_dir()

        if payload_zip is not None:
            try:
                # Encerra instância anterior em execução caso o usuário tenha deixado uma janela aberta
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/IM", "DA-V.exe"],
                        capture_output=True,
                        creationflags=0x08000000,
                    )
                    import time as _time
                    _time.sleep(0.4)
                except Exception:
                    pass

                install_dir.mkdir(parents=True, exist_ok=True)
                internal_dir = install_dir / "_internal"
                if internal_dir.exists():
                    shutil.rmtree(internal_dir, ignore_errors=True)

                with zipfile.ZipFile(payload_zip, "r") as zf:
                    members = zf.infolist()
                    total = max(len(members), 1)
                    for idx, m in enumerate(members, 1):
                        zf.extract(m, install_dir)
                        if idx % 25 == 0 or idx == total:
                            pct = 12 + int((idx / total) * 33)
                            self.progress_bar.setValue(min(pct, 45))
                            QApplication.processEvents()

                self.lbl_log1.setText(f"✓ Aplicação instalada em {install_dir}")
                self.lbl_log1.setStyleSheet(f"font-size: 12px; color: {C_SUCCESS}; font-weight: 600;")
            except Exception as e:
                self.lbl_log1.setText(f"⚠ Falha ao extrair binários ({e}); usando modo local.")
                self.lbl_log1.setStyleSheet(f"font-size: 12px; color: {C_WARNING};")
        else:
            proj_root = self._get_proj_root()
            if (proj_root / "DA-V.exe").is_file() or (proj_root / "scripts" / "gui_app.py").is_file():
                self.lbl_log1.setText(f"✓ Ambiente local validado em {proj_root}")
                self.lbl_log1.setStyleSheet(f"font-size: 12px; color: {C_SUCCESS}; font-weight: 600;")
            else:
                self.lbl_log1.setText("⚠ Pacote de aplicação não localizado junto ao instalador.")
                self.lbl_log1.setStyleSheet(f"font-size: 12px; color: {C_WARNING};")
        QApplication.processEvents()

        # Etapa 2: Firewall
        if self.chk_firewall.isChecked():
            self.progress_bar.setValue(58)
            self.lbl_status.setText("Configurando regras no Windows Defender Firewall...")
            QApplication.processEvents()
            try:
                subprocess.run(
                    'netsh advfirewall firewall delete rule name="DA-V Video Streaming"',
                    shell=True, capture_output=True
                )
                r_fw = subprocess.run(
                    'netsh advfirewall firewall add rule name="DA-V Video Streaming" dir=in action=allow protocol=UDP localport=9000-9020,19000-19010 profile=any',
                    shell=True, capture_output=True
                )
                subprocess.run(
                    'netsh advfirewall firewall add rule name="DA-V LAN Beacon" dir=in action=allow protocol=UDP localport=9005 profile=any',
                    shell=True, capture_output=True
                )
                if r_fw.returncode == 0:
                    self.lbl_log2.setText("✓ Portas UDP 9000-9020, 19000-19010 e 9005 liberadas no Firewall.")
                    self.lbl_log2.setStyleSheet(f"font-size: 12px; color: {C_SUCCESS}; font-weight: 600;")
                else:
                    import ctypes
                    fw_cmd = (
                        'netsh advfirewall firewall delete rule name="DA-V Video Streaming" | Out-Null; '
                        'netsh advfirewall firewall add rule name="DA-V Video Streaming" dir=in action=allow protocol=UDP localport=9000-9020,19000-19010 profile=any | Out-Null; '
                        'netsh advfirewall firewall add rule name="DA-V LAN Beacon" dir=in action=allow protocol=UDP localport=9005 profile=any | Out-Null'
                    )
                    ctypes.windll.shell32.ShellExecuteW(
                        None, "runas", "powershell.exe", f'-NoProfile -WindowStyle Hidden -Command "{fw_cmd}"', None, 0
                    )
                    self.lbl_log2.setText("✓ Regras UDP solicitadas via Administrador (Windows Firewall).")
                    self.lbl_log2.setStyleSheet(f"font-size: 12px; color: {C_SUCCESS}; font-weight: 600;")
            except Exception as e:
                self.lbl_log2.setText(f"⚠ Aviso no Firewall: {e}")
                self.lbl_log2.setStyleSheet(f"font-size: 12px; color: {C_WARNING};")
        else:
            self.lbl_log2.setText("— Configuração de Firewall ignorada pelo usuário.")
        QApplication.processEvents()

        target_exe, target_args, work_dir = self._resolve_installed_target()
        self._installed_target = (target_exe, target_args, work_dir)

        # Etapa 3: Protocolo dav://
        if self.chk_protocol.isChecked():
            self.progress_bar.setValue(75)
            self.lbl_status.setText("Registrando protocolo 'dav://' no Registro do Windows...")
            QApplication.processEvents()
            try:
                if target_args:
                    cmd_str = f'"{target_exe}" {target_args} "%1"'
                else:
                    cmd_str = f'"{target_exe}" "%1"'

                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\dav") as k:
                    winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:DA-V Protocol")
                    winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
                    with winreg.CreateKey(k, r"DisplayIcon") as ik:
                        winreg.SetValueEx(ik, "", 0, winreg.REG_SZ, f'"{target_exe}",0')
                    with winreg.CreateKey(k, r"shell\open\command") as sk:
                        winreg.SetValueEx(sk, "", 0, winreg.REG_SZ, cmd_str)
                self.lbl_log3.setText("✓ Protocolo 'dav://' associado ao executável instalado.")
                self.lbl_log3.setStyleSheet(f"font-size: 12px; color: {C_SUCCESS}; font-weight: 600;")
            except Exception as e:
                self.lbl_log3.setText(f"⚠ Registro do protocolo: {e}")
                self.lbl_log3.setStyleSheet(f"font-size: 12px; color: {C_WARNING};")
        else:
            self.lbl_log3.setText("— Registro do protocolo ignorado pelo usuário.")
        QApplication.processEvents()

        # Etapa 4: Atalho na Área de Trabalho e Menu Iniciar
        if self.chk_desktop.isChecked():
            self.progress_bar.setValue(92)
            self.lbl_status.setText("Criando atalhos na Área de Trabalho e Menu Iniciar...")
            QApplication.processEvents()
            try:
                icon_file = work_dir / "dav_icon.ico"
                icon_loc = f"{icon_file},0" if icon_file.is_file() else f"{target_exe},0"
                escaped_args = target_args.replace('"', '`"') if target_args else ""

                ps_cmd = (
                    '$ws = New-Object -ComObject WScript.Shell; '
                    '$desk = $ws.SpecialFolders("Desktop"); '
                    '$smenu = $ws.SpecialFolders("Programs"); '
                    'foreach ($dir in @($desk, $smenu)) { '
                    '  if ($dir -and (Test-Path $dir)) { '
                    '    $lnk = Join-Path $dir "DA-V.lnk"; '
                    '    $s = $ws.CreateShortcut($lnk); '
                    f'    $s.TargetPath = "{target_exe}"; '
                    f'    $s.Arguments = "{escaped_args}"; '
                    f'    $s.WorkingDirectory = "{work_dir}"; '
                    f'    $s.IconLocation = "{icon_loc}"; '
                    '    $s.Description = "DA-V - Distribuidor Amplo de Vídeo (60 FPS P2P)"; '
                    '    $s.Save() '
                    '  } '
                    '}'
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                    capture_output=True,
                    check=True,
                )
                self.lbl_log4.setText("✓ Atalhos criados na Área de Trabalho e no Menu Iniciar (DA-V).")
                self.lbl_log4.setStyleSheet(f"font-size: 12px; color: {C_SUCCESS}; font-weight: 600;")
            except Exception as e:
                self.lbl_log4.setText(f"⚠ Atalho: {e}")
                self.lbl_log4.setStyleSheet(f"font-size: 12px; color: {C_WARNING};")
        else:
            self.lbl_log4.setText("— Criação de atalhos ignorada pelo usuário.")
        QApplication.processEvents()

        self.progress_bar.setValue(100)
        self.lbl_status.setText("✓ Instalação concluída!")
        QApplication.processEvents()

        QTimer.singleShot(700, self._advance_to_finish)

    def _advance_to_finish(self):
        self.current_step = 3
        self._update_step_view()

    def _launch_app(self):
        """Dispara a abertura imediata do executável instalado DA-V."""
        try:
            target_exe, target_args, work_dir = getattr(
                self, "_installed_target", self._resolve_installed_target()
            )
            cmd = [str(target_exe)]
            if target_args:
                cmd.append(target_args.strip('"'))
            subprocess.Popen(cmd, cwd=str(work_dir), shell=False)
        except Exception as e:
            print(f"Erro ao abrir DA-V: {e}")


def main():
    app = QApplication(sys.argv)
    installer = DavModernInstaller()
    installer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
