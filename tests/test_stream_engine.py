# -*- coding: utf-8 -*-
"""
Testes Unitários da Fatia StreamEngine e Protocolo DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

import time
import numpy as np
import pytest

from src.dav.modules.transport_p2p.packetizer import (
    pack_frame,
    unpack_header,
    build_key_vector,
    DAV_HEADER_SIZE,
    DAV_SSRC,
    MAGIC_SYN,
    MAGIC_ACK,
)
from src.dav.modules.stream_engine.service import StreamEngineService
from src.dav.modules.capture.synthetic_capturer import SyntheticCapturer
from src.dav.kernel.event_bus import EventBus


def test_packetizer_pack_unpack_and_crypto_roundtrip():
    pin = "773-307"
    key_vector = build_key_vector(pin)

    # Cria payload simulado de 5000 bytes (exige múltiplos fragmentos de MTU 1320)
    original_payload = b"DAV_FRAME_TEST_HEADER:" + (b"0123456789ABCDEF" * 300)
    frame_id = 42

    packets, seq = pack_frame(
        payload=original_payload,
        frame_id=frame_id,
        is_keyframe=True,
        key_vector=key_vector,
        start_seq=10,
        max_chunk=1320,
    )

    assert len(packets) >= 4
    assert seq == 10 + len(packets)

    # Remontagem e validação dos pacotes
    reassembled_encrypted_chunks = []
    for idx, pkt in enumerate(packets):
        hdr = unpack_header(pkt)
        assert hdr is not None
        assert hdr.version == 1
        assert hdr.ssrc == DAV_SSRC
        assert hdr.frame_id == frame_id
        assert hdr.is_keyframe is True
        assert hdr.is_encrypted is True
        assert hdr.frag_idx == idx
        assert hdr.frag_tot == len(packets)

        chunk_data = pkt[DAV_HEADER_SIZE : DAV_HEADER_SIZE + hdr.payload_len]
        reassembled_encrypted_chunks.append(chunk_data)

    enc_payload = b"".join(reassembled_encrypted_chunks)
    assert len(enc_payload) == len(original_payload)

    # Decriptografia SIMD
    payload_arr = np.frombuffer(enc_payload, dtype=np.uint8)
    dec_payload = np.bitwise_xor(payload_arr, key_vector[: len(enc_payload)]).tobytes()

    assert dec_payload == original_payload


def test_stream_engine_service_lifecycle():
    bus = EventBus.get_instance()
    service = StreamEngineService(event_bus=bus)

    # Inicia transmissão em porta aleatória com SyntheticCapturer
    res_tx = service.start_transmission(
        pin="123-456",
        port=0,
        width=320,
        height=240,
        fps=30,
        bitrate_kbps=1000,
    )
    assert res_tx.is_success
    assert service.is_transmitting
    assert not service.is_receiving

    # Encerra transmissão
    res_stop = service.stop_all()
    assert res_stop.is_success
    assert not service.is_transmitting
    assert not service.is_receiving

    # Inicia recepção em porta efêmera
    res_rx = service.start_reception(
        pin="123-456",
        port=0,
    )
    assert res_rx.is_success
    assert service.is_receiving
    assert not service.is_transmitting

    service.stop_all()
    assert not service.is_receiving

