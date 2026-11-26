# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Data Plane Unificado (PAKE + AEAD + FEC GF(2^8) + SQP + Audio Mux) — DA-V v4.5
Autor: Dante Ferraz (MonoTech)

Fonte unica de verdade compartilhada entre `StreamEngineService` e os workers de producao
(`scripts/dav_sender_worker.py` e `scripts/dav_client.py`), eliminando qualquer split-brain.
"""

from __future__ import annotations

import collections
import threading
import time
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from src.dav.modules.transport_p2p.crypto_pake import (
    MAGIC_PAKE_ACK,
    MAGIC_PAKE_SYN,
    PakeSession,
)
from src.dav.modules.transport_p2p.dualstack import effective_mtu_for_ip
from src.dav.modules.transport_p2p.fec_engine import (
    AdaptiveFecPolicy,
    FecDecoder,
    FecEncoder,
)
from src.dav.modules.transport_p2p.packetizer import (
    DAV_DEFAULT_MTU,
    FLAG_FEC,
    FLAG_KEYFRAME,
    FLAG_LAST_FRAG,
    FLAG_PIR,
    PT_AUDIO,
    PT_CONTROL,
    PT_FEC,
    PT_INPUT,
    PT_VIDEO,
    PT_WORKSPACE,
    pack_datagram,
    split_chunks,
    unpack_and_decrypt,
)
from src.dav.modules.transport_p2p.sqp_controller import (
    FrameBudget,
    MicroPacer,
    SqpAckData,
    SqpReceiverTracker,
    SqpSenderController,
)


class DataPlaneSender:
    """Orquestrador unificado de saida: PAKE -> SQP Budget -> Video/FEC AEAD + Audio PQ."""

    def __init__(
        self,
        pin: str,
        send_raw_fn: Callable[[bytes], None],
        initial_bitrate_kbps: int = 12000,
        fps: int = 60,
        max_chunk: int = DAV_DEFAULT_MTU,
    ):
        self.pin = pin
        self.max_chunk = int(max_chunk)
        self.pake = PakeSession(role="S", pin=pin)
        self.sqp = SqpSenderController(initial_bitrate_kbps=initial_bitrate_kbps, fps=fps)
        self.pacer = MicroPacer(send_fn=send_raw_fn)

        self._video_seq = 0
        self._audio_seq = 0
        self._ws_seq = 0
        self._seq_lock = threading.Lock()
        self._video_frame_id = 0
        self._audio_frame_id = 0
        self._ws_frame_id = 0
        self.fec_shards_sent = 0
        self.last_fec_parity_m = 0

    def _next_video_seq(self) -> int:
        with self._seq_lock:
            self._video_seq += 1
            return self._video_seq

    def _next_audio_seq(self) -> int:
        with self._seq_lock:
            self._audio_seq += 1
            return self._audio_seq

    def _next_ws_seq(self) -> int:
        with self._seq_lock:
            self._ws_seq += 1
            return self._ws_seq

    def set_target_mtu_for_ip(self, target_ip: str) -> int:
        """Ajusta MTU dinamicamente (`1180 B` em IPv6 <= 1280 RFC 8200; `1300 B` em IPv4)."""
        self.max_chunk = effective_mtu_for_ip(target_ip)
        return self.max_chunk

    def build_pake_syn(self) -> bytes:
        return self.pake.build_syn()

    def build_pake_ack(self) -> Optional[bytes]:
        return self.pake.build_ack()

    def handle_incoming_packet(self, pkt: bytes) -> Tuple[str, Optional[bytes]]:
        """
        Trata pacotes de controle e area de trabalho recebidos pelo Transmissor:
        - Handshake PAKE (`SYN2`/`ACK2`)
        - Pacote AEAD `PT_CONTROL` (`DAV_SQP1` SQP_ACK)
        - Pacote AEAD `PT_INPUT` (24B HID input)
        - Pacote AEAD `PT_WORKSPACE` (ARQ / Clipboard / Arquivos / PTY)
        Retorna (evento, payload_ou_resposta_opcional).
        """
        if pkt.startswith(MAGIC_PAKE_SYN) or pkt.startswith(MAGIC_PAKE_ACK):
            valid, reply_ack, newly_confirmed = self.pake.process_control(pkt)
            if not valid:
                return "ignored", None
            if newly_confirmed:
                return "pake_confirmed", reply_ack
            return "pake_ack", reply_ack

        cipher = self.pake.cipher
        if cipher is not None:
            opened = unpack_and_decrypt(pkt, aead_cipher=cipher, enforce_replay=True)
            if opened is not None:
                hdr, plaintext = opened
                # Confirma e renova timestamp de trafego AEAD valido (blindagem contra SYN2 espurio)
                self.pake.mark_valid_rx()
                if hdr.payload_type == PT_INPUT:
                    return "remote_input", plaintext
                if hdr.payload_type == PT_WORKSPACE:
                    return "workspace_msg", plaintext
                if hdr.payload_type == PT_CONTROL:
                    sqp_ack = SqpAckData.unpack(plaintext)
                    if sqp_ack is not None:
                        self.sqp.on_sqp_ack(sqp_ack)
                        return "sqp_ack", None
        return "other", None

    def send_workspace_datagram(self, ws_bytes: bytes, frame_id: int = 0) -> bool:
        """Empacota mensagem PT_WORKSPACE autenticada via AEAD na fila prioritaria."""
        cipher = self.pake.cipher
        if cipher is None or not self.pake.confirmed or not ws_bytes:
            return False
        with self._seq_lock:
            self._ws_frame_id += 1
            eff_fid = frame_id if frame_id > 0 else self._ws_frame_id
            seq = self._ws_seq + 1
            self._ws_seq = seq
        pkt = pack_datagram(
            PT_WORKSPACE,
            ws_bytes,
            frame_id=eff_fid,
            seq_num=seq,
            frag_idx=0,
            frag_tot=1,
            flags=0,
            aead_cipher=cipher,
        )
        self.pacer.enqueue_high_priority(pkt)
        self.pacer.flush_high_priority()
        return True

    def allocate_budget(self, audio_reserved_bytes: int = 240) -> FrameBudget:
        return self.sqp.allocate_frame_budget(audio_reserved_bytes=audio_reserved_bytes)

    def send_audio_frame(self, encoded_audio: bytes, is_lbrr: bool = False) -> bool:
        """Empacota audio PT_AUDIO autenticado via AEAD e coloca na fila prioritaria."""
        cipher = self.pake.cipher
        if cipher is None or not self.pake.confirmed or not encoded_audio:
            return False

        self._audio_frame_id += 1
        seq = self._next_audio_seq()
        flags = 0x20 if is_lbrr else 0
        pkt = pack_datagram(
            PT_AUDIO,
            encoded_audio,
            frame_id=self._audio_frame_id,
            seq_num=seq,
            frag_idx=0,
            frag_tot=1,
            flags=flags,
            aead_cipher=cipher,
        )
        self.pacer.enqueue_high_priority(pkt)
        self.pacer.flush_high_priority()
        return True

    def send_video_frame(
        self,
        compressed_payload: bytes,
        is_keyframe: bool,
        frame_interval_sec: float,
        pir_mode: bool = False,
        stop_check: Optional[Callable[[], bool]] = None,
    ) -> Tuple[int, int, int]:
        """
        Fragmenta o quadro comprimido, gera paridade FEC adaptativa em GF(2^8),
        aplica ChaCha20-Poly1305 AEAD por pacote e despacha via MicroPacer.
        Retorna `(packets_sent, bytes_sent, fec_parity_count)`.
        """
        cipher = self.pake.cipher
        if cipher is None or not self.pake.confirmed or not compressed_payload:
            return 0, 0, 0

        self._video_frame_id += 1
        frame_id = self._video_frame_id
        ts_us = int(time.time_ns() // 1000)
        chunks = split_chunks(compressed_payload, max_chunk=self.max_chunk)
        k_data = len(chunks)
        if k_data == 0:
            return 0, 0, 0

        eff_owd_for_fec = self.sqp.owd_gradient_ms if self.sqp.loss_rate >= 0.005 else 0.0
        m_parity = AdaptiveFecPolicy.choose_parity(
            k_data=k_data,
            is_keyframe=is_keyframe,
            loss_rate=self.sqp.loss_rate,
            owd_gradient_ms=eff_owd_for_fec,
        )
        self.last_fec_parity_m = m_parity

        extra_flags = (FLAG_KEYFRAME if is_keyframe else 0) | (FLAG_FEC if m_parity > 0 else 0) | (FLAG_PIR if pir_mode else 0)
        datagrams: List[bytes] = []

        for frag_idx, chunk in enumerate(chunks):
            seq = self._next_video_seq()
            pkt_flags = extra_flags | (FLAG_LAST_FRAG if frag_idx == k_data - 1 else 0)
            datagrams.append(
                pack_datagram(
                    PT_VIDEO,
                    chunk,
                    frame_id=frame_id,
                    seq_num=seq,
                    frag_idx=frag_idx,
                    frag_tot=k_data,
                    flags=pkt_flags,
                    ts_us=ts_us,
                    aead_cipher=cipher,
                )
            )

        if m_parity > 0:
            parity_payloads = FecEncoder.encode_shards(chunks, parity_count=m_parity)
            for p_idx, p_payload in enumerate(parity_payloads):
                seq = self._next_video_seq()
                datagrams.append(
                    pack_datagram(
                        PT_FEC,
                        p_payload,
                        frame_id=frame_id,
                        seq_num=seq,
                        frag_idx=p_idx,
                        frag_tot=len(parity_payloads),
                        flags=FLAG_FEC | (FLAG_KEYFRAME if is_keyframe else 0),
                        ts_us=ts_us,
                        aead_cipher=cipher,
                    )
                )
            self.fec_shards_sent += len(parity_payloads)

        heavy_loss_congested = (self.sqp.loss_rate >= 0.08) and (self.sqp.owd_gradient_ms >= 15.0)
        eff_max_span = 0.005 if (is_keyframe and heavy_loss_congested and k_data >= 30) else 0.002
        bytes_sent = self.pacer.send_frame_paced(
            datagrams=datagrams,
            pacing_bps=max(self.sqp.min_bps, self.sqp.estimated_bps * 1.08),
            frame_interval_sec=frame_interval_sec,
            stop_check=stop_check,
            cut_through=not heavy_loss_congested,
            max_span_sec=eff_max_span,
        )
        self.sqp.record_frame_sent(frame_id, bytes_sent)
        return len(datagrams), bytes_sent, m_parity


class DataPlaneReceiver:
    """Orquestrador unificado de entrada: PAKE -> AEAD Verify -> FEC Recover + SQP Feedback + Audio."""

    def __init__(self, pin: str):
        self.pin = pin
        self.pake = PakeSession(role="R", pin=pin)
        self.sqp_tracker = SqpReceiverTracker()

        self._pending: Dict[int, Dict[str, Any]] = collections.OrderedDict()
        self._max_pending = 40
        self._completed_ids: Deque[int] = collections.deque(maxlen=128)
        self._completed_set = set()
        self._ack_seq = 0
        self._input_seq = 0
        self._ws_seq = 0
        self._tx_lock = threading.Lock()

        self.fec_recovered_frames = 0
        self.auth_failures = 0
        self.clock_offset_us: Optional[int] = None
        self._owd_window: Deque[int] = collections.deque(maxlen=120)
        self._latency_ema_ms: float = 0.0
        self.latest_latency_ms: float = 0.0
        self.has_seen_keyframe = False
        self._last_completed_frame_id: int = 0

    def build_pake_syn(self) -> bytes:
        return self.pake.build_syn()

    def build_pake_ack(self) -> Optional[bytes]:
        return self.pake.build_ack()

    def build_input_datagram(self, input_bytes: bytes, event_id: int = 0) -> Optional[bytes]:
        """Constroi datagrama PT_INPUT autenticado via AEAD (thread-safe)."""
        cipher = self.pake.cipher
        if cipher is None or not input_bytes:
            return None
        with self._tx_lock:
            self._input_seq += 1
            seq = self._input_seq
            eff_fid = event_id if event_id > 0 else seq
        return pack_datagram(
            PT_INPUT,
            input_bytes,
            frame_id=eff_fid,
            seq_num=seq,
            frag_idx=0,
            frag_tot=1,
            flags=0,
            aead_cipher=cipher,
        )

    def build_workspace_datagram(self, ws_bytes: bytes, msg_id: int = 0) -> Optional[bytes]:
        """Constroi datagrama PT_WORKSPACE autenticado via AEAD (thread-safe)."""
        cipher = self.pake.cipher
        if cipher is None or not ws_bytes:
            return None
        with self._tx_lock:
            self._ws_seq += 1
            seq = self._ws_seq
            eff_fid = msg_id if msg_id > 0 else seq
        return pack_datagram(
            PT_WORKSPACE,
            ws_bytes,
            frame_id=eff_fid,
            seq_num=seq,
            frag_idx=0,
            frag_tot=1,
            flags=0,
            aead_cipher=cipher,
        )

    def _mark_completed(self, frame_id: int) -> None:
        if len(self._completed_ids) == self._completed_ids.maxlen:
            old = self._completed_ids.popleft()
            self._completed_set.discard(old)
        self._completed_ids.append(frame_id)
        self._completed_set.add(frame_id)

    def _build_sqp_control_datagram(self, ack_data: SqpAckData) -> Optional[bytes]:
        cipher = self.pake.cipher
        if cipher is None:
            return None
        with self._tx_lock:
            self._ack_seq += 1
            seq = self._ack_seq
        return pack_datagram(
            PT_CONTROL,
            ack_data.pack(),
            frame_id=ack_data.last_frame_id,
            seq_num=seq,
            frag_idx=0,
            frag_tot=1,
            flags=0,
            aead_cipher=cipher,
        )

    def process_packet(
        self,
        raw_pkt: bytes,
    ) -> Dict[str, Any]:
        """
        Processa datagrama recebido da rede.
        Retorna dicionario com resultado estruturado:
          kind: "pake" | "video_frame" | "audio_frame" | "fragment" | "ignored"
          reply_pake: bytes | None
          newly_confirmed: bool
          sqp_ack_pkt: bytes | None
          need_pli: bool
          frame_bytes: bytes | None
          is_keyframe: bool
          tx_ts_us: int
          audio_payload: bytes | None
          audio_frame_id: int
          audio_lbrr: bool
        """
        res: Dict[str, Any] = {
            "kind": "ignored",
            "reply_pake": None,
            "newly_confirmed": False,
            "sqp_ack_pkt": None,
            "need_pli": False,
            "frame_bytes": None,
            "is_keyframe": False,
            "tx_ts_us": 0,
            "audio_payload": None,
            "audio_frame_id": 0,
            "audio_lbrr": False,
            "workspace_payload": None,
        }

        if raw_pkt.startswith(MAGIC_PAKE_SYN) or raw_pkt.startswith(MAGIC_PAKE_ACK):
            valid, reply_ack, newly_confirmed = self.pake.process_control(raw_pkt)
            if valid:
                res["kind"] = "pake"
                res["reply_pake"] = reply_ack
                res["newly_confirmed"] = newly_confirmed
            return res

        cipher = self.pake.cipher
        if cipher is None:
            return res

        opened = unpack_and_decrypt(raw_pkt, aead_cipher=cipher, enforce_replay=True)
        if opened is None:
            self.auth_failures += 1
            return res

        hdr, plaintext = opened
        was_confirmed = self.pake.confirmed
        self.pake.mark_valid_rx()
        if not was_confirmed:
            res["newly_confirmed"] = True

        if hdr.payload_type == PT_AUDIO:
            res["kind"] = "audio_frame"
            res["audio_payload"] = plaintext
            res["audio_frame_id"] = hdr.frame_id
            res["audio_lbrr"] = hdr.has_audio_lbrr
            res["tx_ts_us"] = hdr.timestamp_us
            return res

        if hdr.payload_type == PT_WORKSPACE:
            res["kind"] = "workspace_msg"
            res["workspace_payload"] = plaintext
            res["tx_ts_us"] = hdr.timestamp_us
            return res

        if hdr.payload_type not in (PT_VIDEO, PT_FEC):
            return res

        # Medicao de latencia sub-milissegundo via Windowed Min-OWD no 1o fragmento do video
        if hdr.payload_type == PT_VIDEO and hdr.frag_idx == 0 and hdr.timestamp_us > 0:
            now_us = int(time.time_ns() // 1000)
            raw_diff = now_us - hdr.timestamp_us
            self._owd_window.append(raw_diff)
            baseline = min(self._owd_window)
            self.clock_offset_us = baseline
            inst_lat_ms = max(0.3, ((raw_diff - baseline) / 1000.0) + 0.3)
            if self._latency_ema_ms <= 0.0:
                self._latency_ema_ms = inst_lat_ms
            else:
                self._latency_ema_ms = 0.70 * self._latency_ema_ms + 0.30 * inst_lat_ms
            self.latest_latency_ms = self._latency_ema_ms

        self.sqp_tracker.on_packet_received(
            seq_num=hdr.seq_num,
            frame_id=hdr.frame_id,
            tx_ts_us=hdr.timestamp_us,
            pkt_bytes=len(raw_pkt),
        )

        frame_id = hdr.frame_id
        if frame_id in self._completed_set:
            res["kind"] = "fragment"
            return res

        if not hdr.is_keyframe and not self.has_seen_keyframe:
            res["need_pli"] = True
            res["kind"] = "fragment"
            return res

        entry = self._pending.get(frame_id)
        if entry is None:
            while len(self._pending) >= self._max_pending:
                _, old_entry = self._pending.popitem(last=False)
                res["need_pli"] = True
            entry = {
                "data": {},
                "parity": {},
                "k_data": hdr.frag_tot if hdr.payload_type == PT_VIDEO else 0,
                "is_kf": hdr.is_keyframe,
                "ts_us": hdr.timestamp_us,
                "created_mono": time.perf_counter(),
            }
            self._pending[frame_id] = entry

        if hdr.payload_type == PT_VIDEO:
            entry["data"][hdr.frag_idx] = plaintext
            entry["k_data"] = hdr.frag_tot
            if hdr.is_keyframe:
                entry["is_kf"] = True
        else:
            parsed_fec = FecDecoder.parse_parity_payload(plaintext)
            if parsed_fec is not None:
                k_data = parsed_fec[0]
                if entry["k_data"] == 0:
                    entry["k_data"] = k_data
                entry["parity"][hdr.frag_idx] = plaintext

        # Limpeza seletiva apenas quando houver acumulo na fila de remontagem (> 8 quadros / 350 ms)
        if len(self._pending) > 8:
            now_p = time.perf_counter()
            expired = [fid for fid, e in self._pending.items() if (now_p - e["created_mono"]) > 0.350]
            for efid in expired:
                if efid != frame_id:
                    del self._pending[efid]
                    res["need_pli"] = True

        k_data = entry["k_data"]
        n_data = len(entry["data"])
        n_par = len(entry["parity"])

        if k_data > 0 and (n_data == k_data or (n_par > 0 and (n_data + n_par) >= k_data)):
            used_fec = (n_data < k_data)
            shards = FecDecoder.recover(k_data, entry["data"], entry["parity"])
            if shards is not None:
                del self._pending[frame_id]
                self._mark_completed(frame_id)
                if used_fec:
                    self.fec_recovered_frames += 1

                # Descarta fragmentos incompletos de quadros mais antigos e detecta quebra de referencia P-frame
                older_incomplete = [k for k in self._pending if k < frame_id]
                for old_fid in older_incomplete:
                    del self._pending[old_fid]

                if entry["is_kf"]:
                    self.has_seen_keyframe = True
                    res["ref_gap"] = False
                elif (
                    self._last_completed_frame_id > 0
                    and frame_id > (self._last_completed_frame_id + 1)
                ) or older_incomplete:
                    res["need_pli"] = True
                    res["ref_gap"] = True
                else:
                    res["ref_gap"] = False

                if frame_id > self._last_completed_frame_id or entry["is_kf"]:
                    self._last_completed_frame_id = frame_id

                rx_queue_ahead = sum(1 for k in self._pending if k > frame_id)
                ack_data = self.sqp_tracker.on_frame_completed(
                    frame_id=frame_id,
                    tx_ts_us=entry["ts_us"],
                    rx_queue_frames=rx_queue_ahead,
                )
                res["kind"] = "video_frame"
                res["frame_bytes"] = b"".join(shards)
                res["is_keyframe"] = bool(entry["is_kf"])
                res["tx_ts_us"] = entry["ts_us"]
                res["sqp_ack_pkt"] = self._build_sqp_control_datagram(ack_data)
                return res

        if self.sqp_tracker.should_emit_periodic_ack():
            rx_queue_ahead = sum(1 for k in self._pending if k > frame_id)
            ack_data = self.sqp_tracker.emit_periodic_snapshot(
                frame_id=frame_id,
                tx_ts_us=entry["ts_us"],
                rx_queue_frames=rx_queue_ahead,
            )
            res["sqp_ack_pkt"] = self._build_sqp_control_datagram(ack_data)

        res["kind"] = "fragment"
        return res
