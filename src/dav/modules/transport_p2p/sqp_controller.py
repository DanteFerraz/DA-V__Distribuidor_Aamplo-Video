# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Controle de Congestionamento SQP + Acoplamento Salsify e Micro-Pacer — DA-V v4.5
Autor: Dante Ferraz (MonoTech)

Baseado em:
- SQP (Ray et al., Google Research, 2022): sondagem de capacidade acoplada a cadencia de quadros
  e ajuste guiado por gradiente de atraso unidirecional (OWD) + dispersao intra-quadro.
- Salsify (Fouladi et al., NSDI 2018): acoplamento do orcamento de bytes por quadro ao codificador
  H.264/HEVC e regra funcional de frame-skip para manter a latencia na cauda baixa sem bufferbloat.
- MoMQ: fila prioritaria estrita para audio e sinalizacao evitando head-of-line blocking do video.
"""

from __future__ import annotations

import collections
import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable, Deque, Dict, List, Optional, Tuple

MAGIC_SQP_ACK = b"DAV_SQP1"
# !8sIIiIIH = magic(8), last_frame_id(I), echo_ts_low32_us(I), owd_gradient_us(i),
#            dispersion_kbps(I), loss_rate_pm(I), rx_queue_frames(H) -> 30 bytes
SQP_ACK_FORMAT = "!8sIIiIIH"
SQP_ACK_SIZE = 30


@dataclass
class SqpAckData:
    last_frame_id: int
    echo_ts_us32: int
    owd_gradient_us: int
    dispersion_kbps: int
    loss_rate_pm: int  # partes por milha (ex: 25 = 2.5%)
    rx_queue_frames: int

    def pack(self) -> bytes:
        return struct.pack(
            SQP_ACK_FORMAT,
            MAGIC_SQP_ACK,
            self.last_frame_id & 0xFFFFFFFF,
            self.echo_ts_us32 & 0xFFFFFFFF,
            max(-2_000_000_000, min(2_000_000_000, int(self.owd_gradient_us))),
            max(0, min(0xFFFFFFFF, int(self.dispersion_kbps))),
            max(0, min(1000, int(self.loss_rate_pm))),
            max(0, min(65535, int(self.rx_queue_frames))),
        )

    @classmethod
    def unpack(cls, data: bytes) -> Optional["SqpAckData"]:
        if len(data) < SQP_ACK_SIZE or data[:8] != MAGIC_SQP_ACK:
            return None
        _, fid, echo_ts, owd_grad, disp_kbps, loss_pm, rx_q = struct.unpack(
            SQP_ACK_FORMAT, data[:SQP_ACK_SIZE]
        )
        return cls(
            last_frame_id=fid,
            echo_ts_us32=echo_ts,
            owd_gradient_us=owd_grad,
            dispersion_kbps=disp_kbps,
            loss_rate_pm=loss_pm,
            rx_queue_frames=rx_q,
        )


@dataclass
class FrameBudget:
    skip_frame: bool
    max_frame_bytes: int
    target_codec_kbps: int
    pacing_bps: float
    enable_pir: bool


class SqpReceiverTracker:
    """Mede gradiente OWD, dispersao intra-quadro e perda deslizante no Receptor."""

    def __init__(self):
        self._last_tx_ts_us: Optional[int] = None
        self._last_rx_ts_us: Optional[int] = None
        self._ewma_owd_grad_us: float = 0.0
        self._ewma_dispersion_kbps: float = 0.0

        self._frame_timings: Dict[int, List[int]] = {}
        self._highest_seq: Optional[int] = None
        self._recent_outcomes: Deque[int] = collections.deque(maxlen=256)
        self._last_ack_mono: float = 0.0

    def on_packet_received(
        self,
        seq_num: int,
        frame_id: int,
        tx_ts_us: int,
        pkt_bytes: int,
        rx_ts_us: Optional[int] = None,
    ) -> None:
        now_us = rx_ts_us if rx_ts_us is not None else int(time.perf_counter() * 1_000_000)

        # Rastreia perda por buracos de sequence_number
        if self._highest_seq is None:
            self._highest_seq = seq_num
            self._recent_outcomes.append(1)
        elif seq_num > self._highest_seq:
            gap = seq_num - self._highest_seq - 1
            for _ in range(min(gap, 32)):
                self._recent_outcomes.append(0)
            self._recent_outcomes.append(1)
            self._highest_seq = seq_num
        elif seq_num < self._highest_seq:
            # Pacote reordenado chegou depois: substitui um zero recente se possivel
            for i in range(len(self._recent_outcomes) - 1, -1, -1):
                if self._recent_outcomes[i] == 0:
                    self._recent_outcomes[i] = 1
                    break

        rec = self._frame_timings.get(frame_id)
        if rec is None:
            if len(self._frame_timings) > 32:
                oldest = min(self._frame_timings.keys())
                del self._frame_timings[oldest]
            # [first_rx_us, last_rx_us, total_bytes, pkt_count, tx_ts_us]
            self._frame_timings[frame_id] = [now_us, now_us, pkt_bytes, 1, tx_ts_us]
        else:
            rec[1] = now_us
            rec[2] += pkt_bytes
            rec[3] += 1

    def on_frame_completed(self, frame_id: int, tx_ts_us: int, rx_queue_frames: int) -> SqpAckData:
        now_us = int(time.perf_counter() * 1_000_000)
        rec = self._frame_timings.pop(frame_id, None)
        first_rx_us = rec[0] if rec is not None else now_us

        # Gradiente OWD inter-quadros medido no 1o fragmento (imune ao tamanho do quadro e a clock skew fixo)
        if self._last_tx_ts_us is not None and self._last_rx_ts_us is not None:
            d_rx = first_rx_us - self._last_rx_ts_us
            d_tx = tx_ts_us - self._last_tx_ts_us
            if 0 < d_tx < 500_000 and -500_000 < d_rx < 1_000_000:
                inst_grad = float(d_rx - d_tx)
                self._ewma_owd_grad_us = 0.80 * self._ewma_owd_grad_us + 0.20 * inst_grad

        self._last_tx_ts_us = tx_ts_us
        self._last_rx_ts_us = first_rx_us

        if rec is not None and rec[3] >= 3:
            span_us = rec[1] - rec[0]
            if span_us >= 150:  # >= 150us evita picos artificiais de batch NIC coalesce
                inst_kbps = (rec[2] * 8.0 * 1000.0) / float(span_us)
                if self._ewma_dispersion_kbps <= 0.0:
                    self._ewma_dispersion_kbps = inst_kbps
                else:
                    self._ewma_dispersion_kbps = 0.8 * self._ewma_dispersion_kbps + 0.2 * inst_kbps

        loss_rate = self.current_loss_rate
        self._last_ack_mono = time.monotonic()
        return SqpAckData(
            last_frame_id=frame_id,
            echo_ts_us32=tx_ts_us & 0xFFFFFFFF,
            owd_gradient_us=int(self._ewma_owd_grad_us),
            dispersion_kbps=int(self._ewma_dispersion_kbps),
            loss_rate_pm=int(round(loss_rate * 1000.0)),
            rx_queue_frames=rx_queue_frames,
        )

    def should_emit_periodic_ack(self, min_interval_sec: float = 0.014) -> bool:
        return (time.monotonic() - self._last_ack_mono) >= min_interval_sec

    def emit_periodic_snapshot(self, frame_id: int, tx_ts_us: int, rx_queue_frames: int) -> SqpAckData:
        self._last_ack_mono = time.monotonic()
        return SqpAckData(
            last_frame_id=frame_id,
            echo_ts_us32=tx_ts_us & 0xFFFFFFFF,
            owd_gradient_us=int(self._ewma_owd_grad_us),
            dispersion_kbps=int(self._ewma_dispersion_kbps),
            loss_rate_pm=int(round(self.current_loss_rate * 1000.0)),
            rx_queue_frames=rx_queue_frames,
        )

    @property
    def current_loss_rate(self) -> float:
        if not self._recent_outcomes:
            return 0.0
        lost = sum(1 for v in self._recent_outcomes if v == 0)
        return float(lost) / float(len(self._recent_outcomes))

    @property
    def owd_gradient_ms(self) -> float:
        return self._ewma_owd_grad_us / 1000.0


class SqpSenderController:
    """
    Controlador SQP + Salsify no Transmissor:
    Ajusta a banda estimada `estimated_bps` pelo gradiente de atraso e dispersao,
    limita `max_frame_bytes` entregue ao encoder e previne bufferbloat / cascatas de PLI.
    """

    def __init__(
        self,
        initial_bitrate_kbps: int = 12000,
        fps: int = 60,
        min_bitrate_kbps: int = 4500,
        max_bitrate_kbps: int = 35000,
    ):
        self.fps = max(1, int(fps))
        cap_kbps = max(400, int(initial_bitrate_kbps))
        floor_kbps = min(cap_kbps, max(int(min_bitrate_kbps), int(cap_kbps * 0.45)))
        self.min_bps = float(floor_kbps * 1000)
        self.user_cap_bps = float(cap_kbps * 1000)
        self.max_bps = float(max(max_bitrate_kbps * 1000, self.user_cap_bps))
        self.estimated_bps = float(self.user_cap_bps)

        self.rtt_ms: float = 15.0
        self.owd_gradient_ms: float = 0.0
        self.loss_rate: float = 0.0
        self.rx_queue_frames: int = 0
        self.dispersion_kbps: int = initial_bitrate_kbps

        self._inflight: Dict[int, Tuple[int, float]] = {}
        self._rtt_window: Deque[Tuple[float, float]] = collections.deque(maxlen=256)
        self._last_backoff_mono: float = 0.0
        self._consecutive_skips: int = 0
        self._probe_cycle: int = 0
        self._lock = threading.Lock()

    @property
    def is_congested(self) -> bool:
        return (self.owd_gradient_ms >= 4.0) or (self.loss_rate >= 0.02)

    def record_frame_sent(self, frame_id: int, total_bytes: int) -> None:
        now = time.monotonic()
        with self._lock:
            self._inflight[frame_id] = (int(total_bytes), now)
            self._prune_inflight(now)

    def _prune_inflight(self, now: float) -> None:
        ttl = max(0.035, min(0.240, (self.rtt_ms * 1.5) / 1000.0))
        stale = [fid for fid, (_, ts) in self._inflight.items() if (now - ts) > ttl]
        for fid in stale:
            del self._inflight[fid]

    @property
    def inflight_bytes(self) -> int:
        now = time.monotonic()
        with self._lock:
            self._prune_inflight(now)
            return sum(sz for sz, _ in self._inflight.values())

    def on_sqp_ack(self, ack: SqpAckData, now_tx_ts_us: Optional[int] = None) -> None:
        now = time.monotonic()
        cur_us32 = (now_tx_ts_us if now_tx_ts_us is not None else int(time.time_ns() // 1000)) & 0xFFFFFFFF

        with self._lock:
            acked = [fid for fid in self._inflight if fid <= ack.last_frame_id]
            for fid in acked:
                del self._inflight[fid]

            rtt_sample_us = (cur_us32 - ack.echo_ts_us32) & 0xFFFFFFFF
            if 100 <= rtt_sample_us <= 2_000_000:
                rtt_sample_ms = rtt_sample_us / 1000.0
                self.rtt_ms = 0.8 * self.rtt_ms + 0.2 * rtt_sample_ms
                self._rtt_window.append((now, rtt_sample_ms))
                while self._rtt_window and (now - self._rtt_window[0][0]) > 15.0:
                    self._rtt_window.popleft()

            self.owd_gradient_ms = ack.owd_gradient_us / 1000.0
            self.loss_rate = ack.loss_rate_pm / 1000.0
            self.rx_queue_frames = ack.rx_queue_frames
            if ack.dispersion_kbps > 0:
                self.dispersion_kbps = ack.dispersion_kbps

            # Decisao de controle SQP v4.8 com tres zonas (Congestao / Hold / Sondagem suave)
            congested = (
                self.owd_gradient_ms > 5.0
                or self.loss_rate > 0.025
                or self.rx_queue_frames > 5
            )
            near_saturation = (
                self.owd_gradient_ms >= 2.5
                or self.loss_rate >= 0.01
                or self.rx_queue_frames >= 3
            )
            if congested:
                if (now - self._last_backoff_mono) >= 0.080:
                    severity = 0.06
                    if self.owd_gradient_ms > 20.0 or self.loss_rate > 0.10:
                        severity = 0.18
                    elif self.owd_gradient_ms > 10.0 or self.loss_rate > 0.05:
                        severity = 0.12
                    self.estimated_bps = max(self.min_bps, self.estimated_bps * (1.0 - severity))
                    self._last_backoff_mono = now
            elif not near_saturation:
                probe_target = self.estimated_bps * 1.05 + 150_000.0
                self.estimated_bps = min(self.user_cap_bps, probe_target)

    @property
    def base_rtt_ms(self) -> float:
        """RTT base de propagacao (minimo em janela deslizante de 15 s, imune a bufferbloat)."""
        now = time.monotonic()
        with self._lock:
            while self._rtt_window and (now - self._rtt_window[0][0]) > 15.0:
                self._rtt_window.popleft()
            if self._rtt_window:
                return min(s for _, s in self._rtt_window)
            return self.rtt_ms

    def allocate_frame_budget(self, audio_reserved_bytes: int = 0) -> FrameBudget:
        now = time.monotonic()
        frame_interval = 1.0 / float(self.fps)
        with self._lock:
            self._prune_inflight(now)
            while self._rtt_window and (now - self._rtt_window[0][0]) > 15.0:
                self._rtt_window.popleft()
            base_rtt = min((s for _, s in self._rtt_window), default=self.rtt_ms)
            inflight = sum(sz for sz, _ in self._inflight.values())
            est_bps = self.estimated_bps
            owd = self.owd_gradient_ms
            loss = self.loss_rate

            per_frame_cap_bytes = (est_bps * frame_interval) / 8.0
            frame_ms = frame_interval * 1000.0
            natural_bdp_frames = max(1.0, base_rtt / max(1.0, frame_ms))
            natural_bdp_bytes = natural_bdp_frames * per_frame_cap_bytes
            bdp_skip_frames = max(2.2, natural_bdp_frames + 1.5)
            skip_threshold_bytes = bdp_skip_frames * per_frame_cap_bytes

            severe_congestion = (
                self.is_congested
                or self.rx_queue_frames >= 4
                or owd >= 8.0
            )
            should_skip = False
            if (
                severe_congestion
                and inflight > skip_threshold_bytes
                and self._consecutive_skips < 1
            ):
                should_skip = True
                self._consecutive_skips += 1
            else:
                self._consecutive_skips = 0

            excess_inflight = max(0.0, float(inflight) - natural_bdp_bytes)
            raw_budget = per_frame_cap_bytes - (0.25 * excess_inflight) - float(audio_reserved_bytes)
            max_frame_bytes = int(max(8192.0, min(per_frame_cap_bytes * 1.50, raw_budget)))

            self._probe_cycle += 1
            probe_mult = 1.12 if (self._probe_cycle % 2 == 0 and owd < 3.0 and loss < 0.01) else 1.04
            pacing_bps = max(self.min_bps * 1.1, min(self.max_bps * 1.25, est_bps * probe_mult))
            target_kbps = int(max(self.min_bps / 1000.0, min(self.user_cap_bps / 1000.0, est_bps / 1000.0)))
            enable_pir = (owd > 6.0) or (loss > 0.025)

            return FrameBudget(
                skip_frame=should_skip,
                max_frame_bytes=max_frame_bytes,
                target_codec_kbps=target_kbps,
                pacing_bps=pacing_bps,
                enable_pir=enable_pir,
            )


class MicroPacer:
    """
    Despachante com micro-pacing temporal e fila prioritaria estrita para Audio / Controle.
    Evita estouros de fila em roteadores (bufferbloat) e elimina Head-of-Line Blocking do audio.
    """

    def __init__(self, send_fn: Callable[[bytes], None]):
        self._send_fn = send_fn
        self._high_prio: Deque[bytes] = collections.deque()
        self._lock = threading.Lock()

    def enqueue_high_priority(self, datagram: bytes) -> None:
        with self._lock:
            self._high_prio.append(datagram)

    def flush_high_priority(self) -> int:
        if not self._high_prio:
            return 0
        sent = 0
        while True:
            with self._lock:
                if not self._high_prio:
                    break
                pkt = self._high_prio.popleft()
            self._send_fn(pkt)
            sent += 1
        return sent

    def send_frame_paced(
        self,
        datagrams: List[bytes],
        pacing_bps: float,
        frame_interval_sec: float,
        stop_check: Optional[Callable[[], bool]] = None,
        cut_through: bool = True,
        max_span_sec: float = 0.002,
    ) -> int:
        """
        Modo Cut-Through (< 0.35 ms, zero sleep na thread de encode) por padrao em enlace limpo.
        Aplica micro-espacamento leve (<= 2.0 ms) apenas quando ha congestionamento WAN ativo.
        Drena pacotes de Audio / Controle prioritarios continuamente entre os envios.
        """
        sent_bytes = 0
        self.flush_high_priority()

        if not datagrams:
            return 0

        if cut_through or pacing_bps <= 0 or sum(len(d) for d in datagrams) <= 2600:
            for idx, d in enumerate(datagrams):
                if stop_check and stop_check():
                    break
                if idx > 0 and (idx % 6 == 0):
                    self.flush_high_priority()
                self._send_fn(d)
                sent_bytes += len(d)
            self.flush_high_priority()
            return sent_bytes

        total_bytes = sum(len(d) for d in datagrams)
        ideal_span = (total_bytes * 8.0) / float(pacing_bps)
        cap_span = min(max_span_sec, max(0.0005, frame_interval_sec * 0.25))
        span = min(cap_span, ideal_span)

        batch_size = 4
        num_batches = max(1, (len(datagrams) + batch_size - 1) // batch_size)
        gap_sec = span / float(num_batches) if num_batches > 1 else 0.0

        t_next = time.perf_counter()
        for idx in range(0, len(datagrams), batch_size):
            if stop_check and stop_check():
                break
            self.flush_high_priority()
            batch = datagrams[idx : idx + batch_size]
            for d in batch:
                self._send_fn(d)
                sent_bytes += len(d)

            if idx + batch_size < len(datagrams) and gap_sec >= 0.00015:
                t_next += gap_sec
                while time.perf_counter() < t_next:
                    if stop_check and stop_check():
                        break
                    self.flush_high_priority()

        self.flush_high_priority()
        return sent_bytes
