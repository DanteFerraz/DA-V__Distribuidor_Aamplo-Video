# -*- coding: utf-8 -*-
"""
DA-V Engine Bridge & Background Decode Worker
Thread-safe signal bridge connecting the C-ABI / Python Core Engine to Qt main loop.
"""

import sys
import os
import time
import socket
import threading
import queue as _queue
from typing import Optional, Tuple

import ctypes
from scripts.qt_compat import QObject, Signal, QImage
from src.codec.hybrid_codec import HybridDecoder

# Optional Stage Probe integration (fire-and-forget, non-blocking)
_probe_send = None
try:
    from scripts.dav_stage_probe import probe_send as _probe_send
except Exception:
    pass


class EngineBridge(QObject):
    """Bridge for routing signals from background threads to Qt GUI main thread."""
    frame_ready = Signal(QImage, float, float, float, int, int)
    raw_frame_arrived = Signal(bytes, int, int)   # raw bytes, w, h
    telemetry_ready = Signal(float, float, float, int, int)
    sender_stats = Signal(int, float, float, int, int, int)  # frames, fps, mbps, packets, quality, frame_kb
    log_message = Signal(str, str)


class DecodeWorker(QObject):
    """
    Decodes incoming video frames (H.264 NVENC, HEVC, JPEG SIMD, RAW) using HybridDecoder.
    Executes in a dedicated worker thread off the Qt main loop, preventing GUI freezes.
    """
    decoded = Signal(QImage)

    def __init__(self, bridge: 'EngineBridge'):
        super().__init__()
        self._q: '_queue.Queue[Optional[Tuple[bytes, int, int]]]' = _queue.Queue(maxsize=32)
        self._running = False
        self._bridge = bridge
        self._thread: Optional[threading.Thread] = None
        self._decoder = HybridDecoder()

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._decode_run, daemon=True, name="DAV-Decode-Worker")
        self._thread.start()

    def stop(self):
        self._running = False
        try:
            self._q.put_nowait(None)
        except Exception:
            pass

    def submit(self, data: bytes, w: int, h: int):
        """Non-blocking submit maintaining ultra-low latency; drops stale frames if buffer full."""
        try:
            self._q.put_nowait((data, w, h))
        except _queue.Full:
            try:
                self._q.get_nowait()
            except _queue.Empty:
                pass
            try:
                self._q.put_nowait((data, w, h))
            except _queue.Full:
                pass

    def _decode_run(self):
        """Worker loop: decode via HybridDecoder -> BGR numpy -> zero-copy QImage -> Qt Signal."""
        if sys.platform == "win32":
            try:
                h = ctypes.windll.kernel32.GetCurrentThread()
                ctypes.windll.kernel32.SetThreadPriority(h, 2)  # HIGHEST
            except Exception:
                pass

        while self._running:
            try:
                item = self._q.get(timeout=0.15)
            except _queue.Empty:
                continue
            if item is None:
                break

            data, w, h = item
            try:
                _t_dec_start = time.perf_counter()
                bgr_list = self._decoder.decode_all(data, w, h)
                _t_dec_end = time.perf_counter()

                # Stage Probe (sampled)
                if _probe_send is not None:
                    _probe_send("decode", _t_dec_start, _t_dec_end)

                for bgr in bgr_list:
                    if bgr is not None:
                        img = QImage(
                            bgr.data, bgr.shape[1], bgr.shape[0],
                            bgr.strides[0], QImage.Format.Format_BGR888
                        )
                        img._holder = bgr  # Zero-copy reference holder prevents premature GC
                        if not img.isNull():
                            self.decoded.emit(img)
            except Exception:
                pass


def find_available_port(start_port: int = 9000, max_tries: int = 20) -> int:
    """Finds the next free UDP port, allowing multiple instances to run side-by-side locally."""
    for port in range(start_port, start_port + max_tries, 2):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.bind(('0.0.0.0', port))
                return port
        except OSError:
            continue
    return start_port
