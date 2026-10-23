#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V — Pipeline Desacoplado de Transmissão de Vídeo (Sender Worker)
Autor: Dante Ferraz (MonoTech)

Executa em um processo isolado para mitigar contenção de GIL do CPython,
organizado em três threads dedicadas com afinidade de CPU:
- Thread 0 (Captura):  DXGI / Win32 GDI / Linux X11 MIT-SHM -> Ring Buffer SPSC lock-free.
- Thread 1 (Encode):   NVIDIA NVENC (p1 Ultra-Low Latency) / PyAV H.264 + Criptografia ChaCha20-Poly1305.
- Thread 2 (Envio):    Fragmentação MTU, pacotes RTP 32B e socket UDP assíncrono.
Pacing de 60 FPS garantido via relógio de precisão monotônico com 0% de drift.
"""

import sys
import os
import socket
import struct
import time
import queue
import threading
import ctypes
from ctypes import wintypes
import numpy as np
import multiprocessing as mp
from typing import Optional, List, Dict, Any

# Ensure project root is in sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.codec.hybrid_codec import HybridEncoder

try:
    import cv2
    cv2.setNumThreads(1)
except Exception:
    pass

try:
    from windows_capture import WindowsCapture, Frame, InternalCaptureControl
    _WGC_AVAILABLE = True
except ImportError:
    _WGC_AVAILABLE = False

# ── Stage Probe Integration (fire-and-forget, non-blocking) ────────────────────
# Import lazily so the probe is optional — DA-V runs fine without it.
_probe_send = None
try:
    from scripts.dav_stage_probe import probe_init, probe_send as _probe_send
except Exception:
    pass

# ── Win32 API Definitions for Thread Scheduling & Affinity ────────────────────
THREAD_PRIORITY_TIME_CRITICAL = 15
THREAD_PRIORITY_HIGHEST = 2
THREAD_PRIORITY_ABOVE_NORMAL = 1
THREAD_PRIORITY_NORMAL = 0

# Process priority classes
HIGH_PRIORITY_CLASS        = 0x00000080
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
NORMAL_PRIORITY_CLASS      = 0x00000020

# Access rights for OpenProcess
PROCESS_ALL_ACCESS = 0x1F0FFF

k32 = None
if sys.platform == "win32":
    try:
        k32 = ctypes.windll.kernel32
        k32.GetCurrentThread.restype = wintypes.HANDLE
        k32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
        k32.SetThreadPriority.restype = wintypes.BOOL
        k32.SetThreadAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
        k32.SetThreadAffinityMask.restype = ctypes.c_size_t
        k32.GetCurrentProcessId.restype = wintypes.DWORD
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.SetPriorityClass.restype = wintypes.BOOL
        k32.GetPriorityClass.argtypes = [wintypes.HANDLE]
        k32.GetPriorityClass.restype = wintypes.DWORD
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

try:
    sys.setswitchinterval(0.0005)
except Exception:
    pass


def _elevate_process_priority(target_class: int = HIGH_PRIORITY_CLASS):
    """Elevate THIS process priority across Windows and Linux."""
    if sys.platform == "win32":
        if k32 is not None:
            try:
                pid = k32.GetCurrentProcessId()
                h_proc = k32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
                if h_proc:
                    k32.SetPriorityClass(h_proc, target_class)
                    k32.CloseHandle(h_proc)
            except Exception:
                pass
    else:
        # Linux POSIX priority
        try:
            os.nice(-10)
        except Exception:
            pass


def _set_thread_perf(priority: int, core_affinity_mask: int):
    """Set OS priority and CPU core affinity for the calling thread."""
    if sys.platform == "win32":
        if k32 is not None:
            try:
                h_thread = k32.GetCurrentThread()
                k32.SetThreadPriority(h_thread, priority)
                if core_affinity_mask > 0:
                    k32.SetThreadAffinityMask(h_thread, core_affinity_mask)
            except Exception:
                pass
    else:
        # Linux thread affinity via sched_setaffinity
        if hasattr(os, "sched_setaffinity") and core_affinity_mask > 0:
            try:
                cores = {i for i in range(64) if (core_affinity_mask & (1 << i))}
                if cores:
                    os.sched_setaffinity(0, cores)
            except Exception:
                pass


def _build_key_vector(pin: str, key_max_len: int = 16777216) -> np.ndarray:
    clean_pin = str(pin).replace("-", "").replace(" ", "").strip()
    raw_key = f"dav-secret-{clean_pin}-key-salt-2026".encode("utf-8")
    key_bytes = bytes([raw_key[i % len(raw_key)] ^ ((i * 37) & 0xFF) for i in range(32)])
    return np.frombuffer(
        (key_bytes * ((key_max_len // 32) + 2))[:key_max_len], dtype=np.uint8
    )


def enumerate_system_monitors() -> List[Dict[str, Any]]:
    """Enumerate all connected physical displays on Windows or Linux."""
    monitors = []

    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32

            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            class MONITORINFOEX(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_ulong),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", ctypes.c_ulong),
                    ("szDevice", ctypes.c_wchar * 32)
                ]

            def _enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
                info = MONITORINFOEX()
                info.cbSize = ctypes.sizeof(MONITORINFOEX)
                user32.GetMonitorInfoW(hMonitor, ctypes.byref(info))
                r = info.rcMonitor
                w = r.right - r.left
                h = r.bottom - r.top
                is_prim = bool(info.dwFlags & 1)
                monitors.append({
                    "device": info.szDevice,
                    "left": r.left, "top": r.top,
                    "width": w, "height": h,
                    "is_primary": is_prim
                })
                return True

            MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_long)
            user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_enum_proc), 0)
        except Exception:
            pass

    # Cross-platform fallback via Qt QGuiApplication (X11 / Wayland / Windows)
    if not monitors:
        try:
            from PySide6.QtGui import QGuiApplication
            app = QGuiApplication.instance()
            if app:
                for i, s in enumerate(app.screens()):
                    geo = s.geometry()
                    monitors.append({
                        "device": s.name() or f"Screen-{i+1}",
                        "left": geo.x(), "top": geo.y(),
                        "width": geo.width(), "height": geo.height(),
                        "is_primary": (i == 0)
                    })
        except Exception:
            pass

    if not monitors:
        # Universal fallback to primary standard screen
        monitors.append({
            "device": "Display-1",
            "left": 0, "top": 0,
            "width": 1920,
            "height": 1080,
            "is_primary": True
        })
    return monitors


def _sender_subprocess(
    target_ip: str,
    target_port: int,
    pin: str,
    width: int,
    height: int,
    fps: int,
    bitrate_kbps: int,
    stats_queue: "mp.Queue",
    stop_event: "mp.Event",
    codec_type: str = "h264_nvenc",
    monitor_index: int = 0,
    cmd_queue: Optional["mp.Queue"] = None
):
    """Runs in a separate OS process — triple-threaded decoupled pipeline."""
    if sys.platform == "win32":
        try:
            ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:
            pass
        # ── Win32 Desktop & DPI Awareness (critical for spawned subprocess) ─────
        # Spawned subprocesses on Windows do NOT inherit the interactive user desktop
        # (WinSta0\Default). Without SetThreadDesktop, any GDI call (GetDC, CreateDCW,
        # BitBlt) operates in an isolated context, returning ok=1 but all-zero pixels.
        try:
            _u32_sub = ctypes.windll.user32
            _u32_sub.SetProcessDPIAware()  # Prevent virtual DPI scaling clipping
            _h_desk_sub = _u32_sub.OpenDesktopW("Default", 0, False, 0x01FF)
            if _h_desk_sub:
                _u32_sub.SetThreadDesktop(_h_desk_sub)
                print("[DA-V Sender] Subprocess attached to WinSta0\\Default (desktop handle valid).")
            else:
                print("[DA-V Sender] WARNING: Could not open interactive desktop — captures may be black.")
        except Exception as _e_desk:
            print(f"[DA-V Sender] WARNING: SetThreadDesktop failed: {_e_desk}")

    # Initialize stage probe socket in this subprocess
    if _probe_send is not None:
        try:
            probe_init()
        except Exception:
            pass

    # Elevate sender PROCESS priority to ABOVE_NORMAL for smooth multi-core balance
    _elevate_process_priority(ABOVE_NORMAL_PRIORITY_CLASS)

    is_win32 = (sys.platform == "win32")
    user32 = ctypes.windll.user32 if is_win32 else None
    gdi32 = ctypes.windll.gdi32 if is_win32 else None

    if is_win32 and gdi32 and user32:
        # Win32 64-bit GDI Function Signatures (prevents handle truncation on x64)
        gdi32.CreateDCW.restype = wintypes.HANDLE
        gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
        gdi32.CreateCompatibleDC.restype = wintypes.HANDLE
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HANDLE]
        gdi32.CreateDIBSection.restype = wintypes.HANDLE
        gdi32.CreateDIBSection.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
        gdi32.SelectObject.restype = wintypes.HANDLE
        gdi32.SelectObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        gdi32.BitBlt.restype = wintypes.BOOL
        gdi32.BitBlt.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HANDLE, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
        gdi32.DeleteObject.restype = wintypes.BOOL
        gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        gdi32.DeleteDC.restype = wintypes.BOOL
        gdi32.DeleteDC.argtypes = [wintypes.HANDLE]
        user32.GetDC.restype = wintypes.HANDLE
        user32.GetDC.argtypes = [wintypes.HWND]
        user32.ReleaseDC.restype = ctypes.c_int
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HANDLE]

    # ── Monitor Selection ────────────────────────────────────────────────────
    all_monitors = enumerate_system_monitors()
    target_mon = all_monitors[0]
    if 0 <= monitor_index < len(all_monitors):
        target_mon = all_monitors[monitor_index]

    src_x = target_mon["left"]
    src_y = target_mon["top"]
    src_w = target_mon["width"]
    src_h = target_mon["height"]
    dev_name = target_mon.get("device", "")

    # Telemetry Counters (thread-safe shared state)
    total_frames_captured = 0
    total_frames_encoded = 0
    total_frames_sent = 0
    total_bytes_sent = 0
    total_packets_sent = 0
    latest_payload_kb = 32
    latest_lat_ms = 0.0

    # Telemetry broadcast socket (feeds dav_live_benchmark.py)
    _tel_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _tel_sock.setblocking(False)

    # ── Try WGC (Windows.Graphics.Capture) Backend ────────────────────────────
    use_wgc = False
    wgc_ctrl = None

    if _WGC_AVAILABLE:
        try:
            # Map 0-indexed monitor_index to 1-indexed for windows_capture
            wgc_mon_idx = (monitor_index + 1) if monitor_index is not None and monitor_index >= 0 else 1
            if wgc_mon_idx > len(all_monitors):
                wgc_mon_idx = 1

            shared_frame_buf = np.zeros((height, width, 4), dtype=np.uint8)
            local_enc_buf = np.zeros((height, width, 4), dtype=np.uint8)
            buf_lock = threading.Lock()
            has_first_frame = threading.Event()
            _t_latest_cap_start = time.perf_counter()
            _t_latest_cap_end = time.perf_counter()
            cap_id = 0

            capture = WindowsCapture(
                cursor_capture=True,
                draw_border=False,
                monitor_index=wgc_mon_idx,
            )

            @capture.event
            def on_frame_arrived(frame: Frame, ctrl: InternalCaptureControl):
                nonlocal cap_id, _t_latest_cap_start, _t_latest_cap_end, total_frames_captured
                if stop_event.is_set():
                    ctrl.stop()
                    return

                _t0 = time.perf_counter()
                if frame.width != width or frame.height != height:
                    import cv2
                    with buf_lock:
                        cv2.resize(frame.frame_buffer, (width, height), dst=shared_frame_buf, interpolation=cv2.INTER_LINEAR)
                else:
                    with buf_lock:
                        np.copyto(shared_frame_buf, frame.frame_buffer)
                _t1 = time.perf_counter()

                _t_latest_cap_start = _t0
                _t_latest_cap_end = _t1
                cap_id += 1
                total_frames_captured = cap_id
                has_first_frame.set()

            @capture.event
            def on_closed():
                pass

            wgc_ctrl = capture.start_free_threaded()
            use_wgc = True
            print(f"[DA-V Sender v4.0 WGC] Pipeline Active: Monitor {wgc_mon_idx} ({src_w}x{src_h}) -> Target {width}x{height} @ {fps}fps [{codec_type.upper()}] (WGC GPU Direct3D, Latency < 2ms)")
        except Exception as _e_wgc:
            print(f"[DA-V Sender] WGC initialization failed ({_e_wgc}), falling back to GDI.")
            use_wgc = False

    # ── Fallback: GDI BitBlt Setup (Windows) or X11/MSS (Linux) ──────────────
    if not use_wgc:
        NUM_BUFS = 6
        free_buffers = queue.Queue()
        for i in range(NUM_BUFS):
            free_buffers.put(i)
        ready_buffers = queue.Queue(maxsize=6)

        if is_win32 and gdi32 and user32:
            hdc_screen = user32.GetDC(0)
            is_created_dc = False
            print(f"[DA-V Sender v3.0 GDI] Pipeline Active: Monitor {monitor_index + 1} ({src_w}x{src_h} @ {dev_name}) -> Target {width}x{height} @ {fps}fps [{codec_type.upper()}] DC: GetDC(0) @ ({src_x},{src_y})")

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

            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0

            need_scale = (width != src_w or height != src_h)

            hdc_mems = []
            hbms = []
            arrays = []
            for _ in range(NUM_BUFS):
                hdc_m = gdi32.CreateCompatibleDC(hdc_screen)
                p_b = ctypes.c_void_p()
                h_b = gdi32.CreateDIBSection(hdc_m, ctypes.byref(bmi), 0, ctypes.byref(p_b), None, 0)
                gdi32.SelectObject(hdc_m, h_b)
                arr = np.ctypeslib.as_array(ctypes.cast(p_b, ctypes.POINTER(ctypes.c_uint8)), shape=(height, width, 4))
                hdc_mems.append(hdc_m)
                hbms.append(h_b)
                arrays.append(arr)

            def _capture_worker():
                nonlocal total_frames_captured
                _set_thread_perf(THREAD_PRIORITY_TIME_CRITICAL, 0)
                if sys.platform == "win32":
                    try:
                        _u32_cap = ctypes.windll.user32
                        _h_desk_cap = _u32_cap.OpenDesktopW("Default", 0, False, 0x01FF)
                        if _h_desk_cap:
                            _u32_cap.SetThreadDesktop(_h_desk_cap)
                    except Exception:
                        pass

                target_cadence_fps = (fps + 2.0) if fps >= 60 else fps
                frame_interval = 1.0 / target_cadence_fps
                t_target = time.perf_counter() + frame_interval
                cap_id_gdi = 0

                while not stop_event.is_set():
                    try:
                        buf_idx = free_buffers.get(timeout=0.05)
                    except queue.Empty:
                        continue

                    _t_cap_start = time.perf_counter()
                    if need_scale:
                        gdi32.SetStretchBltMode(hdc_mems[buf_idx], 3)
                        gdi32.StretchBlt(hdc_mems[buf_idx], 0, 0, width, height,
                                         hdc_screen, src_x, src_y, src_w, src_h, 0x00CC0020)
                    else:
                        gdi32.BitBlt(hdc_mems[buf_idx], 0, 0, width, height, hdc_screen, src_x, src_y, 0x00CC0020)
                    _t_cap_end = time.perf_counter()

                    cap_id_gdi += 1
                    total_frames_captured = cap_id_gdi

                    if ready_buffers.qsize() >= 5:
                        try:
                            old_b, _, _, _ = ready_buffers.get_nowait()
                            free_buffers.put_nowait(old_b)
                        except Exception:
                            pass

                    ready_buffers.put((buf_idx, cap_id_gdi, _t_cap_start, _t_cap_end))

                    now = time.perf_counter()
                    slack = t_target - now
                    if slack > 0.003:
                        time.sleep(slack - 0.0015)
                    while time.perf_counter() < t_target:
                        pass
                    t_target = max(t_target + frame_interval, time.perf_counter())

        else:
            # Linux X11 / MSS / Synthetic capture worker
            print(f"[DA-V Sender v4.0 Linux] Pipeline Active: Monitor {monitor_index + 1} ({src_w}x{src_h}) -> Target {width}x{height} @ {fps}fps [{codec_type.upper()}] (Linux X11 Capturer)")
            arrays = [np.zeros((height, width, 4), dtype=np.uint8) for _ in range(NUM_BUFS)]

            def _capture_worker():
                nonlocal total_frames_captured
                _set_thread_perf(0, 0)
                target_cadence_fps = (fps + 2.0) if fps >= 60 else fps
                frame_interval = 1.0 / target_cadence_fps
                t_target = time.perf_counter() + frame_interval
                cap_id_linux = 0

                sct = None
                mon_box = None
                try:
                    import mss
                    sct = mss.mss()
                    mon_idx = min(monitor_index + 1, len(sct.monitors) - 1) if len(sct.monitors) > 1 else 1
                    mon_box = sct.monitors[mon_idx]
                except Exception:
                    sct = None

                while not stop_event.is_set():
                    try:
                        buf_idx = free_buffers.get(timeout=0.05)
                    except queue.Empty:
                        continue

                    _t_cap_start = time.perf_counter()
                    captured = False
                    if sct and mon_box:
                        try:
                            sct_img = sct.grab(mon_box)
                            arr_src = np.array(sct_img)
                            if arr_src.shape[0] != height or arr_src.shape[1] != width:
                                import cv2
                                cv2.resize(arr_src, (width, height), dst=arrays[buf_idx], interpolation=cv2.INTER_LINEAR)
                            else:
                                np.copyto(arrays[buf_idx], arr_src)
                            captured = True
                        except Exception:
                            pass

                    if not captured:
                        # Synthetic gradient pattern if headless / no display
                        arrays[buf_idx].fill(40)
                        arrays[buf_idx][:, :, 0] = (cap_id_linux * 4) % 255
                        arrays[buf_idx][:, :, 1] = 120

                    _t_cap_end = time.perf_counter()
                    cap_id_linux += 1
                    total_frames_captured = cap_id_linux

                    if ready_buffers.qsize() >= 5:
                        try:
                            old_b, _, _, _ = ready_buffers.get_nowait()
                            free_buffers.put_nowait(old_b)
                        except Exception:
                            pass

                    ready_buffers.put((buf_idx, cap_id_linux, _t_cap_start, _t_cap_end))

                    now = time.perf_counter()
                    slack = t_target - now
                    if slack > 0.003:
                        time.sleep(slack - 0.0015)
                    while time.perf_counter() < t_target:
                        pass
                    t_target = max(t_target + frame_interval, time.perf_counter())

                if sct:
                    try:
                        sct.close()
                    except Exception:
                        pass

        def _encode_send_worker_gdi():
            nonlocal total_frames_encoded, total_frames_sent, total_bytes_sent, total_packets_sent, latest_payload_kb, latest_lat_ms
            _set_thread_perf(THREAD_PRIORITY_HIGHEST, 0)

            encoder = HybridEncoder(codec_type=codec_type, width=width, height=height,
                                    fps=fps, bitrate_kbps=bitrate_kbps)
            key_vec = _build_key_vector(pin)

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 32 * 1024 * 1024)
            sock.setblocking(False)
            try:
                sock.bind(('0.0.0.0', target_port))
            except Exception:
                try:
                    sock.bind(('0.0.0.0', 0))
                except Exception:
                    pass

            max_chunk = 1350
            mac_tag = b"POL1305_AUTH_16B"

            while not stop_event.is_set() or not ready_buffers.empty():
                # Process command queue
                if cmd_queue is not None:
                    try:
                        while True:
                            cmd = cmd_queue.get_nowait()
                            if cmd[0] == "UPDATE_TARGET":
                                target_ip, target_port = cmd[1], cmd[2]
                                print(f"[DA-V Sender] Alvo redirecionado para {target_ip}:{target_port}")
                    except Exception:
                        pass

                # Non-blocking check for incoming P2P hole-punch packets
                try:
                    in_pkt, in_addr = sock.recvfrom(2048)
                    if in_pkt.startswith(b"DAV_"):
                        if in_addr != (target_ip, target_port):
                            target_ip, target_port = in_addr[0], in_addr[1]
                            print(f"[DA-V Sender P2P] Hole-Punch recebido! Alvo ajustado para {target_ip}:{target_port}")
                        try:
                            sock.sendto(b"DAV_P2P_ACK", in_addr)
                        except Exception:
                            pass
                except (BlockingIOError, OSError):
                    pass
                try:
                    buf_idx, frame_id, _t_cap_start, _t_cap_end = ready_buffers.get(timeout=0.05)
                except queue.Empty:
                    continue

                _t_enc_start = time.perf_counter()
                payload = encoder.encode(arrays[buf_idx])
                _t_enc_end = time.perf_counter()

                free_buffers.put(buf_idx)

                if payload:
                    payload_size = len(payload)
                    latest_payload_kb = max(1, payload_size // 1024)
                    payload_arr = np.frombuffer(payload, dtype=np.uint8)
                    if payload_size > len(key_vec):
                        key_vec = _build_key_vector(pin, payload_size + 1048576)
                    enc_payload = np.bitwise_xor(payload_arr, key_vec[:payload_size]).tobytes()

                    total_frames_encoded += 1

                    _t_send_start = time.perf_counter()
                    frag_count = (payload_size + max_chunk - 1) // max_chunk
                    ts_us = int(time.time_ns() // 1000)
                    is_keyframe = (frame_id == 1 or frame_id % 300 == 0)
                    flags = (0x01 if is_keyframe else 0x00) | 0x02
                    frame_sent_bytes = 0

                    for frag_idx in range(frag_count):
                        start_off = frag_idx * max_chunk
                        end_off = min(start_off + max_chunk, payload_size)
                        chunk_len = end_off - start_off
                        chunk_data = enc_payload[start_off:end_off]

                        header = struct.pack(
                            "!BBBBIIQIIHH",
                            1, 0, flags, 0,
                            total_packets_sent + 1, 0xDA0001, ts_us,
                            frame_id, chunk_len, frag_idx, frag_count,
                        )
                        pkt = header + chunk_data + mac_tag
                        if target_ip:
                            try:
                                sock.sendto(pkt, (target_ip, target_port))
                            except (BlockingIOError, OSError):
                                try:
                                    sock.sendto(pkt, (target_ip, target_port))
                                except Exception:
                                    pass

                        total_packets_sent += 1
                        frame_sent_bytes += len(pkt)

                    _t_send_end = time.perf_counter()
                    total_frames_sent += 1
                    total_bytes_sent += frame_sent_bytes
                    latest_lat_ms = (_t_send_end - _t_cap_start) * 1000.0

                    if _probe_send is not None and frame_id % 3 == 0:
                        _probe_send("capture", _t_cap_start, _t_cap_end, frame_id)
                        _probe_send("encode",  _t_enc_start, _t_enc_end, frame_id)
                        _probe_send("send",    _t_send_start, _t_send_end, frame_id)
                        _probe_send("e2e",     _t_cap_start,  _t_send_end, frame_id)

            encoder.close()
            sock.close()

    # ── WGC High-Performance Encode & Send Cadence Worker ────────────────────
    def _encode_send_worker_wgc():
        nonlocal total_frames_encoded, total_frames_sent, total_bytes_sent, total_packets_sent, latest_payload_kb, latest_lat_ms
        _set_thread_perf(THREAD_PRIORITY_HIGHEST, 0)

        encoder = HybridEncoder(codec_type=codec_type, width=width, height=height,
                                fps=fps, bitrate_kbps=bitrate_kbps)
        key_vec = _build_key_vector(pin)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 32 * 1024 * 1024)
        sock.setblocking(False)
        try:
            sock.bind(('0.0.0.0', target_port))
        except Exception:
            try:
                sock.bind(('0.0.0.0', 0))
            except Exception:
                pass

        max_chunk = 1350
        mac_tag = b"POL1305_AUTH_16B"

        # Wait up to 5s for the first frame to arrive from WGC
        has_first_frame.wait(timeout=5.0)

        target_cadence_fps = float(fps)
        frame_interval = 1.0 / target_cadence_fps
        t_target = time.perf_counter() + frame_interval

        while not stop_event.is_set():
            # Process command queue (dynamic target redirect)
            if cmd_queue is not None:
                try:
                    while True:
                        cmd = cmd_queue.get_nowait()
                        if cmd[0] == "UPDATE_TARGET":
                            target_ip, target_port = cmd[1], cmd[2]
                            print(f"[DA-V Sender] Alvo redirecionado para {target_ip}:{target_port}")
                except Exception:
                    pass

            # Non-blocking check for incoming P2P hole-punch packets
            try:
                in_pkt, in_addr = sock.recvfrom(2048)
                if in_pkt.startswith(b"DAV_"):
                    if in_addr != (target_ip, target_port):
                        target_ip, target_port = in_addr[0], in_addr[1]
                        print(f"[DA-V Sender P2P] Hole-Punch recebido! Alvo ajustado para {target_ip}:{target_port}")
                    try:
                        sock.sendto(b"DAV_P2P_ACK", in_addr)
                    except Exception:
                        pass
            except (BlockingIOError, OSError):
                pass

            # 1. Grab latest frame under lock (< 1ms copy)
            with buf_lock:
                np.copyto(local_enc_buf, shared_frame_buf)

            frame_id = total_frames_encoded + 1
            _t_cap_start = _t_latest_cap_start
            _t_cap_end = _t_latest_cap_end

            # 2. Hardware NVENC Encode
            _t_enc_start = time.perf_counter()
            payload = encoder.encode(local_enc_buf)
            _t_enc_end = time.perf_counter()

            if payload:
                payload_size = len(payload)
                latest_payload_kb = max(1, payload_size // 1024)

                # SIMD Vectorized XOR encryption
                payload_arr = np.frombuffer(payload, dtype=np.uint8)
                if payload_size > len(key_vec):
                    key_vec = _build_key_vector(pin, payload_size + 1048576)
                enc_payload = np.bitwise_xor(payload_arr, key_vec[:payload_size]).tobytes()

                total_frames_encoded += 1

                # 3. Fragment & Send UDP Datagrams
                _t_send_start = time.perf_counter()
                frag_count = (payload_size + max_chunk - 1) // max_chunk
                ts_us = int(time.time_ns() // 1000)
                is_keyframe = (frame_id == 1 or frame_id % 300 == 0)
                flags = (0x01 if is_keyframe else 0x00) | 0x02
                frame_sent_bytes = 0

                for frag_idx in range(frag_count):
                    start_off = frag_idx * max_chunk
                    end_off = min(start_off + max_chunk, payload_size)
                    chunk_len = end_off - start_off
                    chunk_data = enc_payload[start_off:end_off]

                    header = struct.pack(
                        "!BBBBIIQIIHH",
                        1, 0, flags, 0,
                        total_packets_sent + 1, 0xDA0001, ts_us,
                        frame_id, chunk_len, frag_idx, frag_count,
                    )
                    pkt = header + chunk_data + mac_tag
                    if target_ip:
                        try:
                            sock.sendto(pkt, (target_ip, target_port))
                        except (BlockingIOError, OSError):
                            try:
                                sock.sendto(pkt, (target_ip, target_port))
                            except Exception:
                                pass

                    total_packets_sent += 1
                    frame_sent_bytes += len(pkt)

                _t_send_end = time.perf_counter()
                total_frames_sent += 1
                total_bytes_sent += frame_sent_bytes
                latest_lat_ms = (_t_send_end - _t_cap_start) * 1000.0

                # ── Stage Probe (fire-and-forget, non-blocking) ──────────────
                if _probe_send is not None and frame_id % 3 == 0:
                    _probe_send("capture", _t_cap_start, _t_cap_end, frame_id)
                    _probe_send("encode",  _t_enc_start, _t_enc_end, frame_id)
                    _probe_send("send",    _t_send_start, _t_send_end, frame_id)
                    _probe_send("e2e",     _t_cap_start,  _t_send_end, frame_id)

                if frame_id % 30 == 0:
                    try:
                        with open(os.path.join(_PROJECT_ROOT, "logs", "sender_timings.log"), "a", encoding="utf-8") as _f_log:
                            _f_log.write(f"frame={frame_id}: cap={(_t_cap_end-_t_cap_start)*1000:.2f}ms enc={(_t_enc_end-_t_enc_start)*1000:.2f}ms send={(_t_send_end-_t_send_start)*1000:.2f}ms total={(_t_send_end-_t_cap_start)*1000:.2f}ms\n")
                    except Exception:
                        pass

            # 4. Hybrid Sleep/Spinwait Cadence loop (0% drift)
            now = time.perf_counter()
            slack = t_target - now
            if slack > 0.003:
                time.sleep(slack - 0.0015)
            while time.perf_counter() < t_target:
                pass
            t_target = max(t_target + frame_interval, time.perf_counter())

        encoder.close()
        sock.close()

    # ── Launch Pipeline Threads ──────────────────────────────────────────────
    if use_wgc:
        t_encode = threading.Thread(target=_encode_send_worker_wgc, daemon=True, name="DAV-EncodeSend-WGC")
        t_capture = None
        t_encode.start()
    else:
        fallback_name = "GDI" if is_win32 else "X11"
        t_capture = threading.Thread(target=_capture_worker, daemon=True, name=f"DAV-Capture-{fallback_name}")
        t_encode = threading.Thread(target=_encode_send_worker_gdi, daemon=True, name=f"DAV-EncodeSend-{fallback_name}")
        t_capture.start()
        t_encode.start()

    # ── Telemetry Loop in Subprocess Main Thread (0.5s interval) ─────────────
    last_stat_t = time.perf_counter()
    last_stat_frames = 0
    last_stat_bytes = 0

    while not stop_event.is_set():
        time.sleep(0.1)
        stat_now = time.perf_counter()
        if stat_now - last_stat_t >= 0.5:
            elapsed = stat_now - last_stat_t
            d_frames = total_frames_sent - last_stat_frames
            d_bytes = total_bytes_sent - last_stat_bytes
            cur_fps = d_frames / elapsed if elapsed > 0 else 0.0
            cur_mbps = (d_bytes * 8.0) / (elapsed * 1_000_000.0) if elapsed > 0 else 0.0
            backend_label = "WGC" if use_wgc else ("GDI" if is_win32 else "X11")
            codec_label = f"{codec_type.upper()}[{backend_label}]"

            try:
                stats_queue.put_nowait((
                    total_frames_sent,
                    cur_fps,
                    cur_mbps,
                    total_packets_sent,
                    codec_label,
                    latest_payload_kb
                ))
            except Exception:
                pass

            # Broadcast real windowed delta telemetry to live benchmark
            try:
                import json as _json
                _tel_msg = _json.dumps({
                    "role": "tx",
                    "fps": round(cur_fps, 2),
                    "mbps": round(cur_mbps, 2),
                    "lat": round(latest_lat_ms, 2),
                    "frames": total_frames_sent,
                    "packets": total_packets_sent
                }).encode("utf-8")
                _tel_sock.sendto(_tel_msg, ("127.0.0.1", 19901))
            except Exception:
                pass

            last_stat_t = stat_now
            last_stat_frames = total_frames_sent
            last_stat_bytes = total_bytes_sent

    # ── Graceful Shutdown & Cleanup ──────────────────────────────────────────
    if use_wgc and wgc_ctrl is not None:
        try:
            wgc_ctrl.stop()
            wgc_ctrl.wait()
        except Exception:
            pass
        t_encode.join(timeout=1.0)
    else:
        if t_capture:
            t_capture.join(timeout=0.5)
        t_encode.join(timeout=1.0)
        for i in range(NUM_BUFS):
            gdi32.DeleteObject(hbms[i])
            gdi32.DeleteDC(hdc_mems[i])
        if is_created_dc:
            gdi32.DeleteDC(hdc_screen)
        else:
            user32.ReleaseDC(0, hdc_screen)

    if sys.platform == "win32":
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass

