# -*- coding: utf-8 -*-
"""
DA-V Sender / Screen Sharing View
Configuration panel for video capture, hardware codecs (NVENC), network bitrate and live streaming controls.
"""

from scripts.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QSpinBox, QComboBox, QPushButton, QGroupBox,
    QFrame, Signal, Qt
)
from src.ui.theme import Theme
from src.ui.widgets.cards import StatCard
from scripts.dav_sender_worker import enumerate_system_monitors


class SenderView(QWidget):
    """View dedicated to screen capture and video stream broadcasting."""
    send_toggled = Signal()

    def __init__(self, initial_target_ip: str, default_target_port: int, initial_pin: str, parent=None):
        super().__init__(parent)
        self.initial_target_ip = initial_target_ip
        self.default_target_port = default_target_port
        self.initial_pin = initial_pin
        self.is_sending = False

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD)
        layout.setSpacing(Theme.SPACE_MD)

        # ── Capture & Codec Options Card ──
        opts_group = QGroupBox("Parâmetros da Transmissão de Vídeo & Hardware")
        grid = QGridLayout(opts_group)
        grid.setContentsMargins(Theme.SPACE_LG, Theme.SPACE_LG, Theme.SPACE_LG, Theme.SPACE_LG)
        grid.setSpacing(Theme.SPACE_MD)

        # Row 0: Target IP and Target UDP Port
        grid.addWidget(QLabel("IP Alvo (Destino):"), 0, 0)
        self.txt_send_ip = QLineEdit(self.initial_target_ip)
        grid.addWidget(self.txt_send_ip, 0, 1)

        grid.addWidget(QLabel("Porta UDP Alvo:"), 0, 2)
        self.spn_send_port = QSpinBox()
        self.spn_send_port.setRange(1024, 65535)
        self.spn_send_port.setValue(self.default_target_port)
        grid.addWidget(self.spn_send_port, 0, 3)

        # Row 1: Monitor & Video Codec
        grid.addWidget(QLabel("Monitor de Origem:"), 1, 0)
        self.cmb_monitor = QComboBox()
        mons = enumerate_system_monitors()
        for i, m in enumerate(mons):
            prim = " (Principal)" if m.get("is_primary") else " (Secundário)"
            self.cmb_monitor.addItem(f"Monitor {i+1}{prim} — {m['width']}x{m['height']}")
        grid.addWidget(self.cmb_monitor, 1, 1)

        grid.addWidget(QLabel("Codec de Vídeo:"), 1, 2)
        self.cmb_codec = QComboBox()
        self.cmb_codec.addItems([
            "NVIDIA NVENC H.264 (RTX 4070 - Ultra-Low Latency)",
            "NVIDIA NVENC HEVC (RTX 4070 - Alta Compressão)",
            "JPEG SIMD Vetorizado (Universal CPU/GPU)",
            "RAW DIB Sem Compressão (LAN Local)"
        ])
        grid.addWidget(self.cmb_codec, 1, 3)

        # Row 2: Resolution & FPS
        grid.addWidget(QLabel("Resolução de Saída:"), 2, 0)
        self.cmb_res = QComboBox()
        self.cmb_res.addItems([
            "1920x1080 (Full HD - 60 FPS)",
            "1280x720 (HD - 60 FPS Otimizado)",
            "640x360 (Baixo Consumo)"
        ])
        grid.addWidget(self.cmb_res, 2, 1)

        grid.addWidget(QLabel("Taxa de Quadros (FPS):"), 2, 2)
        self.cmb_fps = QComboBox()
        self.cmb_fps.addItems(["60 FPS (Ultra-Fluido)", "30 FPS (Econômico)"])
        grid.addWidget(self.cmb_fps, 2, 3)

        # Row 3: Bitrate & Shared PIN
        grid.addWidget(QLabel("Taxa de Bits (Bitrate):"), 3, 0)
        self.cmb_bitrate = QComboBox()
        self.cmb_bitrate.addItems([
            "12000 kbps (12 Mbps - 1080p 60 FPS)",
            "8000 kbps (8 Mbps)",
            "16000 kbps (16 Mbps)",
            "25000 kbps (25 Mbps Ultra HD)"
        ])
        grid.addWidget(self.cmb_bitrate, 3, 1)

        grid.addWidget(QLabel("PIN de Autenticação:"), 3, 2)
        self.txt_send_pin = QLineEdit(self.initial_pin)
        grid.addWidget(self.txt_send_pin, 3, 3)

        layout.addWidget(opts_group)

        # ── Action Bar / Broadcast Status ──
        action_card = QFrame()
        action_card.setStyleSheet(f"""
            QFrame {{
                background-color: {Theme.SYS["bg_surface_card"]};
                border-radius: {Theme.RADIUS_MD}px;
                border: 1px solid {Theme.SYS["border_subtle"]};
            }}
        """)
        act_layout = QHBoxLayout(action_card)
        act_layout.setContentsMargins(Theme.SPACE_LG, Theme.SPACE_MD, Theme.SPACE_LG, Theme.SPACE_MD)

        self.lbl_send_status = QLabel("Status: Transmissor Inativo")
        self.lbl_send_status.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {Theme.SYS['text_muted']};")
        act_layout.addWidget(self.lbl_send_status)

        act_layout.addStretch()

        self.btn_send_toggle = QPushButton("Iniciar Compartilhamento")
        self.btn_send_toggle.setMinimumWidth(240)
        self.btn_send_toggle.clicked.connect(self.send_toggled.emit)
        act_layout.addWidget(self.btn_send_toggle)

        layout.addWidget(action_card)

        # ── Output Stats Cards ──
        stats_group = QGroupBox("Estatísticas de Saída em Tempo Real")
        stats_layout = QHBoxLayout(stats_group)
        stats_layout.setContentsMargins(Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD)
        stats_layout.setSpacing(Theme.SPACE_MD)

        self.card_fps = StatCard("Taxa de Quadros", "0.0 FPS", "Alvo: 60 FPS", Theme.SYS["accent_primary"])
        self.card_mbps = StatCard("Vazão de Saída", "0.00 Mbps", "Rede local UDP", Theme.SYS["status_info"])
        self.card_frames = StatCard("Quadros Enviados", "0", "H.264 NAL Units", Theme.SYS["status_success"])
        self.card_packets = StatCard("Pacotes Fragmentados", "0", "MTU 1350 bytes", Theme.SYS["status_warning"])

        stats_layout.addWidget(self.card_fps)
        stats_layout.addWidget(self.card_mbps)
        stats_layout.addWidget(self.card_frames)
        stats_layout.addWidget(self.card_packets)

        layout.addWidget(stats_group)
        layout.addStretch()

    def set_sending_state(self, is_sending: bool, details: str = ""):
        self.is_sending = is_sending
        if is_sending:
            self.btn_send_toggle.setText("Parar Compartilhamento")
            self.btn_send_toggle.setObjectName("stopBtn")
            self.lbl_send_status.setText(f"Status: Transmitindo ao Vivo ({details})")
            self.lbl_send_status.setStyleSheet(f"color: {Theme.SYS['status_success']}; font-weight: 700; font-size: 14px;")
        else:
            self.btn_send_toggle.setText("Iniciar Compartilhamento")
            self.btn_send_toggle.setObjectName("")
            self.lbl_send_status.setText("Status: Transmissor Inativo")
            self.lbl_send_status.setStyleSheet(f"color: {Theme.SYS['text_muted']}; font-weight: 700; font-size: 14px;")
        self.btn_send_toggle.setStyle(self.btn_send_toggle.style())

    def update_stats(self, fps: float, mbps: float, frames: int, packets: int):
        self.card_fps.set_value(f"{fps:.1f} FPS")
        self.card_mbps.set_value(f"{mbps:.2f} Mbps")
        self.card_frames.set_value(f"{frames:,}")
        self.card_packets.set_value(f"{packets:,}")
