# -*- coding: utf-8 -*-
"""
Host de Transmissao em Subprocesso Isolado (GIL-Free Sender) — DA-V v4.6
Autor: Dante Ferraz (MonoTech)

Reside integralmente dentro da fatia `src.dav.modules.stream_engine`, consumindo
apenas as fatias `capture`, `codec`, `transport_p2p`, `audio` e `telemetry`.
"""

from __future__ import annotations

import ctypes
import json
import multiprocessing as mp
import os
import queue
import select
import socket
import sys
import threading
import time
from ctypes import wintypes
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.dav.modules.audio.capturer import create_audio_capturer
from src.dav.modules.audio.codec_opus import OpusAudioEncoder
from src.dav.modules.capture.service import enumerate_system_monitors
from src.dav.modules.capture.wayland_portal import WaylandPortalCapturer, is_wayland_session
from src.dav.modules.codec.encoder import VideoEncoder
from src.dav.modules.telemetry.stage_probe import probe_init, probe_send as _probe_send
from src.dav.modules.transport_p2p.blind_relay import normalize_pin, wrap_relay_packet
from src.dav.modules.transport_p2p.candidates import is_lan_address
from src.dav.modules.transport_p2p.data_plane import DataPlaneSender
from src.dav.modules.transport_p2p.packetizer import MAGIC_ACK, MAGIC_PLI, MAGIC_SYN
from src.dav.modules.transport_p2p.service import disable_win_udp_connreset
from src.dav.modules.transport_p2p.signaling_client import (
    build_peer_candidates,
    discover_socket_endpoint,
    send_stun_keepalive,
)

try:
    import cv2
    cv2.setNumThreads(1)
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

try:
    from windows_capture import Frame, InternalCaptureControl, WindowsCapture
    _WGC_AVAILABLE = True
except ImportError:
    _WGC_AVAILABLE = False

THREAD_PRIORITY_TIME_CRITICAL = 15
THREAD_PRIORITY_HIGHEST = 2
HIGH_PRIORITY_CLASS = 0x00000080
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
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
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass


def _elevate_process_priority(target_class: int = HIGH_PRIORITY_CLASS) -> None:
    if sys.platform == "win32" and k32 is not None:
        try:
            pid = k32.GetCurrentProcessId()
            h_proc = k32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
            if h_proc:
                k32.SetPriorityClass(h_proc, target_class)
                k32.CloseHandle(h_proc)
        except Exception:
            pass
    else:
        try:
            os.nice(-10)
        except Exception:
            pass


def _set_thread_perf(priority: int, core_affinity_mask: int) -> None:
    if sys.platform == "win32" and k32 is not None:
        try:
            h_thread = k32.GetCurrentThread()
            k32.SetThreadPriority(h_thread, priority)
            if core_affinity_mask > 0:
                k32.SetThreadAffinityMask(h_thread, core_affinity_mask)
        except Exception:
            pass
    elif hasattr(os, "sched_setaffinity") and core_affinity_mask > 0:
        try:
            cores = {i for i in range(64) if (core_affinity_mask & (1 << i))}
            if cores:
                os.sched_setaffinity(0, cores)
        except Exception:
            pass


class SenderTransportEndpoint:
    """
    Gerencia o descritor unico de socket UDP do Transmissor sobre o DataPlaneSender v4.6:
    - Realiza descoberta STUN RFC 5389 Single-Socket antes do loop nao-bloqueante.
    - Conduz Hole-Punching autenticado via PAKE (CPace-X25519) com forward secrecy.
    - Suporta fallback automatico para Blind Encrypted UDP Relay ('DAV_RLY1').
    - Recebe feedbacks SQP (gradiente OWD e perda) + pedidos PLI em tempo real.
    """

    def __init__(
        self,
        bind_port: int,
        initial_target_ip: str,
        initial_target_port: int,
        pin: str,
        is_streaming_active: threading.Event,
        cmd_queue: Optional["mp.Queue"] = None,
        evt_queue: Optional["mp.Queue"] = None,
        bitrate_kbps: int = 12000,
        fps: int = 60,
        audio_muted_evt: Optional[threading.Event] = None,
    ):
        self.clean_pin = normalize_pin(pin)
        self.target_ip = str(initial_target_ip or "").strip()
        self.target_port = int(initial_target_port or bind_port or 9000)
        self._target_ep: Optional[Tuple[str, int]] = (
            (self.target_ip, self.target_port) if self.target_ip else None
        )
        self.is_streaming_active = is_streaming_active
        self.cmd_queue = cmd_queue
        self.evt_queue = evt_queue
        self.audio_muted_evt = audio_muted_evt

        self.candidates: List[Tuple[str, int, str]] = []
        self.relay_addr: Optional[Tuple[str, int]] = None
        self.use_relay = False
        self.punch_locked = False
        self.punch_started_at = time.monotonic() if self.target_ip else 0.0
        self.last_punch_sent = 0.0
        self.last_lan_upgrade_sent = 0.0
        self.last_relay_bind = 0.0
        self.last_keepalive = time.monotonic()
        self._ctrl_lock = threading.Lock()
        self._active_encoder: Optional[VideoEncoder] = None

        self.dp = DataPlaneSender(
            pin=pin,
            send_raw_fn=self.send_datagram,
            initial_bitrate_kbps=bitrate_kbps,
            fps=fps,
        )

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 32 * 1024 * 1024)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        disable_win_udp_connreset(self.sock)

        desired_bind = int(bind_port or 9000)
        try:
            self.sock.bind(("0.0.0.0", desired_bind))
        except Exception:
            self.sock.bind(("0.0.0.0", 0))

        self.bound_port = int(self.sock.getsockname()[1])

        if self.evt_queue is not None and not self.target_ip:
            ep_info = discover_socket_endpoint(self.sock)
            try:
                self.evt_queue.put_nowait(("ENDPOINT_READY", ep_info))
            except Exception:
                pass
            print(
                f"[Sender P2P] Socket UDP vinculado em 0.0.0.0:{self.bound_port} "
                f"| STUN Publico: {ep_info.get('public_ip')}:{ep_info.get('public_port')} ({ep_info.get('nat_type')})"
            )
        else:
            print(f"[Sender] Socket UDP ativo na porta local {self.bound_port}.")
            if self.evt_queue is not None:
                try:
                    self.evt_queue.put_nowait((
                        "ENDPOINT_READY",
                        {"local_port": self.bound_port, "public_port": self.bound_port, "nat_type": "direct"},
                    ))
                except Exception:
                    pass

        self.sock.setblocking(False)

    def _emit_event(self, payload: tuple):
        if self.evt_queue is not None:
            try:
                self.evt_queue.put_nowait(payload)
            except Exception:
                pass

    def _send_punch_burst(self):
        syn_pkt = self.dp.build_pake_syn()
        for ip, port, _ in self.candidates:
            try:
                self.sock.sendto(syn_pkt, (ip, port))
            except Exception:
                pass
        if self.target_ip and not self.use_relay:
            try:
                self.sock.sendto(syn_pkt, (self.target_ip, self.target_port))
            except Exception:
                pass
        if self.use_relay and self.relay_addr:
            try:
                self.sock.sendto(wrap_relay_packet(self.clean_pin, b"S", syn_pkt), self.relay_addr)
            except Exception:
                pass
        self.last_punch_sent = time.monotonic()

    def _send_lan_upgrade_probe(self):
        syn_pkt = self.dp.build_pake_syn()
        for ip, port, _ in self.candidates:
            if self._is_lan_addr(ip) or str(ip).startswith("100."):
                try:
                    self.sock.sendto(syn_pkt, (ip, port))
                except Exception:
                    pass
        self.last_lan_upgrade_sent = time.monotonic()

    @staticmethod
    def _is_lan_addr(ip_str: str) -> bool:
        return is_lan_address(ip_str)

    def poll_control(self, encoder: Optional[VideoEncoder] = None):
        """Processa comandos IPC, handshake PAKE, feedbacks SQP, PLI e timers STUN."""
        if encoder is not None:
            self._active_encoder = encoder
        if not self._ctrl_lock.acquire(blocking=False):
            return
        try:
            self._poll_control_unlocked(encoder or self._active_encoder)
        finally:
            self._ctrl_lock.release()

    def _poll_control_unlocked(self, encoder: Optional[VideoEncoder] = None):
        if self.cmd_queue is not None:
            while True:
                try:
                    cmd = self.cmd_queue.get_nowait()
                except Exception:
                    break
                action = cmd[0]
                if action in ("UPDATE_TARGET", "START_STREAM"):
                    tip = str(cmd[1]).strip()
                    tport = int(cmd[2])
                    self.target_ip = tip
                    self.target_port = tport
                    self._target_ep = (tip, tport) if tip else None
                    self.use_relay = False
                    self.punch_locked = False
                    self.punch_started_at = time.monotonic()
                    if tip:
                        self.is_streaming_active.set()
                        self._send_punch_burst()
                        print(f"[Sender] Destino direto configurado para {tip}:{tport}")
                elif action == "PAIR_PEER":
                    peer_dict = cmd[1] if len(cmd) > 1 and isinstance(cmd[1], dict) else {}
                    my_pub_ip = cmd[2] if len(cmd) > 2 else None
                    relay_dict = cmd[3] if len(cmd) > 3 and isinstance(cmd[3], dict) else peer_dict.get("_relay")
                    self.candidates = build_peer_candidates(peer_dict, my_public_ip=my_pub_ip)
                    if relay_dict and relay_dict.get("host") and relay_dict.get("port"):
                        self.relay_addr = (str(relay_dict["host"]), int(relay_dict["port"]))
                    self.use_relay = False
                    self.punch_locked = False
                    self.punch_started_at = time.monotonic()
                    self.last_relay_bind = 0.0
                    self._send_punch_burst()
                    print(f"[Sender P2P] Hole-Punching PAKE concorrente para candidatos: {self.candidates}")
                elif action in ("REQUEST_KEYFRAME", "request_idr"):
                    if encoder is not None:
                        encoder.request_keyframe()
                elif action in ("PAUSE_STREAM", "STOP_STREAM"):
                    self.is_streaming_active.clear()
                    self.candidates.clear()
                    self._target_ep = None
                    self.target_ip = ""
                    self.use_relay = False
                    self.punch_locked = False
                    print("[Sender] Transmissao em Standby (0% captura/encode).")
                elif action == "AUDIO_MUTE" and self.audio_muted_evt is not None:
                    if bool(cmd[1]):
                        self.audio_muted_evt.set()
                    else:
                        self.audio_muted_evt.clear()

        while True:
            try:
                in_pkt, in_addr = self.sock.recvfrom(4096)
            except (BlockingIOError, OSError):
                break

            if not in_pkt:
                continue

            evt, reply_ack = self.dp.handle_incoming_packet(in_pkt)
            if evt in ("pake_confirmed", "pake_ack"):
                from_relay = bool(self.relay_addr and in_addr == self.relay_addr)
                should_switch = (
                    not self.punch_locked
                    or (self.use_relay and not from_relay)
                    or (not from_relay and not self._is_lan_addr(self.target_ip) and self._is_lan_addr(in_addr[0]))
                )
                if should_switch and not from_relay:
                    new_ip, new_port = in_addr[0], int(in_addr[1])
                    self._target_ep = (new_ip, new_port)
                    self.target_ip, self.target_port = new_ip, new_port
                    self.punch_locked = True
                    self.use_relay = False
                    self.is_streaming_active.set()
                    mode_tag = "LAN Direto" if self._is_lan_addr(new_ip) else "WAN P2P Direto"
                    print(f"[Sender PAKE] Tunel autenticado ({mode_tag}) -> {new_ip}:{new_port}")
                    self._emit_event(("P2P_LOCKED", new_ip, new_port, mode_tag))
                elif from_relay and not self.punch_locked:
                    self.use_relay = True
                    self.punch_locked = True
                    self.is_streaming_active.set()

                if reply_ack is not None:
                    try:
                        if from_relay and self.relay_addr:
                            self.sock.sendto(wrap_relay_packet(self.clean_pin, b"S", reply_ack), self.relay_addr)
                        else:
                            self.sock.sendto(reply_ack, in_addr)
                    except Exception:
                        pass

                if evt == "pake_confirmed" and encoder is not None:
                    encoder.request_keyframe()
                continue
            elif evt == "sqp_ack":
                continue

            if in_pkt.startswith(MAGIC_PLI):
                if encoder is not None:
                    encoder.request_keyframe()
            elif in_pkt in (b"DAV_RLY_ACK", b"DAV_RLY_PEER_READY"):
                if (not self.punch_locked or not self.dp.pake.confirmed) and self.relay_addr:
                    was_relay = self.use_relay
                    self.use_relay = True
                    self.is_streaming_active.set()
                    self._send_punch_burst()
                    if not was_relay:
                        print(f"[Sender P2P] Blind Encrypted UDP Relay ativo via {self.relay_addr[0]}:{self.relay_addr[1]}")
                        self._emit_event(("P2P_LOCKED", self.relay_addr[0], self.relay_addr[1], "Blind Relay UDP"))
            elif in_pkt.startswith(MAGIC_SYN) or in_pkt.startswith(MAGIC_ACK):
                try:
                    if self.relay_addr and in_addr == self.relay_addr:
                        self.sock.sendto(wrap_relay_packet(self.clean_pin, b"S", self.dp.build_pake_syn()), self.relay_addr)
                    else:
                        self.sock.sendto(self.dp.build_pake_syn(), in_addr)
                except Exception:
                    pass

        now = time.monotonic()
        if not self.dp.pake.confirmed:
            if (self.candidates or self.target_ip or self.use_relay) and (now - self.last_punch_sent >= 0.045):
                self._send_punch_burst()

            if self.candidates and not self.punch_locked:
                elapsed_punch = now - self.punch_started_at
                if elapsed_punch >= 0.85 and self.relay_addr and not self.use_relay and (now - self.last_relay_bind >= 0.3):
                    try:
                        self.sock.sendto(wrap_relay_packet(self.clean_pin, b"S", b"BIND"), self.relay_addr)
                    except Exception:
                        pass
                    self.last_relay_bind = now
                if elapsed_punch >= 1.6 and not self.target_ip:
                    best_ip, best_port, best_mode = self.candidates[0]
                    self._target_ep = (best_ip, int(best_port))
                    self.target_ip, self.target_port = best_ip, best_port
                    self.is_streaming_active.set()
                    print(f"[Sender P2P] Sondando rota primaria PAKE ({best_mode}) para {best_ip}:{best_port}")
        elif (
            self.dp.pake.confirmed
            and self.candidates
            and self.punch_started_at > 0.0
            and (now - self.punch_started_at <= 6.0)
            and (self.use_relay or not self._is_lan_addr(self.target_ip))
            and (now - self.last_lan_upgrade_sent >= 0.20)
        ):
            self._send_lan_upgrade_probe()
        elif not self.is_streaming_active.is_set() and (now - self.last_keepalive >= 15.0):
            send_stun_keepalive(self.sock)
            self.last_keepalive = now

    def send_datagram(self, pkt: bytes):
        use_rly = self.use_relay
        rly = self.relay_addr
        if use_rly and rly:
            wrapped = wrap_relay_packet(self.clean_pin, b"S", pkt)
            try:
                self.sock.sendto(wrapped, rly)
            except (BlockingIOError, OSError):
                pass
            return

        ep = self._target_ep
        if ep:
            try:
                self.sock.sendto(pkt, ep)
            except (BlockingIOError, OSError):
                try:
                    self.sock.sendto(pkt, ep)
                except Exception:
                    pass

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def run_sender_subprocess(
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
    cmd_queue: Optional["mp.Queue"] = None,
    evt_queue: Optional["mp.Queue"] = None,
    bind_port: Optional[int] = None,
    audio_enabled: bool = True,
):
    """Subprocesso dedicado de captura, compressao e envio UDP a 60 FPS."""
    if sys.platform == "win32":
        try:
            ctypes.windll.winmm.timeBeginPeriod(1)
        except Exception:
            pass
        try:
            _u32_sub = ctypes.windll.user32
            _u32_sub.SetProcessDPIAware()
            _h_desk_sub = _u32_sub.OpenDesktopW("Default", 0, False, 0x01FF)
            if _h_desk_sub:
                _u32_sub.SetThreadDesktop(_h_desk_sub)
        except Exception:
            pass

    try:
        probe_init()
    except Exception:
        pass

    _elevate_process_priority(ABOVE_NORMAL_PRIORITY_CLASS)

    is_win32 = sys.platform == "win32"
    user32 = ctypes.windll.user32 if is_win32 else None
    gdi32 = ctypes.windll.gdi32 if is_win32 else None

    if is_win32 and gdi32 and user32:
        gdi32.CreateDCW.restype = wintypes.HANDLE
        gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
        gdi32.CreateCompatibleDC.restype = wintypes.HANDLE
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HANDLE]
        gdi32.CreateDIBSection.restype = wintypes.HANDLE
        gdi32.CreateDIBSection.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
        ]
        gdi32.SelectObject.restype = wintypes.HANDLE
        gdi32.SelectObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        gdi32.BitBlt.restype = wintypes.BOOL
        gdi32.BitBlt.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HANDLE, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
        ]
        gdi32.DeleteObject.restype = wintypes.BOOL
        gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        gdi32.DeleteDC.restype = wintypes.BOOL
        gdi32.DeleteDC.argtypes = [wintypes.HANDLE]
        user32.GetDC.restype = wintypes.HANDLE
        user32.GetDC.argtypes = [wintypes.HWND]
        user32.ReleaseDC.restype = ctypes.c_int
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HANDLE]

    all_monitors = enumerate_system_monitors()
    target_mon = all_monitors[monitor_index] if 0 <= monitor_index < len(all_monitors) else all_monitors[0]
    src_x, src_y = target_mon["left"], target_mon["top"]
    src_w, src_h = target_mon["width"], target_mon["height"]

    total_frames_captured = 0
    total_frames_encoded = 0
    total_frames_sent = 0
    total_bytes_sent = 0
    total_packets_sent = 0
    latest_payload_kb = 32
    latest_lat_ms = 0.0
    active_codec_tag = codec_type.upper()

    is_streaming_active = threading.Event()
    if target_ip and str(target_ip).strip():
        is_streaming_active.set()
    audio_muted_evt = threading.Event()
    if not audio_enabled:
        audio_muted_evt.set()

    effective_bind_port = int(bind_port if bind_port is not None else (target_port or 9000))

    transport = SenderTransportEndpoint(
        bind_port=effective_bind_port,
        initial_target_ip=target_ip,
        initial_target_port=target_port,
        pin=pin,
        is_streaming_active=is_streaming_active,
        cmd_queue=cmd_queue,
        evt_queue=evt_queue,
        bitrate_kbps=bitrate_kbps,
        fps=fps,
        audio_muted_evt=audio_muted_evt,
    )

    _tel_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _tel_sock.setblocking(False)
    disable_win_udp_connreset(_tel_sock)

    use_wgc = False
    wgc_ctrl = None

    if _WGC_AVAILABLE and is_win32 and os.environ.get("DAV_HEADLESS_SYNTHETIC") != "1":
        try:
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
                    if _HAS_CV2:
                        with buf_lock:
                            cv2.resize(
                                frame.frame_buffer, (width, height),
                                dst=shared_frame_buf, interpolation=cv2.INTER_LINEAR,
                            )
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
            print(f"[Sender WGC] Captura Direct3D ativa no Monitor {wgc_mon_idx} ({src_w}x{src_h} -> {width}x{height} @ {fps} FPS).")
        except Exception as wgc_err:
            print(f"[Sender] WGC indisponivel ({wgc_err}); alternando para captura de contingencia.")
            use_wgc = False

    hdc_screen = None
    hdc_mems: list = []
    hbms: list = []
    NUM_BUFS = 6

    if not use_wgc:
        free_buffers: "queue.Queue[int]" = queue.Queue()
        for i in range(NUM_BUFS):
            free_buffers.put(i)
        ready_buffers: "queue.Queue[Tuple[int, int, float, float]]" = queue.Queue(maxsize=NUM_BUFS)

        if is_win32 and gdi32 and user32 and os.environ.get("DAV_HEADLESS_SYNTHETIC") != "1":
            hdc_screen = user32.GetDC(0)

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
            arrays = []
            for _ in range(NUM_BUFS):
                hdc_m = gdi32.CreateCompatibleDC(hdc_screen)
                p_b = ctypes.c_void_p()
                h_b = gdi32.CreateDIBSection(hdc_m, ctypes.byref(bmi), 0, ctypes.byref(p_b), None, 0)
                gdi32.SelectObject(hdc_m, h_b)
                arr = np.ctypeslib.as_array(
                    ctypes.cast(p_b, ctypes.POINTER(ctypes.c_uint8)), shape=(height, width, 4)
                )
                hdc_mems.append(hdc_m)
                hbms.append(h_b)
                arrays.append(arr)

            def _capture_worker():
                nonlocal total_frames_captured
                _set_thread_perf(THREAD_PRIORITY_TIME_CRITICAL, 0)
                try:
                    _u32_cap = ctypes.windll.user32
                    _h_desk_cap = _u32_cap.OpenDesktopW("Default", 0, False, 0x01FF)
                    if _h_desk_cap:
                        _u32_cap.SetThreadDesktop(_h_desk_cap)
                except Exception:
                    pass

                target_cadence_fps = (fps + 2.0) if fps >= 60 else float(fps)
                frame_interval = 1.0 / target_cadence_fps
                t_target = time.perf_counter() + frame_interval
                cap_id_gdi = 0

                while not stop_event.is_set():
                    if not is_streaming_active.is_set():
                        time.sleep(0.03)
                        t_target = time.perf_counter() + frame_interval
                        continue

                    try:
                        buf_idx = free_buffers.get(timeout=0.05)
                    except queue.Empty:
                        continue

                    _t_cap_start = time.perf_counter()
                    if need_scale:
                        gdi32.SetStretchBltMode(hdc_mems[buf_idx], 3)
                        gdi32.StretchBlt(
                            hdc_mems[buf_idx], 0, 0, width, height,
                            hdc_screen, src_x, src_y, src_w, src_h, 0x00CC0020,
                        )
                    else:
                        gdi32.BitBlt(
                            hdc_mems[buf_idx], 0, 0, width, height,
                            hdc_screen, src_x, src_y, 0x00CC0020,
                        )
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
            arrays = [np.zeros((height, width, 4), dtype=np.uint8) for _ in range(NUM_BUFS)]

            def _capture_worker():
                nonlocal total_frames_captured
                _set_thread_perf(0, 0)
                target_cadence_fps = (fps + 2.0) if fps >= 60 else float(fps)
                frame_interval = 1.0 / target_cadence_fps
                t_target = time.perf_counter() + frame_interval
                cap_id_linux = 0

                portal_cap = None
                sct = None
                mon_box = None
                cached_src_shape = None
                cached_y_idx = None
                cached_x_idx = None
                consecutive_black_mss = 0
                tried_portal_fallback = False

                is_synthetic = os.environ.get("DAV_HEADLESS_SYNTHETIC") == "1"

                if not is_synthetic:
                    if is_wayland_session():
                        tried_portal_fallback = True
                        if evt_queue is not None:
                            evt_queue.put((
                                "log",
                                "INFO",
                                "[Wayland] Sessao Wayland detectada — aguardando autorizacao no portal PipeWire...",
                            ))
                        candidate = WaylandPortalCapturer(width=width, height=height, fps=fps)
                        if candidate.start(wait_first_frame_timeout=60.0):
                            portal_cap = candidate
                            if cmd_queue is not None:
                                cmd_queue.put(("request_idr",))
                            if evt_queue is not None:
                                evt_queue.put((
                                    "log",
                                    "SUCCESS",
                                    f"[Wayland] Captura PipeWire ativa em {width}x{height} @ {fps} FPS.",
                                ))
                        else:
                            if evt_queue is not None:
                                evt_queue.put((
                                    "log",
                                    "WARN",
                                    f"[Wayland] Portal PipeWire indisponivel ({candidate.last_error}). Tentando fallback X11/MSS...",
                                ))

                    if portal_cap is None:
                        try:
                            import mss
                            sct = mss.mss()
                            mon_idx = min(monitor_index + 1, len(sct.monitors) - 1) if len(sct.monitors) > 1 else 1
                            mon_box = sct.monitors[mon_idx]
                        except Exception:
                            sct = None

                while not stop_event.is_set():
                    if not is_streaming_active.is_set():
                        time.sleep(0.03)
                        t_target = time.perf_counter() + frame_interval
                        continue

                    try:
                        buf_idx = free_buffers.get(timeout=0.05)
                    except queue.Empty:
                        continue

                    _t_cap_start = time.perf_counter()
                    captured = False

                    if portal_cap is not None:
                        captured = portal_cap.grab_into(arrays[buf_idx])
                    elif sct and mon_box:
                        try:
                            sct_img = sct.grab(mon_box)
                            arr_src = np.asarray(sct_img, dtype=np.uint8)
                            if arr_src.shape[0] != height or arr_src.shape[1] != width:
                                if _HAS_CV2:
                                    cv2.resize(
                                        arr_src,
                                        (width, height),
                                        dst=arrays[buf_idx],
                                        interpolation=cv2.INTER_NEAREST,
                                    )
                                else:
                                    if cached_src_shape != arr_src.shape[:2]:
                                        cached_src_shape = arr_src.shape[:2]
                                        cached_y_idx = np.linspace(0, arr_src.shape[0] - 1, height).astype(np.intp)
                                        cached_x_idx = np.linspace(0, arr_src.shape[1] - 1, width).astype(np.intp)
                                    np.copyto(arrays[buf_idx], arr_src[cached_y_idx][:, cached_x_idx])
                            else:
                                np.copyto(arrays[buf_idx], arr_src)
                            captured = True

                            if not tried_portal_fallback and cap_id_linux < 12:
                                if not np.any(arrays[buf_idx][::16, ::16, :3]):
                                    consecutive_black_mss += 1
                                    if consecutive_black_mss >= 8:
                                        tried_portal_fallback = True
                                        if evt_queue is not None:
                                            evt_queue.put((
                                                "log",
                                                "WARN",
                                                "[Captura Linux] XWayland bloqueou leitura X11. Migrando para PipeWire Portal...",
                                            ))
                                        candidate = WaylandPortalCapturer(width=width, height=height, fps=fps)
                                        if candidate.start(wait_first_frame_timeout=60.0):
                                            portal_cap = candidate
                                            portal_cap.grab_into(arrays[buf_idx])
                                            if cmd_queue is not None:
                                                cmd_queue.put(("request_idr",))
                                            try:
                                                sct.close()
                                            except Exception:
                                                pass
                                            sct = None
                                else:
                                    consecutive_black_mss = 0
                        except Exception:
                            captured = False

                    if not captured:
                        arrays[buf_idx].fill(32)
                        arrays[buf_idx][:, :, 0] = (cap_id_linux * 5) % 255
                        arrays[buf_idx][:, :, 1] = 140
                        arrays[buf_idx][:, :, 2] = 220
                        arrays[buf_idx][:, :, 3] = 255

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

                if portal_cap is not None:
                    portal_cap.close()
                if sct:
                    try:
                        sct.close()
                    except Exception:
                        pass

    def _encode_and_transmit_frame(
        frame_bgra: np.ndarray,
        t_cap_start: float,
        t_cap_end: float,
        encoder: VideoEncoder,
    ):
        nonlocal total_frames_encoded, total_frames_sent, total_bytes_sent, total_packets_sent, latest_payload_kb, latest_lat_ms

        if not transport.dp.pake.confirmed:
            return

        transport.poll_control(encoder)
        frame_interval = 1.0 / float(max(1, fps))
        budget = transport.dp.allocate_budget(
            audio_reserved_bytes=0 if audio_muted_evt.is_set() else 240
        )
        if budget.skip_frame:
            return

        encoder.update_rate_budget(budget.target_codec_kbps, pir_mode=budget.enable_pir)

        t_enc_start = time.perf_counter()
        payload = encoder.encode(frame_bgra)
        t_enc_end = time.perf_counter()

        if not payload:
            return

        total_frames_encoded += 1
        frame_id = total_frames_encoded
        latest_payload_kb = max(1, len(payload) // 1024)
        is_keyframe = encoder.last_frame_was_keyframe or (frame_id == 1)

        t_send_start = time.perf_counter()
        pkts_sent, frame_sent_bytes, _ = transport.dp.send_video_frame(
            payload,
            is_keyframe=is_keyframe,
            frame_interval_sec=frame_interval,
            pir_mode=budget.enable_pir,
            stop_check=stop_event.is_set,
        )
        t_send_end = time.perf_counter()

        total_packets_sent += pkts_sent
        total_frames_sent += 1
        total_bytes_sent += frame_sent_bytes
        latest_lat_ms = (t_send_end - t_cap_start) * 1000.0

        if _probe_send is not None and frame_id % 3 == 0:
            _probe_send("capture", t_cap_start, t_cap_end, frame_id)
            _probe_send("encode", t_enc_start, t_enc_end, frame_id)
            _probe_send("send", t_send_start, t_send_end, frame_id)
            _probe_send("e2e", t_cap_start, t_send_end, frame_id)

    def _encode_send_worker_wgc():
        nonlocal active_codec_tag
        _set_thread_perf(THREAD_PRIORITY_HIGHEST, 0)

        encoder = VideoEncoder(
            codec_type=codec_type, width=width, height=height,
            fps=fps, bitrate_kbps=bitrate_kbps,
        )
        active_codec_tag = encoder.active_backend_name

        t_wait_deadline = time.monotonic() + 2.0
        while not stop_event.is_set() and not has_first_frame.is_set() and time.monotonic() < t_wait_deadline:
            transport.poll_control(encoder)
            has_first_frame.wait(timeout=0.05)
        frame_interval = 1.0 / float(max(1, fps))
        t_target = time.perf_counter() + frame_interval

        while not stop_event.is_set():
            transport.poll_control(encoder)

            if not is_streaming_active.is_set() or not transport.dp.pake.confirmed:
                time.sleep(0.01)
                t_target = time.perf_counter() + frame_interval
                continue

            with buf_lock:
                np.copyto(local_enc_buf, shared_frame_buf)

            _encode_and_transmit_frame(
                local_enc_buf,
                _t_latest_cap_start,
                _t_latest_cap_end,
                encoder,
            )

            now = time.perf_counter()
            slack = t_target - now
            if slack > 0.003:
                time.sleep(slack - 0.0015)
            while time.perf_counter() < t_target:
                pass
            t_target = max(t_target + frame_interval, time.perf_counter())

        encoder.close()

    def _encode_send_worker_buffered():
        nonlocal active_codec_tag
        _set_thread_perf(THREAD_PRIORITY_HIGHEST, 0)

        encoder = VideoEncoder(
            codec_type=codec_type, width=width, height=height,
            fps=fps, bitrate_kbps=bitrate_kbps,
        )
        active_codec_tag = encoder.active_backend_name

        while not stop_event.is_set() or not ready_buffers.empty():
            transport.poll_control(encoder)

            if not is_streaming_active.is_set() or not transport.dp.pake.confirmed:
                time.sleep(0.01)
                continue

            try:
                buf_idx, _, t_cap_start, t_cap_end = ready_buffers.get(timeout=0.03)
            except queue.Empty:
                continue

            while not ready_buffers.empty():
                try:
                    newer = ready_buffers.get_nowait()
                    free_buffers.put_nowait(buf_idx)
                    buf_idx, _, t_cap_start, t_cap_end = newer
                except queue.Empty:
                    break

            frame_view = arrays[buf_idx]
            _encode_and_transmit_frame(
                frame_view,
                t_cap_start,
                t_cap_end,
                encoder,
            )
            free_buffers.put(buf_idx)

        encoder.close()

    def _audio_tx_worker():
        audio_cap = None
        audio_enc = None
        try:
            audio_cap = create_audio_capturer()
            audio_enc = OpusAudioEncoder(bitrate_bps=96000, enable_lbrr_piggyback=True)
            while not stop_event.is_set():
                pcm = audio_cap.read_frame(timeout=0.025)
                if pcm is None:
                    continue
                if audio_muted_evt.is_set() or not is_streaming_active.is_set() or not transport.dp.pake.confirmed:
                    continue
                use_lbrr = transport.dp.sqp.loss_rate > 0.002
                enc_pkt = audio_enc.encode(pcm, lbrr_active=use_lbrr)
                if enc_pkt:
                    transport.dp.send_audio_frame(enc_pkt, is_lbrr=use_lbrr)
        except Exception as exc:
            print(f"[Audio TX] Desativado ({exc}).")
        finally:
            if audio_enc is not None:
                audio_enc.close()
            if audio_cap is not None:
                audio_cap.close()

    def _control_rx_worker():
        while not stop_event.is_set():
            try:
                rlist, _, _ = select.select([transport.sock], [], [], 0.002)
                if rlist:
                    transport.poll_control()
                elif not transport.dp.pake.confirmed:
                    transport.poll_control()
            except Exception:
                time.sleep(0.002)

    t_ctrl = threading.Thread(target=_control_rx_worker, daemon=True, name="DAV-Control-RX")
    t_ctrl.start()

    t_audio = threading.Thread(target=_audio_tx_worker, daemon=True, name="DAV-Audio-TX")
    t_audio.start()

    if use_wgc:
        t_capture = None
        t_encode = threading.Thread(target=_encode_send_worker_wgc, daemon=True, name="DAV-EncodeSend-WGC")
        t_encode.start()
    else:
        cap_tag = "GDI" if is_win32 else "X11"
        t_capture = threading.Thread(target=_capture_worker, daemon=True, name=f"DAV-Capture-{cap_tag}")
        t_encode = threading.Thread(target=_encode_send_worker_buffered, daemon=True, name=f"DAV-EncodeSend-{cap_tag}")
        t_capture.start()
        t_encode.start()

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
            codec_label = f"{active_codec_tag}[{backend_label}]"

            try:
                stats_queue.put_nowait((
                    total_frames_sent,
                    cur_fps,
                    cur_mbps,
                    total_packets_sent,
                    codec_label,
                    latest_payload_kb,
                ))
            except Exception:
                pass

            try:
                _tel_msg = json.dumps({
                    "role": "tx",
                    "fps": round(cur_fps, 2),
                    "mbps": round(cur_mbps, 2),
                    "lat": round(latest_lat_ms, 2),
                    "frames": total_frames_sent,
                    "packets": total_packets_sent,
                }).encode("utf-8")
                _tel_sock.sendto(_tel_msg, ("127.0.0.1", 19901))
            except Exception:
                pass

            last_stat_t = stat_now
            last_stat_frames = total_frames_sent
            last_stat_bytes = total_bytes_sent

    t_ctrl.join(timeout=0.3)
    t_audio.join(timeout=0.5)
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
        if is_win32 and gdi32 and user32:
            for h_b in hbms:
                gdi32.DeleteObject(h_b)
            for hdc_m in hdc_mems:
                gdi32.DeleteDC(hdc_m)
            if hdc_screen:
                user32.ReleaseDC(0, hdc_screen)

    transport.close()

    try:
        _tel_sock.close()
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass


_sender_subprocess = run_sender_subprocess
