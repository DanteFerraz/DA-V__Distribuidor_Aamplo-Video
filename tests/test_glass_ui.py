# -*- coding: utf-8 -*-
"""
Testes Unitarios e de Integracao da Interface Glass UI — DA-V v4.1
Autor: Dante Ferraz (MonoTech)
"""

import glob
import os
import re

from scripts.qt_compat import QApplication, QImage, Qt
from src.ui.glass import (
    FloatingNavPill,
    SenderHomePage,
    SettingsSheet,
    StatsSheet,
    ViewerConnectingPage,
    ViewerIdlePage,
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
    submitted = []
    idle.connect_submitted.connect(submitted.append)

    idle._on_submit()
    assert submitted == []
    assert "Informe" in idle.lbl_status.text()

    idle.set_access_key("300-631")
    assert idle.lbl_status.text() == ""
    idle._on_submit()
    assert submitted == ["300-631"]

    conn = ViewerConnectingPage()
    cancelled = []
    conn.cancel_requested.connect(lambda: cancelled.append(True))
    conn.set_detail("Aguardando...")
    assert conn.lbl_detail.text() == "Aguardando..."
    conn.reset()
    assert conn.lbl_connecting.text() == "Conectando..."
    assert conn.lbl_detail.text() == ""

    sender = SenderHomePage()
    assert sender.btn_toggle_send.text() == "Iniciar Transmissão"
    sender.set_sending_state(True, "Standby")
    assert sender.btn_toggle_send.text() == "Parar Transmissão"
    sender.update_live_stats(60.0, 14.5)
    assert "60 FPS" in sender.lbl_status.text()
    sender.set_sending_state(False)
    assert sender.btn_toggle_send.text() == "Iniciar Transmissão"


def test_nav_pill_and_sheets():
    pill = FloatingNavPill()
    pill.set_ui_scale(1.0)
    pill.expand()
    pill.set_active("settings")
    pill.set_live(True)
    pill.set_over_video(True)
    pill.collapse()

    settings = SettingsSheet("192.168.1.10", 9000, 9002, "300-631", "SIMD", "4.0.0")
    settings.set_tab(1)
    assert settings.segmented.current() == 1
    assert settings.stack.currentIndex() == 1
    settings.set_connection_state(True)
    assert settings.btn_recv_toggle.text() == "Desconectar"
    settings.set_sending_state(True, "60 FPS")
    assert settings.btn_send_toggle.text() == "Parar Transmissão"

    stats = StatsSheet()
    stats.set_peer_count(3)
    assert "Dispositivos (3)" in stats.segmented._items[1]
    stats.set_peer_count(0)
    assert stats.segmented._items[1] == "Dispositivos"


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
    finally:
        win.close()


def test_no_emojis_in_glass_ui():
    emoji_re = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    glass_files = glob.glob(os.path.join(root, "src", "ui", "glass", "*.py"))
    glass_files.append(os.path.join(root, "src", "ui", "main_window.py"))
    for path in glass_files:
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
        assert not emoji_re.search(content), f"Emoji detectado em {path}"
