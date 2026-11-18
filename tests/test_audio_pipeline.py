# -*- coding: utf-8 -*-
"""
Suite de Validacao do Pipeline de Audio Real-Time (WASAPI/PipeWire, Opus, LBRR, ASRC) — DA-V
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import numpy as np

from src.dav.kernel.registry import ModuleRegistry
from src.dav.modules.audio.capturer import (
    AUDIO_FRAME_SAMPLES,
    AUDIO_SAMPLE_RATE,
    SyntheticAudioCapturer,
    resample_to_48k_stereo_s16,
)
from src.dav.modules.audio.codec_opus import OpusAudioDecoder, OpusAudioEncoder
from src.dav.modules.audio.jitter_asrc import AudioJitterAsrcBuffer


def test_resample_arbitrary_rates_to_48k_stereo():
    # Simula captura 192 kHz float32 estereo (10 ms = 1920 amostras)
    src_192 = (np.sin(np.linspace(0, 10, 1920 * 2, dtype=np.float32)) * 0.4).reshape(1920, 2)
    out_48 = resample_to_48k_stereo_s16(src_192, src_rate=192000, src_channels=2, is_float=True)
    assert out_48.dtype == np.int16
    assert out_48.shape == (480, 2)

    # Simula microfone mono 44.1 kHz int16 -> 48 kHz estereo
    src_44 = np.zeros((441, 1), dtype=np.int16)
    out_44 = resample_to_48k_stereo_s16(src_44, src_rate=44100, src_channels=1, is_float=False)
    assert out_44.shape == (480, 2)


def test_opus_encode_decode_and_lbrr_loss_recovery():
    cap = SyntheticAudioCapturer(freq_hz=440.0, amplitude=0.25)
    assert cap.start()
    enc = OpusAudioEncoder(bitrate_bps=96000, enable_lbrr_piggyback=True)
    jb = AudioJitterAsrcBuffer(min_target_ms=12.0, max_target_ms=40.0)

    try:
        encoded_pkts = []
        for idx in range(1, 7):
            pcm = cap.read_frame()
            assert pcm is not None and pcm.shape == (AUDIO_FRAME_SAMPLES, 2)
            encoded_pkts.append((idx, idx * 10000, enc.encode(pcm, lbrr_active=True)))

        # Entrega pacotes 1, 2, [DROP 3], 4, 5, 6 -> pacote 4 deve recuperar frame 3 via LBRR!
        for fid, ts_us, payload in encoded_pkts:
            if fid == 3:
                continue
            jb.push_audio_packet(frame_id=fid, tx_ts_us=ts_us, payload=payload)

        assert jb.packets_received == 5
        assert jb.lbrr_recovered >= 1

        out_bytes = jb.pop_pcm_bytes(max_frames=10)
        # Recuperou todos os 6 frames (6 * 1920 bytes, pequena variacao <= ASRC)
        assert len(out_bytes) >= 5 * 1920

        # Verifica calculo de sincronia labial
        delta = jb.lip_sync_delta_ms(video_tx_ts_us=60000)
        assert delta is not None and abs(delta) < 100.0
    finally:
        jb.close()
        enc.close()
        cap.close()


def test_asrc_adapts_ratio_under_buffer_drift():
    dec = OpusAudioDecoder()
    enc = OpusAudioEncoder(bitrate_bps=64000, enable_lbrr_piggyback=False)
    jb = AudioJitterAsrcBuffer(min_target_ms=10.0, max_target_ms=30.0)
    try:
        cap = SyntheticAudioCapturer(freq_hz=523.25, amplitude=0.2)
        cap.start()
        for i in range(1, 10):
            pcm = cap.read_frame()
            jb.push_audio_packet(i, i * 10000, enc.encode(pcm))
        # Buffer acumulou ~90 ms contra target ~10 ms -> ASRC acelera (> 1.0)
        assert jb.buffered_ms > 50.0
        assert jb.asrc_ratio > 1.0005
        cap.close()
    finally:
        jb.close()
        enc.close()
        dec.close()


def test_audio_module_manifest_discovered_by_kernel():
    reg = ModuleRegistry()
    reg.discover()
    assert reg.is_registered("audio")
    man = reg.get("audio")
    assert man is not None
    svc = man.service_factory()
    enc_res = svc.create_encoder()
    assert enc_res.is_success
    enc_res.value.close()


def test_data_plane_audio_and_video_multiplex():
    import os
    from src.dav.modules.transport_p2p.data_plane import DataPlaneReceiver, DataPlaneSender

    wire_tx = []
    dp_tx = DataPlaneSender("333-444", send_raw_fn=lambda pkt: wire_tx.append(pkt))
    dp_rx = DataPlaneReceiver("333-444")

    _, ack_s = dp_tx.handle_incoming_packet(dp_rx.build_pake_syn())
    res_rx = dp_rx.process_packet(ack_s)
    evt, _ = dp_tx.handle_incoming_packet(res_rx["reply_pake"])
    assert evt == "pake_confirmed"

    cap = SyntheticAudioCapturer(freq_hz=440.0, amplitude=0.2)
    cap.start()
    aenc = OpusAudioEncoder(bitrate_bps=96000, enable_lbrr_piggyback=True)
    jb = AudioJitterAsrcBuffer()
    try:
        pcm = cap.read_frame()
        a_pkt_payload = aenc.encode(pcm, lbrr_active=True)
        assert dp_tx.send_audio_frame(a_pkt_payload, is_lbrr=True) is True
        dp_tx.send_video_frame(b"DAV_H264:" + os.urandom(1800), is_keyframe=True, frame_interval_sec=0.016)

        got_audio = 0
        got_video = 0
        for raw in wire_tx:
            ev = dp_rx.process_packet(raw)
            if ev["kind"] == "audio_frame":
                jb.push_audio_packet(ev["audio_frame_id"], ev["tx_ts_us"], ev["audio_payload"])
                got_audio += 1
            elif ev["kind"] == "video_frame":
                got_video += 1

        assert got_audio == 1
        assert got_video == 1
        assert len(jb.pop_pcm_bytes()) >= 1900
    finally:
        jb.close()
        aenc.close()
        cap.close()
