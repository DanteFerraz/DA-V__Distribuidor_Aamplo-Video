# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Suite Completa de Testes da Fatia `universal_input` e Integracao Multi-Controle P2P — DA-V v5.1
Autor: Dante Ferraz (MonoTech)

Valida:
1. Traducao fiel ao teclado do cliente conectado (`~`, `~/Desktop`, `ã`, `ç`, `/`, `?`, `AltGr`, `Ctrl+~`, `WASD`);
2. Normalizacao de controles DualShock 4, DualSense (Touchpad), Xbox e Genericos DirectInput + pacote 24B exato;
3. Multi-peer P2P simultaneo no mesmo PIN com multiplos controles em slots independentes + Vibracao Remota E2E;
4. Renderizacao offscreen do botao vetorial `ZONE_GAMEPAD` e do `GamepadTesterWidget`.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from typing import Any, Dict, List

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DAV_HEADLESS_SYNTHETIC", "1")

from src.dav.modules.capture.service import CaptureService
from src.dav.modules.codec.encoder import VideoEncoder
from src.dav.modules.remote_desktop.injector_base import NullSyntheticInjector
from src.dav.modules.remote_desktop.protocol import EvType, INPUT_PACKET_SIZE, InputEventPacket
from src.dav.modules.stream_engine.receiver_worker import ReceiverWorker
from src.dav.modules.stream_engine.sender_worker import SenderWorker
from src.dav.modules.universal_input.gamepad_capturer import SyntheticGamepadBackend
from src.dav.modules.universal_input.gamepad_normalizer import (
    classify_controller_kind,
    normalize_generic_joystick,
)
from src.dav.modules.universal_input.keyboard_translator import (
    MOD_ALT,
    MOD_CTRL,
    ClientKeyboardTranslator,
    HostKeyboardReproducer,
    unicode_to_xkb_keysym,
)
from src.dav.modules.universal_input.models import (
    ClientKeyboardProfileDTO,
    ControllerKind,
    GamepadButtonMask,
    GamepadStateDTO,
)


def _bind_loopback_udp() -> tuple[socket.socket, int]:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
    s.bind(("127.0.0.1", 0))
    return s, int(s.getsockname()[1])


def test_client_keyboard_tilde_dead_keys_and_host_reproduction():
    """Garante que '~', dead keys, simbolos ABNT2/US, AltGr e WASD sejam traduzidos fielmente."""
    abnt_profile = ClientKeyboardProfileDTO(layout_code="pt-BR", os_family="windows", variant="abnt2")
    tr_br = ClientKeyboardTranslator(profile=abnt_profile)

    # 1. Pressionar dead_tilde inicial no ABNT2 aguarda composicao (nao emite aspas incorretas)
    assert tr_br.translate_key_press(qt_key=0x01001253, text="") == []

    # 2. Usuario digitou '~' + Espaco no cliente -> commitString entrega '~' literal (0x7E)
    tilde_acts = tr_br.translate_ime_commit("~")
    assert len(tilde_acts) == 1
    assert tilde_acts[0].mode == "unicode"
    assert tilde_acts[0].codepoint == ord("~")

    # 3. Usuario digitou '~' + 'a' -> 'ã' (0xE3) e '~' + '/' -> '~/'
    composed_a = tr_br.translate_ime_commit("ã")
    assert len(composed_a) == 1 and composed_a[0].codepoint == ord("ã")

    path_acts = tr_br.translate_ime_commit("~/")
    assert [a.codepoint for a in path_acts] == [ord("~"), ord("/")]

    # 4. Cliente US pressionando Shift + ` (~ direto via keyPressEvent) -> KEY_UNICODE 0x7E
    us_profile = ClientKeyboardProfileDTO(layout_code="en-US", os_family="linux", variant="standard")
    tr_us = ClientKeyboardTranslator(profile=us_profile)
    us_tilde = tr_us.translate_key_press(qt_key=0x7E, modifiers_mask=0x01, text="~")
    assert len(us_tilde) == 1
    assert us_tilde[0].mode == "unicode"
    assert us_tilde[0].codepoint == 0x7E

    # 5. AltGr no Windows (chega como Ctrl+Alt + texto imprimivel, ex: '°' ou '?') -> KEY_UNICODE
    altgr_acts = tr_br.translate_key_press(
        qt_key=ord("W"),
        modifiers_mask=(MOD_CTRL | MOD_ALT),
        text="?",
    )
    assert len(altgr_acts) == 1
    assert altgr_acts[0].mode == "unicode"
    assert altgr_acts[0].codepoint == ord("?")

    # 6. Atalho Ctrl + ~ (console/IDE) -> tecla HID 0x35
    shortcut_tilde = tr_br.translate_key_press(qt_key=0x01001253, modifiers_mask=MOD_CTRL, text="")
    assert len(shortcut_tilde) == 1
    assert shortcut_tilde[0].mode == "hid"
    assert shortcut_tilde[0].hid_code == 0x35

    # 7. Jogos (segurar W): usa HID fisico com KEY_DOWN e KEY_UP simetricos
    w_down = tr_br.translate_key_press(qt_key=ord("W"), text="w", native_scancode=17)
    assert len(w_down) == 1 and w_down[0].mode == "hid" and w_down[0].hid_code == 0x1A and not w_down[0].is_up
    w_up = tr_br.translate_key_release(qt_key=ord("W"), native_scancode=17)
    assert len(w_up) == 1 and w_up[0].mode == "hid" and w_up[0].hid_code == 0x1A and w_up[0].is_up

    # 8. Reproducao agnostica no Host (UTF-16 Win32, XKB KeySym Wayland/X11 e uinput BR/US)
    assert HostKeyboardReproducer.codepoint_to_utf16_units(ord("~")) == [0x007E]
    assert unicode_to_xkb_keysym(ord("~")) == 0x007E
    assert unicode_to_xkb_keysym(ord("ã")) == 0x00E3

    rep_br = HostKeyboardReproducer(host_profile=abnt_profile)
    rep_us = HostKeyboardReproducer(host_profile=us_profile)
    assert rep_br.codepoint_to_uinput_sequence(ord("~")) == [(40, 1), (40, 0), (57, 1), (57, 0)]
    assert rep_us.codepoint_to_uinput_sequence(ord("~")) == [(42, 1), (41, 1), (41, 0), (42, 0)]


def test_controller_normalization_ds4_dualsense_xbox_generic_and_24b_wire():
    """Valida DualShock 4, DualSense (Touchpad), Xbox e Gamepads Genericos em 24 bytes exatos."""
    assert classify_controller_kind(0x054C, 0x0CE6, "Wireless Controller") == ControllerKind.DUALSENSE
    assert classify_controller_kind(0x054C, 0x09CC, "Sony Interactive") == ControllerKind.DUALSHOCK4
    assert classify_controller_kind(0x045E, 0x0B12, "Controller") == ControllerKind.XBOX
    assert classify_controller_kind(0x0079, 0x0006, "Twin USB Joystick") == ControllerKind.GENERIC

    # DualSense HID raw: botao 1 (Cross->SOUTH), botao 13 (Touchpad->TOUCHPAD_CLICK), gatilhos eixos 3/4
    buttons = [0] * 15
    buttons[1] = 1   # Cross -> SOUTH
    buttons[13] = 1  # Touchpad Click
    axes = [12000, -15000, 5000, 32767, -32768, 8000]  # lx, ly, rx, L2=max, R2=0, ry
    ds_state = normalize_generic_joystick(
        local_slot=1,
        axes_i16=axes,
        buttons_pressed=buttons,
        hat_dpad_mask=int(GamepadButtonMask.DPAD_RIGHT),
        vendor_id=0x054C,
        product_id=0x0CE6,
        device_name="DualSense Wireless Controller",
    )
    assert ds_state.kind == ControllerKind.DUALSENSE
    assert ds_state.buttons_mask & int(GamepadButtonMask.SOUTH)
    assert ds_state.buttons_mask & int(GamepadButtonMask.TOUCHPAD_CLICK)
    assert ds_state.buttons_mask & int(GamepadButtonMask.DPAD_RIGHT)
    assert ds_state.lt_u8 == 255
    assert ds_state.rt_u8 == 0

    # Gamepad Generico DirectInput (Twin USB: 0=Triangle/NORTH, 2=Cross/SOUTH)
    gen_btns = [1, 0, 1, 0, 1, 0, 0, 0, 0, 1]
    gen_state = normalize_generic_joystick(
        local_slot=0,
        axes_i16=[0, 0, 16000, -16000],
        buttons_pressed=gen_btns,
        hat_dpad_mask=int(GamepadButtonMask.DPAD_UP),
        vendor_id=0x0079,
        product_id=0x0006,
        device_name="USB Network Joystick",
    )
    assert gen_state.kind == ControllerKind.GENERIC
    assert gen_state.buttons_mask & int(GamepadButtonMask.WEST)
    assert gen_state.buttons_mask & int(GamepadButtonMask.SOUTH)
    assert gen_state.buttons_mask & int(GamepadButtonMask.LB)
    assert gen_state.buttons_mask & int(GamepadButtonMask.START)
    assert gen_state.buttons_mask & int(GamepadButtonMask.DPAD_UP)

    # Empacotamento e desempacotamento em exatos 24 bytes no PT_INPUT
    b_byte, m_byte, xv, yv, kw, ts = ds_state.to_packet_fields()
    wire = InputEventPacket(
        ev_type=EvType.GAMEPAD_STATE,
        buttons_mask=b_byte,
        modifiers_mask=m_byte,
        x_val=xv,
        y_val=yv,
        key_or_wheel=kw,
        client_ts_us=ts,
    ).pack()
    assert len(wire) == INPUT_PACKET_SIZE == 24

    unpacked_pkt = InputEventPacket.unpack(wire)
    assert unpacked_pkt is not None and unpacked_pkt.ev_type == EvType.GAMEPAD_STATE
    restored = GamepadStateDTO.from_packet_fields(
        unpacked_pkt.buttons_mask,
        unpacked_pkt.modifiers_mask,
        unpacked_pkt.x_val,
        unpacked_pkt.y_val,
        unpacked_pkt.key_or_wheel,
        unpacked_pkt.client_ts_us,
    )
    assert restored.local_slot == 1
    assert restored.kind == ControllerKind.DUALSENSE
    assert restored.buttons_mask == ds_state.buttons_mask
    assert restored.lt_u8 == 255


def test_multi_peer_controllers_and_e2e_remote_rumble_tester():
    """
    Conecta simultaneamente 2 acessos clientes P2P ao mesmo Host (mesmo PIN),
    injeta 3 controles distintos (DualSense, DualShock 4 e Xbox) e valida que clicar
    no Testador de Controles do Host faz vibrar fisicamente os controles dos clientes remotos!
    """
    os.environ["DAV_HEADLESS_SYNTHETIC"] = "1"
    pin = "515-251"
    tx_sock, tx_port = _bind_loopback_udp()
    rx1_sock, _ = _bind_loopback_udp()
    rx2_sock, _ = _bind_loopback_udp()

    capturer = CaptureService().create_capturer(width=320, height=180, fps=30).data
    assert capturer is not None
    encoder = VideoEncoder(codec_type="jpeg", width=320, height=180, fps=30, bitrate_kbps=2000)
    synth_inj = NullSyntheticInjector(elevated=True)

    roster_updates: List[List[Dict[str, Any]]] = []
    rumble_acks: List[Dict[str, Any]] = []
    ack_evt = threading.Event()

    def _on_host_remote_evt(kind: str, payload: Any) -> None:
        if kind == "gamepad_roster":
            roster_updates.append(list(payload))
        elif kind == "gamepad_rumble_ack":
            rumble_acks.append(dict(payload))
            ack_evt.set()

    sender = SenderWorker(
        sock=tx_sock,
        capturer=capturer,
        encoder=encoder,
        pin=pin,
        input_injector=synth_inj,
        initial_permissions={"allow_input": True, "allow_gamepad": True},
        on_remote_event=_on_host_remote_evt,
    )

    gp_backend_1 = SyntheticGamepadBackend(initial_controllers=2, kind=ControllerKind.DUALSENSE)
    gp_backend_1.set_synthetic_state(
        GamepadStateDTO(
            local_slot=0,
            kind=ControllerKind.DUALSENSE,
            connected=True,
            buttons_mask=int(GamepadButtonMask.SOUTH | GamepadButtonMask.TOUCHPAD_CLICK),
            rt_u8=210,
            lx_i16=14000,
            device_name="DualSense PS5 Cliente 1",
        )
    )
    gp_backend_1.set_synthetic_state(
        GamepadStateDTO(
            local_slot=1,
            kind=ControllerKind.DUALSHOCK4,
            connected=True,
            buttons_mask=int(GamepadButtonMask.EAST),
            lt_u8=180,
            device_name="DualShock 4 Cliente 1",
        )
    )

    gp_backend_2 = SyntheticGamepadBackend(initial_controllers=1, kind=ControllerKind.XBOX)
    gp_backend_2.set_synthetic_state(
        GamepadStateDTO(
            local_slot=0,
            kind=ControllerKind.XBOX,
            connected=True,
            buttons_mask=int(GamepadButtonMask.WEST),
            rx_i16=-12000,
            device_name="Xbox Series Cliente 2",
        )
    )

    client1_rumble_events: List[Dict[str, Any]] = []
    client2_rumble_events: List[Dict[str, Any]] = []

    rx1 = ReceiverWorker(
        sock=rx1_sock,
        decoder=None,
        pin=pin,
        candidates=[("127.0.0.1", tx_port, "lan")],
        gamepad_backend=gp_backend_1,
        on_rumble_event=lambda e: client1_rumble_events.append(e),
    )
    rx2 = ReceiverWorker(
        sock=rx2_sock,
        decoder=None,
        pin=pin,
        candidates=[("127.0.0.1", tx_port, "lan")],
        gamepad_backend=gp_backend_2,
        on_rumble_event=lambda e: client2_rumble_events.append(e),
    )

    try:
        sender.start()
        rx1.start()
        # Aguarda Peer 1 fechar PAKE e receber permissoes
        t_dead = time.monotonic() + 3.0
        while time.monotonic() < t_dead and not (rx1.dp.pake.confirmed and rx1.peer_permissions.allow_gamepad):
            time.sleep(0.02)
        assert rx1.dp.pake.confirmed and rx1.peer_permissions.allow_gamepad

        # Inicia Peer 2 simultaneamente no mesmo PIN!
        rx2.start()
        t_dead2 = time.monotonic() + 3.0
        while time.monotonic() < t_dead2 and not (rx2.dp.pake.confirmed and rx2.peer_permissions.allow_gamepad):
            time.sleep(0.02)
        assert rx2.dp.pake.confirmed and rx2.peer_permissions.allow_gamepad

        # Ativa os controles nos 2 clientes remotos
        rx1.set_gamepad_enabled(True)
        rx2.set_gamepad_enabled(True)

        # Aguarda o VirtualGamepadHub do Host registrar os 3 controles (2 do Cliente 1 + 1 do Cliente 2)
        t_dead3 = time.monotonic() + 2.5
        while time.monotonic() < t_dead3 and len(sender.gamepad_hub.get_roster_snapshot()) < 3:
            time.sleep(0.02)

        roster = sender.gamepad_hub.get_roster_snapshot()
        assert len(roster) == 3
        profiles = {r["host_slot"]: r["emulated_profile"] for r in roster}
        assert "synthetic_ds4" in profiles.values()
        assert "synthetic_x360" in profiles.values()

        # Testa injecao de '~' via KEY_UNICODE do Cliente 1 para o Host
        tilde_pkt = InputEventPacket(ev_type=EvType.KEY_UNICODE, key_or_wheel=ord("~"))
        assert rx1.send_remote_input(tilde_pkt)
        t_dead_k = time.monotonic() + 1.5
        while time.monotonic() < t_dead_k and not any(
            p.ev_type == EvType.KEY_UNICODE and p.key_or_wheel == ord("~") for _, p in synth_inj.events
        ):
            time.sleep(0.01)
        assert any(p.ev_type == EvType.KEY_UNICODE and p.key_or_wheel == ord("~") for _, p in synth_inj.events)

        # Dispara o Testador de Controles no Host (Broadcast para vibrar todos os clientes conectados!)
        ack_evt.clear()
        assert sender.trigger_gamepad_rumble_test(host_slot=None)

        t_dead_r = time.monotonic() + 2.5
        while time.monotonic() < t_dead_r and len(rumble_acks) < 3:
            time.sleep(0.02)

        assert len(gp_backend_1.rumble_log) >= 2, "Controles DualSense/DS4 do Cliente 1 devem vibrar"
        assert len(gp_backend_2.rumble_log) >= 1, "Controle Xbox do Cliente 2 deve vibrar"
        assert len(client1_rumble_events) >= 2 and client1_rumble_events[0]["ok"] is True
        assert len(client2_rumble_events) >= 1 and client2_rumble_events[0]["ok"] is True
        assert len(rumble_acks) >= 3
        assert all(a["ok"] is True and a["rtt_ms"] > 0.0 for a in rumble_acks)

        # Desativar botao de controles no Cliente 1 zera imediatamente os eixos/botoes no Host
        rx1.set_gamepad_enabled(False)
        time.sleep(0.08)
        roster_after = sender.gamepad_hub.get_roster_snapshot()
        peer1_slots = [r for r in roster_after if r["peer_id"] == "peer:primary"]
        assert all(r["buttons_mask"] == 0 and r["rt_u8"] == 0 for r in peer1_slots)
    finally:
        rx1.stop()
        rx2.stop()
        sender.stop()


def test_overlay_gamepad_button_and_tester_widget_offscreen():
    """Valida o botao vetorial ZONE_GAMEPAD no VideoOverlayControls e o GamepadTesterWidget."""
    from src.ui.qt_compat import QApplication, Qt
    from PySide6.QtGui import QInputMethodEvent, QMouseEvent
    from src.ui.glass.sheets import GamepadTesterWidget
    from src.ui.glass.widgets import VideoOverlayControls
    from src.ui.widgets.canvas import VideoCanvasWidget

    app = QApplication.instance() or QApplication([])
    _ = app

    overlay = VideoOverlayControls()
    overlay.set_remote_visible(True)
    overlay.set_gamepad_visible(True)
    overlay.set_remote_state(True, True)
    overlay.set_gamepad_state(True, True, count=3)

    assert overlay._active_zones() == [
        VideoOverlayControls.ZONE_REMOTE,
        VideoOverlayControls.ZONE_GAMEPAD,
        VideoOverlayControls.ZONE_AUDIO,
        VideoOverlayControls.ZONE_FULLSCREEN,
    ]

    toggled = []
    overlay.gamepad_toggled.connect(lambda: toggled.append(True))
    gp_rect = overlay._zone_rect(VideoOverlayControls.ZONE_GAMEPAD)
    click_ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        gp_rect.center(),
        gp_rect.center(),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    overlay.mousePressEvent(click_ev)
    assert len(toggled) == 1
    assert not overlay.grab().isNull()

    # Testa emissao de '~' via QInputMethodEvent no VideoCanvasWidget
    canvas = VideoCanvasWidget()
    canvas.is_connected = True
    canvas.remote_control_enabled = True
    canvas.host_allows_input = True
    emitted_pkts: List[InputEventPacket] = []
    canvas.remote_input_event.connect(lambda p: emitted_pkts.append(p))
    ime_ev = QInputMethodEvent()
    ime_ev.setCommitString("~")
    canvas.inputMethodEvent(ime_ev)
    assert len(emitted_pkts) == 1
    assert emitted_pkts[0].ev_type == EvType.KEY_UNICODE
    assert emitted_pkts[0].key_or_wheel == ord("~")

    # Testa GamepadTesterWidget e clique no botao de vibrar controle remoto
    tester = GamepadTesterWidget()
    tester.resize(780, 260)
    tester.update_driver_status({"platform": "windows", "driver_name": "ViGEmBus", "driver_ready": True})
    tester.update_client_keyboard_profile({"layout_code": "pt-BR", "variant": "abnt2"})
    tester.update_roster([
        {
            "host_slot": 0,
            "peer_id": "peer:primary",
            "emulated_profile": "ds4",
            "device_name": "PlayStation DualSense (PS5)",
            "buttons_mask": 0x0801,
            "lt_u8": 40,
            "rt_u8": 255,
            "lx_i16": 12400,
            "ly_i16": -3200,
        },
        {
            "host_slot": 1,
            "peer_id": "peer:a1b2c3d4",
            "emulated_profile": "x360",
            "device_name": "Xbox Wireless Controller",
            "buttons_mask": 0x0004,
            "lt_u8": 0,
            "rt_u8": 120,
            "lx_i16": 0,
            "ly_i16": 0,
        },
    ])
    requested_slots = []
    tester.test_remote_rumble_requested.connect(lambda sl: requested_slots.append(sl))
    tester.btn_test_remote_rumble.click()
    assert requested_slots == [None]
    tester.show_rumble_ack({
        "ok": True,
        "device_name": "PlayStation DualSense (PS5)",
        "rtt_ms": 1.3,
        "backend": "sdl2_universal",
    })
    assert "Vibração confirmada" in tester.lbl_rumble_ack.text()
    assert not tester.grab().isNull()
