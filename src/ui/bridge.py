# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
DA-V Engine Bridge & Zero-Ghosting Background Decode Worker — v5.2
Thread-safe signal bridge connecting the C-ABI / Python Core Engine to Qt main loop.
"""

import collections
import ctypes
import socket
import sys
import threading
import time
from typing import Callable, Deque, Optional, Tuple

import numpy as np
from src.dav.modules.codec.decoder import VideoDecoder as HybridDecoder
from src.dav.modules.telemetry.stage_probe import probe_send as _probe_send
from src.dav.modules.transport_p2p.dualstack import create_dualstack_udp_socket
from src.ui.qt_compat import QImage, QObject, Signal


class EngineBridge(QObject):
    """Bridge for routing signals from background threads to Qt GUI main thread."""
    frame_ready = Signal(QImage, float, float, float, int, int)
    raw_frame_arrived = Signal(bytes, int, int)
    telemetry_ready = Signal(float, float, float, int, int)
    sender_stats = Signal(int, float, float, int, int, int)
    log_message = Signal(str, str)


class DecodeWorker(QObject):
    """
    Decodificador Zero-Ghosting em thread dedicada fora do loop principal Qt.

    Invariantes de integridade do DPB (H.264 / HEVC):
    1. Nunca descarta silenciosamente um P-frame intermediario continuando a decodificar
       os P-frames seguintes (o que causaria macroblocos "gravados" na tela).
    2. Ao receber um IDR (`is_keyframe=True`), drena quadros antigos pendentes para pular
       limpamente para o tempo real (executando `flush()` se houve descontinuidade).
    3. Sob acumulo de P-frames (`2..15`), decodifica em modo fast-catchup (atualizando o
       DPB sem criar/emitir QImage ate o quadro mais recente); acima de `16` quadros ou
       se `last_decode_corrupted` ocorrer, limpa a fila, entra em `awaiting_idr` e aciona
       `on_pli_needed()` imediatamente.
    """

    decoded = Signal(QImage)

    def __init__(
        self,
        bridge: "EngineBridge",
        on_pli_needed: Optional[Callable[[], None]] = None,
    ):
        super().__init__()
        self._q: Deque[Tuple[bytes, int, int, bool]] = collections.deque()
        self._cond = threading.Condition()
        self._max_p_backlog = 16
        self._running = False
        self._bridge = bridge
        self._on_pli_needed = on_pli_needed
        self._thread: Optional[threading.Thread] = None
        self._decoder = HybridDecoder()
        self._awaiting_idr = False
        self._need_flush = False
        self._last_pli_trigger = 0.0

    def set_pli_callback(self, cb: Optional[Callable[[], None]]) -> None:
        self._on_pli_needed = cb

    def reset_stream_state(self) -> None:
        """Limpa fila e DPB entre sessoes de recepcao para evitar residuos do stream anterior."""
        with self._cond:
            self._q.clear()
            self._awaiting_idr = False
            self._need_flush = True
            self._cond.notify_all()

    def _trigger_pli(self) -> None:
        cb = self._on_pli_needed
        if cb is None:
            return
        now = time.monotonic()
        if (now - self._last_pli_trigger) < 0.14:
            return
        self._last_pli_trigger = now
        try:
            cb()
        except Exception:
            pass

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._decode_run, daemon=True, name="DAV-Decode-Worker")
        self._thread.start()

    def stop(self):
        self._running = False
        with self._cond:
            self._q.clear()
            self._cond.notify_all()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        self._thread = None

    def submit(self, data: bytes, w: int, h: int, is_keyframe: bool = False):
        """Enfileira quadro comprimido preservando integridade absoluta da cadeia de referencia."""
        if not data:
            return
        fire_pli = False
        with self._cond:
            if is_keyframe:
                # Salto limpo para o IDR mais recente (descarta atraso antigo sem quebrar DPB)
                if self._q or self._awaiting_idr:
                    self._need_flush = True
                self._q.clear()
                self._awaiting_idr = False
                self._q.append((data, w, h, True))
                self._cond.notify()
            elif self._awaiting_idr:
                fire_pli = True
            elif len(self._q) >= self._max_p_backlog:
                # Backlog extremo: em vez de corromper DPB pulando P-frames, solicita IDR limpo
                self._q.clear()
                self._awaiting_idr = True
                self._need_flush = True
                fire_pli = True
            else:
                self._q.append((data, w, h, False))
                self._cond.notify()

        if fire_pli:
            self._trigger_pli()

    def _decode_run(self):
        """Worker loop: decode via HybridDecoder -> BGR numpy -> zero-copy QImage -> Qt Signal."""
        if sys.platform == "win32":
            try:
                h = ctypes.windll.kernel32.GetCurrentThread()
                ctypes.windll.kernel32.SetThreadPriority(h, 2)  # HIGHEST
            except Exception:
                pass

        logged_err = False
        while self._running:
            with self._cond:
                if not self._q:
                    self._cond.wait(timeout=0.15)
                if not self._running:
                    break
                if not self._q:
                    continue
                data, w, h, is_kf = self._q.popleft()
                remaining_after = len(self._q)
                do_flush = self._need_flush and is_kf
                if do_flush:
                    self._need_flush = False

            try:
                if do_flush and hasattr(self._decoder, "flush"):
                    self._decoder.flush()

                _t_dec_start = time.perf_counter()
                bgr_list = self._decoder.decode_all(data, w, h)
                _t_dec_end = time.perf_counter()

                if _probe_send is not None:
                    _probe_send("decode", _t_dec_start, _t_dec_end)

                if getattr(self._decoder, "last_decode_corrupted", False):
                    with self._cond:
                        self._q.clear()
                        self._awaiting_idr = True
                        self._need_flush = True
                    self._trigger_pli()
                    continue

                # Fast-catchup: se ha >= 2 quadros na fila e este nao e IDR, preserva DPB mas pula QImage
                if remaining_after >= 2 and not is_kf:
                    continue

                for bgr in bgr_list:
                    if bgr is not None:
                        if not bgr.flags["C_CONTIGUOUS"]:
                            bgr = np.ascontiguousarray(bgr)
                        img = QImage(
                            bgr.data,
                            bgr.shape[1],
                            bgr.shape[0],
                            bgr.strides[0],
                            QImage.Format.Format_BGR888,
                        )
                        img._holder = bgr
                        if not img.isNull():
                            self.decoded.emit(img)
            except Exception as exc:
                with self._cond:
                    self._q.clear()
                    self._awaiting_idr = True
                    self._need_flush = True
                self._trigger_pli()
                if not logged_err:
                    logged_err = True
                    try:
                        self._bridge.log_message.emit("ERROR", f"[Decode] Falha ao renderizar quadro decodificado: {exc}")
                    except Exception:
                        pass


def find_available_port(start_port: int = 9000, max_tries: int = 20) -> int:
    """Finds the next free Dual-Stack UDP port, allowing multiple instances to run side-by-side."""
    for port in range(start_port, start_port + max_tries, 2):
        try:
            s = create_dualstack_udp_socket(bind_port=port, rcvbuf_mb=1, sndbuf_mb=1)
            bound = int(s.getsockname()[1])
            s.close()
            if bound == port:
                return port
        except OSError:
            continue
    return start_port
