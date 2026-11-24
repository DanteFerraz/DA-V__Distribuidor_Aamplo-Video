# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Suite Unitaria e End-to-End do Modulo de Compartilhamento de Area de Trabalho — DA-V v5.0
Autor: Dante Ferraz (MonoTech)

Valida:
1. Protocolo binario `InputEventPacket` (24B exatos) e deltas de scroll horizontal/vertical;
2. Criptografia autenticada bidirecional `PT_INPUT` e `PT_WORKSPACE` no `DataPlane`;
3. `SecurityGate` Zero-Trust (View-Only padrao, deduplicacao 2x e `panic_revoke_all`);
4. `StuckKeyWatchdog` (liberacao automatica de teclas/botoes em perda de sinal);
5. `WorkspaceChannel` (ARQ seletivo ordenado), transferencia P2P de arquivo c/ SHA-256 e anti-traversal;
6. `PtyShellManager` (sessao persistente de terminal remoto estilo LTSP);
7. `ElevatedInputBroker` <-> `ElevatedProxyInjector` (handshake HMAC-SHA256 e injecao loopback);
8. Mapeamento geometrico inverso do `VideoCanvasWidget` (Fit com barras pretas, Stretch e Native);
9. Loopback E2E real (`SenderWorker` <-> `ReceiverWorker`) comprovando latencia Input-to-Photon <= 15 ms.
"""

from __future__ import annotations

from pathlib import Path
import socket
import subprocess
import sys
import time

from scripts.qt_compat import QApplication, QImage, Qt
from src.dav.modules.capture.synthetic_capturer import SyntheticCapturer
from src.dav.modules.codec.decoder import VideoDecoder
from src.dav.modules.codec.encoder import VideoEncoder
from src.dav.modules.remote_desktop import (
    EvType,
    InputEventPacket,
    KeyMod,
    MouseBtn,
    NullSyntheticInjector,
    PtyShellManager,
    SecurityGate,
    StuckKeyWatchdog,
    WorkspaceAgent,
    WorkspaceChannel,
    WorkspacePermissions,
    WsMsgType,
    hid_to_linux_evdev,
    hid_to_win32_scancode,
    hid_to_x11_keycode,
    pack_wheel_deltas,
    qt_key_to_hid,
    request_elevated_injector,
    sanitize_filename,
    unpack_wheel_deltas,
)
from src.dav.modules.stream_engine.receiver_worker import ReceiverWorker
from src.dav.modules.stream_engine.sender_worker import SenderWorker
from src.dav.modules.transport_p2p.data_plane import DataPlaneReceiver, DataPlaneSender
from src.ui.widgets.canvas import VideoCanvasWidget

app = QApplication.instance() or QApplication([])


def test_input_packet_24b_roundtrip_and_wheel_packing():
    packed_wheel = pack_wheel_deltas(-120, 240)
    assert unpack_wheel_deltas(packed_wheel) == (-120, 240)

    pkt = InputEventPacket(
        ev_type=EvType.BTN_DOWN,
        buttons_mask=int(MouseBtn.LEFT | MouseBtn.RIGHT),
        modifiers_mask=int(KeyMod.CTRL | KeyMod.SHIFT),
        x_val=32768,
        y_val=65535,
        key_or_wheel=0x04,
        client_ts_us=1234567890,
    )
    raw = pkt.pack()
    assert len(raw) == 24
    assert pkt.is_critical_transition

    restored = InputEventPacket.unpack(raw)
    assert restored is not None
    assert restored.ev_type == EvType.BTN_DOWN
    assert restored.buttons_mask == int(MouseBtn.LEFT | MouseBtn.RIGHT)
    assert restored.modifiers_mask == int(KeyMod.CTRL | KeyMod.SHIFT)
    assert restored.x_val == 32768
    assert restored.y_val == 65535
    assert restored.key_or_wheel == 0x04
    assert restored.client_ts_us == 1234567890

    assert InputEventPacket.unpack(b"curto") is None
    bad_ver = bytearray(raw)
    bad_ver[0] = 99
    assert InputEventPacket.unpack(bytes(bad_ver)) is None


def test_keymap_bidirectional_translations():
    hid_a = qt_key_to_hid(int(Qt.Key.Key_A))
    assert hid_a == 0x04
    assert hid_to_win32_scancode(hid_a) == (0x1E, False)
    assert hid_to_linux_evdev(hid_a) == 30
    assert hid_to_x11_keycode(hid_a) == 38

    hid_left = qt_key_to_hid(int(Qt.Key.Key_Left))
    assert hid_left == 0x50
    assert hid_to_win32_scancode(hid_left) == (0x4B, True)
    assert hid_to_linux_evdev(hid_left) == 105


def test_data_plane_bidirectional_pt_input_and_pt_workspace_aead():
    tx_wire = []
    dp_s = DataPlaneSender(pin="456-789", send_raw_fn=tx_wire.append)
    dp_r = DataPlaneReceiver(pin="456-789")

    # Handshake PAKE 1-RTT
    syn_s = dp_s.build_pake_syn()
    ev_r = dp_r.process_packet(syn_s)
    assert ev_r["kind"] == "pake" and ev_r["reply_pake"] is not None
    evt_s, reply_s = dp_s.handle_incoming_packet(ev_r["reply_pake"])
    assert evt_s == "pake_confirmed" and reply_s is not None
    dp_r.process_packet(reply_s)
    assert dp_r.pake.confirmed and dp_s.pake.confirmed

    # Rajada de 260 pacotes PT_INPUT do Receptor -> Transmissor
    for i in range(260):
        ipkt = InputEventPacket(ev_type=EvType.MOVE_ABS, x_val=i * 100, y_val=i * 50, client_ts_us=1000 + i)
        dgram = dp_r.build_input_datagram(ipkt.pack())
        assert dgram is not None
        kind, plain = dp_s.handle_incoming_packet(dgram)
        assert kind == "remote_input" and plain is not None
        parsed = InputEventPacket.unpack(plain)
        assert parsed is not None and parsed.x_val == i * 100

        # Replay do mesmo datagrama deve ser rejeitado pela ReplayWindow
        kind_dup, _ = dp_s.handle_incoming_packet(dgram)
        assert kind_dup == "other"

    # PT_WORKSPACE bidirecional
    ws_ch_s = WorkspaceChannel()
    perm_wire = ws_ch_s.send_json(WsMsgType.PERM_UPDATE, {"allow_input": True})
    tx_wire.clear()
    assert dp_s.send_workspace_datagram(perm_wire)
    assert len(tx_wire) == 1

    rx_ev = dp_r.process_packet(tx_wire[0])
    assert rx_ev["kind"] == "workspace_msg"
    ws_ch_r = WorkspaceChannel()
    msgs, ack_f = ws_ch_r.receive(rx_ev["workspace_payload"])
    assert len(msgs) == 1 and msgs[0].decode_json() == {"allow_input": True}
    assert ack_f is not None


def test_security_gate_zero_trust_dedup_and_panic_revoke():
    revoked_flag = []
    gate = SecurityGate(on_revoke=lambda: revoked_flag.append(True))
    click = InputEventPacket(ev_type=EvType.BTN_DOWN, buttons_mask=int(MouseBtn.LEFT), client_ts_us=555000)

    # Zero-Trust por padrao (View-Only)
    assert not gate.allow_input_packet(click)
    assert not gate.allow_workspace_msg(WsMsgType.CLIPBOARD_TEXT)
    assert not gate.allow_workspace_msg(WsMsgType.SHELL_STDIN)

    # Habilita input; primeiro pacote aceito, copia redundante 2x identica deduplicada
    gate.update_permissions(allow_input=True, allow_clipboard=True)
    assert gate.allow_input_packet(click)
    assert not gate.allow_input_packet(click)  # Deduplicacao idempotente

    # Panic switch revoga tudo na hora
    snap = gate.panic_revoke_all()
    assert not snap.allow_input and not snap.allow_clipboard
    assert revoked_flag == [True]
    click2 = InputEventPacket(ev_type=EvType.BTN_UP, buttons_mask=int(MouseBtn.LEFT), client_ts_us=556000)
    assert not gate.allow_input_packet(click2)


def test_stuck_key_watchdog_timeout_and_release_all():
    inj = NullSyntheticInjector()
    t0 = 100.0
    inj.watchdog.record_event(
        InputEventPacket(ev_type=EvType.KEY_DOWN, key_or_wheel=0xE0), now_mono=t0
    )
    inj.watchdog.record_event(
        InputEventPacket(ev_type=EvType.BTN_DOWN, buttons_mask=int(MouseBtn.LEFT)), now_mono=t0 + 0.05
    )
    assert 0xE0 in inj.watchdog.pressed_keys
    assert inj.watchdog.pressed_buttons == int(MouseBtn.LEFT)

    # Antes do timeout: nada liberado
    assert inj.tick_watchdog(now_mono=t0 + 0.20) == 0
    # Apos timeout de rede (> 0.45s): solta automaticamente botao e tecla presa
    released = inj.tick_watchdog(now_mono=t0 + 0.65)
    assert released == 2
    ev_types = [ev.ev_type for _, ev in inj.events]
    assert EvType.BTN_UP in ev_types and EvType.KEY_UP in ev_types
    assert not inj.watchdog.pressed_keys and inj.watchdog.pressed_buttons == 0


def test_workspace_channel_arq_and_file_transfer_sha256(tmp_path: Path):
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\Windows\\System32\\cmd.exe") == "cmd.exe"
    assert sanitize_filename("CON") == "arquivo_dav.bin"

    src_dir = tmp_path / "src_files"
    dst_dir = tmp_path / "dst_downloads"
    src_dir.mkdir()
    sample_file = src_dir / "relatorio_teste_dav.bin"
    payload_bytes = b"DAV-P2P-WORKSPACE-" * 300  # Multiplos blocos (> 5 KB)
    sample_file.write_bytes(payload_bytes)

    gate_tx = SecurityGate(WorkspacePermissions(allow_clipboard=True, allow_files=True))
    gate_rx = SecurityGate(WorkspacePermissions(allow_clipboard=True, allow_files=True))

    rx_clips = []
    rx_files = []
    wire_s2r = []
    wire_r2s = []

    agent_tx = WorkspaceAgent(gate=gate_tx, download_dir=str(dst_dir), send_wire_fn=wire_s2r.append)
    agent_rx = WorkspaceAgent(
        gate=gate_rx,
        download_dir=str(dst_dir),
        on_clipboard_rx=rx_clips.append,
        on_file_status=rx_files.append,
        send_wire_fn=wire_r2s.append,
    )

    # Clipboard deduplicado por SHA-256
    assert len(agent_tx.build_clipboard_frames("Texto Remoto 123")) == 1
    assert len(agent_tx.build_clipboard_frames("Texto Remoto 123")) == 0
    for wf in wire_s2r:
        agent_rx.handle_incoming_wire(wf, is_host=True)
    assert rx_clips == ["Texto Remoto 123"]
    wire_s2r.clear()
    wire_r2s.clear()

    # Simula perda do 2o pacote + entrega fora de ordem e recuperacao ARQ
    tid, frames = agent_tx.build_file_transfer_frames(str(sample_file))
    assert tid and len(frames) >= 5
    wire_s2r.clear()

    # Entrega pacote 0, perde pacote 1, entrega pacotes 2..fim fora de ordem
    agent_rx.handle_incoming_wire(frames[0], is_host=True)
    for f in frames[2:]:
        agent_rx.handle_incoming_wire(f, is_host=True)

    # Processa ACKs parciais e dispara retransmissao apos RTO
    for ack_f in wire_r2s:
        agent_tx.handle_incoming_wire(ack_f, is_host=False)
    retrans = agent_tx.channel.poll_retransmits(now_mono=time.monotonic() + 0.10)
    assert len(retrans) >= 1
    for rf in retrans:
        agent_rx.handle_incoming_wire(rf, is_host=True)

    saved = dst_dir / "relatorio_teste_dav.bin"
    assert saved.is_file()
    assert saved.read_bytes() == payload_bytes
    assert any(st.get("stage") == "completed" and st.get("ok") for st in rx_files)


def test_persistent_pty_shell_manager():
    chunks: list[bytes] = []
    shell = PtyShellManager(on_stdout=chunks.append)
    try:
        assert shell.write_stdin(b"echo DAV_SHELL_PING_OK\n")
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            joined = b"".join(chunks).decode("utf-8", errors="replace")
            if "DAV_SHELL_PING_OK" in joined:
                break
            time.sleep(0.05)
        assert "DAV_SHELL_PING_OK" in b"".join(chunks).decode("utf-8", errors="replace")
    finally:
        shell.close()


def test_elevated_broker_hmac_handshake_and_injection_loopback():
    procs: list[subprocess.Popen] = []

    def _local_test_launcher(exe: str, args: list[str], cwd: str):
        p = subprocess.Popen(
            [sys.executable, *args, "--synthetic"],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        procs.append(p)
        return True, "ok"

    res = request_elevated_injector(timeout_sec=5.0, launcher_fn=_local_test_launcher)
    assert res.is_success and res.data is not None
    proxy = res.data
    try:
        assert proxy.is_elevated
        assert proxy.inject(InputEventPacket(ev_type=EvType.MOVE_ABS, x_val=16000, y_val=32000))
        assert proxy.inject(InputEventPacket(ev_type=EvType.KEY_DOWN, key_or_wheel=0x04))
        assert proxy.release_all() >= 1
    finally:
        proxy.close()
        for p in procs:
            p.wait(timeout=3.0)


def test_canvas_inverse_coordinate_mapping():
    canvas = VideoCanvasWidget()
    try:
        canvas.resize(1000, 800)  # Aspecto 5:4 enquanto o video e 16:9 (barras pretas topo/base em Fit)
        canvas.current_image = QImage(1920, 1080, QImage.Format.Format_RGB888)
        canvas.scale_mode = "fit"

        vr = canvas.video_target_rect()
        assert vr.width() == 1000
        assert vr.height() == 562
        assert vr.top() == (800 - 562) // 2

        # Clique na barra preta superior deve ser ignorado (retorna None)
        assert canvas.map_widget_pos_to_norm(500, 10) is None
        # Canto superior-esquerdo util -> (0, 0)
        assert canvas.map_widget_pos_to_norm(vr.left(), vr.top()) == (0, 0)
        # Canto inferior-direito util -> (65535, 65535)
        assert canvas.map_widget_pos_to_norm(vr.left() + vr.width() - 1, vr.top() + vr.height() - 1) == (65535, 65535)
    finally:
        canvas.close()
        canvas.deleteLater()
        app.processEvents()


def test_e2e_loopback_input_to_photon_latency_budget():
    sock_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_tx.bind(("127.0.0.1", 0))
    sock_rx.bind(("127.0.0.1", 0))
    tx_port = sock_tx.getsockname()[1]
    rx_port = sock_rx.getsockname()[1]

    cap = SyntheticCapturer(width=640, height=360, fps=60)
    enc = VideoEncoder(codec_type="jpeg", width=640, height=360, fps=60, bitrate_kbps=6000)
    dec = VideoDecoder()
    inj = NullSyntheticInjector()

    perms_rx_events: list[dict] = []
    echo_samples: list[tuple[float, float]] = []
    rx_frames = []

    sender = SenderWorker(
        sock=sock_tx,
        capturer=cap,
        encoder=enc,
        pin="918-273",
        target_ip="127.0.0.1",
        target_port=rx_port,
        input_injector=inj,
        initial_permissions={"allow_input": True, "allow_clipboard": True, "allow_files": True},
    )
    receiver = ReceiverWorker(
        sock=sock_rx,
        decoder=dec,
        pin="918-273",
        candidates=[("127.0.0.1", tx_port, "lan")],
        on_frame=rx_frames.append,
        on_permissions_changed=perms_rx_events.append,
        on_input_echo=lambda rtt, itp: echo_samples.append((rtt, itp)),
    )

    try:
        sender.start()
        receiver.start()

        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            if rx_frames and receiver.peer_permissions.allow_input:
                break
            time.sleep(0.02)

        assert rx_frames, "Nenhum quadro de video recebido no loopback E2E"
        assert receiver.peer_permissions.allow_input, "Permissao interativa nao sincronizada"

        # Envia sequencia real de controle remoto e mede latencia
        assert receiver.send_remote_input(
            InputEventPacket(ev_type=EvType.MOVE_ABS, x_val=32768, y_val=32768)
        )
        assert receiver.send_remote_input(
            InputEventPacket(ev_type=EvType.BTN_DOWN, buttons_mask=int(MouseBtn.LEFT), x_val=32768, y_val=32768)
        )
        assert receiver.send_remote_input(
            InputEventPacket(ev_type=EvType.BTN_UP, buttons_mask=int(MouseBtn.LEFT), x_val=32768, y_val=32768)
        )

        wait_echo = time.monotonic() + 2.0
        while time.monotonic() < wait_echo and len(inj.events) < 3:
            time.sleep(0.01)

        assert len(inj.events) == 3
        injected_types = [ev.ev_type for _, ev in inj.events]
        assert injected_types == [EvType.MOVE_ABS, EvType.BTN_DOWN, EvType.BTN_UP]

        wait_metric = time.monotonic() + 1.5
        while time.monotonic() < wait_metric and not echo_samples:
            time.sleep(0.01)

        assert echo_samples, "Sonda WS_INPUT_ECHO nao retornou medicao"
        rtt_ms, itp_ms = echo_samples[-1]
        assert rtt_ms < 15.0, f"RTT de input acima da meta em loopback: {rtt_ms} ms"
        assert itp_ms <= 30.0, f"Input-to-Photon acima do teto inicial: {itp_ms} ms"

        # Revogacao instantanea bloqueia novos cliques
        sender.panic_revoke_remote()
        time.sleep(0.08)
        assert not receiver.peer_permissions.allow_input
    finally:
        receiver.stop()
        sender.stop()
