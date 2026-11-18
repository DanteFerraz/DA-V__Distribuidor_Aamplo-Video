# -*- coding: utf-8 -*-
"""
DA-V Glass Design System - Overlay Sheets
Autor: Dante Ferraz (MonoTech)

Folhas tecnicas sobrepostas em vidro escuro translucido:
- SettingsSheet: Configuracoes de Receptor, Transmissor e Sistema
- StatsSheet: Telemetria TUPA, Dispositivos LAN e Registros / Diagnostico
"""

from __future__ import annotations

from typing import List, Optional

from src.dav.modules.capture.service import enumerate_system_monitors
from src.ui.qt_compat import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)
from src.ui.glass import qss
from src.ui.glass import tokens as T
from src.ui.glass.widgets import (
    CardPage,
    GlassButton,
    GlassScrollArea,
    GlassSegmented,
)
from src.ui.views.discovery_view import DiscoveryView
from src.ui.views.troubleshoot_view import TroubleshootView
from src.ui.views.tupa_view import TupaView


class BaseOverlaySheet(CardPage):
    """Base de folha modal translucida com abas segmentadas e area rolavel."""

    close_requested = Signal()

    def __init__(self, tabs: List[str], parent=None):
        super().__init__(parent, dark=True, frac=T.SHEET_FRAC)
        self._last_qss_scale = -1.0

        lay = self.card.content_layout
        lay.setSpacing(T.px(18, 1.0, 6))

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)

        self.btn_close = GlassButton(
            "Fechar",
            design_w=138,
            design_h=54,
            design_font=T.FONT_HINT,
            parent=self.card,
        )
        self.btn_close.setToolTip("Fechar painel (Esc)")
        self.btn_close.clicked.connect(self.close_requested.emit)

        self._left_balance = QWidget(self.card)
        self._left_balance.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._left_balance.setStyleSheet("background: transparent;")
        self._left_balance.setFixedWidth(self.btn_close.width())

        self.segmented = GlassSegmented(tabs, parent=self.card)

        header_row.addWidget(self._left_balance)
        header_row.addStretch(1)
        header_row.addWidget(self.segmented, alignment=Qt.AlignmentFlag.AlignCenter)
        header_row.addStretch(1)
        header_row.addWidget(self.btn_close, alignment=Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(header_row)

        self.scroll = GlassScrollArea(self.card)
        self.stack = QStackedWidget(self.scroll.body)
        self.scroll.body_layout.addWidget(self.stack, stretch=1)
        lay.addWidget(self.scroll, stretch=1)

        self.segmented.selected.connect(self.stack.setCurrentIndex)

    def set_tab(self, index: int) -> None:
        if 0 <= index < self.stack.count():
            self.segmented.set_current(index)
            self.stack.setCurrentIndex(index)

    def set_ui_scale(self, scale: float) -> None:
        super().set_ui_scale(scale)
        self.card.content_layout.setSpacing(T.px(18, scale, 6))
        self._left_balance.setFixedWidth(self.btn_close.width())
        if abs(scale - self._last_qss_scale) >= 0.02:
            self._last_qss_scale = scale
            self.stack.setStyleSheet(qss.sheet_qss(scale))

    def mousePressEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if not self.card.geometry().contains(pos):
            self.close_requested.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


def _refresh_button_style(btn: QPushButton) -> None:
    style = btn.style()
    style.unpolish(btn)
    style.polish(btn)
    btn.update()


def _compact_field(widget: QWidget) -> QWidget:
    widget.setMinimumWidth(0)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    if isinstance(widget, QComboBox):
        widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        widget.setMinimumContentsLength(10)
    return widget


class SettingsSheet(BaseOverlaySheet):
    """Folha de configuracoes: Receptor, Transmissor e Sistema."""

    connect_toggled = Signal()
    send_toggled = Signal()
    hud_toggled = Signal(bool)
    hud_mode_changed = Signal(str)
    audio_rx_toggled = Signal(bool)
    audio_tx_toggled = Signal(bool)
    fullscreen_requested = Signal()
    scale_mode_requested = Signal()
    screenshot_requested = Signal()
    copy_pin_requested = Signal()
    copy_invite_requested = Signal()
    regenerate_pin_requested = Signal()
    check_firewall_requested = Signal()
    fix_firewall_requested = Signal()
    loopback_requested = Signal()
    export_logs_requested = Signal()
    check_update_requested = Signal()
    about_requested = Signal()

    def __init__(
        self,
        local_ip: str,
        default_port: int,
        target_default_port: int,
        initial_pin: str,
        engine_tag: str,
        version_str: str,
        parent=None,
    ):
        super().__init__(["Receptor", "Transmissor", "Sistema"], parent=parent)
        self._local_ip = local_ip
        self._default_port = default_port
        self._target_default_port = target_default_port
        self._initial_pin = initial_pin
        self._engine_tag = engine_tag
        self._version_str = version_str
        self._is_sending = False

        self.stack.addWidget(self._build_receiver_tab())
        self.stack.addWidget(self._build_sender_tab())
        self.stack.addWidget(self._build_system_tab())
        self.set_ui_scale(1.0)

    def _build_receiver_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(14)

        conn_group = QGroupBox("Conexão Manual do Receptor")
        grid = QGridLayout(conn_group)
        grid.setSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        grid.addWidget(QLabel("IP do Transmissor:"), 0, 0)
        self.txt_recv_ip = QLineEdit("")
        self.txt_recv_ip.setPlaceholderText("Deixe vazio para PIN P2P ou IP LAN")
        grid.addWidget(_compact_field(self.txt_recv_ip), 0, 1)

        grid.addWidget(QLabel("Porta UDP:"), 0, 2)
        self.spn_recv_port = QSpinBox()
        self.spn_recv_port.setRange(1024, 65535)
        self.spn_recv_port.setValue(self._default_port)
        grid.addWidget(_compact_field(self.spn_recv_port), 0, 3)

        grid.addWidget(QLabel("PIN de Acesso:"), 1, 0)
        self.txt_recv_pin = QLineEdit(self._initial_pin)
        self.txt_recv_pin.setPlaceholderText("PIN ex: 845-747")
        self.txt_recv_pin.textChanged.connect(self._on_recv_pin_changed)
        grid.addWidget(_compact_field(self.txt_recv_pin), 1, 1)

        self.btn_recv_toggle = QPushButton("Conectar e Assistir")
        self.btn_recv_toggle.clicked.connect(self.connect_toggled.emit)
        grid.addWidget(self.btn_recv_toggle, 1, 2, 1, 2)

        lay.addWidget(conn_group)

        display_group = QGroupBox("Exibição e Atalhos do Player")
        disp_lay = QVBoxLayout(display_group)
        disp_lay.setSpacing(10)

        row_hud = QHBoxLayout()
        row_hud.setSpacing(12)
        self.chk_hud = QCheckBox("Exibir HUD de telemetria sobre o vídeo")
        self.chk_hud.setChecked(True)
        self.chk_hud.toggled.connect(self.hud_toggled.emit)
        row_hud.addWidget(self.chk_hud)

        row_hud.addStretch(1)
        row_hud.addWidget(QLabel("Estilo do HUD:"))
        self.cmb_hud_mode = QComboBox()
        self.cmb_hud_mode.addItems(["Pílula Compacta (Padrão)", "Painel Completo (F2)"])
        self.cmb_hud_mode.currentIndexChanged.connect(
            lambda idx: self.hud_mode_changed.emit("pill" if idx == 0 else "full")
        )
        row_hud.addWidget(_compact_field(self.cmb_hud_mode))
        disp_lay.addLayout(row_hud)

        self.chk_audio_rx = QCheckBox("Reproduzir áudio do sistema remoto (Opus Low-Delay)")
        self.chk_audio_rx.setChecked(True)
        self.chk_audio_rx.toggled.connect(self.audio_rx_toggled.emit)
        disp_lay.addWidget(self.chk_audio_rx)

        act_grid = QGridLayout()
        act_grid.setSpacing(8)
        act_grid.setColumnStretch(0, 1)
        act_grid.setColumnStretch(1, 1)

        btn_fs = QPushButton("Tela Cheia (F11)")
        btn_fs.clicked.connect(self.fullscreen_requested.emit)
        act_grid.addWidget(btn_fs, 0, 0)

        btn_hud_cycle = QPushButton("Alternar HUD (F2 / H)")
        btn_hud_cycle.clicked.connect(lambda: self.cmb_hud_mode.setCurrentIndex(1 - self.cmb_hud_mode.currentIndex()))
        act_grid.addWidget(btn_hud_cycle, 0, 1)

        btn_scale = QPushButton("Ajustar / Preencher (F3 / M)")
        btn_scale.clicked.connect(self.scale_mode_requested.emit)
        act_grid.addWidget(btn_scale, 1, 0)

        btn_shot = QPushButton("Capturar Quadro (F12)")
        btn_shot.clicked.connect(self.screenshot_requested.emit)
        act_grid.addWidget(btn_shot, 1, 1)
        disp_lay.addLayout(act_grid)

        lbl_shortcuts = QLabel(
            "Atalhos na transmissão ao vivo: F11 Tela cheia · F2 / H Alternar HUD · "
            "F3 / M Proporção · F12 Capturar quadro · Esc Sair da tela cheia"
        )
        lbl_shortcuts.setWordWrap(True)
        lbl_shortcuts.setStyleSheet(f"color: {T.SHEET_TEXT_DIM};")
        disp_lay.addWidget(lbl_shortcuts)

        lay.addWidget(display_group)
        lay.addStretch(1)
        return page

    def _build_sender_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(14)

        opts_group = QGroupBox("Parâmetros da Transmissão de Vídeo e Hardware")
        grid = QGridLayout(opts_group)
        grid.setSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        grid.addWidget(QLabel("IP Alvo (Destino):"), 0, 0)
        self.txt_send_ip = QLineEdit("")
        self.txt_send_ip.setPlaceholderText("Vazio p/ P2P (PIN) ou IP direto")
        grid.addWidget(_compact_field(self.txt_send_ip), 0, 1)

        grid.addWidget(QLabel("Porta UDP Alvo:"), 0, 2)
        self.spn_send_port = QSpinBox()
        self.spn_send_port.setRange(1024, 65535)
        self.spn_send_port.setValue(self._target_default_port)
        grid.addWidget(_compact_field(self.spn_send_port), 0, 3)

        grid.addWidget(QLabel("Monitor de Origem:"), 1, 0)
        self.cmb_monitor = QComboBox()
        try:
            mons = enumerate_system_monitors()
        except Exception:
            mons = []
        self.monitors = mons
        if mons:
            for i, m in enumerate(mons):
                prim = " (Principal)" if m.get("is_primary") else " (Secundário)"
                self.cmb_monitor.addItem(f"Monitor {i + 1}{prim} — {m['width']}x{m['height']}")
        else:
            self.cmb_monitor.addItem("Monitor 1 (Principal) — 1920x1080")
        grid.addWidget(_compact_field(self.cmb_monitor), 1, 1)

        grid.addWidget(QLabel("Codec de Vídeo:"), 1, 2)
        self.cmb_codec = QComboBox()
        self.cmb_codec.addItems([
            "H.264 Ultra-Low Latency (Auto: NVENC GPU / libx264 SIMD)",
            "HEVC / H.265 Alta Compressão (Auto: NVENC GPU / H.264)",
            "JPEG SIMD Vetorizado (Compatibilidade Universal)",
            "RAW Sem Compressão (Rede Local Gigabit)",
        ])
        grid.addWidget(_compact_field(self.cmb_codec), 1, 3)

        grid.addWidget(QLabel("Resolução de Saída:"), 2, 0)
        self.cmb_res = QComboBox()
        res_items: List[str] = []
        if mons:
            nat_w = max(640, int(mons[0].get("width", 1920)) & ~1)
            nat_h = max(360, int(mons[0].get("height", 1080)) & ~1)
            if (nat_w, nat_h) not in ((1920, 1080), (1280, 720), (640, 360)):
                res_items.append(f"{nat_w}x{nat_h} (Nativa do Monitor - 60 FPS Zero Escala)")
        res_items.extend([
            "1920x1080 (Full HD - 60 FPS)",
            "1280x720 (HD - 60 FPS Otimizado)",
            "640x360 (Baixo Consumo)",
        ])
        self.cmb_res.addItems(res_items)
        grid.addWidget(_compact_field(self.cmb_res), 2, 1)

        grid.addWidget(QLabel("Taxa de Quadros (FPS):"), 2, 2)
        self.cmb_fps = QComboBox()
        self.cmb_fps.addItems(["60 FPS (Ultra-Fluido)", "30 FPS (Econômico)"])
        grid.addWidget(_compact_field(self.cmb_fps), 2, 3)

        grid.addWidget(QLabel("Taxa de Bits (Bitrate):"), 3, 0)
        self.cmb_bitrate = QComboBox()
        self.cmb_bitrate.addItems([
            "12000 kbps (12 Mbps - 1080p 60 FPS)",
            "8000 kbps (8 Mbps)",
            "16000 kbps (16 Mbps)",
            "25000 kbps (25 Mbps Ultra HD)",
        ])
        grid.addWidget(_compact_field(self.cmb_bitrate), 3, 1)

        grid.addWidget(QLabel("PIN de Autenticação:"), 3, 2)
        self.txt_send_pin = QLineEdit(self._initial_pin)
        grid.addWidget(_compact_field(self.txt_send_pin), 3, 3)

        self.chk_audio_tx = QCheckBox("Transmitir áudio do computador (WASAPI / PipeWire · Opus 48 kHz)")
        self.chk_audio_tx.setChecked(True)
        self.chk_audio_tx.toggled.connect(self.audio_tx_toggled.emit)
        grid.addWidget(self.chk_audio_tx, 4, 0, 1, 4)

        lay.addWidget(opts_group)

        ctrl_group = QGroupBox("Estado e Estatísticas de Saída")
        ctrl_lay = QVBoxLayout(ctrl_group)
        ctrl_lay.setSpacing(10)

        top_row = QHBoxLayout()
        self.lbl_send_status = QLabel("Status: Transmissor Inativo")
        self.lbl_send_status.setStyleSheet(f"font-weight: 700; color: {T.SHEET_TEXT_DIM};")
        top_row.addWidget(self.lbl_send_status)
        top_row.addStretch(1)
        self.btn_send_toggle = QPushButton("Iniciar Transmissão")
        self.btn_send_toggle.clicked.connect(self.send_toggled.emit)
        top_row.addWidget(self.btn_send_toggle)
        ctrl_lay.addLayout(top_row)

        stats_grid = QGridLayout()
        stats_grid.setSpacing(10)
        self.lbl_stat_fps = QLabel("FPS: 0.0")
        self.lbl_stat_mbps = QLabel("Vazão: 0.00 Mbps")
        self.lbl_stat_frames = QLabel("Quadros: 0")
        self.lbl_stat_packets = QLabel("Pacotes: 0")
        for col, lbl in enumerate(
            (self.lbl_stat_fps, self.lbl_stat_mbps, self.lbl_stat_frames, self.lbl_stat_packets)
        ):
            lbl.setStyleSheet("font-weight: 600;")
            stats_grid.addWidget(lbl, 0, col)
        ctrl_lay.addLayout(stats_grid)

        lay.addWidget(ctrl_group)
        lay.addStretch(1)
        return page

    def _build_system_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(14)

        id_group = QGroupBox("Sessão e Chave de Acesso P2P")
        id_lay = QVBoxLayout(id_group)
        id_lay.setSpacing(10)

        info_grid = QGridLayout()
        info_grid.setSpacing(8)
        self.lbl_my_pin = QLabel(f"Meu PIN P2P: {self._initial_pin}")
        self.lbl_my_pin.setStyleSheet("font-weight: 700; color: #a7f3d0;")
        self.lbl_local_ip = QLabel(f"Endereço LAN: {self._local_ip}:{self._default_port}")
        self.lbl_engine = QLabel(f"Motor: {self._engine_tag}")
        self.lbl_version = QLabel(f"Versão: v{self._version_str}")

        info_grid.addWidget(self.lbl_my_pin, 0, 0)
        info_grid.addWidget(self.lbl_local_ip, 0, 1)
        info_grid.addWidget(self.lbl_engine, 1, 0)
        info_grid.addWidget(self.lbl_version, 1, 1)
        id_lay.addLayout(info_grid)

        pin_btns = QHBoxLayout()
        pin_btns.setSpacing(10)
        for text, sig in (
            ("Copiar PIN", self.copy_pin_requested),
            ("Copiar Convite (dav://)", self.copy_invite_requested),
            ("Gerar Novo PIN", self.regenerate_pin_requested),
        ):
            btn = QPushButton(text)
            btn.setMinimumWidth(0)
            btn.clicked.connect(sig.emit)
            pin_btns.addWidget(btn, stretch=1)
        id_lay.addLayout(pin_btns)

        lay.addWidget(id_group)

        tools_group = QGroupBox("Rede, Diagnóstico e Atualizações")
        tools_grid = QGridLayout(tools_group)
        tools_grid.setSpacing(10)
        tools_grid.setColumnStretch(0, 1)
        tools_grid.setColumnStretch(1, 1)

        actions = [
            ("Verificar Firewall", self.check_firewall_requested),
            ("Liberar Portas UDP (9000-9020)", self.fix_firewall_requested),
            ("Testar Loopback Local", self.loopback_requested),
            ("Exportar Diagnóstico (.zip)", self.export_logs_requested),
            ("Buscar Atualizações", self.check_update_requested),
            ("Sobre o Autor (MonoTech)", self.about_requested),
        ]
        for idx, (label, sig) in enumerate(actions):
            btn = QPushButton(label)
            btn.setMinimumWidth(0)
            btn.clicked.connect(sig.emit)
            tools_grid.addWidget(btn, idx // 2, idx % 2)

        lay.addWidget(tools_group)
        lay.addStretch(1)
        return page

    def _on_recv_pin_changed(self, text: str) -> None:
        if "/" in text or "dav:" in text.lower():
            extracted = text.strip().rstrip("/").split("/")[-1].strip()
            if extracted and extracted != text:
                self.txt_recv_pin.blockSignals(True)
                self.txt_recv_pin.setText(extracted)
                self.txt_recv_pin.blockSignals(False)

    def set_connection_state(self, connected: bool) -> None:
        if connected:
            self.btn_recv_toggle.setText("Desconectar")
            self.btn_recv_toggle.setObjectName("stopBtn")
        else:
            self.btn_recv_toggle.setText("Conectar e Assistir")
            self.btn_recv_toggle.setObjectName("")
        _refresh_button_style(self.btn_recv_toggle)

    def set_target(self, ip: str, port: int, pin: str = "") -> None:
        self.txt_recv_ip.setText(ip)
        self.spn_recv_port.setValue(port)
        if pin:
            self.txt_recv_pin.setText(pin)

    def set_sending_state(self, is_sending: bool, details: str = "") -> None:
        self._is_sending = is_sending
        if is_sending:
            self.btn_send_toggle.setText("Parar Transmissão")
            self.btn_send_toggle.setObjectName("stopBtn")
            self.lbl_send_status.setText(f"Status: Transmitindo ao Vivo ({details})")
            self.lbl_send_status.setStyleSheet("font-weight: 700; color: #a7f3d0;")
        else:
            self.btn_send_toggle.setText("Iniciar Transmissão")
            self.btn_send_toggle.setObjectName("")
            self.lbl_send_status.setText("Status: Transmissor Inativo")
            self.lbl_send_status.setStyleSheet(f"font-weight: 700; color: {T.SHEET_TEXT_DIM};")
        _refresh_button_style(self.btn_send_toggle)

    def update_stats(self, fps: float, mbps: float, frames: int, packets: int) -> None:
        self.lbl_stat_fps.setText(f"FPS: {fps:.1f}")
        self.lbl_stat_mbps.setText(f"Vazão: {mbps:.2f} Mbps")
        self.lbl_stat_frames.setText(f"Quadros: {frames:,}")
        self.lbl_stat_packets.setText(f"Pacotes: {packets:,}")

    def update_pin(self, pin: str) -> None:
        self.lbl_my_pin.setText(f"Meu PIN P2P: {pin}")
        self.txt_send_pin.setText(pin)


class StatsSheet(BaseOverlaySheet):
    """Folha de telemetria e diagnostico: TUPA, Dispositivos LAN e Registros."""

    def __init__(self, parent=None):
        super().__init__(["Telemetria", "Dispositivos", "Registros"], parent=parent)
        self.view_tupa = TupaView(self.stack)
        self.view_discovery = DiscoveryView(self.stack)
        self.view_troubleshoot = TroubleshootView(self.stack)

        self.stack.addWidget(self.view_tupa)
        self.stack.addWidget(self.view_discovery)
        self.stack.addWidget(self.view_troubleshoot)
        self.set_ui_scale(1.0)

    def set_peer_count(self, count: int) -> None:
        label = f"Dispositivos ({count})" if count > 0 else "Dispositivos"
        self.segmented.set_item_text(1, label)
