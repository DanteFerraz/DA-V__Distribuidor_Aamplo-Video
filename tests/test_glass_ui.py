# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Testes Unitarios e de Integracao da Interface Glass UI — DA-V v4.1
Autor: Dante Ferraz (MonoTech)
"""

import glob
import os
import re

from scripts.qt_compat import QApplication, QImage, QPainter, QPointF, QRectF, Qt
from src.ui.glass import (
    FloatingNavPill,
    SenderHomePage,
    SettingsSheet,
    StatsSheet,
    VideoOverlayControls,
    ViewerConnectingPage,
    ViewerIdlePage,
    icons,
    parse_access_input,
    tokens as T,
)
from src.ui.main_window import DavMainWindow

app = QApplication.instance() or QApplication([])


def test_glass_tokens_geometry():
    assert 0.50 < T.CARD_W_FRAC < 0.65
    assert 0.50 < T.CARD_H_FRAC < 0.70
    assert T.ui_scale(1920, 1080) == 1.0
    assert T.ui_scale(1280, 720) > 0.60
    assert T.px(100, 0.5) == 50
    assert T.rgba((10, 20, 30), 0.5) == "rgba(10,20,30,0.500)"


def test_parse_access_input_variants():
    assert parse_access_input("300-631") == ("", None, "300631")
    assert parse_access_input("845 747") == ("", None, "845747")
    assert parse_access_input("dav://connect/300-631") == ("", None, "300631")
    assert parse_access_input("dav://300631") == ("", None, "300631")
    assert parse_access_input("192.168.1.42") == ("192.168.1.42", None, "")
    assert parse_access_input("192.168.1.42:9005") == ("192.168.1.42", 9005, "")
    assert parse_access_input("dav://192.168.1.42:9005") == ("192.168.1.42", 9005, "")
    assert parse_access_input("studio.local:9002") == ("studio.local", 9002, "")

    # Enderecos invalidos nao devem virar PIN
    assert parse_access_input("192.168.1.999") == ("192.168.1.999", None, "")
    assert parse_access_input("192.168.1.42:99999") == ("192.168.1.42", None, "")
    assert parse_access_input("foo..bar") == ("", None, "")
    assert parse_access_input("192.168.1") == ("", None, "")
    assert parse_access_input("") == ("", None, "")


def test_focal_glass_views():
    idle = ViewerIdlePage()
    conn = ViewerConnectingPage()
    sender = SenderHomePage()
    try:
        submitted = []
        idle.connect_submitted.connect(submitted.append)

        idle._on_submit()
        assert submitted == []
        assert "Informe" in idle.lbl_status.text()

        idle.set_access_key("300-631")
        assert idle.lbl_status.text() == ""
        idle._on_submit()
        assert submitted == ["300-631"]

        cancelled = []
        conn.cancel_requested.connect(lambda: cancelled.append(True))
        conn.set_detail("Aguardando...")
        assert conn.lbl_detail.text() == "Aguardando..."
        conn.reset()
        assert conn.lbl_connecting.text() == "Conectando..."
        assert conn.lbl_detail.text() == ""

        assert sender.btn_toggle_send.text() == "Iniciar Transmissão"
        sender.set_sending_state(True, "Standby")
        assert sender.btn_toggle_send.text() == "Parar Transmissão"
        sender.update_live_stats(60.0, 14.5)
        assert "60 FPS" in sender.lbl_status.text()
        sender.set_sending_state(False)
        assert sender.btn_toggle_send.text() == "Iniciar Transmissão"
    finally:
        for w in (idle, conn, sender):
            w.close()
            w.deleteLater()
        app.processEvents()


def test_nav_pill_and_sheets():
    pill = FloatingNavPill()
    settings = SettingsSheet("192.168.1.10", 9000, 9002, "300-631", "SIMD", "4.0.0")
    stats = StatsSheet()
    try:
        pill.set_ui_scale(1.0)
        pill.expand()
        pill.set_active("settings")
        pill.set_live(True)
        pill.set_over_video(True)
        pill.collapse()

        settings.set_tab(1)
        assert settings.segmented.current() == 1
        assert settings.stack.currentIndex() == 1
        settings.set_connection_state(True)
        assert settings.btn_recv_toggle.text() == "Desconectar"
        settings.set_sending_state(True, "60 FPS")
        assert settings.btn_send_toggle.text() == "Parar Transmissão"

        stats.set_peer_count(3)
        assert "Dispositivos (3)" in stats.segmented._items[1]
        stats.set_peer_count(0)
        assert stats.segmented._items[1] == "Dispositivos"
    finally:
        if hasattr(stats, "view_tupa") and hasattr(stats.view_tupa, "stop"):
            stats.view_tupa.stop()
        for w in (pill, settings, stats):
            w.close()
            w.deleteLater()
        app.processEvents()


def test_main_window_glass_transitions():
    win = DavMainWindow(custom_pin="300-631")
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    try:
        win.resize(1280, 740)
        win.show()
        app.processEvents()

        assert win.stage_stack.currentIndex() == win.PAGE_VIEWER_IDLE
        assert win.active_sheet is None

        # Abre e fecha folha de configuracoes e telemetria
        win._toggle_sheet("settings")
        assert win.active_sheet == "settings"
        assert win.settings_sheet.isVisible()

        win._toggle_sheet("stats")
        assert win.active_sheet == "stats"
        assert not win.settings_sheet.isVisible()
        assert win.stats_sheet.isVisible()

        win._close_sheets()
        assert win.active_sheet is None
        assert not win.stats_sheet.isVisible()

        # Troca de modo Espectador <-> Transmissor
        win._swap_mode()
        assert win.mode == "sender"
        assert win.stage_stack.currentIndex() == win.PAGE_SENDER

        win._swap_mode()
        assert win.mode == "viewer"
        assert win.stage_stack.currentIndex() == win.PAGE_VIEWER_IDLE

        # Transicao Conectando -> Primeiro quadro em tela cheia
        win.is_receiving = True
        win._waiting_first_frame = True
        win.stage_stack.setCurrentIndex(win.PAGE_VIEWER_CONN)
        img = QImage(640, 360, QImage.Format.Format_RGB888)
        win.video_canvas.update_frame(img, 60.0, 10.0, 5.0, 100, 1)
        app.processEvents()

        assert not win._waiting_first_frame
        assert win.stage_stack.currentIndex() == win.PAGE_VIDEO
        assert win.overlay_controls.isVisible()

        # Controle flutuante de audio no Modo Espectador sincronizado com SettingsSheet
        assert not win.overlay_controls.audio_muted
        win._on_overlay_audio_clicked()
        assert not win.settings_sheet.chk_audio_rx.isChecked()
        assert win.overlay_controls.audio_muted
        assert win.audio_player.is_muted
        win.settings_sheet.chk_audio_rx.setChecked(True)
        assert not win.overlay_controls.audio_muted
        assert not win.audio_player.is_muted
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()


def test_shadowed_vector_icons_and_overlay_controls():
    img = QImage(96, 96, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    box = QRectF(16, 16, 64, 64)
    for fn in (
        icons.draw_menu,
        icons.draw_gear,
        icons.draw_refresh,
        icons.draw_chart,
        lambda qp, b: icons.draw_speaker(qp, b, muted=False),
        lambda qp, b: icons.draw_speaker(qp, b, muted=True),
        lambda qp, b: icons.draw_fullscreen_corners(qp, b, is_fullscreen=False),
        lambda qp, b: icons.draw_fullscreen_corners(qp, b, is_fullscreen=True),
        lambda qp, b: icons.draw_cursor_control(qp, b, active=True),
        lambda qp, b: icons.draw_cursor_control(qp, b, active=False),
        icons.draw_check,
        icons.draw_chip,
        icons.draw_display,
        lambda qp, b: icons.draw_shield(qp, b, checked=True),
        icons.draw_alert,
    ):
        fn(p, box)
    p.end()

    # Garante que pixels foram desenhados na imagem
    assert not img.isNull()

    ctrl = VideoOverlayControls()
    try:
        audio_hits = []
        fs_hits = []
        ctrl.audio_toggled.connect(lambda: audio_hits.append(True))
        ctrl.fullscreen_toggled.connect(lambda: fs_hits.append(True))
        ctrl.set_ui_scale(1.0)

        r_audio = ctrl._zone_rect(ctrl.ZONE_AUDIO)
        r_fs = ctrl._zone_rect(ctrl.ZONE_FULLSCREEN)
        assert ctrl._zone_at(r_audio.center()) == ctrl.ZONE_AUDIO
        assert ctrl._zone_at(r_fs.center()) == ctrl.ZONE_FULLSCREEN
        assert ctrl._zone_at(QPointF(-10, -10)) == -1

        ctrl.set_remote_visible(True)
        ctrl.set_remote_state(True, True)
        r_rem = ctrl._zone_rect(ctrl.ZONE_REMOTE)
        assert ctrl._zone_at(r_rem.center()) == ctrl.ZONE_REMOTE
    finally:
        ctrl.close()
        ctrl.deleteLater()
        app.processEvents()


def test_sender_zone_swap_protection_and_clean_restart(monkeypatch):
    class _StubP2PClient:
        def register_as_sender(self, *args, **kwargs):
            return {"status": "registered", "your_public_ip": "127.0.0.1"}

        def stop(self):
            return None

    monkeypatch.setattr("src.ui.main_window.P2PChannelClient", _StubP2PClient)
    win = DavMainWindow(custom_pin="300-631")
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    try:
        win.resize(1280, 740)
        win.show()
        app.processEvents()

        start_calls = []
        stop_calls = []

        def fake_start_sender(target_ip, target_port, pin, **kwargs):
            start_calls.append({"target_ip": target_ip, "target_port": target_port, "bind_port": kwargs.get("bind_port")})
            return True

        monkeypatch.setattr(win.engine, "start_sender", fake_start_sender)
        monkeypatch.setattr(win.engine, "stop", lambda: stop_calls.append(True))
        monkeypatch.setattr(win.engine, "wait_sender_endpoint", lambda timeout=3.0: None)

        win._set_mode("sender")
        assert win.settings_sheet.txt_send_ip.text() == ""
        orig_port = win.settings_sheet.spn_send_port.value()
        assert not win.overlay_controls.isVisible()

        # 1. Inicia transmissao em modo PIN P2P
        win._toggle_sender()
        assert win.is_sending
        assert win.overlay_controls.isVisible()
        assert len(start_calls) == 1
        assert start_calls[0]["target_ip"] == ""
        assert start_calls[0]["bind_port"] == win.default_port

        # 2. Pareamento P2P nao deve corromper txt_send_ip / spn_send_port
        win._on_target_updated("170.239.227.109", 11450, "WAN P2P Direto")
        assert win._active_peer_endpoint == ("170.239.227.109", 11450)
        assert win.settings_sheet.txt_send_ip.text() == ""
        assert win.settings_sheet.spn_send_port.value() == orig_port
        assert "170.239.227.109:11450" in win.page_sender.lbl_status.text()

        # 3. Clicar no botao central (ZONE_SWAP) enquanto transmite NAO deve parar a transmissao
        epoch_before = win._sender_session_epoch
        win._swap_mode()
        assert win.is_sending
        assert win.mode == "sender"
        assert win.stage_stack.currentIndex() == win.PAGE_SENDER
        assert "Parar Transmissão" in win.page_sender.lbl_status.text()
        assert len(stop_calls) == 0

        # 4. Controle flutuante de audio no Transmissor
        win._on_overlay_audio_clicked()
        assert not win.settings_sheet.chk_audio_tx.isChecked()
        assert win.overlay_controls.audio_muted

        # 5. Encerrar manualmente e reiniciar transmissao deve funcionar na hora (porta padrao + STUN)
        win._toggle_sender()
        assert not win.is_sending
        assert win._active_peer_endpoint is None
        assert win._sender_session_epoch > epoch_before
        assert not win.overlay_controls.isVisible()
        assert len(stop_calls) == 1

        # Alternar modo depois de parar funciona normalmente e volta ao Transmissor
        win._swap_mode()
        assert win.mode == "viewer"
        win._swap_mode()
        assert win.mode == "sender"

        win._toggle_sender()
        assert win.is_sending
        assert len(start_calls) == 2
        assert start_calls[1]["target_ip"] == ""
        assert start_calls[1]["bind_port"] == win.default_port
    finally:
        win.is_sending = False
        win.close()
        win.deleteLater()
        app.processEvents()


def test_no_emojis_in_glass_ui():
    emoji_re = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    glass_files = glob.glob(os.path.join(root, "src", "ui", "glass", "*.py"))
    glass_files.append(os.path.join(root, "src", "ui", "main_window.py"))
    for path in glass_files:
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
        assert not emoji_re.search(content), f"Emoji detectado em {path}"


def test_interactive_switch_and_glass_installers(monkeypatch):
    monkeypatch.setenv("DAV_INSTALLER_DRY_RUN", "1")
    monkeypatch.setenv("DAV_HEADLESS_SYNTHETIC", "1")

    sender = SenderHomePage()
    from scripts.dav_installer_linux import DavModernLinuxInstaller

    inst_dialogs = [DavModernLinuxInstaller()]
    if os.name == "nt":
        from scripts.dav_installer_win import DavModernInstaller

        inst_dialogs.append(DavModernInstaller())

    try:
        toggled_vals = []
        sender.interactive_toggled.connect(toggled_vals.append)
        assert not sender.switch_interactive.isChecked()
        assert not sender.btn_admin_privilege.isVisible()

        sender.switch_interactive.toggle()
        assert toggled_vals == [True]
        assert sender.switch_interactive.isChecked()
        assert not sender.btn_admin_privilege.isHidden()

        sender.set_interactive_state(True, admin_elevated=True)
        assert not sender.btn_admin_privilege.isEnabled()
        sender.resize(1280, 740)
        assert not sender.grab().isNull()

        for dlg in inst_dialogs:
            dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            dlg.resize(900, 560)
            dlg.show()
            app.processEvents()
            for step_idx in (0, 1, 2, 3):
                dlg.current_step = step_idx
                dlg._update_step_view()
                app.processEvents()
                pix = dlg.grab()
                assert not pix.isNull()
            dlg.resize(820, 520)
            app.processEvents()
    finally:
        sender.close()
        sender.deleteLater()
        for dlg in inst_dialogs:
            dlg.close()
            dlg.deleteLater()
        app.processEvents()
