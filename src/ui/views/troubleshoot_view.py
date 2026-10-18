# -*- coding: utf-8 -*-
"""
DA-V Troubleshooting & Logs View
Diagnostics console, local loopback tests, firewall status checker and script triggers.
"""

import os
import time
from scripts.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    Signal, Qt
)
from src.ui.theme import Theme

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TroubleshootView(QWidget):
    """View dedicated to diagnostic actions, firewall verification, and structured logging."""
    loopback_requested = Signal()
    fix_firewall_requested = Signal()
    check_firewall_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD)
        layout.setSpacing(Theme.SPACE_MD)

        # ── Action Buttons ──
        btn_box = QHBoxLayout()
        btn_box.setSpacing(Theme.SPACE_SM)

        btn_loopback = QPushButton("Testar Loopback Local")
        btn_loopback.setObjectName("secondaryBtn")
        btn_loopback.clicked.connect(self.loopback_requested.emit)
        btn_box.addWidget(btn_loopback)

        btn_firewall = QPushButton("Liberar Portas no Firewall (UDP 9000/9005)")
        btn_firewall.setObjectName("secondaryBtn")
        btn_firewall.clicked.connect(self.fix_firewall_requested.emit)
        btn_box.addWidget(btn_firewall)

        btn_check_fw = QPushButton("Verificar Firewall")
        btn_check_fw.setObjectName("secondaryBtn")
        btn_check_fw.clicked.connect(self.check_firewall_requested.emit)
        btn_box.addWidget(btn_check_fw)

        btn_clear_log = QPushButton("Limpar Console")
        btn_clear_log.setObjectName("secondaryBtn")
        btn_clear_log.clicked.connect(lambda: self.txt_logs.clear())
        btn_box.addWidget(btn_clear_log)

        btn_box.addStretch()
        layout.addLayout(btn_box)

        # ── Formatted Log Terminal ──
        self.txt_logs = QTextEdit()
        self.txt_logs.setReadOnly(True)
        layout.addWidget(self.txt_logs)

    def append_log(self, level: str, text: str):
        color = "#38bdf8" if level == "INFO" else ("#f59e0b" if level == "WARN" else ("#ef4444" if level == "ERROR" else "#34d399"))
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.txt_logs.append(
            f"<span style='color:#64748b;'>[{ts[11:]}]</span> "
            f"<span style='color:{color}; font-weight:bold;'>[{level}]</span> "
            f"<span style='color:#e2e8f0;'>{text}</span>"
        )
        try:
            log_dir = os.path.join(_PROJECT_ROOT, "logs")
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "dav_transmission.log"), "a", encoding="utf-8") as f:
                f.write(f"[{ts}] [{level}] {text}\n")
        except Exception:
            pass
