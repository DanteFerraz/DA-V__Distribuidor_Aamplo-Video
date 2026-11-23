# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
DA-V Troubleshooting & Logs View
Diagnostics console, local loopback tests, firewall status checker and script triggers.
"""

import os
import time
from src.ui.qt_compat import (
    QWidget, QVBoxLayout, QGridLayout, QPushButton, QTextEdit,
    Signal, Qt
)
from src.ui.theme import Theme

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TroubleshootView(QWidget):
    """View dedicated to diagnostic actions, firewall verification, and structured logging."""
    loopback_requested = Signal()
    fix_firewall_requested = Signal()
    check_firewall_requested = Signal()
    export_logs_requested = Signal()
    check_update_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD)
        layout.setSpacing(Theme.SPACE_MD)

        # ── Action Buttons (grade 3x2 para caber sem corte na folha) ──
        btn_grid = QGridLayout()
        btn_grid.setSpacing(Theme.SPACE_SM)
        btn_grid.setColumnStretch(0, 1)
        btn_grid.setColumnStretch(1, 1)
        btn_grid.setColumnStretch(2, 1)

        btn_loopback = QPushButton("Testar Loopback Local")
        btn_loopback.setMinimumWidth(0)
        btn_loopback.setObjectName("secondaryBtn")
        btn_loopback.clicked.connect(self.loopback_requested.emit)
        btn_grid.addWidget(btn_loopback, 0, 0)

        btn_firewall = QPushButton("Liberar Portas Firewall")
        btn_firewall.setMinimumWidth(0)
        btn_firewall.setToolTip("Libera UDP 9000-9020 e Beacon 9005 no firewall")
        btn_firewall.setObjectName("secondaryBtn")
        btn_firewall.clicked.connect(self.fix_firewall_requested.emit)
        btn_grid.addWidget(btn_firewall, 0, 1)

        btn_check_fw = QPushButton("Verificar Firewall")
        btn_check_fw.setMinimumWidth(0)
        btn_check_fw.setObjectName("secondaryBtn")
        btn_check_fw.clicked.connect(self.check_firewall_requested.emit)
        btn_grid.addWidget(btn_check_fw, 0, 2)

        btn_clear_log = QPushButton("Limpar Console")
        btn_clear_log.setMinimumWidth(0)
        btn_clear_log.setObjectName("secondaryBtn")
        btn_clear_log.clicked.connect(lambda: self.txt_logs.clear())
        btn_grid.addWidget(btn_clear_log, 1, 0)

        btn_export_zip = QPushButton("Exportar Diagnóstico (.zip)")
        btn_export_zip.setMinimumWidth(0)
        btn_export_zip.setObjectName("secondaryBtn")
        btn_export_zip.setToolTip("Gera pacote compactado YYYY-MM-DD_HH-MM-SS_DA-V-log.zip com logs e telemetria")
        btn_export_zip.clicked.connect(self.export_logs_requested.emit)
        btn_grid.addWidget(btn_export_zip, 1, 1)

        btn_check_update = QPushButton("Buscar Atualizações")
        btn_check_update.setMinimumWidth(0)
        btn_check_update.setObjectName("secondaryBtn")
        btn_check_update.setToolTip("Verifica se há novas versões do DA-V disponíveis")
        btn_check_update.clicked.connect(self.check_update_requested.emit)
        btn_grid.addWidget(btn_check_update, 1, 2)

        layout.addLayout(btn_grid)

        # ── Formatted Log Terminal ──
        self.txt_logs = QTextEdit()
        self.txt_logs.setReadOnly(True)
        self.txt_logs.setMinimumHeight(240)
        layout.addWidget(self.txt_logs, stretch=1)

    def append_log(self, level: str, text: str):
        color = "#7dd3fc" if level == "INFO" else ("#fcd34d" if level == "WARN" else ("#fca5a5" if level == "ERROR" else "#86efac"))
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.txt_logs.append(
            f"<span style='color:#9ccfd8;'>[{ts[11:]}]</span> "
            f"<span style='color:{color}; font-weight:bold;'>[{level}]</span> "
            f"<span style='color:#f2fbfb;'>{text}</span>"
        )
        try:
            import sys
            if getattr(sys, "frozen", False):
                if sys.platform == "win32":
                    base_log = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "DA-V")
                else:
                    base_log = os.path.join(os.path.expanduser("~"), ".local", "state", "dav")
                log_dir = os.path.join(base_log, "logs")
            else:
                log_dir = os.path.join(_PROJECT_ROOT, "logs")
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "dav_transmission.log"), "a", encoding="utf-8") as f:
                f.write(f"[{ts}] [{level}] {text}\n")
        except Exception:
            pass
