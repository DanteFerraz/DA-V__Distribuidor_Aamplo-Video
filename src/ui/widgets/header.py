# -*- coding: utf-8 -*-
"""
DA-V Top Header Bar
Status display showing Local IP, listening port, shared PIN, and hardware engine acceleration tag.
"""

from scripts.qt_compat import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QApplication, Signal, Qt, QFont
)
from src.ui.theme import Theme


class TopHeaderBar(QFrame):
    """Modern top bar providing global connection identity and access tokens."""
    pin_regenerated = Signal()

    def __init__(self, local_ip: str, default_port: int, initial_pin: str, engine_tag: str, parent=None):
        super().__init__(parent)
        self.local_ip = local_ip
        self.default_port = default_port
        self.current_pin = initial_pin
        self.engine_tag = engine_tag

        self.setObjectName("topHeaderFrame")
        self.setStyleSheet(f"""
            QFrame#topHeaderFrame {{
                background-color: {Theme.SYS["bg_surface"]};
                border-bottom: 1px solid {Theme.SYS["border_subtle"]};
            }}
        """)
        self.setFixedHeight(64)

        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(Theme.SPACE_LG, Theme.SPACE_SM, Theme.SPACE_LG, Theme.SPACE_SM)
        layout.setSpacing(Theme.SPACE_MD)

        # ── Left: App Title and Subtitle ──
        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        lbl_app = QLabel("DA-V · DISTRIBUIDOR AMPLO DE VÍDEO")
        lbl_app.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {Theme.SYS['accent_primary']}; letter-spacing: 0.8px;")
        
        self.lbl_sub = QLabel(f"Ultra-Low Latency Video Streaming — {self.engine_tag}")
        self.lbl_sub.setStyleSheet(f"font-size: 11px; color: {Theme.SYS['text_muted']};")

        title_box.addWidget(lbl_app)
        title_box.addWidget(self.lbl_sub)
        layout.addLayout(title_box)

        layout.addStretch()

        # ── Right: Badges & PIN Controls ──
        # IP Badge
        self.lbl_ip_badge = QLabel(f"IP: {self.local_ip}:{self.default_port}")
        self.lbl_ip_badge.setStyleSheet(f"""
            background-color: {Theme.SYS["bg_canvas"]};
            border: 1px solid {Theme.SYS["border_subtle"]};
            border-radius: 6px;
            padding: 5px 12px;
            font-size: 12px;
            font-weight: 600;
            color: {Theme.SYS["text_secondary"]};
        """)
        layout.addWidget(self.lbl_ip_badge)

        # PIN Badge (Highlighted Emerald)
        self.lbl_pin_badge = QLabel(f"Meu PIN: {self.current_pin}")
        self.lbl_pin_badge.setStyleSheet(f"""
            background-color: {Theme.SYS["status_success_bg"]};
            border: 1px solid {Theme.SYS["status_success"]};
            border-radius: 6px;
            padding: 5px 14px;
            font-size: 13px;
            font-weight: 800;
            color: {Theme.SYS["status_success"]};
            letter-spacing: 1px;
        """)
        layout.addWidget(self.lbl_pin_badge)

        # Copy PIN Button
        self.btn_copy_pin = QPushButton("Copiar PIN")
        self.btn_copy_pin.setObjectName("secondaryBtn")
        self.btn_copy_pin.setFixedHeight(30)
        self.btn_copy_pin.clicked.connect(self._copy_pin_to_clipboard)
        layout.addWidget(self.btn_copy_pin)

        # New PIN Button
        self.btn_new_pin = QPushButton("Novo PIN")
        self.btn_new_pin.setObjectName("secondaryBtn")
        self.btn_new_pin.setFixedHeight(30)
        self.btn_new_pin.clicked.connect(self.pin_regenerated.emit)
        layout.addWidget(self.btn_new_pin)

    def update_pin(self, new_pin: str):
        self.current_pin = new_pin
        self.lbl_pin_badge.setText(f"Meu PIN: {new_pin}")

    def set_receiver_mode(self, is_receiver: bool):
        """Hides subtitle and IP badge on Receiver view to match 1:1 reference."""
        if is_receiver:
            self.lbl_sub.hide()
            self.lbl_ip_badge.hide()
        else:
            self.lbl_sub.show()
            self.lbl_ip_badge.show()

    def _copy_pin_to_clipboard(self):
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self.current_pin)
            self.btn_copy_pin.setText("Copiado! ✓")
            from scripts.qt_compat import QTimer
            QTimer.singleShot(1500, lambda: self.btn_copy_pin.setText("Copiar PIN"))
