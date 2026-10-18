#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V Python C-ABI Client & High-Performance Binding Layer
Provides seamless interface between any Python frontend (PySide6/PyQt6/Tkinter)
and the native C++ DA-V Core Engine (dav_core.dll / libdav_core.so) with
accelerated SIMD/NumPy vectorized processing, Jumbo Datagram LAN chunking,
and decoupled Producer-Consumer pipelining for solid 1080p 60 FPS streaming.
"""

import os
import sys
import ctypes
from ctypes import (
    c_int, c_uint16, c_uint32, c_uint64, c_float, c_size_t,
    c_char_p, c_void_p, POINTER, Structure, CFUNCTYPE
)
from typing import Optional, Callable
import time
import socket
import struct
import threading
import numpy as np

# Enable 1ms high-precision multimedia timer and 1ms GIL switch interval on Windows
k32 = None
if sys.platform == "win32":
    try:
        k32 = ctypes.windll.kernel32
        k32.GetCurrentThread.restype = ctypes.c_void_p
        k32.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
        k32.SetThreadPriority.restype = ctypes.c_int
        k32.SetThreadAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        k32.SetThreadAffinityMask.restype = ctypes.c_size_t
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

def _set_thread_perf(priority: int = 2, core_affinity_mask: int = 0):
    if k32 is not None:
        try:
            h = k32.GetCurrentThread()
            k32.SetThreadPriority(h, priority)
            if core_affinity_mask > 0:
                k32.SetThreadAffinityMask(h, core_affinity_mask)
        except Exception:
            pass

try:
    sys.setswitchinterval(0.001)
except Exception:
    pass

# ============================================================================
# C-ABI Structures Mapping
# ============================================================================

class DavRenderFrame(Structure):
    _fields_ = [
        ("width", c_uint32),
        ("height", c_uint32),
        ("stride", c_uint32),
        ("timestamp_us", c_uint64),
        ("rgba_data", POINTER(ctypes.c_uint8)),
        ("data_size", c_size_t),
        ("is_keyframe", c_int)
    ]

class DavTelemetry(Structure):
    _fields_ = [
        ("fps", c_float),
        ("bitrate_mbps", c_float),
        ("latency_ms", c_float),
        ("packets_sent", c_uint64),
        ("packets_received", c_uint64),
        ("packets_lost", c_uint64),
        ("frames_captured", c_uint64),
        ("frames_rendered", c_uint64),
        ("is_connected", c_int)
    ]

# Callback types
DavFrameReadyCallback = CFUNCTYPE(None, POINTER(DavRenderFrame), c_void_p)
DavTelemetryCallback = CFUNCTYPE(None, POINTER(DavTelemetry), c_void_p)
DavLogCallback = CFUNCTYPE(None, c_int, c_char_p, c_void_p)


class DavCoreEngine:
    """Universal High-Performance Engine abstraction for DA-V."""

    def __init__(self):
        self._dll = None
        self._is_native = False
        self._frame_cb_native = None
        self._telemetry_cb_native = None
        self._user_frame_callback: Optional[Callable] = None
        self._user_telemetry_callback: Optional[Callable] = None
        self._user_sender_stats_callback: Optional[Callable] = None   # (frames, fps, mbps, pkts)

        # Fallback state if DLL not yet compiled
        self._fallback_threads = []
        self._fallback_running = False

        self._try_load_native_library()

    def _try_load_native_library(self):
        possible_paths = [
            os.path.join(os.path.dirname(__file__), "..", "build", "Release", "dav_core.dll"),
            os.path.join(os.path.dirname(__file__), "..", "build", "dav_core.dll"),
            os.path.join(os.path.dirname(__file__), "..", "build", "libdav_core.so"),
            os.path.join(os.path.dirname(__file__), "dav_core.dll"),
            "dav_core.dll",
            "libdav_core.so"
        ]

        for p in possible_paths:
            if os.path.exists(p):
                try:
                    self._dll = ctypes.CDLL(os.path.abspath(p))
                    self._setup_c_signatures()
                    self._is_native = True
                    print(f"[DAV-Client] Carregada biblioteca nativa C-ABI: {p}")
                    return
                except Exception as e:
                    print(f"[DAV-Client] Falha ao carregar {p}: {e}")

        print("[DAV-Client] Backend nativo C-ABI (dav_core.dll) nao encontrado. Utilizando runtime ultra-otimizado com aceleracao SIMD.")

    def _setup_c_signatures(self):
        self._dll.dav_init.argtypes = [c_char_p]
        self._dll.dav_init.restype = c_int

        self._dll.dav_start_sender.argtypes = [c_char_p, c_uint16, c_char_p, c_uint32, c_uint32, c_uint32]
        self._dll.dav_start_sender.restype = c_int

        self._dll.dav_start_receiver.argtypes = [c_uint16, c_char_p, DavFrameReadyCallback, DavTelemetryCallback, c_void_p]
        self._dll.dav_start_receiver.restype = c_int

        self._dll.dav_stop.argtypes = []
        self._dll.dav_stop.restype = None

        self._dll.dav_request_keyframe.argtypes = []
        self._dll.dav_request_keyframe.restype = None

        self._dll.dav_get_telemetry.argtypes = [POINTER(DavTelemetry)]
        self._dll.dav_get_telemetry.restype = c_int

        self._dll.dav_get_version.argtypes = []
        self._dll.dav_get_version.restype = c_char_p

        # Initialize
        self._dll.dav_init(None)

    @property
    def is_native_backend(self) -> bool:
        return self._is_native

    def start_sender(
        self,
        target_ip: str,
        target_port: int,
        pin: str,
        width: int = 1920,
        height: int = 1080,
        fps: int = 60,
        bitrate_kbps: int = 12000,
        on_sender_stats: Optional[Callable] = None,
        codec_type: str = "h264_nvenc",
        monitor_index: int = 0
    ) -> bool:
        # Register sender stats callback (frames_sent, fps, mbps, packets_sent, codec, frame_kb)
        self._user_sender_stats_callback = on_sender_stats or (lambda *a: None)
        if self._is_native:
            res = self._dll.dav_start_sender(
                target_ip.encode('utf-8'),
                target_port,
                pin.encode('utf-8'),
                width,
                height,
                fps
            )
            return res == 0
        else:
            return self._start_fallback_sender(
                target_ip, target_port, pin, width, height, fps, bitrate_kbps,
                codec_type=codec_type, monitor_index=monitor_index
            )

    def start_receiver(
        self,
        bind_port: int,
        pin: str,
        on_frame_ready: Callable,
        on_telemetry: Optional[Callable] = None
    ) -> bool:
        self._user_frame_callback = on_frame_ready
        self._user_telemetry_callback = on_telemetry

        if self._is_native:
            def _native_frame_bridge(frame_ptr, user_data):
                if frame_ptr and self._user_frame_callback:
                    f = frame_ptr.contents
                    buf = ctypes.string_at(f.rgba_data, f.data_size)
                    self._user_frame_callback(buf, f.width, f.height, f.timestamp_us, bool(f.is_keyframe))

            def _native_telemetry_bridge(telem_ptr, user_data):
                if telem_ptr and self._user_telemetry_callback:
                    t = telem_ptr.contents
                    self._user_telemetry_callback(
                        t.fps, t.bitrate_mbps, t.latency_ms,
                        t.packets_received, t.frames_rendered
                    )

            self._frame_cb_native = DavFrameReadyCallback(_native_frame_bridge)
            self._telemetry_cb_native = DavTelemetryCallback(_native_telemetry_bridge)

            res = self._dll.dav_start_receiver(
                bind_port,
                pin.encode('utf-8'),
                self._frame_cb_native,
                self._telemetry_cb_native,
                None
            )
            return res == 0
        else:
            return self._start_fallback_receiver(bind_port, pin)

    def stop(self):
        if self._is_native:
            self._dll.dav_stop()
        else:
            self._fallback_running = False
            # Signal and terminate the sender subprocess (GIL-free process)
            if hasattr(self, "_sender_stop_event") and self._sender_stop_event is not None:
                try:
                    self._sender_stop_event.set()
                except Exception:
                    pass
            if hasattr(self, "_sender_process") and self._sender_process is not None:
                try:
                    self._sender_process.join(timeout=0.5)
                    if self._sender_process.is_alive():
                        self._sender_process.terminate()
                except Exception:
                    pass
                self._sender_process = None
            # Join stats poller thread
            for t in self._fallback_threads:
                if t.is_alive():
                    t.join(timeout=0.3)
            self._fallback_threads.clear()

    def request_keyframe(self):
        if self._is_native:
            self._dll.dav_request_keyframe()

    # ========================================================================
    # GIL-Free Subprocess Sender (Separate OS process — no GIL contention)
    # ========================================================================

    def _start_fallback_sender(self, target_ip: str, target_port: int, pin: str,
                                width: int, height: int, fps: int,
                                bitrate_kbps: int = 12000,
                                codec_type: str = "h264_nvenc",
                                monitor_index: int = 0) -> bool:
        """Launch the sender in a separate OS process to bypass the CPython GIL."""
        import multiprocessing as mp
        from scripts.dav_sender_worker import _sender_subprocess

        target_fps = fps if fps > 0 else 60

        ctx = mp.get_context("spawn")
        self._sender_stats_queue: "mp.Queue" = ctx.Queue(maxsize=16)
        self._sender_stop_event: "mp.Event" = ctx.Event()

        self._sender_process = ctx.Process(
            target=_sender_subprocess,
            name="DAV-Sender-GPU",
            daemon=True,
            args=(
                target_ip, target_port, pin,
                width, height, target_fps, bitrate_kbps,
                self._sender_stats_queue,
                self._sender_stop_event,
                codec_type,
                monitor_index,
            ),
        )
        self._sender_process.start()
        self._fallback_running = True

        # Stats poller thread — drains the multiprocessing queue and calls user callback
        def _stats_poller():
            while self._fallback_running:
                try:
                    item = self._sender_stats_queue.get(timeout=0.1)
                    frames_sent, cur_fps, cur_mbps, packets_sent, quality, frame_kb = item
                    if self._user_sender_stats_callback:
                        try:
                            self._user_sender_stats_callback(frames_sent, cur_fps, cur_mbps, packets_sent, quality, frame_kb)
                        except TypeError:
                            self._user_sender_stats_callback(frames_sent, cur_fps, cur_mbps, packets_sent)
                except Exception:
                    pass

        t_poller = threading.Thread(target=_stats_poller, daemon=True, name="DAV-Stats-Poller")
        self._fallback_threads = [t_poller]
        t_poller.start()
        return True


    def _start_fallback_receiver(self, bind_port: int, pin: str) -> bool:
        self._fallback_running = True

        def _receiver_loop():
            _set_thread_perf(priority=2, core_affinity_mask=0)  # Dynamic SMT across all CPU cores
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32 * 1024 * 1024)
            sock.bind(('0.0.0.0', bind_port))
            sock.settimeout(0.5)

            clean_pin = str(pin).replace("-", "").replace(" ", "").strip()
            raw_key = f"dav-secret-{clean_pin}-key-salt-2026".encode('utf-8')
            key_bytes = bytes([raw_key[i % len(raw_key)] ^ ((i * 37) & 0xFF) for i in range(32)])
            
            key_buf_size = 16777216
            key_vec = np.frombuffer((key_bytes * ((key_buf_size // 32) + 2))[:key_buf_size], dtype=np.uint8)

            pending_frames = {}
            packets_received = 0
            frames_rendered = 0
            total_bytes = 0
            latencies_ms = []
            clock_offset_us = None

            last_stat_time = time.perf_counter()
            last_pkts = 0
            last_bytes = 0
            last_frames_stat = 0
            cur_fps = 0.0
            cur_mbps = 0.0
            cur_lat = 0.0


            while self._fallback_running:
                try:
                    data, addr = sock.recvfrom(65536)
                    if not data or len(data) < 32:
                        continue

                    now_us = int(time.time_ns() / 1000)
                    packets_received += 1
                    data_len = len(data)
                    total_bytes += data_len

                    unpacked = struct.unpack('!BBBBIIQIIHH', data[:32])
                    flags = unpacked[2]
                    ts_us = unpacked[6]
                    frame_id = unpacked[7]
                    payload_len = unpacked[8]
                    frag_idx = unpacked[9]
                    frag_tot = unpacked[10]

                    raw_diff = now_us - ts_us
                    if clock_offset_us is None or raw_diff < clock_offset_us:
                        clock_offset_us = raw_diff

                    latencies_ms.append(max(0.5, (raw_diff - clock_offset_us) / 1000.0))

                    # Raw encrypted chunk (stored directly to eliminate per-packet CPU overhead)
                    enc_payload = data[32:32 + payload_len]

                    # Robust Wi-Fi / Remote Jitter Reassembly Window (up to 40 frames in-flight with 350ms timeout)
                    now_t = time.perf_counter()
                    if frame_id not in pending_frames:
                        if len(pending_frames) >= 40:
                            # Prune frames older than 350ms
                            stale = [fid for fid, f in pending_frames.items() if now_t - f[3] > 0.350]
                            for sfid in stale:
                                del pending_frames[sfid]
                            if len(pending_frames) >= 40:
                                del pending_frames[min(pending_frames.keys())]

                        pending_frames[frame_id] = [0, frag_tot, [None] * frag_tot, now_t, flags]

                    frame_entry = pending_frames[frame_id]
                    if frag_idx < frame_entry[1] and frame_entry[2][frag_idx] is None:
                        frame_entry[2][frag_idx] = enc_payload
                        frame_entry[0] += 1

                    if frame_entry[0] == frame_entry[1]:
                        frames_rendered += 1
                        assembled_data = b"".join(frame_entry[2])
                        frame_flags = frame_entry[4]
                        del pending_frames[frame_id]

                        # Complete 1-shot vectorized decryption aligned 1:1 with sender key stream
                        is_encrypted = (frame_flags & 0x02) != 0
                        if is_encrypted:
                            if len(assembled_data) > len(key_vec):
                                key_vec = np.frombuffer((key_bytes * ((len(assembled_data) // 32) + 2))[:len(assembled_data)], dtype=np.uint8)
                            frame_arr = np.frombuffer(assembled_data, dtype=np.uint8)
                            full_frame = np.bitwise_xor(frame_arr, key_vec[:len(assembled_data)]).tobytes()
                        else:
                            full_frame = assembled_data

                        if self._user_frame_callback:
                            self._user_frame_callback(full_frame, 1920, 1080, ts_us, bool(frame_flags & 0x01))

                    cur_now = time.perf_counter()
                    if cur_now - last_stat_time >= 0.5:
                        elapsed = cur_now - last_stat_time
                        sec_bytes = total_bytes - last_bytes
                        # ── Accurate FPS: count actual complete frames delivered ──
                        frame_delta = frames_rendered - last_frames_stat
                        cur_fps = frame_delta / elapsed
                        cur_mbps = (sec_bytes * 8.0) / (elapsed * 1_000_000.0)
                        cur_lat = sum(latencies_ms[-30:]) / len(latencies_ms[-30:]) if latencies_ms else 1.5

                        if self._user_telemetry_callback:
                            self._user_telemetry_callback(cur_fps, cur_mbps, cur_lat, packets_received, frames_rendered)

                        # Broadcast real RX telemetry to live benchmark orchestrator
                        try:
                            import json as _json
                            _rx_msg = _json.dumps({
                                "role": "rx",
                                "fps": round(cur_fps, 2),
                                "mbps": round(cur_mbps, 2),
                                "lat": round(cur_lat, 2),
                                "frames": frames_rendered,
                                "packets": packets_received
                            }).encode("utf-8")
                            sock.sendto(_rx_msg, ("127.0.0.1", 19901))
                        except Exception:
                            pass

                        last_stat_time = cur_now
                        last_pkts = packets_received
                        last_bytes = total_bytes
                        last_frames_stat = frames_rendered



                except socket.timeout:
                    continue
                except Exception:
                    continue

            sock.close()

        t_rec = threading.Thread(target=_receiver_loop, daemon=True, name="DAV-Receiver-Loop")
        self._fallback_threads.append(t_rec)
        t_rec.start()
        return True
