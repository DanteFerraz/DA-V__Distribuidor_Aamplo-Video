# -*- coding: utf-8 -*-
"""
Testes Unitários das Fatias Verticais de Mídia (Capture & Codec) — DA-V v4.0
"""

import numpy as np
import pytest

from src.dav.modules.capture.service import CaptureService, enumerate_system_monitors
from src.dav.modules.capture.synthetic_capturer import SyntheticCapturer
from src.dav.modules.codec.service import CodecService


def test_capture_service_synthetic():
    res = CaptureService.create_capturer(width=640, height=360, fps=30, force_synthetic=True)
    assert res.is_success is True
    cap = res.unwrap()
    assert isinstance(cap, SyntheticCapturer)

    assert cap.start() is True
    buf = np.zeros((360, 640, 4), dtype=np.uint8)
    assert cap.grab_into(buf) is True
    assert buf[0, 0, 3] == 255  # Canal Alpha presente
    cap.close()


def test_enumerate_monitors():
    mons = enumerate_system_monitors()
    assert len(mons) >= 1
    assert "width" in mons[0]
    assert "height" in mons[0]
    assert mons[0]["width"] > 0


def test_codec_encoder_and_decoder_roundtrip():
    try:
        import av  # noqa: F401
    except ImportError:
        pytest.skip("PyAV não instalado no ambiente de teste")

    # Encoder libx264 em 1366x768
    enc_res = CodecService.create_encoder(codec_type="libx264", width=1366, height=768, fps=60, bitrate_kbps=6000)
    assert enc_res.is_success is True
    encoder = enc_res.unwrap()

    # Gera quadro teste 1366x768
    frame = np.full((768, 1366, 4), 180, dtype=np.uint8)
    frame[:, :, 0] = 50   # B
    frame[:, :, 1] = 220  # G
    frame[:, :, 2] = 30   # R
    frame[:, :, 3] = 255

    pkt = encoder.encode(frame)
    assert pkt.startswith(b"DAV_H264:")
    assert len(pkt) > 100
    encoder.close()

    # Decoder
    dec_res = CodecService.create_decoder()
    assert dec_res.is_success is True
    decoder = dec_res.unwrap()

    frames = decoder.decode_all(pkt, width=1366, height=768)
    assert len(frames) >= 1
    bgr = frames[0]
    assert bgr.shape == (768, 1366, 3)
    assert bgr.flags["C_CONTIGUOUS"] is True
    decoder.close()

