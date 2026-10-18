#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V Performance & Cadence Benchmark Tool
Tests and validates each stage of the DA-V pipeline on the current hardware:
1. GDI Screen Capture latency & throughput
2. Zero-copy ring buffer memory transfer
3. AVX2 SIMD Color Conversion (BGRA -> YUV420P)
4. NVIDIA NVENC RTX 4070 Hardware Encoder latency & FPS
5. End-to-End Decoupled Triple-Threaded Pipeline sustained 60+ FPS
"""

import sys
import os
import time
import ctypes
from ctypes import wintypes
import socket
import struct
import queue
import threading
import numpy as np

# Ensure project root in sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.codec.hybrid_codec import HybridEncoder, HybridDecoder, HAS_AV, HAS_CV2

if HAS_CV2:
    import cv2
if HAS_AV:
    import av
    from fractions import Fraction

# Win32 helpers
k32 = None
if sys.platform == "win32":
    try:
        k32 = ctypes.windll.kernel32
        k32.GetCurrentThread.restype = wintypes.HANDLE
        k32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
        k32.SetThreadPriority.restype = wintypes.BOOL
        k32.SetThreadAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
        k32.SetThreadAffinityMask.restype = ctypes.c_size_t
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass


def run_benchmark():
    print("=" * 70)
    print("   DA-V PIPELINE & HARDWARE ACCELERATION BENCHMARK (RTX 4070)")
    print("=" * 70)

    width, height = 1920, 1080
    frame_bytes_raw = width * height * 4

    # ------------------------------------------------------------------------
    # Stage 1: GDI BitBlt
    # ------------------------------------------------------------------------
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
            ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
            ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
            ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]

    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    p_bits = ctypes.c_void_p()
    hbm = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(p_bits), None, 0)
    gdi32.SelectObject(hdc_mem, hbm)

    N = 60
    t0 = time.perf_counter()
    for _ in range(N):
        gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, 0, 0, 0x00CC0020)
    t1 = time.perf_counter()
    gdi_ms = (t1 - t0) / N * 1000.0
    print(f"1. GDI Screen BitBlt (1080p):             {gdi_ms:6.3f} ms / frame ({1000.0/gdi_ms:5.1f} FPS)")

    # ------------------------------------------------------------------------
    # Stage 2: Ring Buffer ctypes.memmove
    # ------------------------------------------------------------------------
    dst_buf = np.zeros((height, width, 4), dtype=np.uint8)
    dst_ptr = dst_buf.ctypes.data
    t0 = time.perf_counter()
    for _ in range(N):
        ctypes.memmove(dst_ptr, p_bits.value, frame_bytes_raw)
    t1 = time.perf_counter()
    memmove_ms = (t1 - t0) / N * 1000.0
    print(f"2. Ring Buffer Direct Transfer:            {memmove_ms:6.3f} ms / frame ({1000.0/memmove_ms:5.1f} FPS)")

    # ------------------------------------------------------------------------
    # Stage 3: Color Conversion BGRA -> YUV420P
    # ------------------------------------------------------------------------
    if HAS_CV2:
        t0 = time.perf_counter()
        for _ in range(N):
            _yuv = cv2.cvtColor(dst_buf, cv2.COLOR_BGRA2YUV_I420)
        t1 = time.perf_counter()
        cv2_ms = (t1 - t0) / N * 1000.0
        print(f"3. SIMD Color Conversion (BGRA->YUV420P):  {cv2_ms:6.3f} ms / frame ({1000.0/cv2_ms:5.1f} FPS)")
    else:
        cv2_ms = 0.0
        print("3. OpenCV (cv2) not available.")

    # ------------------------------------------------------------------------
    # Stage 4: NVIDIA NVENC Hardware Encoder (RTX 4070)
    # ------------------------------------------------------------------------
    encoder = HybridEncoder(codec_type="h264_nvenc", width=width, height=height, fps=60, bitrate_kbps=12000)
    # Warmup 5 frames
    for _ in range(5):
        encoder.encode(dst_buf)

    t0 = time.perf_counter()
    for _ in range(N):
        payload = encoder.encode(dst_buf)
    t1 = time.perf_counter()
    enc_ms = (t1 - t0) / N * 1000.0
    avg_kb = len(payload) / 1024.0 if payload else 0.0
    print(f"4. NVENC H.264 RTX 4070 Hardware Encode:   {enc_ms:6.3f} ms / frame ({1000.0/enc_ms:5.1f} Max FPS, ~{avg_kb:.1f} KB/frame)")
    encoder.close()

    # ------------------------------------------------------------------------
    # Stage 5: Sustained End-to-End Live Pipeline Benchmark (3.0s)
    # ------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("5. Executando Teste de Transmissao ao Vivo End-to-End (3.0 segundos)...")

    TEST_PORT = 19124
    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32 * 1024 * 1024)
    recv_sock.bind(('127.0.0.1', TEST_PORT))
    recv_sock.settimeout(0.5)

    NUM_SLOTS = 3
    ring_slots = [np.zeros((height, width, 4), dtype=np.uint8) for _ in range(NUM_SLOTS)]
    ring_ptrs = [s.ctypes.data for s in ring_slots]

    enc_q = queue.Queue(maxsize=2)
    snd_q = queue.Queue(maxsize=4)
    stop_ev = threading.Event()

    rx_frames = [0]
    tx_frames = [0]

    def _bench_rx():
        decoder = HybridDecoder()
        pending = {}
        while not stop_ev.is_set():
            try:
                data, _ = recv_sock.recvfrom(65536)
            except Exception:
                continue
            if len(data) < 32:
                continue
            unpacked = struct.unpack('!BBBBIIQIIHH', data[:32])
            frame_id, plen, f_idx, f_tot = unpacked[7], unpacked[8], unpacked[9], unpacked[10]
            chunk = data[32:32 + plen]
            if frame_id not in pending:
                pending[frame_id] = [0, f_tot, [None] * f_tot]
            entry = pending[frame_id]
            if f_idx < f_tot and entry[2][f_idx] is None:
                entry[2][f_idx] = chunk
                entry[0] += 1
            if entry[0] == entry[1]:
                full = b"".join(entry[2])
                del pending[frame_id]
                frames = decoder.decode_all(full, width, height)
                for _ in frames:
                    rx_frames[0] += 1

    def _bench_cap():
        if k32 is not None:
            try:
                k32.SetThreadPriority(k32.GetCurrentThread(), 15)
            except Exception:
                pass
        slot_idx = 0
        t_next = time.perf_counter()
        interval = 1.0 / 60.0
        while not stop_ev.is_set():
            gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, 0, 0, 0x00CC0020)
            ctypes.memmove(ring_ptrs[slot_idx], p_bits.value, frame_bytes_raw)
            try:
                enc_q.put_nowait(slot_idx)
                slot_idx = (slot_idx + 1) % NUM_SLOTS
            except queue.Full:
                pass
            t_next += interval
            now = time.perf_counter()
            slack = t_next - now
            if slack > 0.002:
                time.sleep(slack - 0.001)
            while time.perf_counter() < t_next:
                pass
            if time.perf_counter() - t_next > interval:
                t_next = time.perf_counter()

    def _bench_enc():
        if k32 is not None:
            try:
                k32.SetThreadPriority(k32.GetCurrentThread(), 2)
            except Exception:
                pass
        enc = HybridEncoder(codec_type="h264_nvenc", width=width, height=height, fps=60, bitrate_kbps=12000)
        fid = 0
        while not stop_ev.is_set():
            try:
                s_idx = enc_q.get(timeout=0.1)
            except queue.Empty:
                continue
            fid += 1
            payload = enc.encode(ring_slots[s_idx])
            if payload:
                tx_frames[0] += 1
                try:
                    snd_q.put_nowait((payload, fid))
                except queue.Full:
                    pass
        enc.close()

    def _bench_snd():
        if k32 is not None:
            try:
                k32.SetThreadPriority(k32.GetCurrentThread(), 1)
            except Exception:
                pass
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 32 * 1024 * 1024)
        sock.setblocking(False)
        max_chunk = 1350
        while not stop_ev.is_set():
            try:
                payload, fid = snd_q.get(timeout=0.1)
            except queue.Empty:
                continue
            plen = len(payload)
            fcount = (plen + max_chunk - 1) // max_chunk
            ts = int(time.time_ns() // 1000)
            for i in range(fcount):
                start = i * max_chunk
                chunk = payload[start:min(start + max_chunk, plen)]
                hdr = struct.pack('!BBBBIIQIIHH', 1, 0, 0, 0, fid * 100 + i, 0xDA0001, ts, fid, len(chunk), i, fcount)
                sock.sendto(hdr + chunk + b"POL1305_AUTH_16B", ('127.0.0.1', TEST_PORT))
        sock.close()

    t_rx = threading.Thread(target=_bench_rx, daemon=True)
    t_cap = threading.Thread(target=_bench_cap, daemon=True)
    t_enc = threading.Thread(target=_bench_enc, daemon=True)
    t_snd = threading.Thread(target=_bench_snd, daemon=True)

    t_rx.start()
    t_cap.start()
    t_enc.start()
    t_snd.start()

    t_start = time.perf_counter()
    time.sleep(3.0)
    stop_ev.set()

    t_cap.join(0.5)
    t_enc.join(0.5)
    t_snd.join(0.5)
    t_rx.join(0.5)
    t_end = time.perf_counter()

    dur = t_end - t_start
    tx_fps = tx_frames[0] / dur
    rx_fps = rx_frames[0] / dur

    print(f"   Tempo Total de Teste:   {dur:.2f} s")
    print(f"   Quadros TX Enviados:    {tx_frames[0]} ({tx_fps:.2f} FPS)")
    print(f"   Quadros RX Decodificados: {rx_frames[0]} ({rx_fps:.2f} FPS)")

    passed = (tx_fps >= 58.0 and rx_fps >= 58.0)
    status_str = "APROVADO (60 FPS ESTAVEL)" if passed else "REPROVADO"
    print("=" * 70)
    print(f"   STATUS FINAL DO BENCHMARK: [{status_str}]")
    print("=" * 70)

    # Cleanup
    gdi32.DeleteObject(hbm)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)
    recv_sock.close()
    if sys.platform == "win32":
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass


if __name__ == "__main__":
    run_benchmark()
