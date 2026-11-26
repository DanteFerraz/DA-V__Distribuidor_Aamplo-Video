# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
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

from src.dav.kernel.contracts import (
    EVENT_CLIENT_KEYBOARD_PROFILE,
    EVENT_GAMEPAD_ROSTER_CHANGED,
    EVENT_GAMEPAD_RUMBLE_ACK,
    EVENT_REMOTE_CLIPBOARD,
    EVENT_REMOTE_FILE_STATUS,
    EVENT_REMOTE_INPUT_METRICS,
    EVENT_REMOTE_PERM_CHANGED,
    EVENT_REMOTE_SHELL_OUTPUT,
)
from src.dav.kernel.registry import ModuleRegistry
from src.dav.modules.audio.service import AudioService
from src.dav.modules.stream_engine.service import StreamEngineService
from src.dav.modules.telemetry.service import TelemetryService
from src.dav.modules.telemetry.tupa_checker import TupaMetricsSnapshot
from src.dav.modules.transport_p2p.blind_relay import normalize_pin
from src.dav.modules.transport_p2p.dualstack import (
    canonicalize_ip,
    format_endpoint_display,
    get_local_ipv6,
    is_valid_ip,
    parse_host_port,
    resolve_host_dualstack,
)
from src.dav.modules.transport_p2p.service import TransportService
from src.dav.modules.transport_p2p.signaling_client import P2PChannelClient
from src.dav.modules.universal_input.service import UniversalInputService
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
    remote_perms_signal = Signal(dict)
    remote_clipboard_signal = Signal(str)
    remote_file_signal = Signal(dict)
    remote_shell_signal = Signal(str)
    remote_metrics_signal = Signal(dict)
    gamepad_roster_signal = Signal(list)
    gamepad_rumble_ack_signal = Signal(dict)
    client_kb_profile_signal = Signal(dict)

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
        self.universal_input_service: UniversalInputService = (
            self.kernel.get_service("universal_input") or UniversalInputService()
        )

        self.version_str = self._load_version()
        self.setWindowTitle(f"DA-V v{self.version_str} — Distribuidor Amplo de Vídeo")
        self._apply_window_icon()
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
        self._admin_prompted_once: bool = False
        self._applying_remote_clipboard: bool = False
        self._client_gamepad_enabled: bool = False
        self._host_gamepad_count: int = 0

        self._conn_hint_timer = QTimer(self)
        self._conn_hint_timer.setSingleShot(True)
        self._conn_hint_timer.timeout.connect(self._on_conn_wait_timeout)

        self.engine: StreamEngineService = self.kernel.get_service("stream_engine") or StreamEngineService()
        self.bridge = EngineBridge()
        self.bridge.frame_ready.connect(self._on_frame_rendered)
        self.bridge.telemetry_ready.connect(self._on_telemetry_updated)
        self.bridge.sender_stats.connect(self._on_sender_stats_updated)
        self.bridge.log_message.connect(self._append_log)

        self._decode_worker = DecodeWorker(
            self.bridge,
            on_pli_needed=self.engine.request_receiver_pli,
        )
        self._decode_worker.decoded.connect(self._on_decoded_frame)
        self._decode_worker.start()
        self._sender_global_ipv6: Optional[str] = get_local_ipv6()
        self._sender_global_ipv6_port: int = self.default_port
        self._rendezvous_online: bool = True
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
        self.remote_perms_signal.connect(self._on_remote_perms_event)
        self.remote_clipboard_signal.connect(self._on_remote_clipboard_event)
        self.remote_file_signal.connect(self._on_remote_file_event)
        self.remote_shell_signal.connect(self._on_remote_shell_event)
        self.remote_metrics_signal.connect(self._on_remote_metrics_event)
        self.gamepad_roster_signal.connect(self._on_gamepad_roster_event)
        self.gamepad_rumble_ack_signal.connect(self._on_gamepad_rumble_ack_event)
        self.client_kb_profile_signal.connect(self._on_client_kb_profile_event)
        self.tupa_checker.start(lambda snap: self.tupa_metrics_signal.emit(snap))

        self.engine.bus.subscribe(EVENT_REMOTE_PERM_CHANGED, lambda p: self.remote_perms_signal.emit(dict(p or {})))
        self.engine.bus.subscribe(EVENT_REMOTE_CLIPBOARD, lambda t: self.remote_clipboard_signal.emit(str(t or "")))
        self.engine.bus.subscribe(EVENT_REMOTE_FILE_STATUS, lambda s: self.remote_file_signal.emit(dict(s or {})))
        self.engine.bus.subscribe(EVENT_REMOTE_SHELL_OUTPUT, lambda o: self.remote_shell_signal.emit(str(o or "")))
        self.engine.bus.subscribe(EVENT_REMOTE_INPUT_METRICS, lambda m: self.remote_metrics_signal.emit(dict(m or {})))
        self.engine.bus.subscribe(EVENT_GAMEPAD_ROSTER_CHANGED, lambda r: self.gamepad_roster_signal.emit(list(r or [])))
        self.engine.bus.subscribe(EVENT_GAMEPAD_RUMBLE_ACK, lambda a: self.gamepad_rumble_ack_signal.emit(dict(a or {})))
        self.engine.bus.subscribe(EVENT_CLIENT_KEYBOARD_PROFILE, lambda p: self.client_kb_profile_signal.emit(dict(p or {})))

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

    def _apply_window_icon(self) -> None:
        try:
            from PySide6.QtGui import QIcon
            root_dir = getattr(sys, "_MEIPASS", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
            for icon_rel in (
                "installer/dav_icon.ico",
                "installer/dav_icon.png",
                "dav_icon.ico",
                "dav_icon.png",
                "design/blocks_components/DA-V.icon.ico",
                "design/blocks_components/DA-V.icon.png",
            ):
                icon_candidate = os.path.join(root_dir, icon_rel)
                if os.path.isfile(icon_candidate):
                    self.setWindowIcon(QIcon(icon_candidate))
                    break
        except Exception:
            pass

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
        self.video_canvas.remote_input_event.connect(self._on_canvas_remote_input)
        self.video_canvas.files_dropped.connect(self._on_files_dropped)
        self.stage_stack.addWidget(self.video_canvas)

        self.page_sender = SenderHomePage(self.stage_stack)
        self.page_sender.copy_key_clicked.connect(self._copy_sender_access_key)
        self.page_sender.copy_ipv6_link_clicked.connect(self._copy_ipv6_direct_link)
        self.page_sender.set_ipv6_direct_available(bool(self._sender_global_ipv6), self._sender_global_ipv6 or "")
        self.page_sender.toggle_send_clicked.connect(self._toggle_sender)
        self.page_sender.interactive_toggled.connect(self._on_sender_interactive_toggled)
        self.page_sender.admin_elevation_requested.connect(lambda: self._request_admin_elevation(auto_triggered=False))
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
        self.settings_sheet.remote_perms_changed.connect(self._on_granular_perms_changed)
        self.settings_sheet.admin_elevation_requested.connect(lambda: self._request_admin_elevation(auto_triggered=False))
        self.settings_sheet.panic_revoke_requested.connect(self._on_panic_revoke_remote)
        self.settings_sheet.open_gamepad_tester_requested.connect(self._open_gamepad_tester_sheet)

        self.stats_sheet = StatsSheet(parent=self.central_host)
        self.stats_sheet.hide()
        self.stats_sheet.close_requested.connect(self._close_sheets)

        self.view_tupa = self.stats_sheet.view_tupa
        self.view_discovery = self.stats_sheet.view_discovery
        self.view_workspace = self.stats_sheet.view_workspace
        self.view_troubleshoot = self.stats_sheet.view_troubleshoot
        self.gamepad_tester = self.view_workspace.gamepad_tester

        self.view_workspace.send_file_requested.connect(self._send_p2p_file)
        self.view_workspace.shell_command_submitted.connect(self._send_remote_shell_cmd)
        self.gamepad_tester.test_remote_rumble_requested.connect(self._on_test_remote_rumble_clicked)
        self.gamepad_tester.test_local_rumble_requested.connect(self._on_test_local_rumble_clicked)
        self.gamepad_tester.install_driver_requested.connect(self._on_install_gamepad_driver_clicked)
        self.gamepad_tester.update_driver_status(self.universal_input_service.check_host_gamepad_driver())

        self.view_discovery.connect_peer_requested.connect(self._quick_connect_peer)
        self.view_discovery.refresh_requested.connect(self._manual_refresh_peers)
        self.view_troubleshoot.loopback_requested.connect(self._run_loopback_diagnostic)
        self.view_troubleshoot.fix_firewall_requested.connect(self._fix_firewall)
        self.view_troubleshoot.check_firewall_requested.connect(self._check_firewall_status)
        self.view_troubleshoot.export_logs_requested.connect(self._export_diagnostic_bundle)
        self.view_troubleshoot.check_update_requested.connect(self._manual_check_updates)

        # Controles flutuantes no canto inferior direito (Controle Remoto, Controles/Gamepads, Audio & Tela Cheia)
        self.overlay_controls = VideoOverlayControls(self.central_host)
        self.overlay_controls.remote_toggled.connect(self._on_overlay_remote_clicked)
        self.overlay_controls.gamepad_toggled.connect(self._on_overlay_gamepad_clicked)
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

        # Atalhos globais de seguranca e diagnostico
        try:
            self.shortcut_diag = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
            self.shortcut_diag.activated.connect(self._export_diagnostic_bundle)
            self.shortcut_panic = QShortcut(QKeySequence("Ctrl+Alt+Shift+Esc"), self)
            self.shortcut_panic.activated.connect(self._on_panic_revoke_remote)
        except Exception:
            pass

        cb = QApplication.clipboard()
        if cb is not None:
            try:
                cb.dataChanged.connect(self._on_local_clipboard_changed)
            except Exception:
                pass

        init_perms = self.engine.get_remote_permissions()
        self.settings_sheet.sync_remote_permissions(init_perms)
        self.page_sender.set_interactive_state(False, admin_elevated=bool(init_perms.get("admin_elevated")))

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
        is_viewer_live = cur_page == self.PAGE_VIDEO and self.mode == "viewer"
        is_sender_live = cur_page == self.PAGE_SENDER and self.is_sending
        self.overlay_controls.set_remote_visible(is_viewer_live)
        self.overlay_controls.set_remote_state(
            self.video_canvas.remote_control_enabled,
            self.video_canvas.host_allows_input,
        )
        self.overlay_controls.set_gamepad_visible(is_viewer_live or is_sender_live)
        if is_sender_live:
            self.overlay_controls.set_gamepad_state(
                self.settings_sheet.chk_allow_gamepad.isChecked(),
                True,
                count=self._host_gamepad_count,
            )
        else:
            local_gp_cnt = len(self.engine.get_local_gamepads()) if self.is_receiving else 0
            self.overlay_controls.set_gamepad_state(
                self._client_gamepad_enabled,
                self.video_canvas.host_allows_gamepad,
                count=local_gp_cnt,
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

    def _on_overlay_remote_clicked(self):
        if not self.video_canvas.host_allows_input:
            self._append_log("WARN", "O Transmissor ainda não habilitou o Modo Interativo nesta sessão.")
            return
        self.video_canvas.remote_control_enabled = not self.video_canvas.remote_control_enabled
        if not self.video_canvas.remote_control_enabled:
            from src.dav.modules.remote_desktop.protocol import EvType, InputEventPacket

            self.engine.send_remote_input(InputEventPacket(ev_type=EvType.RELEASE_ALL))
        else:
            self.video_canvas.setFocus()
        self._sync_overlay_controls_state()
        self.video_canvas.update()
        state_lbl = "ATIVADO" if self.video_canvas.remote_control_enabled else "PAUSADO"
        self._append_log("INFO", f"Controle remoto de mouse e teclado {state_lbl}.")

    def _on_overlay_gamepad_clicked(self):
        if self.mode == "sender":
            new_allow = not self.settings_sheet.chk_allow_gamepad.isChecked()
            self.settings_sheet.chk_allow_gamepad.setChecked(new_allow)
            self._sync_overlay_controls_state()
            self._append_log(
                "INFO",
                f"Controles / gamepads remotos no Host {'ATIVADOS' if new_allow else 'DESATIVADOS'}.",
            )
            return

        if not self.video_canvas.host_allows_gamepad:
            self._append_log("WARN", "O Transmissor ainda não habilitou controles / gamepads nesta sessão.")
            return
        self._client_gamepad_enabled = not self._client_gamepad_enabled
        self.engine.set_client_gamepad_enabled(self._client_gamepad_enabled)
        self._sync_overlay_controls_state()
        st_lbl = "ATIVADO" if self._client_gamepad_enabled else "PAUSADO"
        self._append_log("INFO", f"Envio de controles locais (DualShock / DualSense / Xbox / Genéricos) {st_lbl}.")

    def _open_gamepad_tester_sheet(self):
        self.gamepad_tester.update_driver_status(self.universal_input_service.check_host_gamepad_driver())
        self.settings_sheet.hide()
        self.active_sheet = "stats"
        scale = T.ui_scale(self.width(), self.height())
        self.stats_sheet.set_ui_scale(scale)
        self.stats_sheet.setGeometry(0, 0, self.central_host.width(), self.central_host.height())
        self.stats_sheet.set_tab(2)
        self.stats_sheet.show()
        self.stats_sheet.raise_()
        self.nav_pill.set_active("stats")
        self.nav_pill.raise_()

    def _on_test_remote_rumble_clicked(self, host_slot):
        if not self.is_sending:
            self.gamepad_tester.show_rumble_ack({
                "ok": False,
                "device_name": "Inicie a transmissão e conecte um cliente remoto antes de testar a vibração",
            })
            return
        if not self.settings_sheet.chk_allow_gamepad.isChecked():
            self.settings_sheet.chk_allow_gamepad.setChecked(True)
        sent = self.engine.trigger_remote_gamepad_rumble_test(host_slot=host_slot)
        if sent:
            self._append_log("INFO", "[Controles] Comando de vibração enviado ao controle do cliente remoto.")
        else:
            self.gamepad_tester.show_rumble_ack({
                "ok": False,
                "device_name": "Nenhum cliente P2P autenticado no momento",
            })

    def _on_test_local_rumble_clicked(self):
        ok, dev_name = self.engine.test_local_gamepad_rumble()
        self.gamepad_tester.show_rumble_ack({
            "ok": ok,
            "device_name": dev_name,
            "rtt_ms": 0.1,
            "backend": "local",
        })
        self._append_log(
            "SUCCESS" if ok else "WARN",
            f"[Controles Locais] Teste de vibração local: {dev_name}.",
        )

    def _on_install_gamepad_driver_clicked(self):
        ok, msg = self.universal_input_service.install_host_gamepad_driver()
        self._append_log("INFO" if ok else "WARN", f"[ViGEmBus] {msg}")
        QTimer.singleShot(
            6000,
            lambda: self.gamepad_tester.update_driver_status(
                self.universal_input_service.check_host_gamepad_driver()
            ),
        )

    def _on_canvas_remote_input(self, pkt):
        self.engine.send_remote_input(pkt)

    def _on_sender_interactive_toggled(self, enabled: bool):
        snap = self.engine.set_remote_permissions(
            allow_input=enabled,
            allow_gamepad=enabled,
            allow_clipboard=enabled,
            allow_files=enabled,
        )
        self.settings_sheet.sync_remote_permissions(snap)
        self.page_sender.set_interactive_state(enabled, admin_elevated=bool(snap.get("admin_elevated")))
        self._sync_overlay_controls_state()
        if enabled:
            self._append_log(
                "SUCCESS",
                "[Modo Interativo] Área de trabalho e controles universais ativados (Ctrl+Alt+Shift+Esc para revogar).",
            )
            if (
                not snap.get("admin_elevated")
                and not self._admin_prompted_once
                and os.environ.get("DAV_HEADLESS_SYNTHETIC") != "1"
            ):
                self._admin_prompted_once = True
                self._request_admin_elevation(auto_triggered=True)
        else:
            self._append_log("INFO", "[Modo Interativo] Sessão retornou para Somente Visualização.")

    def _on_granular_perms_changed(self, perms: dict):
        snap = self.engine.set_remote_permissions(**perms)
        any_interactive = bool(
            snap.get("allow_input")
            or snap.get("allow_gamepad")
            or snap.get("allow_clipboard")
            or snap.get("allow_files")
            or snap.get("allow_shell")
        )
        self.page_sender.set_interactive_state(any_interactive, admin_elevated=bool(snap.get("admin_elevated")))
        self._sync_overlay_controls_state()

    def _request_admin_elevation(self, auto_triggered: bool = False):
        if self.engine.is_remote_admin_elevated():
            snap = self.engine.get_remote_permissions()
            snap["admin_elevated"] = True
            self.settings_sheet.sync_remote_permissions(snap)
            self.page_sender.set_interactive_state(self.page_sender.switch_interactive.isChecked(), True)
            return

        self._append_log(
            "INFO",
            "[Segurança] Solicitando autorização de Administrador (Windows UAC / Linux Polkit)...",
        )

        def _elev_worker():
            res = self.engine.request_remote_admin_elevation()
            if not res.is_success and not auto_triggered and not self._is_closing:
                self.bridge.log_message.emit(
                    "WARN",
                    f"[Segurança] Elevação Admin não concedida ({res.error}). Operando em modo usuário.",
                )

        threading.Thread(target=_elev_worker, daemon=True, name="DAV-UI-AdminElevate").start()

    def _on_panic_revoke_remote(self):
        snap = self.engine.panic_revoke_remote()
        self.settings_sheet.sync_remote_permissions(snap)
        self.page_sender.set_interactive_state(False, admin_elevated=bool(snap.get("admin_elevated")))
        self.page_sender.flash_warning("Controle remoto revogado imediatamente (Modo Somente Vídeo).")
        self._append_log("WARN", "[PANIC SWITCH] Todas as permissões remotas foram revogadas pelo Host.")

    @Slot(dict)
    def _on_remote_perms_event(self, perms: dict):
        if self._is_closing:
            return
        if self.mode == "sender" or self.is_sending:
            any_int = bool(
                perms.get("allow_input")
                or perms.get("allow_gamepad")
                or perms.get("allow_clipboard")
                or perms.get("allow_files")
                or perms.get("allow_shell")
            )
            self.settings_sheet.sync_remote_permissions(perms)
            self.page_sender.set_interactive_state(any_int, admin_elevated=bool(perms.get("admin_elevated")))
            self._sync_overlay_controls_state()
        if self.is_receiving:
            allow_in = bool(perms.get("allow_input"))
            allow_gp = bool(perms.get("allow_gamepad"))
            was_allowed = self.video_canvas.host_allows_input
            was_gp_allowed = self.video_canvas.host_allows_gamepad
            self.video_canvas.host_allows_input = allow_in
            self.video_canvas.host_allows_gamepad = allow_gp
            self.video_canvas.host_allows_files = bool(perms.get("allow_files"))
            if allow_in and not was_allowed:
                self.video_canvas.remote_control_enabled = True
                self._append_log("SUCCESS", "[Área Remota] O Transmissor liberou o controle interativo.")
            elif not allow_in and was_allowed:
                self.video_canvas.remote_control_enabled = False
                self._append_log("WARN", "[Área Remota] O Transmissor revogou o controle interativo.")
            if allow_gp and not was_gp_allowed:
                self._client_gamepad_enabled = True
                self.engine.set_client_gamepad_enabled(True)
                self._append_log("SUCCESS", "[Controles] O Transmissor habilitou controles / gamepads remotos.")
            elif not allow_gp and was_gp_allowed:
                self._client_gamepad_enabled = False
                self.engine.set_client_gamepad_enabled(False)
                self._append_log("WARN", "[Controles] O Transmissor desativou controles / gamepads remotos.")
            self.view_workspace.update_peer_permissions(perms)
            self._sync_overlay_controls_state()
            self.video_canvas.update()

    @Slot(list)
    def _on_gamepad_roster_event(self, roster: list):
        if self._is_closing:
            return
        self._host_gamepad_count = len(roster)
        self.gamepad_tester.update_roster(roster)
        self._sync_overlay_controls_state()

    @Slot(dict)
    def _on_gamepad_rumble_ack_event(self, ack: dict):
        if self._is_closing:
            return
        self.gamepad_tester.show_rumble_ack(ack)
        lvl = "SUCCESS" if ack.get("ok") else "WARN"
        self._append_log(
            lvl,
            f"[Testador de Controles] Vibração no cliente: {ack.get('device_name')} (RTT {ack.get('rtt_ms', 0.0):.1f} ms).",
        )

    @Slot(dict)
    def _on_client_kb_profile_event(self, prof: dict):
        if self._is_closing:
            return
        self.gamepad_tester.update_client_keyboard_profile(prof)
        self._append_log(
            "INFO",
            f"[Teclado Universal] Layout do cliente conectado: {prof.get('layout_code')} ({prof.get('variant')}).",
        )

    @Slot(str)
    def _on_remote_clipboard_event(self, text: str):
        if not text or self._is_closing:
            return
        cb = QApplication.clipboard()
        if cb is not None:
            self._applying_remote_clipboard = True
            try:
                cb.setText(text)
            finally:
                self._applying_remote_clipboard = False

    def _on_local_clipboard_changed(self):
        if self._applying_remote_clipboard or self._is_closing:
            return
        if not (self.is_receiving or self.is_sending):
            return
        cb = QApplication.clipboard()
        if cb is None:
            return
        txt = cb.text()
        if txt and len(txt) <= 2 * 1024 * 1024:
            self.engine.send_clipboard_text(txt)

    @Slot(dict)
    def _on_remote_file_event(self, info: dict):
        if self._is_closing:
            return
        self.view_workspace.update_file_status(info)
        if info.get("stage") == "completed":
            self._append_log("SUCCESS", f"[Arquivo P2P] Arquivo recebido com sucesso: {info.get('filename')}")

    @Slot(str)
    def _on_remote_shell_event(self, out_text: str):
        if not self._is_closing:
            self.view_workspace.append_shell_output(out_text)

    @Slot(dict)
    def _on_remote_metrics_event(self, metrics: dict):
        if self._is_closing:
            return
        itp = float(metrics.get("input_to_photon_ms", 0.0))
        if itp > 0.0:
            self.video_canvas.input_to_photon_ms = itp

    def _on_files_dropped(self, file_paths: list):
        for fp in file_paths:
            self._send_p2p_file(fp)

    def _send_p2p_file(self, file_path: str):
        try:
            tid = self.engine.send_file(file_path)
            if tid:
                fname = os.path.basename(file_path)
                self.view_workspace.update_file_status({"stage": "sending", "filename": fname, "progress": 100.0})
                self._append_log("INFO", f"[Arquivo P2P] Enviando '{fname}' ao par conectado...")
            else:
                self._append_log("WARN", "[Arquivo P2P] Envio não permitido ou par ainda não conectado.")
        except Exception as exc:
            self._append_log("ERROR", f"[Arquivo P2P] Erro ao enviar arquivo: {exc}")

    def _send_remote_shell_cmd(self, cmd_with_nl: str):
        if not self.engine.send_shell_input(cmd_with_nl):
            self.view_workspace.append_shell_output("[Aviso] Terminal remoto desabilitado pelo Transmissor.\n")

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
                "Chave inválida. Informe um PIN (6 dígitos), link dav://, IPv4 ou [IPv6]:porta.",
                error=True,
            )
            return
        if target_ip and not is_valid_ip(target_ip):
            resolved_ip = resolve_host_dualstack(target_ip, prefer_ipv6=bool(self._sender_global_ipv6))
            if resolved_ip and is_valid_ip(resolved_ip):
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
        # Em rede IPv6-only sem Rendezvous disponivel, copia o link direto IPv6 + PIN automaticamente
        if not self._rendezvous_online and self._sender_global_ipv6:
            self._copy_ipv6_direct_link()
            return
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self.my_pin)
        self.page_sender.flash_copied(f"Chave copiada: {self.my_pin}")
        self._append_log("INFO", f"Chave de acesso copiada: {self.my_pin}")

    def _copy_ipv6_direct_link(self):
        v6 = self._sender_global_ipv6 or get_local_ipv6()
        if not v6:
            self.page_sender.flash_warning("Nenhum endereço IPv6 global detectado nesta rede.")
            return
        self._sender_global_ipv6 = v6
        v6_port = self._sender_global_ipv6_port or self.default_port
        uri = f"dav://[{v6}]:{v6_port}/{self.my_pin}"
        cb = QApplication.clipboard()
        if cb:
            cb.setText(uri)
        self.page_sender.flash_copied("Link Direto IPv6 copiado!")
        self._append_log("INFO", f"[IPv6 Direto] Link P2P copiado (sem servidor): {uri}")

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
            self._client_gamepad_enabled = False
            self.engine.set_client_gamepad_enabled(False)
            self.video_canvas.remote_control_enabled = False
            self.video_canvas.host_allows_input = False
            self.video_canvas.host_allows_gamepad = False
            self.video_canvas.host_allows_files = False
            self.view_workspace.update_peer_permissions({})
            self.video_canvas.clear_display()
            self.nav_pill.set_over_video(False)
            self.nav_pill.set_live(False)
            if self.mode == "viewer":
                self.stage_stack.setCurrentIndex(self.PAGE_VIEWER_IDLE)
            self._sync_overlay_controls_state()
            self._append_log("INFO", "Receptor desconectado pelo usuário.")
            return

        raw_recv_ip = self.settings_sheet.txt_recv_ip.text().strip()
        port = self.settings_sheet.spn_recv_port.value()
        target_ip, inline_port = parse_host_port(raw_recv_ip)
        if inline_port is not None:
            port = inline_port
            self.settings_sheet.spn_recv_port.setValue(port)
        pin = self.settings_sheet.txt_recv_pin.text().strip()
        clean_pin = normalize_pin(pin)

        if target_ip and not is_valid_ip(target_ip):
            resolved_ip = resolve_host_dualstack(target_ip, prefer_ipv6=bool(self._sender_global_ipv6))
            if resolved_ip and is_valid_ip(resolved_ip):
                target_ip = resolved_ip
            elif clean_pin:
                self._append_log(
                    "WARN",
                    f"[P2P] Endereço '{target_ip}' inválido ou incompleto. Alternando para Modo PIN Universal ('{pin}')...",
                )
                target_ip = ""
                self.settings_sheet.txt_recv_ip.setText("")
            else:
                msg = f"O endereço '{target_ip}' é inválido. Informe um IPv4, [IPv6]:porta ou PIN."
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

        self._decode_worker.reset_stream_state()

        def _on_raw_frame(frame_data, width, height, ts, is_kf):
            if isinstance(frame_data, bytes):
                self._decode_worker.submit(frame_data, width, height, is_keyframe=bool(is_kf))

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
                f"[{route_label}] Fluxo estabelecido com {format_endpoint_display(remote_ip, remote_port)}.",
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
            mode_str = (
                f"PIN Universal {pin}"
                if not target_ip
                else f"Direto {format_endpoint_display(target_ip, port)}"
            )
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

        raw_send_ip = self.settings_sheet.txt_send_ip.text().strip()
        target_port = self.settings_sheet.spn_send_port.value()
        target_ip, send_inline_port = parse_host_port(raw_send_ip)
        if send_inline_port is not None:
            target_port = send_inline_port
            self.settings_sheet.spn_send_port.setValue(target_port)
        if target_ip and not is_valid_ip(target_ip):
            resolved_tx = resolve_host_dualstack(target_ip, prefer_ipv6=bool(self._sender_global_ipv6))
            if resolved_tx:
                target_ip = resolved_tx
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
                f"[{mode_tag}] Túnel de transmissão confirmado -> {format_endpoint_display(remote_ip, remote_port)}",
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
                    self._rendezvous_online = True
                    reg_holder.update(reg)
                    pub_ep_str = format_endpoint_display(
                        str(reg.get("your_public_ip") or ""),
                        int((ep_info or {}).get("public_port", eff_local_port)),
                    )
                    nat_str = (ep_info or {}).get("nat_type", "auto")
                    pub_v6 = (ep_info or {}).get("public_ipv6")
                    pub_v6_p = int((ep_info or {}).get("public_ipv6_port") or eff_local_port)
                    if pub_v6:
                        self._sender_global_ipv6 = str(pub_v6)
                        self._sender_global_ipv6_port = pub_v6_p
                        QTimer.singleShot(
                            0,
                            lambda v6=str(pub_v6): self.page_sender.set_ipv6_direct_available(True, v6),
                        )
                        _emit_log(
                            "INFO",
                            f"[IPv6 Direto] Endereço global ativo: dav://[{pub_v6}]:{pub_v6_p}/{pin}",
                        )
                    _emit_log(
                        "SUCCESS",
                        f"[P2P] PIN '{pin}' ativo no Rendezvous (Endpoint Público: {pub_ep_str} · NAT: {nat_str}).",
                    )
                else:
                    self._rendezvous_online = False
                    pub_v6 = (ep_info or {}).get("public_ipv6") or get_local_ipv6()
                    pub_v6_p = int((ep_info or {}).get("public_ipv6_port") or eff_local_port)
                    if pub_v6:
                        self._sender_global_ipv6 = str(pub_v6)
                        self._sender_global_ipv6_port = pub_v6_p
                        QTimer.singleShot(
                            0,
                            lambda v6=str(pub_v6): self.page_sender.set_ipv6_direct_available(True, v6),
                        )
                        _emit_log(
                            "WARN",
                            f"[P2P] Rendezvous indisponível; use 'Copiar Link Direto IPv6' (dav://[{pub_v6}]:{pub_v6_p}/{pin}) ou Beacon LAN.",
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
        ep_disp = format_endpoint_display(ip, int(port))
        details = f"{res_txt} @ {fps_txt} [{mode_tag} -> {ep_disp}]"
        self.settings_sheet.set_sending_state(True, details)
        self.page_sender.set_sending_state(True, f"Transmitindo -> {ep_disp}")

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
        self.page_viewer_idle.set_access_key(format_endpoint_display(ip, int(port)))
        self._set_mode("viewer")
        self._close_sheets()
        self._append_log("INFO", f"Conectando diretamente a {format_endpoint_display(ip, int(port))} na rede local...")
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
        if hasattr(self, "view_tupa") and self.view_tupa and hasattr(self.view_tupa, "stop"):
            self.view_tupa.stop()
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
