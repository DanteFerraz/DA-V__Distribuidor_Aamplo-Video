# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Suite de Validacao Criptografica PAKE (CPace-X25519) + ChaCha20-Poly1305 AEAD — DA-V
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import os
import struct

from src.dav.modules.transport_p2p.crypto_pake import (
    PakeSession,
    ReplayWindow,
)
from src.dav.modules.transport_p2p.packetizer import (
    DAV_HEADER_SIZE,
    PT_VIDEO,
    pack_frame,
    unpack_and_decrypt,
)


def _complete_pake_pair(pin_tx: str, pin_rx: str):
    tx = PakeSession("S", pin_tx)
    rx = PakeSession("R", pin_rx)

    syn_r = rx.build_syn()
    ok1, ack_s, _ = tx.process_control(syn_r)
    if not ok1 or ack_s is None:
        return tx, rx, False

    ok2, ack_r, conf_rx = rx.process_control(ack_s)
    if not ok2 or ack_r is None:
        return tx, rx, False

    ok3, _, conf_tx = tx.process_control(ack_r)
    return tx, rx, bool(ok3 and conf_rx and conf_tx and tx.confirmed and rx.confirmed)


def test_pake_handshake_valid_pin_and_forward_secrecy():
    tx1, rx1, ok1 = _complete_pake_pair("845-747", "845747")
    assert ok1 is True
    assert tx1.cipher is not None and rx1.cipher is not None

    # Segunda sessao com o MESMO PIN deve gerar chaves efemeras distintas (PFS)
    tx2, rx2, ok2 = _complete_pake_pair("845-747", "845-747")
    assert ok2 is True
    assert tx1.local_share != tx2.local_share
    assert tx1._shared_z != tx2._shared_z


def test_pake_rejects_wrong_pin_and_all_zero_share():
    tx, rx, ok = _complete_pake_pair("845-747", "845-748")
    assert ok is False
    assert not tx.confirmed

    # Rejeita ponto pequeno / all-zero (ataque de subgrupo pequeno)
    malformed_syn = b"DAV_P2P_SYN2" + tx.tag + b"R" + os.urandom(16) + (b"\x00" * 32)
    valid, reply, _ = tx.process_control(malformed_syn)
    assert valid is False
    assert reply is None


def test_aead_roundtrip_tamper_aad_and_replay_window():
    tx, rx, ok = _complete_pake_pair("912-340", "912-340")
    assert ok

    payload = b"DAV_H264:" + os.urandom(4200)
    pkts, next_seq = pack_frame(
        payload=payload,
        frame_id=7,
        is_keyframe=True,
        start_seq=100,
        aead_cipher=tx.cipher,
        max_chunk=1300,
    )
    assert len(pkts) == 4
    assert next_seq == 104

    # 1. Entrega fora de ordem (inversa) deve decifrar perfeitamente
    recovered_chunks = [None] * len(pkts)
    for pkt in reversed(pkts):
        opened = unpack_and_decrypt(pkt, aead_cipher=rx.cipher, enforce_replay=True)
        assert opened is not None
        hdr, pt = opened
        assert hdr.is_aead and hdr.is_encrypted and hdr.is_keyframe
        assert hdr.payload_type == PT_VIDEO
        recovered_chunks[hdr.frag_idx] = pt
    assert b"".join(recovered_chunks) == payload

    # 2. Replay do mesmo pacote e rejeitado
    assert unpack_and_decrypt(pkts[0], aead_cipher=rx.cipher, enforce_replay=True) is None

    # 3. Adulteracao de ciphertext OU AAD (flags no cabecalho) falha Poly1305
    p_mod_ct = bytearray(pkts[1])
    p_mod_ct[DAV_HEADER_SIZE + 5] ^= 0xFF
    assert unpack_and_decrypt(bytes(p_mod_ct), aead_cipher=rx.cipher, enforce_replay=False) is None

    p_mod_aad = bytearray(pkts[2])
    p_mod_aad[3] ^= 0x01  # altera byte reserved do cabecalho AAD
    assert unpack_and_decrypt(bytes(p_mod_aad), aead_cipher=rx.cipher, enforce_replay=False) is None


def test_replay_window_edge_cases():
    rw = ReplayWindow(size=64)
    assert rw.check_and_update(10) is True
    assert rw.check_and_update(10) is False  # duplicado
    assert rw.check_and_update(9) is True    # fora de ordem valido dentro da janela
    assert rw.check_and_update(9) is False   # duplicado fora de ordem
    assert rw.check_and_update(100) is True
    assert rw.check_and_update(20) is False  # antigo demais (> 64 pacotes atras)
