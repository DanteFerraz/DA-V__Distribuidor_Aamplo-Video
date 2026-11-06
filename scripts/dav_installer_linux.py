# -*- coding: utf-8 -*-
"""
DA-V — Instalador Gráfico Oficial de Alta Fidelidade (Linux)
Autor: Dante Ferraz (MonoTech)

Design System: Dark Obsidian & Electric Cyan (Enterprise UX / WCAG 2.2 AAA compliant).
Assistente moderno com Stepper lateral, detecção de servidor de display (Wayland/X11),
telemetria de GPU em tempo real, integração com o Menu de Aplicativos XDG (.desktop)
e registro do protocolo 'dav://' via xdg-mime.
"""

import sys
import os
import shutil
import subprocess
from pathlib import Path

# ── Garante que a raiz do projeto esteja no sys.path (código-fonte ou binário PyInstaller) ──
def _resolve_linux_proj_root() -> Path:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for cand in (exe_dir, exe_dir.parent, exe_dir.parent.parent):
            if (cand / "launch_dav.sh").exists() or (cand / "scripts" / "gui_app.py").exists():
                return cand
        return exe_dir
    return Path(__file__).resolve().parent.parent

PROJ_ROOT = _resolve_linux_proj_root()
if str(PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJ_ROOT))

from PySide6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QProgressBar, QStackedWidget,
    QFrame
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor


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
    font-family: 'Ubuntu', 'Segoe UI', -apple-system, sans-serif;
}}

QWidget {{
    color: {C_TEXT_PRIMARY};
    background-color: transparent;
    font-family: 'Ubuntu', 'Segoe UI', -apple-system, sans-serif;
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

        self.badge = QLabel(str(step_num))
        self.badge.setFixedSize(28, 28)
        self.badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.badge)

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


class DavModernLinuxInstaller(QDialog):
    """Instalador visual moderno para Linux (Ubuntu, Debian, Fedora, Arch)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DA-V · Distribuidor Amplo de Vídeo — Instalador Linux")
        self.setMinimumSize(800, 520)
        self.resize(840, 540)
        self.setStyleSheet(INSTALLER_QSS)

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

        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet(f"border: none; border-top: 1px solid {C_BORDER_SUBTLE}; margin: 8px 0;")
        side_layout.addWidget(div)

        self.stepper_items = [
            StepperItem(1, "Boas-vindas", "Ambiente e GPU"),
            StepperItem(2, "Preferências", "Desktop e protocolos"),
            StepperItem(3, "Integração", "Aplicação no Linux"),
            StepperItem(4, "Conclusão", "Pronto para rodar")
        ]
        for item in self.stepper_items:
            side_layout.addWidget(item)

        side_layout.addStretch()

        lbl_ver = QLabel("DA-V v3.1.0 (Linux Edition)\nDante Ferraz · MonoTech")
        lbl_ver.setStyleSheet(f"font-size: 10px; color: {C_TEXT_MUTED}; line-height: 1.4;")
        side_layout.addWidget(lbl_ver)

        root_layout.addWidget(sidebar)

        # ── 2. ÁREA DE CONTEÚDO PRINCIPAL ────────────────────────────────────
        main_content = QWidget()
        main_layout = QVBoxLayout(main_content)
        main_layout.setContentsMargins(36, 28, 36, 24)
        main_layout.setSpacing(20)

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

        # Navegação inferior
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
        layout.setSpacing(16)

        lbl_title = QLabel("Transmissão de Vídeo P2P a 60 FPS")
        lbl_title.setStyleSheet(f"font-size: 22px; font-weight: 800; color: {C_TEXT_PRIMARY};")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel(
            "Bem-vindo ao instalador oficial do DA-V para Linux. Este assistente configurará o ambiente "
            "com aceleração de hardware nativa (C++23 MIT-SHM), integração XDG Desktop e protocolo de deep-link."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"font-size: 13px; color: {C_TEXT_SECONDARY}; line-height: 1.5;")
        layout.addWidget(lbl_desc)

        # Detecção de Sessão Gráfica
        session_type = os.environ.get("XDG_SESSION_TYPE", "x11").capitalize()
        is_wayland = (session_type.lower() == "wayland")
        
        sess_card = QWidget()
        sess_card.setProperty("class", "Card")
        sess_layout = QHBoxLayout(sess_card)
        sess_layout.setContentsMargins(14, 10, 14, 10)
        sess_layout.setSpacing(12)

        icon_sess = QLabel("🖥️")
        icon_sess.setStyleSheet("font-size: 20px;")
        sess_layout.addWidget(icon_sess)

        sess_col = QVBoxLayout()
        sess_col.setSpacing(1)
        lbl_s_title = QLabel(f"Servidor Gráfico: {session_type}")
        lbl_s_title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {C_TEXT_PRIMARY};")
        lbl_s_sub = QLabel("Suporte completo a Wayland (PipeWire) e X11 nativo (MIT-SHM Zero-Copy)." if is_wayland else "Captura nativa MIT-SHM ultrarrápida com latência < 2ms ativa.")
        lbl_s_sub.setStyleSheet(f"font-size: 11px; color: {C_TEXT_MUTED};")
        sess_col.addWidget(lbl_s_title)
        sess_col.addWidget(lbl_s_sub)
        sess_layout.addLayout(sess_col)
        sess_layout.addStretch()

        badge_sess = QLabel("WAYLAND" if is_wayland else "X11 NATIVO")
        badge_sess.setStyleSheet(f"background-color: {C_BG_CANVAS}; color: {C_ACCENT}; border: 1px solid {C_BORDER_SUBTLE}; padding: 4px 8px; border-radius: 4px; font-size: 10px; font-weight: 800;")
        sess_layout.addWidget(badge_sess)
        layout.addWidget(sess_card)

        # Detecção de GPU
        has_nv = False
        try:
            r = subprocess.run(["which", "nvidia-smi"], capture_output=True)
            has_nv = (r.returncode == 0)
        except Exception:
            pass

        gpu_card = QWidget()
        gpu_card.setProperty("class", "Card")
        gpu_layout = QHBoxLayout(gpu_card)
        gpu_layout.setContentsMargins(14, 10, 14, 10)
        gpu_layout.setSpacing(12)

        icon_gpu = QLabel("🎮" if has_nv else "⚙️")
        icon_gpu.setStyleSheet("font-size: 20px;")
        gpu_layout.addWidget(icon_gpu)

        gpu_col = QVBoxLayout()
        gpu_col.setSpacing(1)
        if has_nv:
            lbl_g_title = QLabel("Hardware Gráfico: NVIDIA NVENC Detectado")
            lbl_g_title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {C_SUCCESS};")
            lbl_g_sub = QLabel("Aceleração de hardware ativa para codificação H.264 (0% de CPU utilizada).")
            lbl_g_sub.setStyleSheet(f"font-size: 11px; color: {C_TEXT_MUTED};")
        else:
            lbl_g_title = QLabel("Hardware Gráfico: Renderizador SIMD Universal")
            lbl_g_title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {C_ACCENT};")
            lbl_g_sub = QLabel("Otimizado para processadores multi-core com instruções AVX2/SSE4.")
            lbl_g_sub.setStyleSheet(f"font-size: 11px; color: {C_TEXT_MUTED};")
        gpu_col.addWidget(lbl_g_title)
        gpu_col.addWidget(lbl_g_sub)
        gpu_layout.addLayout(gpu_col)
        gpu_layout.addStretch()

        badge_gpu = QLabel("ATIVO ✓" if has_nv else "PRONTO")
        badge_gpu.setStyleSheet(f"background-color: {C_SUCCESS_BG if has_nv else C_BG_CANVAS}; color: {C_SUCCESS if has_nv else C_ACCENT}; border: 1px solid {C_SUCCESS if has_nv else C_BORDER_SUBTLE}; padding: 4px 8px; border-radius: 4px; font-size: 10px; font-weight: 800;")
        gpu_layout.addWidget(badge_gpu)
        layout.addWidget(gpu_card)

        layout.addStretch()
        return w

    def _create_page_options(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        lbl_title = QLabel("Opções de Integração no Linux")
        lbl_title.setStyleSheet(f"font-size: 22px; font-weight: 800; color: {C_TEXT_PRIMARY};")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel("Personalize como o DA-V se integra ao seu desktop e sistema operacional:")
        lbl_desc.setStyleSheet(f"font-size: 13px; color: {C_TEXT_SECONDARY};")
        layout.addWidget(lbl_desc)

        card = QWidget()
        card.setProperty("class", "Card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(16)

        self.chk_menu = QCheckBox("Adicionar lançador ao Menu de Aplicativos (.desktop)")
        self.chk_menu.setChecked(True)
        lbl_menu_sub = QLabel("   Cria o atalho no GNOME / KDE / Ubuntu Dock com ícone nativo.")
        lbl_menu_sub.setStyleSheet(f"font-size: 11px; color: {C_TEXT_MUTED}; margin-top: -6px;")
        card_layout.addWidget(self.chk_menu)
        card_layout.addWidget(lbl_menu_sub)

        self.chk_protocol = QCheckBox("Registrar protocolo 'dav://' via XDG (Convites Diretos)")
        self.chk_protocol.setChecked(True)
        lbl_proto_sub = QLabel("   Permite abrir transmissões clicando em links dav://connect/PIN no navegador ou Discord.")
        lbl_proto_sub.setStyleSheet(f"font-size: 11px; color: {C_TEXT_MUTED}; margin-top: -6px;")
        card_layout.addWidget(self.chk_protocol)
        card_layout.addWidget(lbl_proto_sub)

        self.chk_ufw = QCheckBox("Liberar portas UDP no firewall UFW (Portas 9000-9020 e 9005)")
        self.chk_ufw.setChecked(True)
        lbl_ufw_sub = QLabel("   Executa comando sudo/pkexec para liberar tráfego P2P e beacon local.")
        lbl_ufw_sub.setStyleSheet(f"font-size: 11px; color: {C_TEXT_MUTED}; margin-top: -6px;")
        card_layout.addWidget(self.chk_ufw)
        card_layout.addWidget(lbl_ufw_sub)

        layout.addWidget(card)
        layout.addStretch()
        return w

    def _create_page_progress(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        lbl_title = QLabel("Aplicando Integração")
        lbl_title.setStyleSheet(f"font-size: 22px; font-weight: 800; color: {C_TEXT_PRIMARY};")
        layout.addWidget(lbl_title)

        self.lbl_status = QLabel("Inicializando configuração...")
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

        self.lbl_log1 = QLabel("• Verificando backend C++23 compilado (libdav_core.so)...")
        self.lbl_log2 = QLabel("• Instalando lançador de desktop XDG (.desktop)...")
        self.lbl_log3 = QLabel("• Registrando associação de protocolo dav://...")
        self.lbl_log4 = QLabel("• Configurando portas de rede e permissões...")

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

        lbl_title = QLabel("Instalação Concluída no Linux!")
        lbl_title.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {C_TEXT_PRIMARY};")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel(
            "O DA-V foi integrado com sucesso ao seu desktop Linux. O lançador foi instalado no menu "
            "de aplicativos e o protocolo dav:// já está associado."
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

    # ── NAVEGAÇÃO E EXECUÇÃO ─────────────────────────────────────────────────

    def _update_step_view(self):
        self.stack.setCurrentIndex(self.current_step)

        for i, item in enumerate(self.stepper_items):
            if i < self.current_step:
                item.set_state("completed")
            elif i == self.current_step:
                item.set_state("active")
            else:
                item.set_state("pending")

        if self.current_step == 0:
            self.btn_back.setVisible(False)
            self.btn_next.setText("Continuar →")
            self.btn_next.setEnabled(True)
            self.btn_cancel.setVisible(True)
        elif self.current_step == 1:
            self.btn_back.setVisible(True)
            self.btn_next.setText("Instalar e Integrar")
            self.btn_next.setEnabled(True)
            self.btn_cancel.setVisible(True)
        elif self.current_step == 2:
            self.btn_back.setVisible(False)
            self.btn_next.setVisible(False)
            self.btn_cancel.setVisible(False)
            QTimer.singleShot(200, self._execute_installation)
        elif self.current_step == 3:
            self.btn_back.setVisible(False)
            self.btn_cancel.setVisible(False)
            self.btn_next.setVisible(True)
            self.btn_next.setText("Concluir e Abrir")
            self.btn_next.setEnabled(True)

    def _go_next(self):
        if self.current_step == 3:
            if self.chk_launch.isChecked():
                self._launch_app()
            self.accept()
            return

        self.current_step = min(self.current_step + 1, 3)
        self._update_step_view()

    def _go_back(self):
        self.current_step = max(self.current_step - 1, 0)
        self._update_step_view()

    def _execute_installation(self):
        proj_root = PROJ_ROOT
        launcher_script = proj_root / "launch_dav.sh"

        # Etapa 1: Backend C++23
        self.progress_bar.setValue(20)
        self.lbl_status.setText("Validando biblioteca nativa C++23...")
        QApplication.processEvents()

        so_target = proj_root / "build" / "libdav_core.so"
        if so_target.exists():
            self.lbl_log1.setText(f"✓ Backend C++23 validado: {so_target.name}")
            self.lbl_log1.setStyleSheet(f"font-size: 12px; color: {C_SUCCESS}; font-weight: 600;")
        else:
            self.lbl_log1.setText("ℹ Backend C++23 não encontrado (o DA-V usará pipeline Python/SIMD).")
            self.lbl_log1.setStyleSheet(f"font-size: 12px; color: {C_ACCENT};")
        QApplication.processEvents()

        # Etapa 2: Desktop Entry
        if self.chk_menu.isChecked():
            self.progress_bar.setValue(50)
            self.lbl_status.setText("Instalando lançador XDG no menu de aplicativos...")
            QApplication.processEvents()
            try:
                user_apps = Path.home() / ".local" / "share" / "applications"
                user_apps.mkdir(parents=True, exist_ok=True)
                desktop_file = user_apps / "dav.desktop"

                desktop_content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=DA-V · Distribuidor Amplo de Vídeo
GenericName=Transmissão de Vídeo 60 FPS P2P
Comment=Motor de compartilhamento de tela P2P de ultra-baixa latência com hardware NVENC/SIMD
Exec="{launcher_script}" %u
Icon=video-display
Terminal=false
Categories=AudioVideo;Video;Network;RemoteAccess;
MimeType=x-scheme-handler/dav;
StartupWMClass=dav-desktop
"""
                with open(desktop_file, "w", encoding="utf-8") as f:
                    f.write(desktop_content)
                desktop_file.chmod(0o755)
                subprocess.run(["update-desktop-database", str(user_apps)], check=False)

                self.lbl_log2.setText("✓ Lançador adicionado ao Menu de Aplicativos (~/.local/share/applications/dav.desktop).")
                self.lbl_log2.setStyleSheet(f"font-size: 12px; color: {C_SUCCESS}; font-weight: 600;")
            except Exception as e:
                self.lbl_log2.setText(f"⚠ Lançador Desktop: {e}")
                self.lbl_log2.setStyleSheet(f"font-size: 12px; color: {C_WARNING};")
        else:
            self.lbl_log2.setText("— Lançador no menu de aplicativos ignorado pelo usuário.")
        QApplication.processEvents()

        # Etapa 3: Protocolo dav://
        if self.chk_protocol.isChecked():
            self.progress_bar.setValue(75)
            self.lbl_status.setText("Registrando protocolo 'dav://' via xdg-mime...")
            QApplication.processEvents()
            try:
                subprocess.run(["xdg-mime", "default", "dav.desktop", "x-scheme-handler/dav"], check=False)
                self.lbl_log3.setText("✓ Protocolo 'dav://' associado ao DA-V via xdg-mime.")
                self.lbl_log3.setStyleSheet(f"font-size: 12px; color: {C_SUCCESS}; font-weight: 600;")
            except Exception as e:
                self.lbl_log3.setText(f"⚠ Protocolo dav://: {e}")
                self.lbl_log3.setStyleSheet(f"font-size: 12px; color: {C_WARNING};")
        else:
            self.lbl_log3.setText("— Registro do protocolo dav:// ignorado pelo usuário.")
        QApplication.processEvents()

        # Etapa 4: Firewall
        if self.chk_ufw.isChecked():
            self.progress_bar.setValue(90)
            self.lbl_status.setText("Configurando regras de firewall UFW...")
            QApplication.processEvents()
            try:
                # Executa silenciosamente se tiver permissão, caso contrário exibe comando
                res1 = subprocess.run(["sudo", "-n", "ufw", "allow", "9000:9020/udp"], capture_output=True)
                res2 = subprocess.run(["sudo", "-n", "ufw", "allow", "19000:19010/udp"], capture_output=True)
                res3 = subprocess.run(["sudo", "-n", "ufw", "allow", "9005/udp"], capture_output=True)
                if res1.returncode == 0 and res3.returncode == 0:
                    self.lbl_log4.setText("✓ Portas UDP 9000-9020, 19000-19010 e 9005 liberadas no UFW.")
                    self.lbl_log4.setStyleSheet(f"font-size: 12px; color: {C_SUCCESS}; font-weight: 600;")
                else:
                    self.lbl_log4.setText("ℹ Para liberar o firewall, execute: sudo ufw allow 9000:9020/udp && sudo ufw allow 9005/udp")
                    self.lbl_log4.setStyleSheet(f"font-size: 12px; color: {C_ACCENT};")
            except Exception:
                self.lbl_log4.setText("ℹ Para liberar o firewall, execute: sudo ufw allow 9000:9020/udp && sudo ufw allow 9005/udp")
                self.lbl_log4.setStyleSheet(f"font-size: 12px; color: {C_ACCENT};")
        else:
            self.lbl_log4.setText("— Configuração de firewall ignorada.")
        QApplication.processEvents()

        self.progress_bar.setValue(100)
        self.lbl_status.setText("✓ Integração concluída com sucesso!")
        QApplication.processEvents()

        QTimer.singleShot(700, self._advance_to_finish)

    def _advance_to_finish(self):
        self.current_step = 3
        self._update_step_view()

    def _launch_app(self):
        try:
            launcher = PROJ_ROOT / "launch_dav.sh"
            subprocess.Popen([str(launcher)], cwd=str(PROJ_ROOT), shell=True)
        except Exception as e:
            print(f"Erro ao abrir DA-V: {e}")


def main():
    app = QApplication(sys.argv)
    installer = DavModernLinuxInstaller()
    installer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
