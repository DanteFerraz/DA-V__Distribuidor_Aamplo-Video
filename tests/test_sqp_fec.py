# -*- coding: utf-8 -*-
"""
Suite de Validacao do Data Plane (FEC GF(2^8), SQP, Salsify e MicroPacer) — DA-V
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import os
import time

from src.dav.modules.transport_p2p.data_plane import DataPlaneReceiver, DataPlaneSender
from src.dav.modules.transport_p2p.fec_engine import (
    AdaptiveFecPolicy,
    FecDecoder,
    FecEncoder,
)
from src.dav.modules.transport_p2p.packetizer import split_chunks
from src.dav.modules.transport_p2p.sqp_controller import (
    MicroPacer,
    SqpReceiverTracker,
    SqpSenderController,
)


def test_fec_xor_recovers_single_and_uneven_last_shard():
    # Ultimo fragmento intencionalmente menor que MTU (3000 % 1300 = 400 bytes)
    original = os.urandom(3000)
    shards = split_chunks(original, max_chunk=1300)
    assert [len(s) for s in shards] == [1300, 1300, 400]

    parities = FecEncoder.encode_shards(shards, parity_count=1)
    assert len(parities) == 1

    # Caso 1: Perda do fragmento 0
    rec0 = FecDecoder.recover(3, {1: shards[1], 2: shards[2]}, {0: parities[0]})
    assert rec0 is not None and b"".join(rec0) == original

    # Caso 2: Perda do ultimo fragmento menor (400 bytes exact!)
    rec2 = FecDecoder.recover(3, {0: shards[0], 1: shards[1]}, {0: parities[0]})
    assert rec2 is not None and b"".join(rec2) == original


def test_fec_cauchy_gf256_recovers_multiple_losses():
    original = os.urandom(12150)  # 9x1300 + 450 = 10 fragmentos
    shards = split_chunks(original, max_chunk=1300)
    k_data = len(shards)
    assert k_data == 10

    parities = FecEncoder.encode_shards(shards, parity_count=3)
    assert len(parities) == 3

    # Derruba 3 fragmentos aleatorios (incluindo o primeiro e o ultimo menor)
    dropped = {0, 4, 9}
    rx_data = {i: shards[i] for i in range(k_data) if i not in dropped}
    rx_par = {i: parities[i] for i in range(3)}

    rec = FecDecoder.recover(k_data, rx_data, rx_par)
    assert rec is not None and b"".join(rec) == original

    # Se perder 4 (> M=3), retorna None limpamente sem dados corrompidos
    rx_data_too_many_lost = {i: shards[i] for i in range(k_data) if i not in {0, 1, 4, 9}}
    assert FecDecoder.recover(k_data, rx_data_too_many_lost, rx_par) is None


def test_adaptive_fec_and_sqp_salsify_controller():
    assert AdaptiveFecPolicy.choose_parity(8, is_keyframe=True, loss_rate=0.0, owd_gradient_ms=0.0) >= 1
    assert AdaptiveFecPolicy.choose_parity(10, is_keyframe=True, loss_rate=0.05, owd_gradient_ms=1.0) >= 2
    assert AdaptiveFecPolicy.choose_parity(5, is_keyframe=False, loss_rate=0.04, owd_gradient_ms=12.0) == 0

    sqp = SqpSenderController(initial_bitrate_kbps=12000, fps=60)
    trk = SqpReceiverTracker()

    # Simula rajada sem perda com gradiente baixo -> largura se mantem alta
    base_tx = 1_000_000
    for f_id in range(1, 5):
        for s in range(4):
            trk.on_packet_received(seq_num=(f_id - 1) * 4 + s + 1, frame_id=f_id, tx_ts_us=base_tx + f_id * 16666, pkt_bytes=1300, rx_ts_us=base_tx + f_id * 16666 + s * 400)
        ack = trk.on_frame_completed(f_id, base_tx + f_id * 16666, rx_queue_frames=0)
        sqp.on_sqp_ack(ack)

    # Simula fila crescendo (OWD gradient sobe) e perda 4% -> SQP deve reduzir taxa
    before_bps = sqp.estimated_bps
    time.sleep(0.055)
    for f_id in range(5, 8):
        ack = trk.on_frame_completed(f_id, base_tx + f_id * 16666, rx_queue_frames=5)
        ack.owd_gradient_us = 12_000  # +12 ms delay gradient
        ack.loss_rate_pm = 45         # 4.5% loss
        sqp.on_sqp_ack(ack)
    assert sqp.estimated_bps < before_bps

    # Regra Salsify frame-skip quando inflight estoura 1.85x orcamento de frame
    sqp.record_frame_sent(999, int((sqp.estimated_bps / 60.0 / 8.0) * 3.0))
    budget = sqp.allocate_frame_budget(audio_reserved_bytes=240)
    assert budget.skip_frame is True


def test_micropacer_audio_priority_preemption():
    sent_order = []
    pacer = MicroPacer(send_fn=lambda b: sent_order.append(b))
    pacer.enqueue_high_priority(b"AUDIO_PRIO_PKT")
    video_pkts = [b"VID_1", b"VID_2", b"VID_3", b"VID_4"]
    pacer.send_frame_paced(video_pkts, pacing_bps=10_000_000, frame_interval_sec=0.016)
    assert sent_order[0] == b"AUDIO_PRIO_PKT"
    assert sent_order[1:] == video_pkts


def test_data_plane_end_to_end_with_lossy_packet_recovery():
    tx_wire = []
    dp_tx = DataPlaneSender("555-777", send_raw_fn=lambda pkt: tx_wire.append(pkt), initial_bitrate_kbps=10000, fps=60)
    dp_rx = DataPlaneReceiver("555-777")

    # Handshake PAKE sobre pacotes simulados
    _, ack_s = dp_tx.handle_incoming_packet(dp_rx.build_pake_syn())
    res_rx = dp_rx.process_packet(ack_s)
    assert res_rx["kind"] == "pake" and res_rx["reply_pake"] is not None
    evt, _ = dp_tx.handle_incoming_packet(res_rx["reply_pake"])
    assert evt == "pake_confirmed" and dp_tx.pake.confirmed

    # Forca perda controlada para garantir >=1 FEC shard no keyframe mesmo com 0% perda inicial
    frame_bytes = b"DAV_H264:" + os.urandom(5600)
    pkts_cnt, _, fec_m = dp_tx.send_video_frame(frame_bytes, is_keyframe=True, frame_interval_sec=0.016)
    assert fec_m >= 1
    assert pkts_cnt >= 6

    # Simula perda de 1 fragmento de dados no transito (drop indice 1)
    delivered = [pkt for idx, pkt in enumerate(tx_wire) if idx != 1]
    assembled_frames = []
    need_pli_flags = []
    for pkt in delivered:
        ev = dp_rx.process_packet(pkt)
        need_pli_flags.append(ev["need_pli"])
        if ev["kind"] == "video_frame":
            assembled_frames.append(ev["frame_bytes"])

    assert len(assembled_frames) == 1
    assert assembled_frames[0] == frame_bytes
    assert dp_rx.fec_recovered_frames == 1
    assert not any(need_pli_flags)
