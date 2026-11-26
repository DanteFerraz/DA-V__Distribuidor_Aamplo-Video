# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Motor de Forward Error Correction (FEC) Intra-Quadro Adaptativo & Block-RS — DA-V v5.2
Autor: Dante Ferraz (MonoTech)

Implementa FEC sistematico em GF(2^8) (polinomio primitivo 0x11d):
- `k_data <= 200` (cabecalho 8B `!HBBHH`, 100% retrocompativel com v4.5-v5.1):
  - M == 1 (`FEC_ALGO_XOR = 0`): Paridade XOR rapida via NumPy/AVX2 (< 10 us).
  - M >= 2 (`FEC_ALGO_RS_GF256 = 1`): Matriz de Cauchy Reed-Solomon sobre GF(2^8).
- `k_data > 200` (Mega-IDRs de 260 KB a 5 MB, cabecalho 12B `!HBBHHHH`):
  - `FEC_ALGO_BLOCKED_RS_GF256 = 2`: Particiona os fragmentos em sub-blocos contiguos
    de ate `MAX_FEC_BLOCK_K = 160` fragmentos, aplicando Reed-Solomon GF(2^8) independente
    por sub-bloco (eliminando o teto silencioso de 255 que deixava Mega-IDRs com M=0).
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
import numpy as np

FEC_ALGO_XOR = 0
FEC_ALGO_RS_GF256 = 1
FEC_ALGO_BLOCKED_RS_GF256 = 2

# Cabecalho padrao (8B): k_data(uint16), m_parity(uint8), algo(uint8), normal_len(uint16), last_len(uint16)
FEC_META_FORMAT = "!HBBHH"
FEC_META_SIZE = 8

# Cabecalho estendido Block-RS (12B): total_k(H), block_m(B), algo=2(B), shard_len(H), block_last_len(H), block_offset(H), block_k(H)
FEC_BLOCK_META_FORMAT = "!HBBHHHH"
FEC_BLOCK_META_SIZE = 12

SINGLE_BLOCK_MAX_K = 200
MAX_FEC_BLOCK_K = 160


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
    payload: bytes


class AdaptiveFecPolicy:
    """Calcula M (paridade por bloco) considerando criticidade (IDR vs P-frame) e rede."""

    @staticmethod
    def choose_parity(
        k_data: int,
        is_keyframe: bool,
        loss_rate: float = 0.0,
        owd_gradient_ms: float = 0.0,
        max_parity: int = 8,
    ) -> int:
        if k_data <= 1 or k_data > 4096:
            return 0

        eff_block_k = min(k_data, MAX_FEC_BLOCK_K) if k_data > SINGLE_BLOCK_MAX_K else k_data
        eff_max_m = min(max_parity, max(1, 254 - eff_block_k))
        severe_queue = owd_gradient_ms > 10.0

        if is_keyframe:
            # Keyframes (incluindo Mega-IDRs > 200 shards) SEMPRE recebem protecao FEC!
            if loss_rate >= 0.03 and not severe_queue:
                m = math.ceil(eff_block_k * min(0.25, max(0.12, loss_rate * 2.5)))
                return min(eff_max_m, max(3, m))
            if loss_rate >= 0.005:
                return min(eff_max_m, max(2, math.ceil(eff_block_k * 0.12)))
            if k_data > SINGLE_BLOCK_MAX_K:
                return min(eff_max_m, 3)
            return min(eff_max_m, 2 if k_data >= 24 else 1)

        if severe_queue:
            return 0
        if loss_rate >= 0.025:
            m = math.ceil(eff_block_k * min(0.22, loss_rate * 2.2))
            return min(eff_max_m, max(1, m))
        if (loss_rate >= 0.001 and k_data >= 2) or (owd_gradient_ms >= 1.5 and k_data >= 4):
            return 1
        return 0


def _encode_single_block_matrix(block_shards: Sequence[bytes], parity_count: int) -> Tuple[int, int, List[bytes]]:
    k_blk = len(block_shards)
    shard_len = max(len(s) for s in block_shards)
    last_len = len(block_shards[-1])
    if shard_len == 0:
        return 0, 0, []

    matrix = np.zeros((k_blk, shard_len), dtype=np.uint8)
    for idx, s in enumerate(block_shards):
        if s:
            matrix[idx, : len(s)] = np.frombuffer(s, dtype=np.uint8)

    if parity_count == 1:
        parity_row = np.bitwise_xor.reduce(matrix, axis=0)
        return shard_len, last_len, [parity_row.tobytes()]

    raw_parities: List[bytes] = []
    for p_idx in range(parity_count):
        acc = np.zeros(shard_len, dtype=np.uint8)
        for j in range(k_blk):
            c = _cauchy_coef(p_idx, j, k_blk)
            if c == 1:
                acc ^= matrix[j]
            elif c != 0:
                acc ^= _GF_MUL[c, matrix[j]]
        raw_parities.append(acc.tobytes())
    return shard_len, last_len, raw_parities


class FecEncoder:
    """Codificador FEC sistematico intra-quadro (XOR, RS GF(2^8) e Block-RS para Mega-IDRs)."""

    @staticmethod
    def encode_shards(data_shards: Sequence[bytes], parity_count: int) -> List[bytes]:
        k_data = len(data_shards)
        if parity_count <= 0 or k_data <= 1:
            return []

        # 1. Caminho padrao (k_data <= 200): 8B meta retrocompativel
        if k_data <= SINGLE_BLOCK_MAX_K and (k_data + parity_count) <= 255:
            shard_len, last_len, raw_parities = _encode_single_block_matrix(data_shards, parity_count)
            if not raw_parities:
                return []
            algo = FEC_ALGO_XOR if parity_count == 1 else FEC_ALGO_RS_GF256
            meta = struct.pack(FEC_META_FORMAT, k_data, parity_count, algo, shard_len, last_len)
            return [meta + p for p in raw_parities]

        # 2. Caminho Block-RS (Mega-IDRs com k_data > 200): sub-blocos contiguos <= 160 shards
        num_blocks = math.ceil(k_data / MAX_FEC_BLOCK_K)
        base_blk_k = math.ceil(k_data / num_blocks)
        out: List[bytes] = []

        offset = 0
        while offset < k_data:
            blk_k = min(base_blk_k, k_data - offset)
            if blk_k <= 1:
                offset += blk_k
                continue
            blk_m = max(2, min(parity_count, 254 - blk_k))
            blk_shards = data_shards[offset : offset + blk_k]
            shard_len, blk_last_len, raw_parities = _encode_single_block_matrix(blk_shards, blk_m)
            if raw_parities:
                meta = struct.pack(
                    FEC_BLOCK_META_FORMAT,
                    k_data,
                    blk_m,
                    FEC_ALGO_BLOCKED_RS_GF256,
                    shard_len,
                    blk_last_len,
                    offset,
                    blk_k,
                )
                for p_bytes in raw_parities:
                    out.append(meta + p_bytes)
            offset += blk_k

        return out


def _recover_single_block(
    k_data: int,
    data_shards: Dict[int, bytes],
    parsed_parities: List[Tuple[int, int, int, int, int, bytes]],
) -> Optional[List[bytes]]:
    if len(data_shards) == k_data:
        return [data_shards[i] for i in range(k_data)]

    missing = [i for i in range(k_data) if i not in data_shards]
    r = len(missing)
    if r == 0:
        return [data_shards[i] for i in range(k_data)]
    if len(parsed_parities) < r:
        return None

    # Fast-path perda simples (r == 1)
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
            if algo in (FEC_ALGO_RS_GF256, FEC_ALGO_BLOCKED_RS_GF256):
                c = _cauchy_coef(p_idx, j, k_data)
                if c != 1:
                    row = _GF_MUL[c, row]
            acc ^= row

        if algo in (FEC_ALGO_RS_GF256, FEC_ALGO_BLOCKED_RS_GF256):
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
    selected = [item for item in parsed_parities if item[2] in (FEC_ALGO_RS_GF256, FEC_ALGO_BLOCKED_RS_GF256)][:r]
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


class FecDecoder:
    """Decodificador sistematico para reconstruir fragmentos perdidos antes do decode H.264."""

    @staticmethod
    def parse_parity_payload(raw_fec_payload: bytes) -> Optional[Tuple[int, int, int, int, int, bytes]]:
        """
        Retorna `(total_k, m_parity, algo, normal_len, last_len, parity_data)` para formatos
        padrao (`algo=0/1`) e estendido (`algo=2`).
        """
        if len(raw_fec_payload) <= FEC_META_SIZE:
            return None
        k_data, m_parity, algo, normal_len, last_len = struct.unpack(
            FEC_META_FORMAT, raw_fec_payload[:FEC_META_SIZE]
        )
        if algo == FEC_ALGO_BLOCKED_RS_GF256:
            if len(raw_fec_payload) <= FEC_BLOCK_META_SIZE:
                return None
            parity_data = raw_fec_payload[FEC_BLOCK_META_SIZE:]
            if k_data == 0 or len(parity_data) != normal_len:
                return None
            return k_data, m_parity, algo, normal_len, last_len, parity_data

        parity_data = raw_fec_payload[FEC_META_SIZE:]
        if k_data == 0 or len(parity_data) != normal_len:
            return None
        return k_data, m_parity, algo, normal_len, last_len, parity_data

    @staticmethod
    def parse_blocked_parity(
        raw_fec_payload: bytes,
    ) -> Optional[Tuple[int, int, int, int, int, int, int, bytes]]:
        if len(raw_fec_payload) <= FEC_BLOCK_META_SIZE:
            return None
        total_k, block_m, algo, normal_len, block_last_len, block_offset, block_k = struct.unpack(
            FEC_BLOCK_META_FORMAT, raw_fec_payload[:FEC_BLOCK_META_SIZE]
        )
        if algo != FEC_ALGO_BLOCKED_RS_GF256:
            return None
        parity_data = raw_fec_payload[FEC_BLOCK_META_SIZE:]
        if total_k == 0 or block_k == 0 or len(parity_data) != normal_len:
            return None
        return total_k, block_m, algo, normal_len, block_last_len, block_offset, block_k, parity_data

    @staticmethod
    def recover(
        k_data: int,
        data_shards: Dict[int, bytes],
        parity_shards: Dict[int, bytes],
    ) -> Optional[List[bytes]]:
        """
        Reconstroi todos os `k_data` fragmentos originais (suportando bloco unico e Block-RS `algo=2`).
        """
        if k_data <= 0:
            return None

        if len(data_shards) == k_data:
            return [data_shards[i] for i in range(k_data)]

        # Detecta se os shards de paridade usam formato Block-RS (algo == 2)
        blocked_groups: Dict[Tuple[int, int], List[Tuple[int, int, int, int, int, bytes]]] = {}
        standard_parities: List[Tuple[int, int, int, int, int, bytes]] = []
        block_m_map: Dict[Tuple[int, int], int] = {}

        for global_p_idx, raw_p in sorted(parity_shards.items()):
            blk_parsed = FecDecoder.parse_blocked_parity(raw_p)
            if blk_parsed is not None:
                total_k, block_m, algo, n_len, b_last_len, b_offset, b_k, p_bytes = blk_parsed
                if total_k != k_data or block_m <= 0:
                    continue
                g_key = (b_offset, b_k)
                block_m_map[g_key] = block_m
                # Indice local de paridade dentro do sub-bloco: modulo block_m
                local_p_idx = global_p_idx % block_m
                blocked_groups.setdefault(g_key, []).append(
                    (local_p_idx, b_k, algo, n_len, b_last_len, p_bytes)
                )
                continue

            parsed = FecDecoder.parse_parity_payload(raw_p)
            if parsed is not None:
                pk, _, algo, n_len, l_len, p_bytes = parsed
                if pk == k_data:
                    standard_parities.append((global_p_idx, pk, algo, n_len, l_len, p_bytes))

        if blocked_groups:
            reconstructed = dict(data_shards)
            for (b_offset, b_k), grp_parities in sorted(blocked_groups.items()):
                local_data: Dict[int, bytes] = {}
                for local_i in range(b_k):
                    g_idx = b_offset + local_i
                    if g_idx in reconstructed:
                        local_data[local_i] = reconstructed[g_idx]
                if len(local_data) == b_k:
                    continue
                rec_blk = _recover_single_block(b_k, local_data, grp_parities)
                if rec_blk is None:
                    return None
                for local_i, shard_b in enumerate(rec_blk):
                    reconstructed[b_offset + local_i] = shard_b

            if len(reconstructed) == k_data:
                return [reconstructed[i] for i in range(k_data)]
            return None

        if not standard_parities:
            return None
        return _recover_single_block(k_data, data_shards, standard_parities)
