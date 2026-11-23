# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Motor de Forward Error Correction (FEC) Intra-Quadro Adaptativo — DA-V v4.5
Autor: Dante Ferraz (MonoTech)

Implementa FEC sistematico em GF(2^8) (polinomio primitivo 0x11d):
- M == 1: Paridade XOR rapida via AVX2/NumPy (latencia < 10 us).
- M >= 2: Matriz de Cauchy Reed-Solomon sobre GF(2^8) com inversao r x r exata.
Suporta reconstrucao bit-exata mesmo quando o ultimo fragmento tem tamanho menor que o MTU.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
import numpy as np

FEC_ALGO_XOR = 0
FEC_ALGO_RS_GF256 = 1

# !HBBHH = k_data(uint16), m_parity(uint8), algo(uint8), normal_len(uint16), last_len(uint16)
FEC_META_FORMAT = "!HBBHH"
FEC_META_SIZE = 8


def _build_gf256_tables() -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    exp = np.zeros(512, dtype=np.uint8)
    log = np.zeros(256, dtype=np.uint8)
    inv = np.zeros(256, dtype=np.uint8)
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]

    mul = np.zeros((256, 256), dtype=np.uint8)
    for a in range(1, 256):
        la = int(log[a])
        inv[a] = exp[255 - la]
        for b in range(1, 256):
            mul[a, b] = exp[(la + int(log[b])) % 255]
    return exp, log, inv, mul


_GF_EXP, _GF_LOG, _GF_INV, _GF_MUL = _build_gf256_tables()


def _cauchy_coef(parity_idx: int, data_idx: int, k_data: int) -> int:
    x_i = k_data + parity_idx
    y_j = data_idx
    return int(_GF_INV[x_i ^ y_j])


def _gf_invert_matrix(mat: List[List[int]]) -> Optional[List[List[int]]]:
    """Eliminacao Gauss-Jordan exata sobre GF(2^8) para matriz quadrada r x r."""
    n = len(mat)
    aug = [row[:] + [1 if i == j else 0 for j in range(n)] for i, row in enumerate(mat)]

    for col in range(n):
        pivot = -1
        for r in range(col, n):
            if aug[r][col] != 0:
                pivot = r
                break
        if pivot == -1:
            return None
        if pivot != col:
            aug[col], aug[pivot] = aug[pivot], aug[col]

        inv_piv = int(_GF_INV[aug[col][col]])
        if inv_piv != 1:
            for c in range(col, 2 * n):
                aug[col][c] = int(_GF_MUL[aug[col][c], inv_piv])

        for r in range(n):
            if r != col and aug[r][col] != 0:
                factor = aug[r][col]
                for c in range(col, 2 * n):
                    aug[r][c] ^= int(_GF_MUL[factor, aug[col][c]])

    return [row[n:] for row in aug]


@dataclass
class FecParityShard:
    parity_index: int
    k_data: int
    m_parity: int
    algo: int
    normal_len: int
    last_len: int
    payload: bytes  # Inclui 8B FEC_META + dados de paridade


class AdaptiveFecPolicy:
    """Calcula M (numero de shards de paridade) por quadro considerando criticidade e rede."""

    @staticmethod
    def choose_parity(
        k_data: int,
        is_keyframe: bool,
        loss_rate: float = 0.0,
        owd_gradient_ms: float = 0.0,
        max_parity: int = 6,
    ) -> int:
        if k_data <= 1 or (k_data + max_parity) > 255:
            return 0
        # Se a fila do gargalo esta severamente saturada, reduz FEC em P-frames para aliviar atraso
        severe_queue = owd_gradient_ms > 8.0

        if is_keyframe:
            if loss_rate >= 0.03 and not severe_queue:
                m = math.ceil(k_data * min(0.28, max(0.15, loss_rate * 2.5)))
                return min(max_parity, max(2, m))
            if loss_rate >= 0.01:
                return min(max_parity, max(2, math.ceil(k_data * 0.15)))
            return 1 if k_data >= 2 else 0

        if severe_queue:
            return 0
        if loss_rate >= 0.025:
            m = math.ceil(k_data * min(0.22, loss_rate * 2.2))
            return min(max_parity, max(1, m))
        if (loss_rate >= 0.001 and k_data >= 2) or (owd_gradient_ms >= 1.5 and k_data >= 4):
            return 1
        return 0


class FecEncoder:
    """Codificador FEC sistematico intra-quadro (XOR e Reed-Solomon GF(2^8))."""

    @staticmethod
    def encode_shards(data_shards: Sequence[bytes], parity_count: int) -> List[bytes]:
        k_data = len(data_shards)
        if parity_count <= 0 or k_data <= 1 or (k_data + parity_count) > 255:
            return []

        normal_len = len(data_shards[0])
        last_len = len(data_shards[-1])
        shard_len = max(normal_len, last_len, *(len(s) for s in data_shards))
        if shard_len == 0:
            return []

        matrix = np.zeros((k_data, shard_len), dtype=np.uint8)
        for idx, s in enumerate(data_shards):
            if s:
                matrix[idx, : len(s)] = np.frombuffer(s, dtype=np.uint8)

        algo = FEC_ALGO_XOR if parity_count == 1 else FEC_ALGO_RS_GF256
        meta = struct.pack(FEC_META_FORMAT, k_data, parity_count, algo, shard_len, last_len)

        if parity_count == 1:
            parity_row = np.bitwise_xor.reduce(matrix, axis=0)
            return [meta + parity_row.tobytes()]

        out: List[bytes] = []
        for p_idx in range(parity_count):
            acc = np.zeros(shard_len, dtype=np.uint8)
            for j in range(k_data):
                c = _cauchy_coef(p_idx, j, k_data)
                if c == 1:
                    acc ^= matrix[j]
                elif c != 0:
                    acc ^= _GF_MUL[c, matrix[j]]
            out.append(meta + acc.tobytes())
        return out


class FecDecoder:
    """Decodificador sistematico para reconstruir fragmentos perdidos antes do decode H.264."""

    @staticmethod
    def parse_parity_payload(raw_fec_payload: bytes) -> Optional[Tuple[int, int, int, int, int, bytes]]:
        if len(raw_fec_payload) <= FEC_META_SIZE:
            return None
        k_data, m_parity, algo, normal_len, last_len = struct.unpack(
            FEC_META_FORMAT, raw_fec_payload[:FEC_META_SIZE]
        )
        parity_data = raw_fec_payload[FEC_META_SIZE:]
        if k_data == 0 or len(parity_data) != normal_len:
            return None
        return k_data, m_parity, algo, normal_len, last_len, parity_data

    @staticmethod
    def recover(
        k_data: int,
        data_shards: Dict[int, bytes],
        parity_shards: Dict[int, bytes],
    ) -> Optional[List[bytes]]:
        """
        Reconstroi todos os `k_data` fragmentos originais se houver ao menos `k_data`
        fragmentos recebidos no conjunto (dados + paridade). Retorna None caso contrario.
        """
        if k_data <= 0:
            return None

        # Se todos os fragmentos de dados ja chegaram, nao precisa de matematica FEC
        if len(data_shards) == k_data:
            return [data_shards[i] for i in range(k_data)]

        missing = [i for i in range(k_data) if i not in data_shards]
        r = len(missing)
        if r == 0:
            return [data_shards[i] for i in range(k_data)]

        parsed_parities: List[Tuple[int, int, int, int, int, bytes]] = []
        normal_len = 0
        last_len = 0
        for p_idx, raw_p in sorted(parity_shards.items()):
            parsed = FecDecoder.parse_parity_payload(raw_p)
            if parsed is not None:
                pk, _, algo, n_len, l_len, p_bytes = parsed
                if pk == k_data:
                    normal_len = n_len
                    last_len = l_len
                    parsed_parities.append((p_idx, pk, algo, n_len, l_len, p_bytes))

        if len(parsed_parities) < r or normal_len <= 0:
            return None

        # Fast-path XOR (perda simples == 1 shard)
        if r == 1:
            miss_idx = missing[0]
            p_idx, _, algo, shard_len, last_len, p_bytes = parsed_parities[0]
            acc = np.frombuffer(p_bytes, dtype=np.uint8).copy()
            for j in range(k_data):
                if j == miss_idx:
                    continue
                row = np.zeros(shard_len, dtype=np.uint8)
                src = data_shards[j]
                row[: len(src)] = np.frombuffer(src, dtype=np.uint8)
                if algo == FEC_ALGO_RS_GF256:
                    c = _cauchy_coef(p_idx, j, k_data)
                    if c != 1:
                        row = _GF_MUL[c, row]
                acc ^= row

            if algo == FEC_ALGO_RS_GF256:
                c_miss = _cauchy_coef(p_idx, miss_idx, k_data)
                inv_c = int(_GF_INV[c_miss])
                if inv_c != 1:
                    acc = _GF_MUL[inv_c, acc]

            rec_bytes = acc.tobytes()
            target_len = last_len if miss_idx == (k_data - 1) else shard_len
            reconstructed = dict(data_shards)
            reconstructed[miss_idx] = rec_bytes[:target_len]
            return [reconstructed[i] for i in range(k_data)]

        # Caminho geral Cauchy Reed-Solomon GF(2^8) para 2 <= r <= M perdas
        selected = [item for item in parsed_parities if item[2] == FEC_ALGO_RS_GF256][:r]
        if len(selected) < r:
            return None

        shard_len = selected[0][3]
        last_len = selected[0][4]
        rhs_mat = np.zeros((r, shard_len), dtype=np.uint8)
        sub_mat: List[List[int]] = [[0] * r for _ in range(r)]

        for row_i, (p_idx, _, _, _, _, p_bytes) in enumerate(selected):
            acc = np.frombuffer(p_bytes, dtype=np.uint8).copy()
            for j, present_bytes in data_shards.items():
                coef = _cauchy_coef(p_idx, j, k_data)
                if coef == 0:
                    continue
                d_row = np.zeros(shard_len, dtype=np.uint8)
                d_row[: len(present_bytes)] = np.frombuffer(present_bytes, dtype=np.uint8)
                if coef == 1:
                    acc ^= d_row
                else:
                    acc ^= _GF_MUL[coef, d_row]
            rhs_mat[row_i] = acc

            for col_j, miss_idx in enumerate(missing):
                sub_mat[row_i][col_j] = _cauchy_coef(p_idx, miss_idx, k_data)

        inv_mat = _gf_invert_matrix(sub_mat)
        if inv_mat is None:
            return None

        reconstructed = dict(data_shards)
        for out_row, miss_idx in enumerate(missing):
            acc = np.zeros(shard_len, dtype=np.uint8)
            for col_k in range(r):
                c = inv_mat[out_row][col_k]
                if c == 1:
                    acc ^= rhs_mat[col_k]
                elif c != 0:
                    acc ^= _GF_MUL[c, rhs_mat[col_k]]
            target_len = last_len if miss_idx == (k_data - 1) else shard_len
            reconstructed[miss_idx] = acc.tobytes()[:target_len]

        return [reconstructed[i] for i in range(k_data)]
