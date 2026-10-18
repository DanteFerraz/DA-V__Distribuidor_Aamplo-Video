# -*- coding: utf-8 -*-
"""
DA-V Viewer / Receiver View
Interactive video playback canvas with integrated quick-connection controls and HUD toggle.
"""

from scripts.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QPushButton, QCheckBox, QGroupBox, Signal, Qt
)
from src.ui.theme import Theme
from src.ui.widgets.canvas import VideoCanvasWidget


class ViewerView(QWidget):
    """View dedicated to viewing received real-time video streams."""
    connect_toggled = Signal()

    def __init__(self, initial_ip: str, default_port: int, initial_pin: str, parent=None):
        super().__init__(parent)
        self.initial_ip = initial_ip
        self.default_port = default_port
        self.initial_pin = initial_pin
        self.is_connected = False

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD)
        layout.setSpacing(Theme.SPACE_MD)

        # ── Quick Connection Bar ──
        ctrl_box = QGroupBox("Controles de Conexão do Receptor")
        ctrl_layout = QHBoxLayout(ctrl_box)
        ctrl_layout.setContentsMargins(Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD)
        ctrl_layout.setSpacing(Theme.SPACE_MD)

        ctrl_layout.addWidget(QLabel("IP do Transmissor:"))
        self.txt_recv_ip = QLineEdit(self.initial_ip)
        self.txt_recv_ip.setPlaceholderText("Vazio p/ P2P Remoto ou IP local")
        ctrl_layout.addWidget(self.txt_recv_ip)

        ctrl_layout.addWidget(QLabel("Porta UDP:"))
        self.spn_recv_port = QSpinBox()
        self.spn_recv_port.setRange(1024, 65535)
        self.spn_recv_port.setValue(self.default_port)
        ctrl_layout.addWidget(self.spn_recv_port)

        ctrl_layout.addWidget(QLabel("PIN de Acesso:"))
        self.txt_recv_pin = QLineEdit(self.initial_pin)
        self.txt_recv_pin.setFixedWidth(110)
        ctrl_layout.addWidget(self.txt_recv_pin)

        self.btn_recv_toggle = QPushButton("Conectar e Assistir")
        self.btn_recv_toggle.setMinimumWidth(180)
        self.btn_recv_toggle.clicked.connect(self.connect_toggled.emit)
        ctrl_layout.addWidget(self.btn_recv_toggle)

        self.chk_hud = QCheckBox("Exibir HUD Telemetria")
        self.chk_hud.setChecked(True)
        self.chk_hud.toggled.connect(self._on_hud_toggled)
        ctrl_layout.addWidget(self.chk_hud)

        layout.addWidget(ctrl_box)

        # ── Real-Time Video Canvas ──
        self.video_canvas = VideoCanvasWidget(self)
        layout.addWidget(self.video_canvas, stretch=1)

    def _on_hud_toggled(self, checked: bool):
        self.video_canvas.show_hud = checked
        self.video_canvas.update()

    def set_connection_state(self, connected: bool):
        self.is_connected = connected
        if connected:
            self.btn_recv_toggle.setText("Desconectar")
            self.btn_recv_toggle.setObjectName("stopBtn")
        else:
            self.btn_recv_toggle.setText("Conectar e Assistir")
            self.btn_recv_toggle.setObjectName("")
            self.video_canvas.clear_display()
        self.btn_recv_toggle.setStyle(self.btn_recv_toggle.style())

    def set_target(self, ip: str, port: int, pin: str = ""):
        self.txt_recv_ip.setText(ip)
        self.spn_recv_port.setValue(port)
        if pin:
            self.txt_recv_pin.setText(pin)
