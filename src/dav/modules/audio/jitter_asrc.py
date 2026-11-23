# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Micro-Jitter Buffer Adaptativo e Reamostrador ASRC (+/- 0.25%) — DA-V v4.5
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import collections
import math
import threading
import time
from typing import Dict, Optional, Tuple
import numpy as np

from src.dav.modules.audio.capturer import (
    AUDIO_CHANNELS,
    AUDIO_FRAME_SAMPLES,
    AUDIO_SAMPLE_RATE,
)
from src.dav.modules.audio.codec_opus import OpusAudioDecoder


class AudioJitterAsrcBuffer:
    """
    Buffer adaptativo com:
    - Estimador de jitter online de Welford (janela-alvo entre 10 ms e 45 ms).
    - Reordenacao e recuperacao instantanea via piggyback LBRR ou PLC.
    - ASRC (Adaptive Sample Rate Conversion) guiado por controlador PI no nivel de
      ocupacao da fila para compensar clock drift entre placas de som sem glitches.
    - Rastreamento de clock mestre A/V (lip-sync).
    """

    def __init__(
        self,
        min_target_ms: float = 12.0,
        max_target_ms: float = 45.0,
        max_buffer_ms: float = 120.0,
    ):
        self.min_target_ms = float(min_target_ms)
        self.max_target_ms = float(max_target_ms)
        self.max_buffer_samples = int((max_buffer_ms / 1000.0) * AUDIO_SAMPLE_RATE)

        self.decoder = OpusAudioDecoder()
        self._pcm_chunks: "collections.deque[np.ndarray]" = collections.deque()
        self._buffered_samples = 0

        # Welford online variance de intervalo de chegada
        self._last_rx_mono: Optional[float] = None
        self._last_tx_ts_us: Optional[int] = None
        self._welford_n = 0
        self._welford_mean_ms = 0.0
        self._welford_m2 = 0.0
        self.target_delay_ms = float(min_target_ms)

        # Controle PI de ASRC (razao de leitura -> output)
        self.asrc_ratio: float = 1.0
        self._integral_err: float = 0.0
        self._last_expected_frame_id: Optional[int] = None
        self.audio_master_ts_us: int = 0
        self._last_rx_clock_mono: float = 0.0

        self.packets_received = 0
        self.lbrr_recovered = 0
        self.plc_concealed = 0
        self._lock = threading.Lock()

    def _update_welford_jitter(self, tx_ts_us: int) -> None:
        now = time.monotonic()
        if self._last_rx_mono is not None and self._last_tx_ts_us is not None:
            d_rx_ms = (now - self._last_rx_mono) * 1000.0
            d_tx_ms = (tx_ts_us - self._last_tx_ts_us) / 1000.0
            if 0.0 < d_tx_ms < 200.0:
                jitter_sample = abs(d_rx_ms - d_tx_ms)
                self._welford_n += 1
                delta = jitter_sample - self._welford_mean_ms
                self._welford_mean_ms += delta / float(self._welford_n)
                delta2 = jitter_sample - self._welford_mean_ms
                self._welford_m2 += delta * delta2
                if self._welford_n > 32:
                    self._welford_n = 32
                    self._welford_m2 = (self._welford_m2 / 32.0) * 31.0
                std_ms = math.sqrt(self._welford_m2 / max(1, self._welford_n - 1))
                self.target_delay_ms = max(
                    self.min_target_ms,
                    min(self.max_target_ms, 10.0 + 2.5 * std_ms),
                )
        self._last_rx_mono = now
        self._last_tx_ts_us = tx_ts_us

    def _update_asrc_ratio(self) -> None:
        cur_ms = (self._buffered_samples / float(AUDIO_SAMPLE_RATE)) * 1000.0
        err_ms = cur_ms - self.target_delay_ms
        # Controle PI suave: mantem razao em [0.9975, 1.0025] (+-0.25% imperceptivel)
        self._integral_err = max(-40.0, min(40.0, self._integral_err + err_ms * 0.01))
        adj = (err_ms * 0.00008) + (self._integral_err * 0.00001)
        # Se ha excesso de buffer (err > 0), acelera consumo levemente (consumindo mais input por output)
        self.asrc_ratio = max(0.9975, min(1.0025, 1.0 + adj))

    def _apply_asrc_if_needed(self, pcm: np.ndarray) -> np.ndarray:
        if pcm.shape[0] < 4 or abs(self.asrc_ratio - 1.0) < 0.00015:
            return pcm
        n_in = pcm.shape[0]
        # ratio > 1.0 consome um pouco mais rapido (gera levemente menos amostras out)
        n_out = max(1, int(round(n_in / self.asrc_ratio)))
        if n_out == n_in:
            return pcm
        x_old = np.linspace(0.0, 1.0, n_in, endpoint=False)
        x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
        c0 = np.interp(x_new, x_old, pcm[:, 0].astype(np.float32))
        c1 = np.interp(x_new, x_old, pcm[:, 1].astype(np.float32))
        return np.clip(np.column_stack((c0, c1)), -32768.0, 32767.0).astype(np.int16)

    def push_audio_packet(self, frame_id: int, tx_ts_us: int, payload: bytes) -> None:
        with self._lock:
            self.packets_received += 1
            self._update_welford_jitter(tx_ts_us)
            self._update_asrc_ratio()

            need_prev = False
            gap = 0
            if self._last_expected_frame_id is not None and frame_id > self._last_expected_frame_id:
                gap = frame_id - self._last_expected_frame_id
                if gap == 1:
                    need_prev = True
                elif gap > 1:
                    need_prev = True
                    for _ in range(min(gap - 1, 4)):
                        plc = self.decoder.conceal_loss()
                        self._append_pcm_locked(plc)
                        self.plc_concealed += 1

            prev_pcm, cur_pcm = self.decoder.decode_payload(payload, need_prev_recovery=need_prev)
            if prev_pcm is not None:
                self._append_pcm_locked(self._apply_asrc_if_needed(prev_pcm))
                self.lbrr_recovered += 1
            elif gap == 1:
                plc = self.decoder.conceal_loss()
                self._append_pcm_locked(plc)
                self.plc_concealed += 1

            self._append_pcm_locked(self._apply_asrc_if_needed(cur_pcm))
            self._last_expected_frame_id = max(
                (self._last_expected_frame_id or 0), frame_id
            ) + 1
            self.audio_master_ts_us = tx_ts_us
            self._last_rx_clock_mono = time.monotonic()

    def _append_pcm_locked(self, pcm: np.ndarray) -> None:
        if pcm.size == 0:
            return
        self._pcm_chunks.append(pcm)
        self._buffered_samples += pcm.shape[0]
        while self._buffered_samples > self.max_buffer_samples and len(self._pcm_chunks) > 1:
            dropped = self._pcm_chunks.popleft()
            self._buffered_samples -= dropped.shape[0]

    def pop_pcm_bytes(self, max_frames: int = 8) -> bytes:
        """Retira ate `max_frames` de audio prontos (s16 interleaved) para reproducao."""
        with self._lock:
            if not self._pcm_chunks:
                return b""
            out = []
            popped = 0
            while self._pcm_chunks and popped < max_frames:
                blk = self._pcm_chunks.popleft()
                self._buffered_samples -= blk.shape[0]
                out.append(blk.tobytes())
                popped += 1
            return b"".join(out)

    @property
    def buffered_ms(self) -> float:
        with self._lock:
            return (self._buffered_samples / float(AUDIO_SAMPLE_RATE)) * 1000.0

    def lip_sync_delta_ms(self, video_tx_ts_us: int) -> Optional[float]:
        """
        Retorna diferenca (video_pts - audio_master_pts) em ms quando o stream
        de audio esteve ativo nos ultimos 250 ms. Positivo = video adiantado.
        """
        with self._lock:
            if self.audio_master_ts_us <= 0 or (time.monotonic() - self._last_rx_clock_mono) > 0.25:
                return None
            # Subtrai o atraso ainda enfileirado no ring buffer para estimar o PTS tocando agora
            playing_pts = self.audio_master_ts_us - int(
                (self._buffered_samples / float(AUDIO_SAMPLE_RATE)) * 1_000_000.0
            )
            return float(video_tx_ts_us - playing_pts) / 1000.0

    def close(self) -> None:
        with self._lock:
            self._pcm_chunks.clear()
            self._buffered_samples = 0
            self.decoder.close()
