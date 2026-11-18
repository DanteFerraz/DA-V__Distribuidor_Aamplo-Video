# -*- coding: utf-8 -*-
"""
DA-V — Janela Principal da Aplicacao (v4.1 Glass UI)
Autor: Dante Ferraz (MonoTech)

Shell principal de tela unica em vidro translucido sobre gradiente mint-teal:
- Pilula flutuante superior (Configuracoes | Troca de Modo | Telemetria/Estatisticas)
- Tela de entrada minima (Modo Espectador / Conectando... / Video em tela cheia / Modo Transmissor)
- Folhas sobrepostas translucidas com todos os controles avancados, TUPA, LAN e Diagnosticos
"""

import os
import platform
import random
import re
import socket
import sys
import threading
import time
from typing import Any, Optional

from src.dav.kernel.registry import ModuleRegistry
from src.dav.modules.audio.service import AudioService
from src.dav.modules.stream_engine.service import StreamEngineService
from src.dav.modules.telemetry.service import TelemetryService
from src.dav.modules.telemetry.tupa_checker import TupaMetricsSnapshot
from src.dav.modules.transport_p2p.blind_relay import normalize_pin
from src.dav.modules.transport_p2p.service import TransportService
from src.dav.modules.transport_p2p.signaling_client import P2PChannelClient
from src.ui.audio_sink import DesktopAudioPlayer
from src.ui.bridge import DecodeWorker, EngineBridge, find_available_port
from src.ui.glass import paint as glass_paint
from src.ui.glass import tokens as T
from src.ui.glass.nav_pill import FloatingNavPill
from src.ui.glass.sheets import SettingsSheet, StatsSheet
from src.ui.glass.views import (
    SenderHomePage,
    ViewerConnectingPage,
    ViewerIdlePage,
    parse_access_input,
)
from src.ui.glass.widgets import VideoOverlayControls
from src.ui.qt_compat import (
    QApplication,
    QEvent,
    QKeySequence,
    QMainWindow,
    QMessageBox,
    QPainter,
    QShortcut,
    QStackedWidget,
    Qt,
    QTimer,
    QWidget,
    Signal,
    Slot,
)
from src.ui.widgets.canvas import VideoCanvasWidget

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _detect_engine_badge(is_native: bool) -> str:
    if is_native:
        return "Nativo C-ABI (dav_core)"
    os_tag = "Windows" if sys.platform == "win32" else f"Linux ({platform.machine()})"
    return f"SQP + FEC GF(2^8) + PAKE · {os_tag}"


def _is_valid_ipv4(ip_str: str) -> bool:
    parts = ip_str.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


class DavMainWindow(QMainWindow):
    """Shell principal da interface desktop do DA-V no sistema visual vidro."""

    PAGE_VIEWER_IDLE = 0
    PAGE_VIEWER_CONN = 1
    PAGE_VIDEO = 2
    PAGE_SENDER = 3

    peers_updated_signal = Signal(list)
    tupa_metrics_signal = Signal(object)
    target_updated_signal = Signal(str, int, str)
    update_checked_signal = Signal(object, bool)

    def __init__(
        self,
        custom_port: Optional[int] = None,
        custom_target_port: Optional[int] = None,
        auto_recv: bool = False,
        auto_send: bool = False,
        monitor_idx: int = 1,
        custom_pin: Optional[str] = None,
        p2p_uri_mode: bool = False,
        kernel: Optional[ModuleRegistry] = None,
        parent=None,
    ):
        super().__init__(parent)
        if kernel is None:
            kernel = ModuleRegistry()
            kernel.discover()
        self.kernel = kernel
        self.transport_service: TransportService = self.kernel.get_service("transport_p2p") or TransportService()
        self.audio_service: AudioService = self.kernel.get_service("audio") or AudioService()
        self.telemetry_service: TelemetryService = self.kernel.get_service("telemetry") or TelemetryService()

        self.version_str = self._load_version()
        self.setWindowTitle(f"DA-V v{self.version_str} — Distribuidor Amplo de Vídeo")
        self.setMinimumSize(1120, 740)
        self.resize(1280, 740)

        self.local_ip = self.transport_service.get_local_ip()
        self.hostname = socket.gethostname()
        self.default_port = custom_port if custom_port else find_available_port(9000)
        self.target_default_port = custom_target_port if custom_target_port else (
            9002 if self.default_port == 9000 else 9000
        )

        if custom_pin:
            self.my_pin = custom_pin
        elif auto_recv or auto_send:
            self.my_pin = "777-888"
        else:
            self.my_pin = f"{random.randint(100, 999)}-{random.randint(100, 999)}"

        self.mode = "viewer"
        self.active_sheet: Optional[str] = None
        self.is_receiving = False
        self.is_sending = False
        self._waiting_first_frame = False
        self.cur_fps = 0.0
        self.cur_mbps = 0.0
        self.cur_lat = 0.0
        self.pkts_count = 0
        self.frames_count = 0
        self._last_rx_log_time = 0.0
        self._last_rx_log_frames = 0
        self._last_tx_log_time = 0.0
        self._last_tx_log_frames = 0
        self._tx_mbps_sum = 0.0
        self._tx_mbps_samples = 0
        self._active_p2p_client: Optional[P2PChannelClient] = None
        self._sender_session_epoch: int = 0
        self._active_peer_endpoint: Optional[tuple[str, int]] = None
        self._is_closing: bool = False

        self._conn_hint_timer = QTimer(self)
        self._conn_hint_timer.setSingleShot(True)
        self._conn_hint_timer.timeout.connect(self._on_conn_wait_timeout)

        self.engine: StreamEngineService = self.kernel.get_service("stream_engine") or StreamEngineService()
        self.bridge = EngineBridge()
        self.bridge.frame_ready.connect(self._on_frame_rendered)
        self.bridge.telemetry_ready.connect(self._on_telemetry_updated)
        self.bridge.sender_stats.connect(self._on_sender_stats_updated)
        self.bridge.log_message.connect(self._append_log)

        self._decode_worker = DecodeWorker(self.bridge)
        self._decode_worker.decoded.connect(self._on_decoded_frame)
        self._decode_worker.start()
        self.audio_player = DesktopAudioPlayer(
            parent=self,
            jitter_buffer=self.audio_service.create_jitter_buffer(),
        )

        self.peers_updated_signal.connect(self._on_peers_discovered)
        self.beacon_service = self.transport_service.create_lan_beacon(
            self.hostname, stream_port=self.default_port, pin=self.my_pin
        )
        self.beacon_service.on_peers_updated = lambda peers: self.peers_updated_signal.emit(peers)
        self.beacon_service.start()

        self.tupa_checker = self.telemetry_service.create_tupa_checker(sample_interval_sec=1.0)
        self.tupa_metrics_signal.connect(self._on_tupa_metrics_updated)
        self.target_updated_signal.connect(self._on_target_updated)
        self.tupa_checker.start(lambda snap: self.tupa_metrics_signal.emit(snap))

        self._init_ui()

        self.updater_service = None
        try:
            from src.dav.modules.updater.service import UpdaterService
            self.updater_service = UpdaterService(current_version=self.version_str)
        except Exception as exc:
            self._append_log("WARN", f"Módulo de atualização não inicializado: {exc}")

        self.update_checked_signal.connect(self._handle_update_check_result)

        backend_tag = _detect_engine_badge(self.engine.is_native_backend)
        self._append_log(
            "INFO",
            f"DA-V v{self.version_str} pronto em {self.local_ip}:{self.default_port} ({backend_tag}).",
        )
        self._fw_init_timer = QTimer(self)
        self._fw_init_timer.setSingleShot(True)
        self._fw_init_timer.timeout.connect(self._check_firewall_status)
        self._fw_init_timer.start(1000)

        self._upd_init_timer = QTimer(self)
        self._upd_init_timer.setSingleShot(True)
        self._upd_init_timer.timeout.connect(self._check_updates_on_startup)
        self._upd_init_timer.start(2500)

        if auto_recv:
            recv_auto_ip = "" if p2p_uri_mode else "127.0.0.1"
            self.settings_sheet.set_target(recv_auto_ip, self.default_port, self.my_pin)
            self.page_viewer_idle.set_access_key(self.my_pin if p2p_uri_mode else f"127.0.0.1:{self.default_port}")
            self._set_mode("viewer")
            QTimer.singleShot(600, self._toggle_receiver)

        if auto_send:
            self.settings_sheet.txt_send_ip.setText("127.0.0.1")
            self.settings_sheet.spn_send_port.setValue(self.target_default_port)
            self.settings_sheet.txt_send_pin.setText(self.my_pin)
            if 0 <= monitor_idx < self.settings_sheet.cmb_monitor.count():
                self.settings_sheet.cmb_monitor.setCurrentIndex(monitor_idx)
            self._set_mode("sender")
            QTimer.singleShot(800, self._toggle_sender)

    def _load_version(self) -> str:
        from src.dav import get_version
        return get_version()

    def _init_ui(self):
        self.central_host = QWidget(self)
        self.central_host.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCentralWidget(self.central_host)

        # Pilha principal de telas focais (edge-to-edge)
        self.stage_stack = QStackedWidget(self.central_host)
        self.stage_stack.setStyleSheet("QStackedWidget { background: transparent; border: none; }")

        self.page_viewer_idle = ViewerIdlePage(self.stage_stack)
        self.page_viewer_idle.connect_submitted.connect(self._on_viewer_key_submitted)
        self.stage_stack.addWidget(self.page_viewer_idle)

        self.page_viewer_conn = ViewerConnectingPage(self.stage_stack)
        self.page_viewer_conn.cancel_requested.connect(self._cancel_connecting)
        self.stage_stack.addWidget(self.page_viewer_conn)

        self.video_canvas = VideoCanvasWidget(self.stage_stack)
        self.video_canvas.first_frame_received.connect(self._on_first_video_frame)
        self.stage_stack.addWidget(self.video_canvas)

        self.page_sender = SenderHomePage(self.stage_stack)
        self.page_sender.copy_key_clicked.connect(self._copy_sender_access_key)
        self.page_sender.toggle_send_clicked.connect(self._toggle_sender)
        self.stage_stack.addWidget(self.page_sender)

        # Folhas sobrepostas translucidas (ocultas ate acionadas pela pilula)
        backend_desc = _detect_engine_badge(self.engine.is_native_backend)
        self.settings_sheet = SettingsSheet(
            local_ip=self.local_ip,
            default_port=self.default_port,
            target_default_port=self.target_default_port,
            initial_pin=self.my_pin,
            engine_tag=backend_desc,
            version_str=self.version_str,
            parent=self.central_host,
        )
        self.settings_sheet.hide()
        self.settings_sheet.close_requested.connect(self._close_sheets)
        self.settings_sheet.connect_toggled.connect(self._toggle_receiver)
        self.settings_sheet.send_toggled.connect(self._toggle_sender)
        self.settings_sheet.hud_toggled.connect(self._on_hud_toggled)
        self.settings_sheet.hud_mode_changed.connect(self._on_hud_mode_changed)
        self.settings_sheet.audio_rx_toggled.connect(self._on_audio_rx_toggled)
        self.settings_sheet.audio_tx_toggled.connect(self._on_audio_tx_toggled)
        self.settings_sheet.fullscreen_requested.connect(self._toggle_fullscreen)
        self.settings_sheet.scale_mode_requested.connect(self.video_canvas.toggle_scale_mode)
        self.settings_sheet.screenshot_requested.connect(self._take_screenshot)
        self.settings_sheet.copy_pin_requested.connect(self._copy_sender_access_key)
        self.settings_sheet.copy_invite_requested.connect(self._copy_invite_uri)
        self.settings_sheet.regenerate_pin_requested.connect(self._regenerate_pin)
        self.settings_sheet.check_firewall_requested.connect(self._check_firewall_status)
        self.settings_sheet.fix_firewall_requested.connect(self._fix_firewall)
        self.settings_sheet.loopback_requested.connect(self._run_loopback_diagnostic)
        self.settings_sheet.export_logs_requested.connect(self._export_diagnostic_bundle)
        self.settings_sheet.check_update_requested.connect(self._manual_check_updates)
        self.settings_sheet.about_requested.connect(self._show_author_showcase)

        self.stats_sheet = StatsSheet(parent=self.central_host)
        self.stats_sheet.hide()
        self.stats_sheet.close_requested.connect(self._close_sheets)

        self.view_tupa = self.stats_sheet.view_tupa
        self.view_discovery = self.stats_sheet.view_discovery
        self.view_troubleshoot = self.stats_sheet.view_troubleshoot

        self.view_discovery.connect_peer_requested.connect(self._quick_connect_peer)
        self.view_discovery.refresh_requested.connect(self._manual_refresh_peers)
        self.view_troubleshoot.loopback_requested.connect(self._run_loopback_diagnostic)
        self.view_troubleshoot.fix_firewall_requested.connect(self._fix_firewall)
        self.view_troubleshoot.check_firewall_requested.connect(self._check_firewall_status)
        self.view_troubleshoot.export_logs_requested.connect(self._export_diagnostic_bundle)
        self.view_troubleshoot.check_update_requested.connect(self._manual_check_updates)

        # Controles flutuantes no canto inferior direito (Audio & Tela Cheia)
        self.overlay_controls = VideoOverlayControls(self.central_host)
        self.overlay_controls.audio_toggled.connect(self._on_overlay_audio_clicked)
        self.overlay_controls.fullscreen_toggled.connect(self._toggle_fullscreen)
        self.overlay_controls.hide()

        # Pilula flutuante de navegacao no topo central
        self.nav_pill = FloatingNavPill(self.central_host)
        self.nav_pill.settings_clicked.connect(lambda: self._toggle_sheet("settings"))
        self.nav_pill.swap_clicked.connect(self._swap_mode)
        self.nav_pill.stats_clicked.connect(lambda: self._toggle_sheet("stats"))
        self.nav_pill.set_swap_tooltip("Alternar para Modo Transmissor")
        self.nav_pill.raise_()

        # Atalho global para exportacao de diagnostico
        try:
            self.shortcut_diag = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
            self.shortcut_diag.activated.connect(self._export_diagnostic_bundle)
        except Exception:
            pass

        self._set_mode("viewer")
        self._sync_layout_geometry()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w > 0 and h > 0:
            pix = glass_paint.background_pixmap(w, h, self.devicePixelRatioF())
            p = QPainter(self)
            p.drawPixmap(0, 0, pix)
            p.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_layout_geometry()

    def _sync_layout_geometry(self):
        w = self.central_host.width() or self.width()
        h = self.central_host.height() or self.height()
        if w < 10 or h < 10:
            return
        scale = T.ui_scale(w, h)
        self.stage_stack.setGeometry(0, 0, w, h)
        self.settings_sheet.setGeometry(0, 0, w, h)
        self.stats_sheet.setGeometry(0, 0, w, h)

        self.page_viewer_idle.set_ui_scale(scale)
        self.page_viewer_conn.set_ui_scale(scale)
        self.page_sender.set_ui_scale(scale)
        self.settings_sheet.set_ui_scale(scale)
        self.stats_sheet.set_ui_scale(scale)
        self.nav_pill.set_ui_scale(scale)
        self.nav_pill.reposition()
        self.overlay_controls.set_ui_scale(scale)
        self.overlay_controls.reposition()

        self.overlay_controls.raise_()
        if self.active_sheet == "settings":
            self.settings_sheet.raise_()
        elif self.active_sheet == "stats":
            self.stats_sheet.raise_()
        self.nav_pill.raise_()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "overlay_controls"):
            self.overlay_controls.set_fullscreen(self.isFullScreen())

    def _toggle_fullscreen(self):
        self.video_canvas.toggle_fullscreen()
        if hasattr(self, "overlay_controls"):
            self.overlay_controls.set_fullscreen(self.isFullScreen())

    def _sync_overlay_controls_state(self):
        if not hasattr(self, "overlay_controls"):
            return
        cur_page = self.stage_stack.currentIndex()
        show_overlay = (
            cur_page == self.PAGE_VIDEO
            or (cur_page == self.PAGE_SENDER and self.is_sending)
        )
        muted = (
            not self.settings_sheet.chk_audio_tx.isChecked()
            if self.mode == "sender"
            else not self.settings_sheet.chk_audio_rx.isChecked()
        )
        self.overlay_controls.set_audio_muted(muted)
        self.overlay_controls.set_fullscreen(self.isFullScreen())
        self.overlay_controls.setVisible(show_overlay)
        if show_overlay:
            self.overlay_controls.reposition()
            self.overlay_controls.raise_()
            if self.active_sheet == "settings":
                self.settings_sheet.raise_()
            elif self.active_sheet == "stats":
                self.stats_sheet.raise_()
            self.nav_pill.raise_()

    def _on_overlay_audio_clicked(self):
        if self.mode == "sender":
            self.settings_sheet.chk_audio_tx.setChecked(
                not self.settings_sheet.chk_audio_tx.isChecked()
            )
        else:
            self.settings_sheet.chk_audio_rx.setChecked(
                not self.settings_sheet.chk_audio_rx.isChecked()
            )

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.active_sheet is not None:
                self._close_sheets()
                event.accept()
                return
            if self.isFullScreen():
                self.showNormal()
                event.accept()
                return
            if self.mode == "viewer" and self.is_receiving and self._waiting_first_frame:
                self._cancel_connecting()
                event.accept()
                return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------------
    # NAVEGACAO POR MODOS E FOLHAS
    # ------------------------------------------------------------------------
    def _set_mode(self, mode: str):
        self.mode = mode
        if mode == "sender":
            self.stage_stack.setCurrentIndex(self.PAGE_SENDER)
            self.nav_pill.set_swap_tooltip(
                "Encerre a transmissão antes de alternar de modo"
                if self.is_sending
                else "Alternar para Modo Espectador"
            )
            self.nav_pill.set_over_video(False)
            self.nav_pill.set_live(self.is_sending)
            self.settings_sheet.set_tab(1)
        else:
            if self.is_receiving and not self._waiting_first_frame:
                self.stage_stack.setCurrentIndex(self.PAGE_VIDEO)
                self.nav_pill.set_over_video(True)
            elif self.is_receiving:
                self.stage_stack.setCurrentIndex(self.PAGE_VIEWER_CONN)
                self.nav_pill.set_over_video(False)
            else:
                self.stage_stack.setCurrentIndex(self.PAGE_VIEWER_IDLE)
                self.nav_pill.set_over_video(False)
            self.nav_pill.set_swap_tooltip("Alternar para Modo Transmissor")
            self.nav_pill.set_live(self.is_receiving)
            self.settings_sheet.set_tab(0)
        self._sync_overlay_controls_state()
        self.nav_pill.raise_()

    def _swap_mode(self):
        self._close_sheets()
        if self.mode == "viewer":
            if self.is_receiving:
                self._toggle_receiver()
            self._set_mode("sender")
            self._append_log("INFO", "Alternado para Modo Transmissor.")
        else:
            if self.is_sending:
                # Protege transmissao ativa: evita interrupcao acidental no botao central da barra
                self.page_sender.flash_warning(
                    "Transmissão em andamento. Clique em 'Parar Transmissão' antes de alternar de modo."
                )
                self._append_log(
                    "WARN",
                    "Alternância de modo bloqueada enquanto a transmissão está ativa.",
                )
                return
            self._set_mode("viewer")
            self.page_viewer_idle.focus_input()
            self._append_log("INFO", "Alternado para Modo Espectador.")

    def _toggle_sheet(self, which: str):
        if self.active_sheet == which:
            self._close_sheets()
            return
        self.settings_sheet.hide()
        self.stats_sheet.hide()
        self.active_sheet = which
        scale = T.ui_scale(self.width(), self.height())
        if which == "settings":
            self.settings_sheet.set_ui_scale(scale)
            self.settings_sheet.setGeometry(0, 0, self.central_host.width(), self.central_host.height())
            self.settings_sheet.show()
            self.settings_sheet.raise_()
            self.settings_sheet.setFocus()
        else:
            self.stats_sheet.set_ui_scale(scale)
            self.stats_sheet.setGeometry(0, 0, self.central_host.width(), self.central_host.height())
            self.stats_sheet.show()
            self.stats_sheet.raise_()
            self.stats_sheet.setFocus()
        self.nav_pill.set_active(which)
        self.nav_pill.raise_()

    def _close_sheets(self):
        self.active_sheet = None
        self.settings_sheet.hide()
        self.stats_sheet.hide()
        self.nav_pill.set_active(None)
        if self.mode == "viewer" and self.is_receiving and not self._waiting_first_frame:
            self.video_canvas.setFocus()

    # ------------------------------------------------------------------------
    # ACOES DA TELA FOCAL DE ESPECTADOR & TRANSMISSOR
    # ------------------------------------------------------------------------
    def _on_viewer_key_submitted(self, raw: str):
        target_ip, target_port, pin = parse_access_input(raw)
        if not target_ip and not pin:
            self.page_viewer_idle.set_status(
                "Chave inválida. Informe um PIN (6 dígitos), link dav:// ou IPv4.",
                error=True,
            )
            return
        if target_ip and not _is_valid_ipv4(target_ip):
            resolved_ip = None
            if not target_ip.replace(".", "").isdigit():
                try:
                    resolved_ip = socket.gethostbyname(target_ip)
                except OSError:
                    resolved_ip = None
            if resolved_ip and _is_valid_ipv4(resolved_ip):
                target_ip = resolved_ip
            else:
                self.page_viewer_idle.set_status(
                    f"Endereço '{target_ip}' inválido ou não resolvido.",
                    error=True,
                )
                return

        self.settings_sheet.txt_recv_ip.setText(target_ip)
        if target_port is not None:
            self.settings_sheet.spn_recv_port.setValue(target_port)
        if pin:
            self.settings_sheet.txt_recv_pin.setText(pin)

        if self.is_receiving:
            self._toggle_receiver()
        self._toggle_receiver()

    def _cancel_connecting(self):
        if self.is_receiving:
            self._toggle_receiver()
        else:
            self._conn_hint_timer.stop()
            self._waiting_first_frame = False
            self.stage_stack.setCurrentIndex(self.PAGE_VIEWER_IDLE)
            self._sync_overlay_controls_state()

    def _on_conn_wait_timeout(self):
        if self.is_receiving and self._waiting_first_frame:
            self.page_viewer_conn.set_detail("Aguardando primeiro quadro de vídeo... (Esc para cancelar)")

    def _on_first_video_frame(self):
        if self.mode == "viewer" and self.is_receiving:
            self._conn_hint_timer.stop()
            self._waiting_first_frame = False
            self.stage_stack.setCurrentIndex(self.PAGE_VIDEO)
            self.nav_pill.set_over_video(True)
            self._sync_overlay_controls_state()
            self.nav_pill.raise_()
            if self.active_sheet is None:
                self.video_canvas.setFocus()

    def _on_hud_toggled(self, checked: bool):
        self.video_canvas.show_hud = checked
        self.video_canvas.update()

    def _on_hud_mode_changed(self, mode_name: str):
        self.video_canvas.hud_mode = mode_name
        self.video_canvas.show_hud = True
        self.settings_sheet.chk_hud.blockSignals(True)
        self.settings_sheet.chk_hud.setChecked(True)
        self.settings_sheet.chk_hud.blockSignals(False)
        self.video_canvas.update()

    def _on_audio_rx_toggled(self, enabled: bool):
        self.audio_player.set_muted(not enabled)
        self._sync_overlay_controls_state()
        self._append_log("INFO", f"Audio remoto {'ativado' if enabled else 'silenciado'}.")

    def _on_audio_tx_toggled(self, enabled: bool):
        if self.is_sending:
            self.engine.set_sender_audio_muted(not enabled)
        self._sync_overlay_controls_state()
        self._append_log("INFO", f"Captura de audio do sistema {'ativada' if enabled else 'mutada'}.")

    def _take_screenshot(self):
        path = self.video_canvas.save_screenshot()
        if path:
            self._append_log("SUCCESS", f"Captura salva em: {path}")
        else:
            self._append_log("WARN", "Nenhum quadro de vídeo disponível para captura.")

    def _copy_sender_access_key(self):
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self.my_pin)
        self.page_sender.flash_copied(f"Chave copiada: {self.my_pin}")
        self._append_log("INFO", f"Chave de acesso copiada: {self.my_pin}")

    def _copy_invite_uri(self):
        uri = f"dav://connect/{self.my_pin}"
        cb = QApplication.clipboard()
        if cb:
            cb.setText(uri)
        self.page_sender.flash_copied(f"Convite copiado: {uri}")
        self._append_log("INFO", f"Link de convite copiado: {uri}")

    # ------------------------------------------------------------------------
    # AUXILIARES DE DIAGNOSTICO E ATUALIZACAO
    # ------------------------------------------------------------------------
    def _show_author_showcase(self):
        """Abre o dialogo institucional de apresentacao de Dante Ferraz e MonoTech."""
        try:
            from src.dav.modules.presentation.author_dialog import AuthorShowcaseDialog
            dlg = AuthorShowcaseDialog(self)
            dlg.exec()
        except Exception as exc:
            self._append_log("WARN", f"Falha ao abrir diálogo institucional: {exc}")

    def _export_diagnostic_bundle(self):
        """Coleta logs, telemetria e estado de rede gerando 'data-hora_DA-V-log.zip'."""
        try:
            from src.dav.modules.telemetry.diagnostic_packager import DiagnosticPackager
            logs_text = self.view_troubleshoot.txt_logs.toPlainText()
            extra_telem = {
                "fps": getattr(self, "cur_fps", 0.0),
                "bitrate_mbps": getattr(self, "cur_mbps", 0.0),
                "latency_ms": getattr(self, "cur_lat", 0.0),
                "frames_count": getattr(self, "frames_count", 0),
                "packets_count": getattr(self, "pkts_count", 0),
            }
            route_info = {
                "active_pin": getattr(self, "my_pin", ""),
                "local_ip": getattr(self, "local_ip", ""),
                "default_port": getattr(self, "default_port", 9000),
                "is_receiving": getattr(self, "is_receiving", False),
                "is_sending": getattr(self, "is_sending", False),
            }
            res = DiagnosticPackager.generate_bundle(
                logs_text=logs_text,
                extra_telemetry=extra_telem,
                route_info=route_info,
            )
            if res.is_success:
                self._append_log("SUCCESS", f"Pacote de diagnóstico gerado com sucesso: {res.value}")
                try:
                    QMessageBox.information(
                        self,
                        "Diagnóstico Exportado",
                        f"Pacote compactado gerado com sucesso em:\n\n{res.value}\n\n"
                        "Você pode compartilhar este arquivo para suporte técnico ou análise de rede.",
                    )
                except Exception:
                    pass
            else:
                self._append_log("ERROR", f"Falha ao gerar pacote de diagnóstico: {res.error}")
        except Exception as exc:
            self._append_log("ERROR", f"Exceção ao gerar diagnóstico: {exc}")

    def _check_updates_on_startup(self):
        """Verifica atualizacoes em segundo plano sem travar a interface inicial."""
        if not self.updater_service:
            return
        self._append_log("INFO", "Verificando se há atualizações disponíveis no repositório...")
        self.updater_service.start_background_check(
            on_complete=lambda res: self.update_checked_signal.emit(res, False)
        )

    def _manual_check_updates(self):
        """Dispara verificacao manual solicitada pelo usuario."""
        if not self.updater_service:
            self._append_log("WARN", "Serviço de atualização indisponível.")
            return
        self._append_log("INFO", "Buscando novas atualizações do DA-V no GitHub...")
        started = self.updater_service.start_background_check(
            on_complete=lambda res: self.update_checked_signal.emit(res, True)
        )
        if not started:
            self._append_log("WARN", "Verificação de atualizações já em andamento.")

    @Slot(object, bool)
    def _handle_update_check_result(self, result, is_manual: bool):
        """Processa o resultado da verificacao de atualizacoes na thread da UI."""
        if not result.is_success:
            if is_manual:
                self._append_log("WARN", f"Não foi possível verificar atualizações: {result.error}")
                try:
                    QMessageBox.warning(
                        self,
                        "Verificação de Atualizações",
                        f"Não foi possível consultar os servidores do DA-V no momento.\n\nDetalhe: {result.error}",
                    )
                except Exception:
                    pass
            return

        info = result.value
        if info.has_update:
            self._append_log("INFO", f"Nova versão encontrada: v{info.latest_version} (atual: v{info.current_version}).")
            self._prompt_update_consent(info)
        else:
            self._append_log("INFO", f"DA-V está atualizado (v{info.current_version}).")
            if is_manual:
                try:
                    QMessageBox.information(
                        self,
                        "DA-V Atualizado",
                        f"Você já está utilizando a versão mais recente do DA-V (v{info.current_version}).\n\n"
                        "Nenhuma atualização necessária.",
                    )
                except Exception:
                    pass

    def _prompt_update_consent(self, update_info):
        """Abre o dialogo modal de consentimento com notas de versao e instalacao."""
        try:
            from src.dav.modules.updater.update_dialog import UpdateConsentDialog
            dlg = UpdateConsentDialog(update_info=update_info, parent=self)
            dlg.exec()
        except Exception as exc:
            self._append_log("ERROR", f"Falha ao exibir diálogo de atualização: {exc}")

    # ------------------------------------------------------------------------
    # CONTROLADOR DO RECEPTOR (VIEWER) — P2P SINGLE-SOCKET & LAN DIRETO
    # ------------------------------------------------------------------------
    def _fail_receiver(self, message: str):
        self._conn_hint_timer.stop()
        if hasattr(self, "audio_player") and self.audio_player:
            self.audio_player.stop()
        self._waiting_first_frame = False
        if self.mode == "viewer":
            self.stage_stack.setCurrentIndex(self.PAGE_VIEWER_IDLE)
            self.page_viewer_idle.set_status(message, error=True)
        self.nav_pill.set_over_video(False)
        self.nav_pill.set_live(False)
        self._sync_overlay_controls_state()

    def _toggle_receiver(self):
        if self.is_receiving:
            self._conn_hint_timer.stop()
            self.audio_player.stop()
            self.engine.stop()
            self.is_receiving = False
            self._waiting_first_frame = False
            self.settings_sheet.set_connection_state(False)
            self.video_canvas.clear_display()
            self.nav_pill.set_over_video(False)
            self.nav_pill.set_live(False)
            if self.mode == "viewer":
                self.stage_stack.setCurrentIndex(self.PAGE_VIEWER_IDLE)
            self._sync_overlay_controls_state()
            self._append_log("INFO", "Receptor desconectado pelo usuário.")
            return

        target_ip = self.settings_sheet.txt_recv_ip.text().strip()
        port = self.settings_sheet.spn_recv_port.value()
        pin = self.settings_sheet.txt_recv_pin.text().strip()
        clean_pin = normalize_pin(pin)

        if target_ip and not _is_valid_ipv4(target_ip):
            if clean_pin:
                self._append_log(
                    "WARN",
                    f"[P2P] IP '{target_ip}' inválido ou incompleto. Alternando para Modo PIN Universal ('{pin}')...",
                )
                target_ip = ""
                self.settings_sheet.txt_recv_ip.setText("")
            else:
                msg = f"O IP '{target_ip}' é inválido. Informe um IPv4 completo ou PIN."
                self._append_log("ERROR", msg)
                self._fail_receiver(msg)
                return

        if not target_ip and not clean_pin:
            msg = "Informe o PIN de Acesso (6 dígitos) ou o IP do Transmissor."
            self._append_log("ERROR", msg)
            self._fail_receiver(msg)
            return

        # Exibe "Conectando..." imediatamente enquanto resolve P2P/STUN
        self._close_sheets()
        self.page_viewer_idle.set_status("")
        self.page_viewer_conn.reset()
        self.mode = "viewer"
        self.stage_stack.setCurrentIndex(self.PAGE_VIEWER_CONN)
        self.nav_pill.set_over_video(False)
        self._sync_overlay_controls_state()
        self.nav_pill.raise_()
        QApplication.processEvents()

        target_peer = None
        peer_info = None
        my_pub_ip = None
        relay_info = None
        eff_bind_port = port

        if not target_ip:
            self._append_log("INFO", f"[P2P] Alocando socket UDP e consultando STUN RFC 5389 para o PIN '{pin}'...")
            p2p = P2PChannelClient()
            recv_ep = self.engine.prepare_receiver_socket(
                port, rendezvous_host=p2p.rendezvous_host, stun_port=p2p.stun_port
            )
            eff_bind_port = int(recv_ep.get("local_port") or port)
            my_pub_ip = str(recv_ep.get("public_ip") or "")

            res = p2p.resolve_receiver_target(
                clean_pin,
                eff_bind_port,
                node_name=self.hostname,
                endpoint_info=recv_ep,
            )

            if res and res.get("status") == "paired":
                peer_info = res["peer"]
                relay_info = res.get("relay")
                my_pub_ip = str(res.get("your_public_ip") or my_pub_ip or "")
                peer_name = peer_info.get("node_name", "Transmissor")
                self._append_log(
                    "SUCCESS",
                    f"[P2P] PIN '{pin}' pareado com '{peer_name}' "
                    f"(WAN {peer_info.get('public_ip')}:{peer_info.get('public_port')} | "
                    f"LAN {peer_info.get('local_ip')}:{peer_info.get('local_port')}).",
                )
            else:
                local_peer = self.beacon_service.find_peer_by_pin(clean_pin)
                if local_peer:
                    peer_target_ip = local_peer["ip"]
                    peer_target_port = int(local_peer.get("port", port))
                    target_peer = (peer_target_ip, peer_target_port)
                    self._append_log(
                        "SUCCESS",
                        f"[P2P Local] Transmissor localizado via Beacon LAN: "
                        f"{local_peer.get('node_name')} em {peer_target_ip}:{peer_target_port}",
                    )
                else:
                    self.engine._close_prepared_recv_sock()
                    msg = f"PIN '{pin}' não encontrado. Confirme se o Transmissor está ativo."
                    self._append_log("WARN", f"[P2P] {msg}")
                    self._fail_receiver(msg)
                    return
        else:
            target_peer = (target_ip, port)

        def _on_raw_frame(frame_data, width, height, ts, is_kf):
            if isinstance(frame_data, bytes):
                self._decode_worker.submit(frame_data, width, height)

        def _on_telem(fps, mbps, lat, pkts, frames):
            self.cur_fps = fps
            self.cur_mbps = mbps
            self.cur_lat = lat
            self.pkts_count = pkts
            self.frames_count = frames
            self.bridge.telemetry_ready.emit(fps, mbps, lat, pkts, frames)

        def _on_rx_p2p_status(remote_ip: str, remote_port: int, route_label: str):
            self.bridge.log_message.emit(
                "SUCCESS",
                f"[{route_label}] Fluxo estabelecido com {remote_ip}:{remote_port}.",
            )

        def _on_audio_pkt(audio_fid: int, tx_ts_us: int, audio_payload: bytes):
            self.audio_player.push_network_packet(audio_fid, tx_ts_us, audio_payload)

        if self.settings_sheet.chk_audio_rx.isChecked():
            self.audio_player.set_muted(False)
        else:
            self.audio_player.set_muted(True)
        self.audio_player.start()

        success = self.engine.start_receiver(
            eff_bind_port,
            pin,
            _on_raw_frame,
            _on_telem,
            target_peer=target_peer,
            peer_info=peer_info,
            my_public_ip=my_pub_ip or None,
            relay_info=relay_info,
            on_p2p_status=_on_rx_p2p_status,
            on_audio_ready=_on_audio_pkt,
        )
        if success:
            self.is_receiving = True
            self._last_rx_log_time = 0.0
            self._last_rx_log_frames = 0
            self._waiting_first_frame = True
            self.video_canvas.is_connected = True
            self.settings_sheet.set_connection_state(True)
            self.nav_pill.set_live(True)
            self._conn_hint_timer.start(3000)
            mode_str = f"PIN Universal {pin}" if not target_ip else f"LAN Direto {target_ip}:{port}"
            self._append_log("INFO", f"Receptor ativo na porta UDP {eff_bind_port} ({mode_str}).")
        else:
            self.audio_player.stop()
            msg = f"Não foi possível iniciar o Receptor na porta UDP {eff_bind_port}."
            self._append_log("ERROR", msg)
            self._fail_receiver(msg)

    # ------------------------------------------------------------------------
    # CONTROLADOR DO TRANSMISSOR (SENDER) — P2P SINGLE-SOCKET & STANDBY
    # ------------------------------------------------------------------------
    def _toggle_sender(self):
        if self.is_sending:
            self._sender_session_epoch += 1
            self._active_peer_endpoint = None
            if self._active_p2p_client:
                self._active_p2p_client.stop()
                self._active_p2p_client = None
            self.engine.stop()
            self.is_sending = False
            self.settings_sheet.set_sending_state(False)
            self.page_sender.set_sending_state(False)
            self.nav_pill.set_live(False)
            if self.mode == "sender":
                self.nav_pill.set_swap_tooltip("Alternar para Modo Espectador")
            self.beacon_service.update_status(False)
            self._sync_overlay_controls_state()
            self._append_log("INFO", "Compartilhamento de tela encerrado.")
            return

        if self.is_receiving:
            self._toggle_receiver()

        target_ip = self.settings_sheet.txt_send_ip.text().strip()
        target_port = self.settings_sheet.spn_send_port.value()
        pin = self.settings_sheet.txt_send_pin.text().strip()

        res_text = self.settings_sheet.cmb_res.currentText()
        m_res = re.search(r"(\d{3,5})x(\d{3,5})", res_text)
        if m_res:
            w = max(320, int(m_res.group(1)) & ~1)
            h = max(240, int(m_res.group(2)) & ~1)
        else:
            w, h = 1280, 720
        fps = 60 if "60 FPS" in self.settings_sheet.cmb_fps.currentText() else 30

        bitrate_text = self.settings_sheet.cmb_bitrate.currentText()
        bitrate_kbps = 12000
        if "25000" in bitrate_text:
            bitrate_kbps = 25000
        elif "16000" in bitrate_text:
            bitrate_kbps = 16000
        elif "8000" in bitrate_text:
            bitrate_kbps = 8000

        codec_text = self.settings_sheet.cmb_codec.currentText()
        codec_type = (
            "h264_nvenc"
            if "H.264" in codec_text
            else ("hevc_nvenc" if "HEVC" in codec_text else ("raw" if "RAW" in codec_text else "jpeg"))
        )
        monitor_index = self.settings_sheet.cmb_monitor.currentIndex()
        sender_bind_port = self.default_port if not target_ip else target_port

        def _on_sender_stats(frames_sent, cur_fps, cur_mbps, packets, codec="NVENC", frame_kb=24):
            self.bridge.sender_stats.emit(frames_sent, cur_fps, cur_mbps, packets, 75, frame_kb)

        def _on_tx_p2p_locked(remote_ip: str, remote_port: int, mode_tag: str):
            self.bridge.log_message.emit(
                "SUCCESS",
                f"[{mode_tag}] Túnel de transmissão confirmado -> {remote_ip}:{remote_port}",
            )
            self.target_updated_signal.emit(remote_ip, remote_port, mode_tag)

        success = self.engine.start_sender(
            target_ip,
            target_port,
            pin,
            width=w,
            height=h,
            fps=fps,
            bitrate_kbps=bitrate_kbps,
            on_sender_stats=_on_sender_stats,
            codec_type=codec_type,
            monitor_index=monitor_index,
            bind_port=sender_bind_port,
            on_p2p_event=_on_tx_p2p_locked,
            on_log=lambda lvl, msg: self.bridge.log_message.emit(lvl, msg),
            audio_enabled=self.settings_sheet.chk_audio_tx.isChecked(),
        )
        if not success:
            err = f"Falha ao iniciar o Transmissor ({target_ip}:{target_port})."
            self._append_log("ERROR", err)
            self.page_sender.set_status(err, error=True)
            return

        self._sender_session_epoch += 1
        session_epoch = self._sender_session_epoch
        self._active_peer_endpoint = None
        self.is_sending = True
        self._last_tx_log_time = 0.0
        self._last_tx_log_frames = 0
        self._tx_mbps_sum = 0.0
        self._tx_mbps_samples = 0
        if target_ip:
            details = f"{w}x{h} @ {fps}fps [{codec_type.upper()}] -> {target_ip}:{target_port}"
            card_status = f"Transmitindo para {target_ip}:{target_port}"
        else:
            details = f"{w}x{h} @ {fps}fps [{codec_type.upper()}] (Standby · Aguardando PIN {pin})"
            card_status = f"Transmissão pronta · Chave {pin}"

        self.settings_sheet.set_sending_state(True, details)
        self.page_sender.set_sending_state(True, card_status)
        self.nav_pill.set_live(True)
        if self.mode == "sender":
            self.nav_pill.set_swap_tooltip("Encerre a transmissão antes de alternar de modo")
        self._sync_overlay_controls_state()
        self.beacon_service.update_status(True, pin=pin)
        dest_str = f"{target_ip}:{target_port}" if target_ip else f"Modo P2P Universal (PIN: {pin})"
        self._append_log("INFO", f"Transmissor iniciado ({dest_str}).")

        def _bg_register_sender():
            def _emit_log(level: str, msg: str):
                if not self._is_closing:
                    try:
                        self.bridge.log_message.emit(level, msg)
                    except RuntimeError:
                        pass

            try:
                ep_info = self.engine.wait_sender_endpoint(timeout=3.0)
                if self._is_closing or not self.is_sending or session_epoch != self._sender_session_epoch:
                    return

                p2p = P2PChannelClient()
                if self._is_closing or not self.is_sending or session_epoch != self._sender_session_epoch:
                    p2p.stop()
                    return
                self._active_p2p_client = p2p
                clean_pin = normalize_pin(pin)
                eff_local_port = int((ep_info or {}).get("local_port") or sender_bind_port)
                if eff_local_port != self.beacon_service.stream_port:
                    self.beacon_service.stream_port = eff_local_port

                reg_holder = {}

                def _on_receiver_paired(peer: dict):
                    if self._is_closing or not self.is_sending or session_epoch != self._sender_session_epoch:
                        return
                    my_pub_ip = reg_holder.get("your_public_ip") or (ep_info or {}).get("public_ip")
                    node_name = peer.get("node_name", "Receptor Remoto")
                    _emit_log(
                        "INFO",
                        f"[P2P] Receptor '{node_name}' solicitou conexão via PIN '{pin}'. Iniciando Hole-Punching...",
                    )
                    self.engine.pair_sender_peer(
                        peer_info=peer,
                        my_public_ip=str(my_pub_ip) if my_pub_ip else None,
                        relay_info=peer.get("_relay"),
                    )

                reg = p2p.register_as_sender(
                    clean_pin,
                    eff_local_port,
                    node_name=self.hostname,
                    on_paired_callback=_on_receiver_paired,
                    endpoint_info=ep_info,
                )
                if self._is_closing or not self.is_sending or session_epoch != self._sender_session_epoch:
                    p2p.stop()
                    return
                if reg:
                    reg_holder.update(reg)
                    pub_ep_str = f"{reg.get('your_public_ip')}:{(ep_info or {}).get('public_port', eff_local_port)}"
                    nat_str = (ep_info or {}).get("nat_type", "auto")
                    _emit_log(
                        "SUCCESS",
                        f"[P2P] PIN '{pin}' ativo no Rendezvous (Endpoint Público: {pub_ep_str} · NAT: {nat_str}).",
                    )
                else:
                    _emit_log(
                        "WARN",
                        "[P2P] Servidor Rendezvous indisponível no momento; pareamento por PIN permanece ativo na rede local (Beacon LAN).",
                    )
            except Exception as exc:
                _emit_log("DEBUG", f"[P2P] Aviso no registro assíncrono: {exc}")

        threading.Thread(target=_bg_register_sender, daemon=True, name=f"P2P-Reg-{pin}").start()

    # ------------------------------------------------------------------------
    # SINAIS E ATUALIZACOES DE TELEMETRIA DA INTERFACE
    # ------------------------------------------------------------------------
    @Slot(object, float, float, float, int, int)
    def _on_frame_rendered(self, img, fps: float, mbps: float, lat: float, pkts: int, frames: int):
        self.cur_fps = fps
        self.cur_mbps = mbps
        self.cur_lat = lat
        self.pkts_count = pkts
        self.frames_count = frames
        self.video_canvas.update_frame(img, fps, mbps, lat, pkts, frames)
        self.view_tupa.cur_fps = fps

    @Slot(object)
    def _on_decoded_frame(self, img):
        self.video_canvas.update_frame(
            img,
            self.cur_fps,
            self.cur_mbps,
            self.cur_lat,
            self.pkts_count,
            self.frames_count,
        )

    @Slot(str, int, str)
    def _on_target_updated(self, ip: str, port: int, mode_tag: str):
        if not self.is_sending:
            return
        # Preserva txt_send_ip e spn_send_port intactos para que reinicios futuros em Modo PIN
        # continuem executando descoberta STUN e registro limpo na porta padrao.
        self._active_peer_endpoint = (ip, int(port))
        res_txt = self.settings_sheet.cmb_res.currentText().split()[0]
        fps_txt = self.settings_sheet.cmb_fps.currentText().split()[0]
        details = f"{res_txt} @ {fps_txt} [{mode_tag} -> {ip}:{port}]"
        self.settings_sheet.set_sending_state(True, details)
        self.page_sender.set_sending_state(True, f"Transmitindo -> {ip}:{port}")

    @Slot(float, float, float, int, int)
    def _on_telemetry_updated(self, fps: float, mbps: float, lat: float, pkts: int, frames: int):
        self.cur_fps = fps
        self.cur_mbps = mbps
        self.cur_lat = lat
        self.pkts_count = pkts
        self.frames_count = frames
        self.video_canvas.update_telemetry_only(fps, mbps, lat, pkts, frames)
        self.view_tupa.cur_fps = fps

        now = time.perf_counter()
        if now - self._last_rx_log_time >= 2.0:
            elapsed = now - self._last_rx_log_time
            d_frames = frames - self._last_rx_log_frames
            smooth_fps = d_frames / elapsed if elapsed > 0 else fps
            self._last_rx_log_time = now
            self._last_rx_log_frames = frames
            self._append_log(
                "TELEMETRY-RX",
                f"Recepção: {smooth_fps:.1f} FPS | {mbps:.2f} Mbps | Latência: {lat:.2f} ms | "
                f"Quadros: {frames} | Pacotes: {pkts}",
            )

    @Slot(int, float, float, int, int, int)
    def _on_sender_stats_updated(
        self,
        frames: int,
        fps: float,
        mbps: float,
        packets: int,
        quality: int = 75,
        frame_kb: int = 32,
    ):
        self.cur_fps = fps
        self.cur_mbps = mbps
        self.frames_count = frames
        self.pkts_count = packets

        self.settings_sheet.update_stats(fps, mbps, frames, packets)
        self.page_sender.update_live_stats(fps, mbps)
        self.video_canvas.sender_quality = quality
        self.video_canvas.sender_frame_kb = frame_kb
        self.view_tupa.cur_fps = fps

        now = time.perf_counter()
        if self._last_tx_log_time == 0.0:
            self._last_tx_log_time = now
            self._last_tx_log_frames = frames
            self._tx_mbps_sum = 0.0
            self._tx_mbps_samples = 0
            return

        if frames > 0:
            self._tx_mbps_sum += mbps
            self._tx_mbps_samples += 1

        if now - self._last_tx_log_time >= 2.0:
            elapsed = now - self._last_tx_log_time
            d_frames = max(0, frames - self._last_tx_log_frames)
            smooth_fps = d_frames / elapsed if elapsed > 0 else fps
            avg_mbps = (
                (self._tx_mbps_sum / self._tx_mbps_samples)
                if self._tx_mbps_samples > 0
                else mbps
            )
            self._last_tx_log_time = now
            self._last_tx_log_frames = frames
            self._tx_mbps_sum = 0.0
            self._tx_mbps_samples = 0
            self._append_log(
                "TELEMETRY-TX",
                f"Envio: {smooth_fps:.1f} FPS | {avg_mbps:.2f} Mbps | {frame_kb} KB/quadro | "
                f"Quadros: {frames} | Pacotes: {packets}",
            )

    @Slot(object)
    def _on_tupa_metrics_updated(self, snap: TupaMetricsSnapshot):
        self.view_tupa.update_tupa_metrics(snap)

    @Slot(list)
    def _on_peers_discovered(self, peers: list):
        self.view_discovery.update_peers(peers)
        self.stats_sheet.set_peer_count(len(peers))

    def _quick_connect_peer(self, ip: str, port: int):
        if self.is_sending:
            self._toggle_sender()
        if self.is_receiving:
            self._toggle_receiver()
        self.settings_sheet.set_target(ip, port)
        self.page_viewer_idle.set_access_key(f"{ip}:{port}")
        self._set_mode("viewer")
        self._close_sheets()
        self._append_log("INFO", f"Conectando diretamente a {ip}:{port} na rede local...")
        QTimer.singleShot(150, self._toggle_receiver)

    def _manual_refresh_peers(self):
        self._append_log("INFO", "Executando varredura ativa na sub-rede local (Beacon UDP 9005)...")
        self.beacon_service.trigger_subnet_sweep()
        peers = self.beacon_service.get_peers()
        self._on_peers_discovered(peers)
        if not peers:
            self._append_log("WARN", "Nenhum host ativo respondeu na sub-rede local.")

    def _regenerate_pin(self):
        self.my_pin = f"{random.randint(100, 999)}-{random.randint(100, 999)}"
        self.settings_sheet.update_pin(self.my_pin)
        self.settings_sheet.txt_recv_pin.setText(self.my_pin)
        self.beacon_service.update_status(self.is_sending, self.my_pin)
        self.page_sender.flash_copied(f"Novo PIN gerado: {self.my_pin}")
        self._append_log("INFO", f"Novo código PIN gerado: {self.my_pin}")

    def _check_firewall_status(self):
        try:
            import subprocess
            if sys.platform == "win32":
                res = subprocess.run(
                    'netsh advfirewall firewall show rule name="DA-V Video Streaming"',
                    shell=True,
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0:
                    self._append_log(
                        "SUCCESS",
                        "Windows Firewall: Regras de entrada UDP (9000-9020 / 9005) ativas.",
                    )
                else:
                    self._append_log(
                        "WARN",
                        "Windows Firewall: Regra UDP não encontrada. Use 'Liberar Portas' na aba Sistema ou Registros.",
                    )
            else:
                res = subprocess.run(["which", "ufw"], capture_output=True)
                if res.returncode == 0:
                    st = subprocess.run(["sudo", "-n", "ufw", "status"], capture_output=True, text=True)
                    if "9000:9020/udp" in st.stdout or "ALLOW" in st.stdout:
                        self._append_log("SUCCESS", "Firewall Linux (UFW): Portas UDP 9000-9020 liberadas.")
                        return
                self._append_log(
                    "INFO",
                    "Linux: Caso utilize UFW ativo, libere as portas com 'sudo ufw allow 9000:9020/udp'.",
                )
        except Exception as exc:
            self._append_log("WARN", f"Verificação de Firewall ignorada: {exc}")

    def _fix_firewall(self):
        if sys.platform == "win32":
            self._append_log("INFO", "Solicitando elevação UAC para liberar portas UDP 9000-9020 e 9005...")
            try:
                import ctypes
                ps_script = os.path.join(_PROJECT_ROOT, "scripts", "setup_firewall.ps1")
                if os.path.isfile(ps_script):
                    params = f'-NoProfile -ExecutionPolicy Bypass -File "{ps_script}"'
                else:
                    inline_cmd = (
                        'netsh advfirewall firewall delete rule name="DA-V Video Streaming" | Out-Null; '
                        'netsh advfirewall firewall add rule name="DA-V Video Streaming" dir=in action=allow protocol=UDP localport=9000-9020,19000-19010 profile=any | Out-Null; '
                        'netsh advfirewall firewall add rule name="DA-V LAN Beacon" dir=in action=allow protocol=UDP localport=9005 profile=any | Out-Null'
                    )
                    params = f'-NoProfile -ExecutionPolicy Bypass -Command "{inline_cmd}"'
                ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", params, None, 1)
                self._append_log("SUCCESS", "Confirme a janela de Administrador para concluir a liberação.")
                QTimer.singleShot(4000, self._check_firewall_status)
            except Exception as exc:
                self._append_log("ERROR", f"Falha ao abrir configurador de Firewall: {exc}")
        else:
            self._append_log("INFO", "No Linux, execute: sudo ufw allow 9000:9020/udp && sudo ufw allow 9005/udp")

    def _run_loopback_diagnostic(self):
        self._append_log("INFO", "Iniciando autodiagnóstico de Loopback em 127.0.0.1...")
        self.settings_sheet.set_target("127.0.0.1", self.default_port, self.my_pin)
        self.settings_sheet.txt_send_ip.setText("127.0.0.1")
        self.settings_sheet.spn_send_port.setValue(self.default_port)
        self.settings_sheet.txt_send_pin.setText(self.my_pin)
        self._toggle_receiver()
        time.sleep(0.1)
        self._toggle_sender()

    def _append_log(self, level: str, text: str):
        self.view_troubleshoot.append_log(level, text)

    def closeEvent(self, event):
        self._is_closing = True
        self._sender_session_epoch += 1
        if hasattr(self, "_fw_init_timer"):
            self._fw_init_timer.stop()
        if hasattr(self, "_upd_init_timer"):
            self._upd_init_timer.stop()
        self._conn_hint_timer.stop()
        if self._active_p2p_client:
            self._active_p2p_client.stop()
        if hasattr(self, "tupa_checker") and self.tupa_checker:
            self.tupa_checker.stop()
        if hasattr(self, "_decode_worker") and self._decode_worker:
            self._decode_worker.stop()
        if hasattr(self, "beacon_service") and self.beacon_service:
            self.beacon_service.on_peers_updated = None
            self.beacon_service.stop()
        if hasattr(self, "audio_player") and self.audio_player:
            self.audio_player.stop()
        if hasattr(self, "engine") and self.engine:
            self.engine.stop()
        event.accept()
