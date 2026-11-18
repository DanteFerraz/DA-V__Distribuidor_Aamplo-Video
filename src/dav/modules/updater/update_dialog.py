# -*- coding: utf-8 -*-
"""
Diálogo de Consentimento de Atualização (Blocks.so UI) — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import threading
from typing import Optional

from src.ui.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit, QFrame, Qt, Signal, Slot, QApplication
)
from src.ui.theme import Theme
from src.dav.modules.updater.update_checker import UpdateInfo
from src.dav.modules.updater.auto_installer import AutoInstaller


class UpdateConsentDialog(QDialog):
    """
    Diálogo modal de atualização aderente ao Design System Blocks.so.
    Exibe notas de lançamento, solicita consentimento explícito do usuário,
    efetua o download em tempo real com barra de progresso e dispara a instalação.
    """

    download_progress_signal = Signal(int, int)
    download_finished_signal = Signal(str)
    download_error_signal = Signal(str)

    def __init__(self, update_info: UpdateInfo, parent=None):
        super().__init__(parent)
        self.info = update_info
        self.setWindowTitle("Atualização Disponível — DA-V")
        self.setFixedSize(540, 480)
        self.setModal(True)

        self.download_progress_signal.connect(self._on_progress)
        self.download_finished_signal.connect(self._on_finished)
        self.download_error_signal.connect(self._on_error)

        self._init_ui()

    def _init_ui(self):
        s = Theme.SYS
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {s["bg_canvas"]};
                color: {s["text_primary"]};
                font-family: 'Segoe UI', Inter, sans-serif;
            }}
            QLabel {{
                color: {s["text_primary"]};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # ── Badge & Versões ──
        header_row = QHBoxLayout()
        lbl_badge = QLabel("NOVA VERSÃO DISPONÍVEL")
        lbl_badge.setStyleSheet(f"""
            background-color: {s["accent_primary"]};
            color: #ffffff;
            font-weight: 800;
            font-size: 11px;
            padding: 4px 10px;
            border-radius: 4px;
        """)
        header_row.addWidget(lbl_badge)
        header_row.addStretch()

        lbl_ver_comp = QLabel(f"v{self.info.current_version}  ->  <b>v{self.info.latest_version}</b>")
        lbl_ver_comp.setStyleSheet(f"font-size: 13px; color: {s['text_accent']};")
        header_row.addWidget(lbl_ver_comp)
        layout.addLayout(header_row)

        # ── Título ──
        lbl_title = QLabel(self.info.release_title)
        lbl_title.setStyleSheet("font-size: 18px; font-weight: 800;")
        layout.addWidget(lbl_title)

        # ── Notas de Lançamento (Card Blocks.so) ──
        box_notes = QFrame()
        box_notes.setStyleSheet(f"""
            QFrame {{
                background-color: {s["bg_surface_card"]};
                border: 1px solid {s["border_subtle"]};
                border-radius: {Theme.RADIUS_LG}px;
                padding: 10px;
            }}
        """)
        notes_layout = QVBoxLayout(box_notes)
        notes_layout.setContentsMargins(8, 8, 8, 8)

        lbl_notes_title = QLabel("Novidades e Melhorias:")
        lbl_notes_title.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {s['text_muted']};")
        notes_layout.addWidget(lbl_notes_title)

        self.txt_notes = QTextEdit()
        self.txt_notes.setReadOnly(True)
        self.txt_notes.setPlainText(self.info.release_notes)
        self.txt_notes.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                border: none;
                color: {s["text_primary"]};
                font-size: 12px;
            }}
        """)
        notes_layout.addWidget(self.txt_notes)
        layout.addWidget(box_notes, stretch=1)

        # ── Barra de Progresso do Download (Inicialmente oculta) ──
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Deseja baixar e instalar esta atualização agora?")
        self.lbl_status.setStyleSheet(f"font-size: 12px; color: {s['text_secondary']};")
        layout.addWidget(self.lbl_status)

        # ── Botões de Ação ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_cancel = QPushButton("Lembrar Mais Tarde")
        self.btn_cancel.setObjectName("secondaryBtn")
        self.btn_cancel.setFixedHeight(36)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)

        self.btn_update = QPushButton("Atualizar Agora")
        self.btn_update.setFixedHeight(36)
        self.btn_update.setStyleSheet(f"""
            QPushButton {{
                background-color: {s["accent_primary"]};
                color: #ffffff;
                font-weight: 700;
                border-radius: 6px;
                padding: 0 20px;
                border: 1px solid {s["accent_primary"]};
            }}
            QPushButton:hover {{
                background-color: {s["accent_primary_hover"]};
            }}
        """)
        self.btn_update.clicked.connect(self._start_download)
        btn_row.addWidget(self.btn_update)

        layout.addLayout(btn_row)

    def _start_download(self):
        """Inicia o download em segundo plano e bloqueia os botões."""
        self.btn_update.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.lbl_status.setText("Baixando nova versão do DA-V...")

        def _worker():
            def _progress(downloaded: int, total: int):
                pct = int((downloaded / total) * 100) if total > 0 else 0
                self.download_progress_signal.emit(pct, total)

            res = AutoInstaller.download_asset(
                download_url=self.info.download_url,
                asset_name=self.info.asset_name,
                on_progress=_progress,
            )
            if res.is_success and res.value:
                self.download_finished_signal.emit(res.value)
            else:
                self.download_error_signal.emit(res.error or "Erro desconhecido no download")

        threading.Thread(target=_worker, daemon=True, name="DAV-Updater-Download").start()

    @Slot(int, int)
    def _on_progress(self, pct: int, total: int):
        self.progress_bar.setValue(pct)
        total_mb = total / (1024 * 1024) if total > 0 else 0
        self.lbl_status.setText(f"Baixando pacote... {pct}% ({total_mb:.1f} MB)")

    @Slot(str)
    def _on_finished(self, installer_path: str):
        self.lbl_status.setText("Download concluído! Iniciando instalador e reiniciando aplicação...")
        self.progress_bar.setValue(100)
        # Dispara o instalador
        res_launch = AutoInstaller.launch_installer_and_exit(installer_path)
        if res_launch.is_success:
            self.accept()
            # Encerra o aplicativo atual para liberar arquivos em uso
            app = QApplication.instance()
            if app:
                from src.ui.qt_compat import QTimer
                QTimer.singleShot(600, app.quit)
        else:
            self.lbl_status.setText(f"Falha ao iniciar instalador: {res_launch.error}")
            self.btn_cancel.setEnabled(True)

    @Slot(str)
    def _on_error(self, err_msg: str):
        self.lbl_status.setText(f"Erro: {err_msg}")
        self.btn_update.setEnabled(True)
        self.btn_cancel.setEnabled(True)

