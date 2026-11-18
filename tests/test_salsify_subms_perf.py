# -*- coding: utf-8 -*-
"""
Benchmark e Validacao de Regressao Salsify/SQP Sub-Milissegundo (DA-V v4.7)
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import os
import time
import pytest

from src.dav.modules.codec.encoder import VideoEncoder
from src.dav.modules.transport_p2p.data_plane import DataPlaneReceiver, DataPlaneSender
from src.dav.modules.transport_p2p.packetizer import PT_AUDIO, PT_VIDEO, pack_frame, unpack_and_decrypt
from src.dav.modules.transport_p2p.sqp_controller import SqpAckData, SqpSenderController


def _make_confirmed_pair(bitrate_kbps: int = 12000):
    wire = []
    dp_tx = DataPlaneSender(
        "777-888",
        send_raw_fn=lambda pkt: wire.append(pkt),
        initial_bitrate_kbps=bitrate_kbps,
        fps=60,
    )
    dp_rx = DataPlaneReceiver("777-888")

    _, ack_s = dp_tx.handle_incoming_packet(dp_rx.build_pake_syn())
    res_rx = dp_rx.process_packet(ack_s)
    assert res_rx["kind"] == "pake" and res_rx["reply_pake"] is not None
    evt, _ = dp_tx.handle_incoming_packet(res_rx["reply_pake"])
    assert evt == "pake_confirmed"
    return dp_tx, dp_rx, wire


def test_audio_and_video_multiplex_zero_phantom_loss():
    """
    Garante que intercalar 240 pacotes de audio PT_AUDIO em 120 quadros de video 1080p60
    mantem perda em 0.0%, bitrate travado em 12000 kbps, zero frame skips e latencia <= 1 ms.
    """
    dp_tx, dp_rx, wire = _make_confirmed_pair(bitrate_kbps=12000)

    skips = 0
    video_ok = 0
    audio_ok = 0

    for f in range(120):
        budget = dp_tx.allocate_budget(audio_reserved_bytes=240)
        if budget.skip_frame:
            skips += 1
        is_kf = (f % 60 == 0)
        payload = b"DAV_H264:" + os.urandom(58000 if is_kf else 18000)
        wire.clear()

        assert dp_tx.send_audio_frame(b"\xaa" * 120) is True
        assert dp_tx.send_audio_frame(b"\xbb" * 120) is True
        dp_tx.send_video_frame(payload, is_keyframe=is_kf, frame_interval_sec=1.0 / 60.0)

        for pkt in wire:
            ev = dp_rx.process_packet(pkt)
            if ev["kind"] == "video_frame":
                video_ok += 1
            elif ev["kind"] == "audio_frame":
                audio_ok += 1
            if ev["sqp_ack_pkt"] is not None:
                dp_tx.handle_incoming_packet(ev["sqp_ack_pkt"])

    assert video_ok == 120
    assert audio_ok == 240
    assert skips == 0
    assert dp_rx.auth_failures == 0
    assert dp_rx.sqp_tracker.current_loss_rate == 0.0
    assert dp_tx.sqp.loss_rate == 0.0
    assert dp_tx.sqp.estimated_bps == 12_000_000.0
    assert dp_rx.latest_latency_ms <= 1.0


def test_cut_through_send_video_frame_subms():
    """Comprova envio Cut-Through abaixo de 0.5 ms na media por quadro P 1080p (~18 KB)."""
    dp_tx, _, wire = _make_confirmed_pair(bitrate_kbps=12000)
    sample_p = b"DAV_H264:" + os.urandom(18000)

    # Warmup de 5 quadros
    for _ in range(5):
        wire.clear()
        dp_tx.send_video_frame(sample_p, is_keyframe=False, frame_interval_sec=1.0 / 60.0)

    t0 = time.perf_counter()
    for _ in range(60):
        wire.clear()
        dp_tx.send_video_frame(sample_p, is_keyframe=False, frame_interval_sec=1.0 / 60.0)
    elapsed = time.perf_counter() - t0
    avg_ms = (elapsed / 60.0) * 1000.0

    # Em CPU moderno local fica em ~0.08 ms; teto de 0.5 ms garante rigor sem falsos positivos
    assert avg_ms < 0.5, f"Esperado < 0.5 ms por quadro em Cut-Through, obtido {avg_ms:.3f} ms"


def test_pake_nonce_domain_separation_audio_vs_video():
    """
    Garante que Video (PT_VIDEO) e Audio (PT_AUDIO) usando o mesmo frame_id=1 e seq_num=1
    produzem chaves/nonces AEAD distintos e janelas ReplayWindow independentes.
    """
    dp_tx, dp_rx, _ = _make_confirmed_pair()
    cipher_tx = dp_tx.pake.cipher
    cipher_rx = dp_rx.pake.cipher
    assert cipher_tx is not None and cipher_rx is not None

    pkts_v, _ = pack_frame(b"VIDEO_DATA_BLOCK", frame_id=1, is_keyframe=False, start_seq=0, aead_cipher=cipher_tx)
    from src.dav.modules.transport_p2p.packetizer import pack_datagram

    pkt_a = pack_datagram(PT_AUDIO, b"AUDIO_DATA_BLOCK", frame_id=1, seq_num=1, aead_cipher=cipher_tx)

    # Ambos devem decriptar perfeitamente apesar de frame_id=1 e seq_num=1 identicos
    opened_v = unpack_and_decrypt(pkts_v[0], aead_cipher=cipher_rx, enforce_replay=True)
    opened_a = unpack_and_decrypt(pkt_a, aead_cipher=cipher_rx, enforce_replay=True)
    assert opened_v is not None and opened_v[0].payload_type == PT_VIDEO and opened_v[1] == b"VIDEO_DATA_BLOCK"
    assert opened_a is not None and opened_a[0].payload_type == PT_AUDIO and opened_a[1] == b"AUDIO_DATA_BLOCK"


def test_salsify_hd_floor_and_recovery():
    """Verifica piso minimo HD (>= 45% de 12 Mbps = 5.4 Mbps), pacing de congestao e recuperacao."""
    sqp = SqpSenderController(initial_bitrate_kbps=12000, fps=60)
    assert sqp.min_bps == 5_400_000.0

    # Simula 40 ciclos de perda real severa -> deve respeitar o piso 5.4 Mbps (nunca 800 kbps)
    for idx in range(1, 41):
        ack = SqpAckData(
            last_frame_id=idx,
            echo_ts_us32=1000,
            owd_gradient_us=25_000,
            dispersion_kbps=6000,
            loss_rate_pm=120,
            rx_queue_frames=6,
        )
        sqp._last_backoff_mono = 0.0
        sqp.on_sqp_ack(ack)

    assert sqp.estimated_bps == 5_400_000.0
    assert sqp.is_congested is True

    # Limpa rede -> deve recuperar rapidamente de volta para 12 Mbps e voltar a Cut-Through
    for idx in range(41, 60):
        clean_ack = SqpAckData(
            last_frame_id=idx,
            echo_ts_us32=1000,
            owd_gradient_us=200,
            dispersion_kbps=12000,
            loss_rate_pm=0,
            rx_queue_frames=0,
        )
        sqp.on_sqp_ack(clean_ack)

    assert sqp.estimated_bps == 12_000_000.0
    assert sqp.is_congested is False


def test_encoder_hysteresis_ignores_small_or_frequent_jitter():
    """Garante que oscilacoes < 12% ou mais rapidas que 400 ms nao desestabilizam `ctx.bit_rate`."""
    try:
        import av  # noqa: F401
    except ImportError:
        pytest.skip("PyAV nao instalado no ambiente de teste")

    enc = VideoEncoder(codec_type="libx264", width=640, height=360, fps=60, bitrate_kbps=12000)
    try:
        if enc._av_codec is None:
            pytest.skip("Codec FFmpeg indisponivel")
        orig_br = enc._av_codec.bit_rate

        # Oscilacao de 5% (< 12%) -> nao altera ctx.bit_rate
        enc.update_rate_budget(11400)
        assert enc._av_codec.bit_rate == orig_br

        # Oscilacao grande (> 12%) porem antes de 400 ms -> mantem estavel
        enc.update_rate_budget(8000)
        assert enc._av_codec.bit_rate == orig_br

        # Apos 400 ms com variacao > 12% -> aplica novo bitrate suavemente
        enc._last_bitrate_update_mono -= 0.45
        enc.update_rate_budget(8000)
        assert enc._av_codec.bit_rate == 8_000_000
    finally:
        enc.close()


def test_wan_50ms_rtt_sustains_60fps_without_undue_skips():
    """
    Reproduz o cenario real de WAN (RTT = 50 ms, ~3 quadros de 25.8 KB sempre em voo no BDP)
    e comprova que o SqpSenderController mantem 60.0 FPS (zero skip_frame) quando nao ha
    congestionamento, sem cair indevidamente para 45 FPS ou 30 FPS.
    """
    import collections

    sqp = SqpSenderController(initial_bitrate_kbps=12000, fps=60)
    sqp.rtt_ms = 50.0
    dt = 1.0 / 60.0
    frame_wire_bytes = 25_800

    orig_mono = time.monotonic
    t_now = [1000.0]
    time.monotonic = lambda: t_now[0]
    ack_queue = collections.deque()
    sent_frames = 0
    skips = 0

    try:
        for i in range(180):
            t_now[0] = 1000.0 + i * dt
            while ack_queue and ack_queue[0][0] <= t_now[0]:
                _, ack_fid, echo_us = ack_queue.popleft()
                ack = SqpAckData(
                    last_frame_id=ack_fid,
                    echo_ts_us32=echo_us,
                    owd_gradient_us=500,
                    dispersion_kbps=12000,
                    loss_rate_pm=0,
                    rx_queue_frames=0,
                )
                sqp.on_sqp_ack(ack, now_tx_ts_us=int(t_now[0] * 1_000_000))

            budget = sqp.allocate_frame_budget(audio_reserved_bytes=240)
            if budget.skip_frame:
                skips += 1
            else:
                sent_frames += 1
                tx_us = int(t_now[0] * 1_000_000) & 0xFFFFFFFF
                sqp.record_frame_sent(sent_frames, frame_wire_bytes)
                ack_queue.append((t_now[0] + 0.050, sent_frames, tx_us))
                assert budget.max_frame_bytes >= 18_000
    finally:
        time.monotonic = orig_mono

    assert skips == 0
    assert sent_frames == 180


def test_adaptive_fec_eliminates_low_loss_dead_zone():
    """
    Garante que 1 unico pacote perdido na janela de 256 pacotes (~0.39% loss) ou jitter WAN
    moderado (>= 1.5 ms) ja ativa paridade XOR rapida (m=1) em P-frames, evitando PLI.
    """
    from src.dav.modules.transport_p2p.fec_engine import AdaptiveFecPolicy

    # Enlace LAN totalmente limpo (0% loss, 0.2 ms gradiente) -> m=0 em P-frames
    assert AdaptiveFecPolicy.choose_parity(16, is_keyframe=False, loss_rate=0.0, owd_gradient_ms=0.2) == 0

    # 1 pacote perdido em 256 (loss_rate = 1/256 = 0.0039) -> ativa XOR m=1 (antes retornava 0!)
    assert AdaptiveFecPolicy.choose_parity(16, is_keyframe=False, loss_rate=1.0 / 256.0, owd_gradient_ms=0.5) == 1

    # Jitter WAN moderado (owd_gradient = 2.0 ms) em P-frame de 16 pacotes -> ativa XOR m=1 proativo
    assert AdaptiveFecPolicy.choose_parity(16, is_keyframe=False, loss_rate=0.0, owd_gradient_ms=2.0) == 1


def test_libx264_vbv_clamping_and_pli_debounce():
    """
    Comprova que libx264 inicializa VBV (maxrate/bufsize), responde dinamicamente a
    update_rate_budget() em PTS monotonico sem reabrir o contexto e aplica debounce de IDR.
    """
    import numpy as np

    try:
        import av  # noqa: F401
    except ImportError:
        pytest.skip("PyAV nao instalado")

    enc = VideoEncoder(codec_type="libx264", width=640, height=360, fps=60, bitrate_kbps=12000)
    try:
        if enc._av_codec is None:
            pytest.skip("libx264 indisponivel")

        assert enc._av_codec.bit_rate == 12_000_000

        rng = np.random.default_rng(7)
        frames = [rng.integers(0, 255, (360, 640, 4), dtype=np.uint8) for _ in range(6)]

        # Primeiro quadro e keyframe; pedido imediato de novo keyframe dentro de 600ms sofre debounce
        p1 = enc.encode(frames[0])
        assert p1 and enc.last_frame_was_keyframe is True
        enc.request_keyframe(force=False)
        assert enc._force_next_idr is False
        enc.request_keyframe(force=True)
        assert enc._force_next_idr is True

        sz_12m = [len(enc.encode(frames[i % 6])) for i in range(1, 31)]
        enc._last_bitrate_update_mono -= 0.50
        enc.update_rate_budget(4500)
        sz_45m = [len(enc.encode(frames[i % 6])) for i in range(31, 61)]

        assert sum(sz_45m[5:]) < sum(sz_12m[5:]) * 0.75
    finally:
        enc.close()


def test_sqp_base_rtt_immunity_and_hold_zone():
    """
    Garante duas propriedades criticas de estabilidade SQP:
    1. Enlace limpo perto da saturacao (owd=3.5ms) entra na zona Hold sem oscilar +5%/quadro;
    2. Bufferbloat que infla `rtt_ms` para 180ms nao infla o `base_rtt_ms` usado no BDP.
    """
    sqp = SqpSenderController(initial_bitrate_kbps=12000, fps=60)
    # Estabelece baseline fisica de 20 ms
    for fid in range(1, 6):
        sqp.on_sqp_ack(
            SqpAckData(fid, 1000, owd_gradient_us=300, dispersion_kbps=12000, loss_rate_pm=0, rx_queue_frames=0),
            now_tx_ts_us=21_000,
        )
    assert abs(sqp.base_rtt_ms - 20.0) < 0.5

    # Reduz para 8 Mbps e simula zona Hold (owd=3.5 ms, abaixo do limiar de backoff > 5 ms)
    sqp.estimated_bps = 8_000_000.0
    for fid in range(6, 12):
        sqp.on_sqp_ack(
            SqpAckData(fid, 1000, owd_gradient_us=3500, dispersion_kbps=8000, loss_rate_pm=0, rx_queue_frames=1),
            now_tx_ts_us=21_000,
        )
    assert sqp.estimated_bps == 8_000_000.0

    # Simula explosao de bufferbloat (rtt_ms sobe para >100 ms, owd=12 ms), base_rtt_ms segue ~20 ms
    for fid in range(12, 22):
        sqp.on_sqp_ack(
            SqpAckData(fid, 1000, owd_gradient_us=12_000, dispersion_kbps=6000, loss_rate_pm=0, rx_queue_frames=5),
            now_tx_ts_us=181_000,
        )
    assert sqp.rtt_ms > 100.0
    assert abs(sqp.base_rtt_ms - 20.0) < 0.5

    # Como o excesso acima do BDP real (20ms) estoura, skip_frame atua em vez de aceitar 180ms de fila
    sqp.record_frame_sent(99, int((sqp.estimated_bps / 60.0 / 8.0) * 3.5))
    budget = sqp.allocate_frame_budget(audio_reserved_bytes=240)
    assert budget.skip_frame is True
