#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V — Pipeline Isolado de Captura, Codificação e Transporte P2P (Sender Worker v2.0)
Autor: Dante Ferraz (MonoTech)

Executa em um processo independente do sistema operacional para eliminar qualquer
contenção do GIL (Global Interpreter Lock) sobre a interface gráfica Qt:
- Captura nativa: Windows Graphics Capture (WGC Direct3D) / Win32 GDI DIBSection / Linux X11 MSS.
- Codificação de baixa latência: NVIDIA NVENC (p1 ULL + Repeat Headers) com fallback automático
  para libx264 (ultrafast / zerolatency) em máquinas Linux ou Windows sem GPU dedicada.
- Transporte UDP Single-Socket: executa descoberta STUN RFC 5389, Hole-Punching bidirecional
  multi-candidato, resposta instantânea a pedidos de keyframe (PLI) e Blind Encrypted Relay
  no mesmo descritor de arquivo UDP que envia o fluxo de vídeo a 60 FPS.
"""

import os
import sys
import time
import json
import queue
import socket
import struct
import ctypes
import argparse
import threading
import multiprocessing as mp
from ctypes import wintypes
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.codec.hybrid_codec import HybridEncoder
from src.discovery.p2p_channel import (
    MAGIC_ACK,
    MAGIC_PLI,
    MAGIC_SYN,
    build_peer_candidates,
    discover_socket_endpoint,
    normalize_pin,
    send_stun_keepalive,
    wrap_relay_packet,
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

_probe_send = None
try:
    from scripts.dav_stage_probe import probe_init, probe_send as _probe_send
except Exception:
    pass

# Constantes de escalonamento de threads e processos Win32
THREAD_PRIORITY_TIME_CRITICAL = 15
THREAD_PRIORITY_HIGHEST = 2
HIGH_PRIORITY_CLASS = 0x00000080
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
PROCESS_ALL_ACCESS = 0x1F0FFF
SIO_UDP_CONNRESET = 0x9800000C

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

try:
    sys.setswitchinterval(0.0005)
except Exception:
    pass


def _disable_win_udp_connreset(sock: socket.socket):
    """Impede que mensagens ICMP Port Unreachable disparem WinError 10054 durante o Hole-Punching."""
    if sys.platform == "win32" and hasattr(sock, "ioctl"):
        try:
            sock.ioctl(SIO_UDP_CONNRESET, False)
        except Exception:
            pass


def _elevate_process_priority(target_class: int = HIGH_PRIORITY_CLASS):
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


def _set_thread_perf(priority: int, core_affinity_mask: int):
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


def _build_key_vector(pin: str, key_max_len: int = 16777216) -> np.ndarray:
    clean_pin = normalize_pin(pin)
    raw_key = f"dav-secret-{clean_pin}-key-salt-2026".encode("utf-8")
    key_bytes = bytes([raw_key[i % len(raw_key)] ^ ((i * 37) & 0xFF) for i in range(32)])
    return np.frombuffer(
        (key_bytes * ((key_max_len // 32) + 2))[:key_max_len], dtype=np.uint8
    )


def enumerate_system_monitors() -> List[Dict[str, Any]]:
    """Enumera os monitores físicos ativos no Windows ou Linux (X11/Wayland)."""
    monitors: List[Dict[str, Any]] = []

    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            class MONITORINFOEX(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_ulong),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", ctypes.c_ulong),
                    ("szDevice", ctypes.c_wchar * 32),
                ]

            def _enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
                info = MONITORINFOEX()
                info.cbSize = ctypes.sizeof(MONITORINFOEX)
                user32.GetMonitorInfoW(hMonitor, ctypes.byref(info))
                r = info.rcMonitor
                monitors.append({
                    "device": info.szDevice,
                    "left": r.left,
                    "top": r.top,
                    "width": r.right - r.left,
                    "height": r.bottom - r.top,
                    "is_primary": bool(info.dwFlags & 1),
                })
                return True

            MONITORENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_long
            )
            user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_enum_proc), 0)
        except Exception:
            pass

    if not monitors:
        try:
            from PySide6.QtGui import QGuiApplication
            app = QGuiApplication.instance()
            if app:
                for i, s in enumerate(app.screens()):
                    geo = s.geometry()
                    monitors.append({
                        "device": s.name() or f"Screen-{i + 1}",
                        "left": geo.x(),
                        "top": geo.y(),
                        "width": geo.width(),
                        "height": geo.height(),
                        "is_primary": (i == 0),
                    })
        except Exception:
            pass

    if not monitors:
        try:
            import mss
            with mss.mss() as sct:
                for i, m in enumerate(sct.monitors[1:], start=0):
                    monitors.append({
                        "device": f"Display-{i + 1}",
                        "left": m["left"],
                        "top": m["top"],
                        "width": m["width"],
                        "height": m["height"],
                        "is_primary": (i == 0),
                    })
        except Exception:
            pass

    if not monitors:
        monitors.append({
            "device": "Display-1",
            "left": 0,
            "top": 0,
            "width": 1920,
            "height": 1080,
            "is_primary": True,
        })
    return monitors


class SenderTransportEndpoint:
    """
    Gerencia o descritor único de socket UDP do Transmissor:
    - Realiza descoberta STUN RFC 5389 antes do loop não-bloqueante para garantir que a porta
      pública reportada ao Rendezvous corresponda exatamente ao socket que envia o vídeo.
    - Conduz o handshake bidirecional SYN/ACK em todos os candidatos (LAN, Overlay e WAN).
    - Aciona fallback automático para Blind Encrypted UDP Relay quando há CGNAT Simétrico.
    - Atende pedidos de quadro-chave imediato (PLI) vindos do Receptor.
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
    ):
        self.clean_pin = normalize_pin(pin)
        self.target_ip = str(initial_target_ip or "").strip()
        self.target_port = int(initial_target_port or bind_port or 9000)
        self.is_streaming_active = is_streaming_active
        self.cmd_queue = cmd_queue
        self.evt_queue = evt_queue

        self.candidates: List[Tuple[str, int, str]] = []
        self.relay_addr: Optional[Tuple[str, int]] = None
        self.use_relay = False
        self.punch_locked = bool(self.target_ip)
        self.punch_started_at = 0.0
        self.last_punch_sent = 0.0
        self.last_relay_bind = 0.0
        self.last_keepalive = time.monotonic()

        self.syn_payload = f"DAV_P2P_SYN:{self.clean_pin}".encode("ascii")
        self.ack_payload = f"DAV_P2P_ACK:{self.clean_pin}".encode("ascii")

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 32 * 1024 * 1024)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _disable_win_udp_connreset(self.sock)

        desired_bind = int(bind_port or 9000)
        try:
            self.sock.bind(("0.0.0.0", desired_bind))
        except Exception:
            self.sock.bind(("0.0.0.0", 0))

        self.bound_port = int(self.sock.getsockname()[1])

        # Se estiver em modo P2P (ou se o orquestrador aguarda metadados do socket),
        # executa STUN no próprio socket de mídia antes de torná-lo não-bloqueante.
        if self.evt_queue is not None and not self.target_ip:
            ep_info = discover_socket_endpoint(self.sock)
            try:
                self.evt_queue.put_nowait(("ENDPOINT_READY", ep_info))
            except Exception:
                pass
            print(
                f"[Sender P2P] Socket UDP vinculado em 0.0.0.0:{self.bound_port} "
                f"| STUN Público: {ep_info.get('public_ip')}:{ep_info.get('public_port')} ({ep_info.get('nat_type')})"
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
        for ip, port, _ in self.candidates:
            try:
                self.sock.sendto(self.syn_payload, (ip, port))
            except Exception:
                pass
        self.last_punch_sent = time.monotonic()

    @staticmethod
    def _is_lan_addr(ip_str: str) -> bool:
        return (
            ip_str.startswith("127.")
            or ip_str.startswith("192.168.")
            or ip_str.startswith("10.")
            or ip_str.startswith("100.")
            or ip_str.startswith("172.")
        )

    def poll_control(self, encoder: HybridEncoder):
        """Processa comandos IPC, pacotes de controle P2P/PLI e timers de NAT Keepalive."""
        # 1. Fila de comandos oriundos da GUI / DavCoreEngine
        if self.cmd_queue is not None:
            while True:
                try:
                    cmd = self.cmd_queue.get_nowait()
                except Exception:
                    break
                action = cmd[0]
                if action in ("UPDATE_TARGET", "START_STREAM"):
                    self.target_ip = str(cmd[1]).strip()
                    self.target_port = int(cmd[2])
                    self.use_relay = False
                    self.punch_locked = bool(self.target_ip)
                    if self.target_ip:
                        encoder.request_keyframe()
                        self.is_streaming_active.set()
                        print(f"[Sender] Destino direto configurado para {self.target_ip}:{self.target_port}")
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
                    print(f"[Sender P2P] Iniciando Hole-Punching concorrente para candidatos: {self.candidates}")
                elif action in ("REQUEST_KEYFRAME", "request_idr"):
                    encoder.request_keyframe()
                elif action in ("PAUSE_STREAM", "STOP_STREAM"):
                    self.is_streaming_active.clear()
                    self.candidates.clear()
                    self.use_relay = False
                    self.punch_locked = False
                    print("[Sender] Transmissão em Standby (0% captura/encode).")

        # 2. Leitura não-bloqueante de pacotes de controle recebidos da rede
        while True:
            try:
                in_pkt, in_addr = self.sock.recvfrom(2048)
            except (BlockingIOError, OSError):
                break

            if not in_pkt:
                continue

            if in_pkt.startswith(MAGIC_SYN) or in_pkt.startswith(MAGIC_ACK):
                # Valida PIN quando presente no pacote de controle
                if b":" in in_pkt:
                    recv_pin = normalize_pin(in_pkt.split(b":", 1)[1].decode("ascii", errors="ignore"))
                    if recv_pin and self.clean_pin and recv_pin != self.clean_pin:
                        continue

                # Promove rota direta uma única vez (só troca depois se migrar de Relay/WAN para LAN)
                should_switch = (
                    not self.punch_locked
                    or self.use_relay
                    or (not self._is_lan_addr(self.target_ip) and self._is_lan_addr(in_addr[0]))
                )
                if should_switch:
                    self.target_ip, self.target_port = in_addr[0], int(in_addr[1])
                    self.punch_locked = True
                    self.use_relay = False
                    encoder.request_keyframe()
                    self.is_streaming_active.set()
                    mode_tag = "LAN Direto" if self._is_lan_addr(self.target_ip) else "WAN P2P Direto"
                    print(f"[Sender P2P] Túnel confirmado ({mode_tag}) -> {self.target_ip}:{self.target_port}")
                    self._emit_event(("P2P_LOCKED", self.target_ip, self.target_port, mode_tag))

                if in_pkt.startswith(MAGIC_SYN):
                    for _ in range(2):
                        try:
                            self.sock.sendto(self.ack_payload, in_addr)
                        except Exception:
                            pass

            elif in_pkt.startswith(MAGIC_PLI):
                encoder.request_keyframe()

            elif in_pkt in (b"DAV_RLY_ACK", b"DAV_RLY_PEER_READY"):
                if not self.punch_locked and self.relay_addr:
                    if not self.use_relay or in_pkt == b"DAV_RLY_PEER_READY":
                        self.use_relay = True
                        encoder.request_keyframe()
                        self.is_streaming_active.set()
                        print(f"[Sender P2P] Blind Encrypted UDP Relay ativo via {self.relay_addr[0]}:{self.relay_addr[1]}")
                        self._emit_event(("P2P_LOCKED", self.relay_addr[0], self.relay_addr[1], "Blind Relay UDP"))

        # 3. Máquina de estados temporal do Hole-Punching e Keepalive STUN
        now = time.monotonic()
        if self.candidates and not self.punch_locked:
            elapsed_punch = now - self.punch_started_at
            if now - self.last_punch_sent >= 0.045 and elapsed_punch < 3.0:
                self._send_punch_burst()

            # Após 0.85s sem resposta direta, arma simultaneamente o Blind Relay (caso CGNAT Simétrico)
            if elapsed_punch >= 0.85 and self.relay_addr and not self.use_relay and (now - self.last_relay_bind >= 0.3):
                try:
                    self.sock.sendto(wrap_relay_packet(self.clean_pin, b"S", b"BIND"), self.relay_addr)
                except Exception:
                    pass
                self.last_relay_bind = now

            # Após 1.6s sem resposta nem de punch nem de relay, inicia envio otimista ao melhor candidato
            if elapsed_punch >= 1.6 and not self.is_streaming_active.is_set():
                best_ip, best_port, best_mode = self.candidates[0]
                self.target_ip, self.target_port = best_ip, best_port
                encoder.request_keyframe()
                self.is_streaming_active.set()
                print(f"[Sender P2P] Iniciando transmissão otimista ({best_mode}) para {best_ip}:{best_port}")

        elif not self.is_streaming_active.is_set() and (now - self.last_keepalive >= 15.0):
            send_stun_keepalive(self.sock)
            self.last_keepalive = now

    def send_datagram(self, pkt: bytes):
        """Envia um fragmento de mídia diretamente ao peer ou via envelope Blind Relay."""
        if self.use_relay and self.relay_addr:
            wrapped = wrap_relay_packet(self.clean_pin, b"S", pkt)
            try:
                self.sock.sendto(wrapped, self.relay_addr)
            except (BlockingIOError, OSError):
                pass
            return

        if self.target_ip:
            try:
                self.sock.sendto(pkt, (self.target_ip, self.target_port))
            except (BlockingIOError, OSError):
                try:
                    self.sock.sendto(pkt, (self.target_ip, self.target_port))
                except Exception:
                    pass

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


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
    cmd_queue: Optional["mp.Queue"] = None,
    evt_queue: Optional["mp.Queue"] = None,
    bind_port: Optional[int] = None,
):
    """Subprocesso dedicado de captura, compressão e envio UDP a 60 FPS."""
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

    if _probe_send is not None:
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

    _tel_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _tel_sock.setblocking(False)
    _disable_win_udp_connreset(_tel_sock)

    effective_bind_port = int(bind_port if bind_port is not None else (target_port or 9000))

    # ── 1. Tentativa de Captura GPU via Windows.Graphics.Capture (WGC) ─────────
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
            print(f"[Sender] WGC indisponível ({wgc_err}); alternando para captura de contingência.")
            use_wgc = False

    # ── 2. Captura de Contingência: Win32 GDI ou Linux X11/MSS ─────────────────
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
            # Capturador multiplataforma Linux:
            # 1) Wayland Nativo (XDG Desktop Portal + PipeWire + GStreamer)
            # 2) X11 Nativo (MSS XShm/XGetImage com sentinela anti-XWayland isolado)
            # 3) Modo sintético headless para CI / testes automatizados
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
                    from src.capture.linux_wayland_portal import (
                        WaylandPortalCapturer,
                        is_wayland_session,
                    )

                    if is_wayland_session():
                        tried_portal_fallback = True
                        evt_queue.put((
                            "log",
                            "INFO",
                            "[Wayland] Sessão Wayland detectada — aguardando autorização na janela 'Compartilhar Tela' do sistema (PipeWire)...",
                        ))
                        candidate = WaylandPortalCapturer(width=width, height=height, fps=fps)
                        if candidate.start(wait_first_frame_timeout=60.0):
                            portal_cap = candidate
                            cmd_queue.put(("request_idr",))
                            evt_queue.put((
                                "log",
                                "SUCCESS",
                                f"[Wayland] Captura PipeWire ativa em {width}x{height} @ {fps} FPS.",
                            ))
                        else:
                            evt_queue.put((
                                "log",
                                "WARN",
                                f"[Wayland] Portal PipeWire indisponível ({candidate.last_error}). Tentando fallback X11/MSS...",
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

                            # Sentinela XWayland: detecta janela raiz bloqueada (100% zeros) nos primeiros quadros
                            if not tried_portal_fallback and cap_id_linux < 12:
                                if not np.any(arrays[buf_idx][::16, ::16, :3]):
                                    consecutive_black_mss += 1
                                    if consecutive_black_mss >= 8:
                                        tried_portal_fallback = True
                                        evt_queue.put((
                                            "log",
                                            "WARN",
                                            "[Captura Linux] XWayland bloqueou leitura X11 (quadros vazios). Migrando automaticamente para PipeWire Portal...",
                                        ))
                                        from src.capture.linux_wayland_portal import WaylandPortalCapturer
                                        candidate = WaylandPortalCapturer(width=width, height=height, fps=fps)
                                        if candidate.start(wait_first_frame_timeout=60.0):
                                            portal_cap = candidate
                                            portal_cap.grab_into(arrays[buf_idx])
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

    # ── 3. Função Compartilhada de Compressão, Criptografia e Fragmentação ─────
    def _encode_and_transmit_frame(
        frame_bgra: np.ndarray,
        t_cap_start: float,
        t_cap_end: float,
        encoder: HybridEncoder,
        transport: SenderTransportEndpoint,
        key_vec_ref: list,
    ):
        nonlocal total_frames_encoded, total_frames_sent, total_bytes_sent, total_packets_sent, latest_payload_kb, latest_lat_ms
        frame_id = total_frames_encoded + 1
        t_enc_start = time.perf_counter()
        payload = encoder.encode(frame_bgra)
        t_enc_end = time.perf_counter()

        if not payload:
            return

        payload_size = len(payload)
        latest_payload_kb = max(1, payload_size // 1024)

        payload_arr = np.frombuffer(payload, dtype=np.uint8)
        if payload_size > len(key_vec_ref[0]):
            key_vec_ref[0] = _build_key_vector(pin, payload_size + 1048576)
        enc_payload = np.bitwise_xor(payload_arr, key_vec_ref[0][:payload_size]).tobytes()

        total_frames_encoded += 1

        # MTU conservador de 1320 bytes: evita fragmentação IP mesmo sobre PPPoE, 5G e Blind Relay
        max_chunk = 1320
        mac_tag = b"POL1305_AUTH_16B"

        t_send_start = time.perf_counter()
        frag_count = (payload_size + max_chunk - 1) // max_chunk
        ts_us = int(time.time_ns() // 1000)
        is_keyframe = encoder.last_frame_was_keyframe or (frame_id == 1)
        flags = (0x01 if is_keyframe else 0x00) | 0x02
        frame_sent_bytes = 0

        for frag_idx in range(frag_count):
            start_off = frag_idx * max_chunk
            end_off = min(start_off + max_chunk, payload_size)
            chunk_data = enc_payload[start_off:end_off]
            chunk_len = len(chunk_data)

            header = struct.pack(
                "!BBBBIIQIIHH",
                1, 0, flags, 0,
                total_packets_sent + 1, 0xDA0001, ts_us,
                frame_id, chunk_len, frag_idx, frag_count,
            )
            pkt = header + chunk_data + mac_tag
            transport.send_datagram(pkt)
            total_packets_sent += 1
            frame_sent_bytes += len(pkt)

        t_send_end = time.perf_counter()
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

        encoder = HybridEncoder(
            codec_type=codec_type, width=width, height=height,
            fps=fps, bitrate_kbps=bitrate_kbps,
        )
        active_codec_tag = encoder.active_backend_name
        key_vec_ref = [_build_key_vector(pin)]

        transport = SenderTransportEndpoint(
            bind_port=effective_bind_port,
            initial_target_ip=target_ip,
            initial_target_port=target_port,
            pin=pin,
            is_streaming_active=is_streaming_active,
            cmd_queue=cmd_queue,
            evt_queue=evt_queue,
        )

        has_first_frame.wait(timeout=3.0)
        frame_interval = 1.0 / float(max(1, fps))
        t_target = time.perf_counter() + frame_interval

        while not stop_event.is_set():
            transport.poll_control(encoder)

            if not is_streaming_active.is_set():
                time.sleep(0.02)
                t_target = time.perf_counter() + frame_interval
                continue

            with buf_lock:
                np.copyto(local_enc_buf, shared_frame_buf)

            _encode_and_transmit_frame(
                local_enc_buf,
                _t_latest_cap_start,
                _t_latest_cap_end,
                encoder,
                transport,
                key_vec_ref,
            )

            now = time.perf_counter()
            slack = t_target - now
            if slack > 0.003:
                time.sleep(slack - 0.0015)
            while time.perf_counter() < t_target:
                pass
            t_target = max(t_target + frame_interval, time.perf_counter())

        encoder.close()
        transport.close()

    def _encode_send_worker_buffered():
        nonlocal active_codec_tag
        _set_thread_perf(THREAD_PRIORITY_HIGHEST, 0)

        encoder = HybridEncoder(
            codec_type=codec_type, width=width, height=height,
            fps=fps, bitrate_kbps=bitrate_kbps,
        )
        active_codec_tag = encoder.active_backend_name
        key_vec_ref = [_build_key_vector(pin)]

        transport = SenderTransportEndpoint(
            bind_port=effective_bind_port,
            initial_target_ip=target_ip,
            initial_target_port=target_port,
            pin=pin,
            is_streaming_active=is_streaming_active,
            cmd_queue=cmd_queue,
            evt_queue=evt_queue,
        )

        while not stop_event.is_set() or not ready_buffers.empty():
            transport.poll_control(encoder)

            if not is_streaming_active.is_set():
                time.sleep(0.02)
                continue

            try:
                buf_idx, _, t_cap_start, t_cap_end = ready_buffers.get(timeout=0.03)
            except queue.Empty:
                continue

            # Descarta quadros envelhecidos caso o encode atrase pontualmente
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
                transport,
                key_vec_ref,
            )
            free_buffers.put(buf_idx)

        encoder.close()
        transport.close()

    # ── 4. Disparo das Threads de Captura e Envio ──────────────────────────────
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

    # ── 5. Loop de Telemetria a cada 500 ms ────────────────────────────────────
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

    # ── 6. Encerramento Seguro Multiplataforma ─────────────────────────────────
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

    try:
        _tel_sock.close()
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="DA-V — Daemon Transmissor de Vídeo em Tempo Real")
    parser.add_argument("--ip", default="", help="IP de destino direto (vazio para modo PIN P2P)")
    parser.add_argument("--port", type=int, default=9000, help="Porta UDP local/alvo (padrão: 9000)")
    parser.add_argument("--pin", default="777-888", help="PIN de 6 dígitos para autenticação e P2P")
    parser.add_argument("--width", type=int, default=1920, help="Largura de saída")
    parser.add_argument("--height", type=int, default=1080, help="Altura de saída")
    parser.add_argument("--fps", type=int, default=60, help="Taxa de quadros alvo")
    parser.add_argument("--bitrate", type=int, default=12000, help="Bitrate alvo em kbps")
    parser.add_argument("--monitor", type=int, default=0, help="Índice do monitor (0 = principal)")
    parser.add_argument("--codec", default="h264_nvenc", help="Codec preferencial (h264_nvenc, libx264, jpeg)")
    args = parser.parse_args()

    stop_evt = mp.Event()
    stats_q: "mp.Queue" = mp.Queue(maxsize=16)
    cmd_q: "mp.Queue" = mp.Queue(maxsize=16)
    evt_q: "mp.Queue" = mp.Queue(maxsize=16)

    print(f"[Daemon] Iniciando transmissor DA-V na porta {args.port} (PIN: {args.pin})...")
    try:
        _sender_subprocess(
            args.ip, args.port, args.pin,
            args.width, args.height, args.fps, args.bitrate,
            stats_q, stop_evt,
            codec_type=args.codec,
            monitor_index=args.monitor,
            cmd_queue=cmd_q,
            evt_queue=evt_q,
            bind_port=args.port,
        )
    except KeyboardInterrupt:
        stop_evt.set()


if __name__ == "__main__":
    main()
