# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Suite de Regressao v5.2.0 — Zero-Ghosting H.264, Dual-Stack IPv6, Block-FEC, Relay HTTP e ViGEm Nativo
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import asyncio
import http.server
import json
import os
import socket
import struct
import threading
import time
from pathlib import Path
from typing import List

import numpy as np
import pytest

from src.dav.modules.codec.decoder import VideoDecoder
from src.dav.modules.codec.encoder import VideoEncoder
from src.dav.modules.remote_desktop.protocol import EvType, InputEventPacket, WsMsgType
from src.dav.modules.stream_engine.receiver_worker import ReceiverWorker
from src.dav.modules.stream_engine.sender_worker import SenderWorker
from src.dav.modules.transport_p2p.blind_relay import wrap_relay_packet
from src.dav.modules.transport_p2p.candidates import build_peer_candidates, is_lan_address
from src.dav.modules.transport_p2p.data_plane import DataPlaneReceiver, DataPlaneSender
from src.dav.modules.transport_p2p.dualstack import (
    IPV4_DEFAULT_MTU,
    IPV6_SAFE_MTU,
    canonicalize_ip,
    create_dualstack_udp_socket,
    effective_mtu_for_ip,
    format_endpoint_display,
    is_valid_ip,
    normalize_recv_addr,
    parse_host_port,
    sendto_dualstack,
    synthesize_nat64_ipv6,
)
from src.dav.modules.transport_p2p.fec_engine import (
    AdaptiveFecPolicy,
    FEC_ALGO_BLOCKED_RS_GF256,
    FecDecoder,
    FecEncoder,
)
from src.dav.modules.transport_p2p.http_tunnel_relay import HttpTunnelRelayClient
from src.dav.modules.transport_p2p.signaling_client import P2PChannelClient
from src.dav.modules.transport_p2p.stun import (
    STUN_ATTR_XOR_MAPPED_ADDRESS,
    STUN_BINDING_RESPONSE,
    STUN_MAGIC_COOKIE,
    parse_stun_response,
)
from src.dav.modules.universal_input.models import GamepadButtonMask, GamepadStateDTO
from src.dav.modules.universal_input.vigem_ctypes import (
    Ds4Dpad,
    XusbButton,
    build_ds4_report,
    build_xusb_report,
    find_vigem_bus_installer_msi,
    find_vigem_client_dll,
)
from src.signaling.server.dav_rendezvous import DavRendezvousServer
from src.ui.bridge import DecodeWorker, EngineBridge
from src.ui.glass.views import parse_access_input


# =============================================================================
# 1. ViGEm Pre-Compilado Versionado & Structs ctypes
# =============================================================================

def test_vendored_vigem_binaries_and_ctypes_reports():
    dll_path = find_vigem_client_dll()
    msi_path = find_vigem_bus_installer_msi()
    assert dll_path is not None and dll_path.is_file()
    assert msi_path is not None and msi_path.is_file()
    assert dll_path.stat().st_size > 80_000

    state = GamepadStateDTO(
        connected=True,
        buttons_mask=int(
            GamepadButtonMask.SOUTH
            | GamepadButtonMask.RB
            | GamepadButtonMask.DPAD_UP
            | GamepadButtonMask.DPAD_RIGHT
            | GamepadButtonMask.TOUCHPAD_CLICK
        ),
        lt_u8=200,
        rt_u8=255,
        lx_i16=-32768,
        ly_i16=-16000,
        rx_i16=32767,
        ry_i16=16000,
    )

    xrep = build_xusb_report(state)
    assert xrep.bLeftTrigger == 200
    assert xrep.bRightTrigger == 255
    assert bool(xrep.wButtons & int(XusbButton.A))
    assert bool(xrep.wButtons & int(XusbButton.RIGHT_SHOULDER))
    assert xrep.sThumbLY == 16000  # Y invertido para XInput

    drep = build_ds4_report(state)
    assert drep.bTriggerL == 200
    assert drep.bTriggerR == 255
    assert (drep.wButtons & 0xF) == int(Ds4Dpad.NORTHEAST)
    assert drep.bSpecial != 0  # Touchpad click


# =============================================================================
# 2. Deduplicacao Rendezvous Legado (Elimina Loop de 1.2s)
# =============================================================================

def test_signaling_legacy_server_no_1200ms_repairing_loop():
    """Simula VPS legado (sem since_index/next_index) e prova que on_paired dispara apenas 1 vez."""
    peer_obj = {
        "node_name": "mijolin",
        "public_ip": "187.10.20.30",
        "public_port": 9000,
        "local_ip": "192.168.1.50",
        "local_port": 9000,
        "candidates": [],
        "nat_type": "cone",
    }

    class _LegacyHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_POST(self):
            ln = int(self.headers.get("Content-Length", "0"))
            _ = self.rfile.read(ln) if ln else b""
            if self.path.endswith("/register"):
                body = json.dumps({
                    "status": "registered",
                    "token": "tok-legacy",
                    "your_public_ip": "45.234.138.8",
                    "relay": {"host": "127.0.0.1", "port": 8768},
                }).encode("utf-8")
            else:
                # Servidor legado ignora since_index e devolve sempre status=paired sem next_index
                body = json.dumps({"status": "paired", "peer": peer_obj}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            # Fecha SSE imediatamente apos o 1o evento (comportamento legado)
            evt = f"data: {json.dumps({'status': 'paired', 'peer': peer_obj})}\n\n".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(evt)))
            self.end_headers()
            self.wfile.write(evt)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _LegacyHandler)
    port = srv.server_address[1]
    t_srv = threading.Thread(target=srv.serve_forever, daemon=True)
    t_srv.start()

    calls: List[dict] = []
    client = P2PChannelClient(rendezvous_host="127.0.0.1", http_port=port, stun_port=8768)
    try:
        reg = client.register_as_sender(
            pin="423-391",
            local_port=9000,
            on_paired_callback=lambda p: calls.append(p),
            endpoint_info={"local_ip": "127.0.0.1", "local_port": 9000, "public_ip": "127.0.0.1", "public_port": 9000, "nat_type": "local", "candidates": []},
        )
        assert reg is not None
        time.sleep(3.2)
        assert len(calls) == 1, f"Esperado exatamente 1 pareamento em 3.2s, obteve {len(calls)}"
    finally:
        client.stop()
        srv.shutdown()
        srv.server_close()


# =============================================================================
# 3. Blindagem PAKE contra SYN2 Espurio Mid-Stream
# =============================================================================

def test_pake_active_session_rejects_rogue_syn2():
    rx_wire: List[bytes] = []
    tx = DataPlaneSender(pin="777-888", send_raw_fn=lambda pkt: rx_wire.append(pkt))
    rx = DataPlaneReceiver(pin="777-888")

    ev1 = rx.process_packet(tx.build_pake_syn())
    assert ev1["reply_pake"] is not None
    evt_s, ack_s = tx.handle_incoming_packet(ev1["reply_pake"])
    assert evt_s == "pake_confirmed"
    assert ack_s is not None
    ev2 = rx.process_packet(ack_s)
    assert rx.pake.confirmed and tx.pake.confirmed

    # Envia 1 frame valido para atualizar last_valid_rx_mono
    rx_wire.clear()
    tx.send_video_frame(b"H264" + b"\x11" * 2048, is_keyframe=True, frame_interval_sec=1 / 60.0)
    for pkt in rx_wire:
        rx.process_packet(pkt)
    assert rx.auth_failures == 0

    # Injeta SYN2 espurio vindo de um novo DataPlaneSender (mesmo PIN, nonce diferente)
    rogue_tx = DataPlaneSender(pin="777-888", send_raw_fn=lambda _p: None)
    rogue_ev = rx.process_packet(rogue_tx.build_pake_syn())
    assert rogue_ev["kind"] == "ignored"
    assert rx.pake.confirmed is True

    # Trafego subsequente do TX original continua descriptografando com 0 auth_failures
    rx_wire.clear()
    tx.send_video_frame(b"H264" + b"\x22" * 2048, is_keyframe=False, frame_interval_sec=1 / 60.0)
    completed = False
    for pkt in rx_wire:
        r = rx.process_packet(pkt)
        if r["kind"] == "video_frame":
            completed = True
    assert completed is True
    assert rx.auth_failures == 0


# =============================================================================
# 4. Block-RS FEC (algo=2) para Mega-IDRs (> 255 fragmentos)
# =============================================================================

def test_blocked_rs_fec_recovers_450kb_mega_idr_with_losses():
    """Prova que um Mega-IDR de 450 KB (~350 fragmentos) recebe FEC algo=2 e recupera 6 perdas."""
    tx_pkts: List[bytes] = []
    tx = DataPlaneSender(pin="555-666", send_raw_fn=lambda p: tx_pkts.append(p))
    rx = DataPlaneReceiver(pin="555-666")

    # Handshake PAKE
    ev1 = rx.process_packet(tx.build_pake_syn())
    _, ack_s = tx.handle_incoming_packet(ev1["reply_pake"])
    rx.process_packet(ack_s)

    mega_idr = os.urandom(450_000)
    k_expected = (len(mega_idr) + tx.max_chunk - 1) // tx.max_chunk
    assert k_expected > 300

    # Garante que AdaptiveFecPolicy nao devolve 0 para Mega-IDRs
    m_pol = AdaptiveFecPolicy.choose_parity(k_data=k_expected, is_keyframe=True, loss_rate=0.01)
    assert m_pol >= 2

    tx_pkts.clear()
    n_sent, _, m_used = tx.send_video_frame(mega_idr, is_keyframe=True, frame_interval_sec=1 / 60.0)
    assert m_used >= 2
    assert n_sent > k_expected

    # Verifica formato algo=2 direto no FecEncoder
    chunks = [mega_idr[i : i + 1300] for i in range(0, len(mega_idr), 1300)]
    parities = FecEncoder.encode_shards(chunks, parity_count=3)
    assert len(parities) >= 6
    parsed_blk = FecDecoder.parse_blocked_parity(parities[0])
    assert parsed_blk is not None and parsed_blk[2] == FEC_ALGO_BLOCKED_RS_GF256

    # Simula perda de 6 fragmentos de video espalhados pelos 3 sub-blocos (2 perdas por bloco!)
    drop_indices = {5, 42, 130, 175, 260, 310}
    recovered_payload = None
    for idx, pkt in enumerate(tx_pkts):
        if idx in drop_indices:
            continue
        ev = rx.process_packet(pkt)
        if ev["kind"] == "video_frame":
            recovered_payload = ev["frame_bytes"]

    assert recovered_payload == mega_idr
    assert rx.fec_recovered_frames == 1


# =============================================================================
# 5. Zero-Ghosting Gate (ReceiverWorker + DecodeWorker) & Gamepad Cadence Cap
# =============================================================================

def test_zero_ghosting_decode_worker_no_silent_pframe_drop():
    bridge = EngineBridge()
    pli_hits = []
    dw = DecodeWorker(bridge, on_pli_needed=lambda: pli_hits.append(1))
    # Nao inicia thread para inspecionar politica da fila deterministicamente

    # 1. Enfileira 10 P-frames: NENHUM P-frame e descartado silenciosamente
    for i in range(10):
        dw.submit(b"P" * 32, 640, 360, is_keyframe=False)
    assert len(dw._q) == 10
    assert dw._awaiting_idr is False

    # 2. Ao exceder max_p_backlog (16), limpa fila, entra em awaiting_idr e solicita PLI
    for i in range(7):
        dw.submit(b"P" * 32, 640, 360, is_keyframe=False)
    assert dw._awaiting_idr is True
    assert len(dw._q) == 0
    assert len(pli_hits) >= 1

    # 3. P-frames orfaos continuam bloqueados ate chegar um IDR limpo
    dw.submit(b"P" * 32, 640, 360, is_keyframe=False)
    assert len(dw._q) == 0

    # 4. IDR limpo desbloqueia o worker e marca flush obrigatorio do DPB
    dw.submit(b"I" * 64, 640, 360, is_keyframe=True)
    assert dw._awaiting_idr is False
    assert dw._need_flush is True
    assert len(dw._q) == 1 and dw._q[0][3] is True


def test_receiver_worker_zero_ghosting_never_releases_broken_pframes_after_450ms():
    """Prova que ReceiverWorker segura P-frames apos ref_gap mesmo depois de > 0.55s ate o IDR."""
    s_tx = create_dualstack_udp_socket(0, rcvbuf_mb=1, sndbuf_mb=1)
    s_rx = create_dualstack_udp_socket(0, rcvbuf_mb=1, sndbuf_mb=1)
    rx_port = int(s_rx.getsockname()[1])

    delivered: List[tuple] = []
    pli_received: List[bytes] = []

    rx = ReceiverWorker(
        sock=s_rx,
        decoder=None,
        pin="112-233",
        candidates=[("127.0.0.1", int(s_tx.getsockname()[1]), "lan")],
        on_encoded_frame=lambda data, w, h, ts, kf: delivered.append((len(data), kf)),
        enable_gamepad_capture=False,
    )
    tx_dp = DataPlaneSender(
        pin="112-233",
        send_raw_fn=lambda pkt: sendto_dualstack(s_tx, pkt, "127.0.0.1", rx_port),
    )

    try:
        rx.start()
        s_tx.settimeout(0.05)
        # Completa PAKE
        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline and not tx_dp.pake.confirmed:
            sendto_dualstack(s_tx, tx_dp.build_pake_syn(), "127.0.0.1", rx_port)
            try:
                pkt, _ = s_tx.recvfrom(4096)
                evt, rep = tx_dp.handle_incoming_packet(pkt)
                if rep:
                    sendto_dualstack(s_tx, rep, "127.0.0.1", rx_port)
            except socket.timeout:
                pass
        assert tx_dp.pake.confirmed

        # Frame 1: IDR limpo (deve passar!)
        tx_dp.send_video_frame(b"IDR1" + b"\x01" * 600, is_keyframe=True, frame_interval_sec=1 / 60.0)
        time.sleep(0.08)
        assert len(delivered) == 1 and delivered[0][1] is True

        # Simula perda completa do Frame 2 (avanca _video_frame_id sem enviar!)
        tx_dp._video_frame_id += 1

        # Envia P-frames 3..8 ao longo de 0.65s (ultrapassa antigo timeout sujo de 450 ms!)
        for _ in range(6):
            tx_dp.send_video_frame(b"PFRM" + b"\x02" * 600, is_keyframe=False, frame_interval_sec=1 / 60.0)
            time.sleep(0.11)
            try:
                while True:
                    p_in, _ = s_tx.recvfrom(4096)
                    if p_in.startswith(b"DAV_P2P_PLI"):
                        pli_received.append(p_in)
                    else:
                        evt, payload = tx_dp.handle_incoming_packet(p_in)
                        if evt == "workspace_msg" and payload:
                            pli_received.append(payload)
            except socket.timeout:
                pass

        # NENHUM P-frame corrompido pode ter vazado apos 450 ms!
        assert len(delivered) == 1, f"P-frame quebrado vazou para o decoder: {delivered}"
        assert len(pli_received) >= 1

        # Envia IDR limpo de recuperacao -> fluxo volta imediatamente!
        tx_dp.send_video_frame(b"IDR2" + b"\x03" * 600, is_keyframe=True, frame_interval_sec=1 / 60.0)
        time.sleep(0.08)
        assert len(delivered) == 2 and delivered[1][1] is True
    finally:
        rx.stop()
        s_tx.close()


def test_gamepad_125hz_does_not_trigger_input_wake_overshoot():
    class _DummyCap:
        width, height, fps = 320, 240, 60
        def start(self): pass
        def grab_into(self, _buf): return False
        def close(self): pass

    sock = create_dualstack_udp_socket(0, rcvbuf_mb=1, sndbuf_mb=1)
    enc = VideoEncoder(codec_type="raw", width=320, height=240, fps=60)
    sw = SenderWorker(
        sock=sock,
        capturer=_DummyCap(),
        encoder=enc,
        pin="222-333",
        initial_permissions={"allow_input": True, "allow_gamepad": True},
    )
    try:
        gp = GamepadStateDTO(connected=True, lx_i16=12000)
        b_b, m_b, xv, yv, kw, ts = gp.to_packet_fields()
        pkt = InputEventPacket(
            ev_type=EvType.GAMEPAD_STATE,
            buttons_mask=b_b,
            modifiers_mask=m_b,
            x_val=xv,
            y_val=yv,
            key_or_wheel=kw,
            client_ts_us=ts,
        )
        sw._input_wake_evt.clear()
        sw._process_remote_input_bytes("peer:primary", sw.dp, pkt.pack())
        assert not sw._input_wake_evt.is_set(), "GAMEPAD_STATE nao deve acordar encoder acima do FPS"

        key_pkt = InputEventPacket(ev_type=EvType.KEY_DOWN, key_or_wheel=0x1E)
        sw._process_remote_input_bytes("peer:primary", sw.dp, key_pkt.pack())
        assert sw._input_wake_evt.is_set(), "Transicao discreta KEY_DOWN deve sinalizar input_wake_evt"
    finally:
        sw.gamepad_hub.close()
        enc.close()
        sock.close()


# =============================================================================
# 6. Dual-Stack IPv6, STUN IPv6 (0x02), NAT64 RFC 7050 & Parser URI IPv6
# =============================================================================

def test_ipv6_parsing_stun_nat64_and_mtu():
    # Parser de chave de acesso IPv6 + URI direta com PIN
    assert parse_access_input("[2804:3690:8001::1]:9000") == ("2804:3690:8001::1", 9000, "")
    assert parse_access_input("2804:3690:8001::1") == ("2804:3690:8001::1", None, "")
    assert parse_access_input("::1") == ("::1", None, "")
    assert parse_access_input("dav://[2804:3690:8001::1]:9004/423-391") == ("2804:3690:8001::1", 9004, "423391")
    assert parse_access_input("dav://[2804:3690:8001::1]:9004?pin=423-391") == ("2804:3690:8001::1", 9004, "423391")
    assert parse_host_port("[2804:3690::1]:9000") == ("2804:3690::1", 9000)
    assert format_endpoint_display("2804:3690::1", 9000) == "[2804:3690::1]:9000"
    assert format_endpoint_display("::ffff:192.168.10.100", 9000) == "192.168.10.100:9000"
    assert is_valid_ip("2804:3690::1") and is_valid_ip("192.168.10.100")
    assert is_lan_address("::1") and is_lan_address("fd12:3456::1") and not is_lan_address("2804:3690::1")

    # MTU IPv6 seguro vs IPv4
    assert effective_mtu_for_ip("2804:3690::1") == IPV6_SAFE_MTU
    assert effective_mtu_for_ip("45.234.138.8") == IPV4_DEFAULT_MTU

    # Sintese NAT64 RFC 7050 (64:ff9b::/96 + 129.148.26.150 -> 64:ff9b::8194:1a96)
    wk_prefix = bytes.fromhex("0064ff9b0000000000000000")
    assert synthesize_nat64_ipv6("129.148.26.150", prefix_12b=wk_prefix) == "64:ff9b::8194:1a96"

    # Decodificacao STUN RFC 5389 IPv6 (family == 0x02, 128-bit XOR-MAPPED-ADDRESS)
    trans_id = bytes(range(12))
    v6_addr = "2804:3690:8001:45e7::abcd"
    v6_port = 54321
    raw_v6 = socket.inet_pton(socket.AF_INET6, v6_addr)
    xor_mask = struct.pack("!I", STUN_MAGIC_COOKIE) + trans_id
    x_v6 = bytes(a ^ b for a, b in zip(raw_v6, xor_mask))
    x_port = v6_port ^ (STUN_MAGIC_COOKIE >> 16)
    attr = struct.pack("!HHBBH", STUN_ATTR_XOR_MAPPED_ADDRESS, 20, 0, 0x02, x_port) + x_v6
    pkt = struct.pack("!HHI12s", STUN_BINDING_RESPONSE, len(attr), STUN_MAGIC_COOKIE, trans_id) + attr
    assert parse_stun_response(pkt, trans_id=trans_id) == (v6_addr, v6_port)

    # Priorizacao de candidatos IPv6 Global acima de WAN IPv4
    cands = build_peer_candidates({
        "public_ip": "187.1.2.3",
        "public_port": 40000,
        "public_ipv6": "2804:3690:8001::5",
        "public_ipv6_port": 9000,
        "local_ip": "192.168.1.20",
        "local_port": 9000,
    })
    modes = [m for _, _, m in cands]
    assert "ipv6" in modes
    assert modes.index("ipv6") < modes.index("wan")


@pytest.mark.skipif(not getattr(socket, "has_ipv6", False), reason="IPv6 desabilitado no host")
def test_dualstack_socket_ipv6_and_ipv4_mapped_interoperability():
    """Prova que um unico socket Dual-Stack comunica via ::1 (IPv6 puro) e 127.0.0.1 (IPv4)."""
    ds_sock = create_dualstack_udp_socket(0, rcvbuf_mb=1, sndbuf_mb=1)
    assert ds_sock.family == socket.AF_INET6
    ds_port = int(ds_sock.getsockname()[1])
    ds_sock.settimeout(1.0)

    v6_only = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    v4_only = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    v6_only.settimeout(1.0)
    v4_only.settimeout(1.0)
    try:
        v6_only.bind(("::1", 0))
        v4_only.bind(("127.0.0.1", 0))
        v6_port = int(v6_only.getsockname()[1])
        v4_port = int(v4_only.getsockname()[1])

        # Dual-Stack -> IPv6 puro (::1) e volta
        assert sendto_dualstack(ds_sock, b"PING_V6", "::1", v6_port)
        d6, _ = v6_only.recvfrom(64)
        assert d6 == b"PING_V6"
        v6_only.sendto(b"PONG_V6", ("::1", ds_port))
        r6, a6 = ds_sock.recvfrom(64)
        assert r6 == b"PONG_V6"
        assert normalize_recv_addr(a6) == ("::1", v6_port)

        # Dual-Stack -> IPv4 puro (127.0.0.1 via ::ffff:) e volta
        assert sendto_dualstack(ds_sock, b"PING_V4", "127.0.0.1", v4_port)
        d4, _ = v4_only.recvfrom(64)
        assert d4 == b"PING_V4"
        v4_only.sendto(b"PONG_V4", ("127.0.0.1", ds_port))
        r4, a4 = ds_sock.recvfrom(64)
        assert r4 == b"PONG_V4"
        assert normalize_recv_addr(a4) == ("127.0.0.1", v4_port)
    finally:
        ds_sock.close()
        v6_only.close()
        v4_only.close()


# =============================================================================
# 7. Blind Relay Hibrido: HTTP-Stream (Porta 80/443) + UDP Cross-Family IPv4<->IPv6
# =============================================================================

def test_rendezvous_http_stream_relay_and_cross_family_udp_relay():
    """Prova Blind Relay HTTP-Stream E2E e Blind Relay UDP Cross-Family (IPv4 <-> IPv6)."""
    # Aloca portas livres
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as st:
        st.bind(("127.0.0.1", 0))
        http_port = st.getsockname()[1]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as su:
        su.bind(("127.0.0.1", 0))
        stun_port = su.getsockname()[1]

    loop = asyncio.new_event_loop()
    srv = DavRendezvousServer(host="0.0.0.0", http_port=http_port, stun_port=stun_port)

    def _run_srv():
        asyncio.set_event_loop(loop)
        task = loop.create_task(srv.start())
        try:
            loop.run_until_complete(task)
        except Exception:
            pass
        finally:
            try:
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for pt in pending:
                    pt.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass

    t_srv = threading.Thread(target=_run_srv, daemon=True)
    t_srv.start()
    time.sleep(0.35)

    p2p = P2PChannelClient(rendezvous_host="127.0.0.1", http_port=http_port, stun_port=stun_port)
    rx_http_pkts: List[bytes] = []
    tx_http_pkts: List[bytes] = []
    rel_s = None
    rel_r = None
    try:
        reg = p2p.register_as_sender(
            pin="909-808",
            local_port=9000,
            endpoint_info={"local_ip": "127.0.0.1", "local_port": 9000, "public_ip": "127.0.0.1", "public_port": 9000, "nat_type": "local", "candidates": []},
        )
        assert reg is not None

        # A. Teste Blind Relay HTTP-Stream (atravessa firewall que bloqueia 100% do UDP)
        s_ready = threading.Event()
        r_ready = threading.Event()
        rel_s = HttpTunnelRelayClient(
            base_url=f"http://127.0.0.1:{http_port}",
            pin="909-808",
            role="S",
            on_packet_rx=lambda b: tx_http_pkts.append(b),
            on_connected=s_ready.set,
        )
        rel_r = HttpTunnelRelayClient(
            base_url=f"http://127.0.0.1:{http_port}",
            pin="909-808",
            role="R",
            on_packet_rx=lambda b: rx_http_pkts.append(b),
            on_connected=r_ready.set,
        )
        rel_s.start()
        rel_r.start()
        assert s_ready.wait(timeout=3.0) and r_ready.wait(timeout=3.0)

        rel_s.send_datagram(b"ENC_VIDEO_FRAME_001")
        rel_r.send_datagram(b"ENC_INPUT_GAMEPAD_001")

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and (not rx_http_pkts or not tx_http_pkts):
            time.sleep(0.03)
        assert b"ENC_VIDEO_FRAME_001" in rx_http_pkts
        assert b"ENC_INPUT_GAMEPAD_001" in tx_http_pkts

        # B. Teste Blind Relay UDP Cross-Family: Sender IPv4 (127.0.0.1) <-> Receiver IPv6 (::1)
        if getattr(socket, "has_ipv6", False):
            s_v4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            r_v6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            s_v4.settimeout(1.5)
            r_v6.settimeout(1.5)
            try:
                s_v4.bind(("127.0.0.1", 0))
                r_v6.bind(("::1", 0))
                s_v4.sendto(wrap_relay_packet("909808", b"S", b"BIND"), ("127.0.0.1", stun_port))
                assert s_v4.recvfrom(64)[0] in (b"DAV_RLY_ACK", b"DAV_RLY_PEER_READY")
                r_v6.sendto(wrap_relay_packet("909808", b"R", b"BIND"), ("::1", stun_port))
                assert r_v6.recvfrom(64)[0] in (b"DAV_RLY_ACK", b"DAV_RLY_PEER_READY")

                # Envia pacote cifrado do IPv4-only -> chega no IPv6-only!
                s_v4.sendto(wrap_relay_packet("909808", b"S", b"CROSS_FAMILY_V4_TO_V6"), ("127.0.0.1", stun_port))
                got_v6, _ = r_v6.recvfrom(128)
                assert got_v6 == b"CROSS_FAMILY_V4_TO_V6"

                # Envia retorno do IPv6-only -> chega no IPv4-only!
                r_v6.sendto(wrap_relay_packet("909808", b"R", b"CROSS_FAMILY_V6_TO_V4"), ("::1", stun_port))
                # Drena eventual DAV_RLY_PEER_READY antes do payload
                got_v4 = b""
                for _ in range(3):
                    d, _ = s_v4.recvfrom(128)
                    if d == b"CROSS_FAMILY_V6_TO_V4":
                        got_v4 = d
                        break
                assert got_v4 == b"CROSS_FAMILY_V6_TO_V4"
            finally:
                s_v4.close()
                r_v6.close()
    finally:
        if rel_s is not None:
            rel_s.stop()
        if rel_r is not None:
            rel_r.stop()
        p2p.stop()
        loop.call_soon_threadsafe(loop.stop)
