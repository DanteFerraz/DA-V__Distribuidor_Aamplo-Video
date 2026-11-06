#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V — Motor Cliente Unificado e Camada de Transporte de Recepção (v2.0)
Autor: Dante Ferraz (MonoTech)

Conecta a interface gráfica (PySide6) ou scripts de automação ao pipeline de mídia:
- Unifica por padrão o protocolo de rede entre Windows e Linux utilizando o motor
  multiprocesso GIL-free + vetorização SIMD NumPy + PyAV/NVENC (mantendo suporte opcional
  ao binário C-ABI via `DAV_USE_NATIVE_CORE=1`).
- Implementa pré-alocação de socket UDP Single-Socket para STUN RFC 5389, garantindo que
  a porta pública negociada no Rendezvous seja idêntica à porta real de recepção do vídeo.
- Executa Hole-Punching concorrente (LAN, Overlay e WAN), fallback automático para
  Blind Encrypted UDP Relay e recuperação instantânea de keyframe via PLI.
"""

import os
import sys
import json
import time
import socket
import struct
import ctypes
import threading
from ctypes import (
    CFUNCTYPE,
    POINTER,
    Structure,
    c_char_p,
    c_float,
    c_int,
    c_size_t,
    c_uint16,
    c_uint32,
    c_uint64,
    c_void_p,
)
from typing import Callable, Dict, Optional, Tuple

import numpy as np

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.discovery.p2p_channel import (
    DEFAULT_RENDEZVOUS_HOST,
    DEFAULT_STUN_PORT,
    MAGIC_ACK,
    MAGIC_PLI,
    MAGIC_SYN,
    build_peer_candidates,
    discover_socket_endpoint,
    normalize_pin,
    wrap_relay_packet,
)

SIO_UDP_CONNRESET = 0x9800000C

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


def _disable_win_udp_connreset(sock: socket.socket):
    """Evita WinError 10054 (WSAECONNRESET) quando sondas UDP atingem portas NAT ainda fechadas."""
    if sys.platform == "win32" and hasattr(sock, "ioctl"):
        try:
            sock.ioctl(SIO_UDP_CONNRESET, False)
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
# Estruturas da Ponte C-ABI (libdav_core.so / dav_core.dll)
# ============================================================================

class DavRenderFrame(Structure):
    _fields_ = [
        ("width", c_uint32),
        ("height", c_uint32),
        ("stride", c_uint32),
        ("timestamp_us", c_uint64),
        ("rgba_data", POINTER(ctypes.c_uint8)),
        ("data_size", c_size_t),
        ("is_keyframe", c_int),
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
        ("is_connected", c_int),
    ]


DavFrameReadyCallback = CFUNCTYPE(None, POINTER(DavRenderFrame), c_void_p)
DavTelemetryCallback = CFUNCTYPE(None, POINTER(DavTelemetry), c_void_p)
DavLogCallback = CFUNCTYPE(None, c_int, c_char_p, c_void_p)


class DavCoreEngine:
    """
    Orquestrador unificado do cliente DA-V para Windows e Linux.
    Coordena o subprocesso Transmissor (GIL-free), o loop Receptor de baixa latência
    e o pareamento P2P Single-Socket com fallback automático para Blind Relay.
    """

    def __init__(self):
        self._dll = None
        self._is_native = False
        self._frame_cb_native = None
        self._telemetry_cb_native = None
        self._user_frame_callback: Optional[Callable] = None
        self._user_telemetry_callback: Optional[Callable] = None
        self._user_sender_stats_callback: Optional[Callable] = None
        self._user_p2p_event_callback: Optional[Callable] = None

        self._fallback_threads: list = []
        self._fallback_running = False
        self._prepared_recv_sock: Optional[socket.socket] = None
        self._sender_endpoint_info: Optional[Dict[str, object]] = None
        self._sender_endpoint_ready = threading.Event()

        self._try_load_native_library()

    def _try_load_native_library(self):
        """
        Mantém por padrão o motor unificado Python/SIMD ativo tanto no Windows quanto no Linux
        para assegurar 100% de compatibilidade binária P2P entre sistemas operacionais.
        A biblioteca C-ABI experimental pode ser ativada explicitamente via `DAV_USE_NATIVE_CORE=1`.
        """
        if os.environ.get("DAV_USE_NATIVE_CORE") != "1":
            return

        possible_paths = [
            os.path.join(os.path.dirname(__file__), "..", "build", "Release", "dav_core.dll"),
            os.path.join(os.path.dirname(__file__), "..", "build", "dav_core.dll"),
            os.path.join(os.path.dirname(__file__), "..", "build", "libdav_core.so"),
            os.path.join(os.path.dirname(__file__), "dav_core.dll"),
            "dav_core.dll",
            "libdav_core.so",
        ]

        for p in possible_paths:
            if os.path.exists(p):
                try:
                    self._dll = ctypes.CDLL(os.path.abspath(p))
                    self._setup_c_signatures()
                    self._is_native = True
                    print(f"[Engine] Biblioteca nativa C-ABI carregada sob demanda: {p}")
                    return
                except Exception as exc:
                    print(f"[Engine] Falha ao carregar biblioteca C-ABI {p}: {exc}")

    def _setup_c_signatures(self):
        self._dll.dav_init.argtypes = [c_char_p]
        self._dll.dav_init.restype = c_int
        self._dll.dav_start_sender.argtypes = [c_char_p, c_uint16, c_char_p, c_uint32, c_uint32, c_uint32]
        self._dll.dav_start_sender.restype = c_int
        self._dll.dav_start_receiver.argtypes = [
            c_uint16, c_char_p, DavFrameReadyCallback, DavTelemetryCallback, c_void_p
        ]
        self._dll.dav_start_receiver.restype = c_int
        self._dll.dav_stop.argtypes = []
        self._dll.dav_stop.restype = None
        self._dll.dav_request_keyframe.argtypes = []
        self._dll.dav_request_keyframe.restype = None
        self._dll.dav_get_telemetry.argtypes = [POINTER(DavTelemetry)]
        self._dll.dav_get_telemetry.restype = c_int
        self._dll.dav_get_version.argtypes = []
        self._dll.dav_get_version.restype = c_char_p
        self._dll.dav_init(None)

    @property
    def is_native_backend(self) -> bool:
        return self._is_native

    # ========================================================================
    # Controle do Transmissor (Sender) + Sincronia STUN Single-Socket
    # ========================================================================

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
        monitor_index: int = 0,
        bind_port: Optional[int] = None,
        on_p2p_event: Optional[Callable] = None,
        on_log: Optional[Callable] = None,
    ) -> bool:
        self._user_sender_stats_callback = on_sender_stats or (lambda *a: None)
        self._user_p2p_event_callback = on_p2p_event
        self._user_log_callback = on_log
        self._sender_endpoint_info = None
        self._sender_endpoint_ready.clear()

        if self._is_native:
            res = self._dll.dav_start_sender(
                target_ip.encode("utf-8"),
                target_port,
                pin.encode("utf-8"),
                width,
                height,
                fps,
            )
            return res == 0

        return self._start_fallback_sender(
            target_ip,
            target_port,
            pin,
            width,
            height,
            fps,
            bitrate_kbps,
            codec_type=codec_type,
            monitor_index=monitor_index,
            bind_port=bind_port,
        )

    def wait_sender_endpoint(self, timeout: float = 2.8) -> Optional[Dict[str, object]]:
        """
        Aguarda o subprocesso Transmissor concluir o bind e a consulta STUN RFC 5389
        no próprio socket de mídia, retornando a porta pública real mapeada pelo NAT.
        """
        self._sender_endpoint_ready.wait(timeout=timeout)
        return self._sender_endpoint_info

    def pair_sender_peer(
        self,
        peer_info: dict,
        my_public_ip: Optional[str] = None,
        relay_info: Optional[dict] = None,
    ):
        """Envia todos os candidatos do Receptor pareado para iniciar o Hole-Punching no Sender."""
        if hasattr(self, "_sender_cmd_queue") and self._sender_cmd_queue is not None:
            try:
                self._sender_cmd_queue.put(("PAIR_PEER", peer_info, my_public_ip, relay_info))
            except Exception as exc:
                print(f"[Engine] Erro ao encaminhar candidatos P2P ao Transmissor: {exc}")

    def update_sender_target(self, new_ip: str, new_port: int):
        """Redireciona diretamente o IP e a porta de destino do Transmissor."""
        if hasattr(self, "_sender_cmd_queue") and self._sender_cmd_queue is not None:
            try:
                self._sender_cmd_queue.put(("UPDATE_TARGET", str(new_ip), int(new_port)))
            except Exception as exc:
                print(f"[Engine] Erro ao atualizar destino do Transmissor: {exc}")

    def pause_sender(self):
        """Coloca o Transmissor em modo Standby (0% captura e 0% GPU)."""
        if hasattr(self, "_sender_cmd_queue") and self._sender_cmd_queue is not None:
            try:
                self._sender_cmd_queue.put(("PAUSE_STREAM",))
            except Exception:
                pass

    def resume_sender(self, ip: str, port: int):
        """Retoma o envio ativo para o destino informado."""
        if hasattr(self, "_sender_cmd_queue") and self._sender_cmd_queue is not None:
            try:
                self._sender_cmd_queue.put(("START_STREAM", str(ip), int(port)))
            except Exception:
                pass

    def request_keyframe(self):
        if self._is_native:
            self._dll.dav_request_keyframe()
        elif hasattr(self, "_sender_cmd_queue") and self._sender_cmd_queue is not None:
            try:
                self._sender_cmd_queue.put(("REQUEST_KEYFRAME",))
            except Exception:
                pass

    # ========================================================================
    # Controle do Receptor (Viewer) + Pré-Alocação Single-Socket STUN
    # ========================================================================

    def prepare_receiver_socket(
        self,
        bind_port: int,
        rendezvous_host: str = DEFAULT_RENDEZVOUS_HOST,
        stun_port: int = DEFAULT_STUN_PORT,
    ) -> Dict[str, object]:
        """
        Abre, vincula e executa descoberta STUN RFC 5389 no exato socket UDP que será
        reutilizado por `start_receiver()`, impedindo que o roteador troque a porta externa.
        """
        self._close_prepared_recv_sock()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32 * 1024 * 1024)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 * 1024 * 1024)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _disable_win_udp_connreset(sock)

        try:
            sock.bind(("0.0.0.0", int(bind_port)))
        except OSError:
            sock.bind(("0.0.0.0", 0))

        self._prepared_recv_sock = sock
        return discover_socket_endpoint(sock, rendezvous_host=rendezvous_host, stun_port=stun_port)

    def _close_prepared_recv_sock(self):
        if self._prepared_recv_sock is not None:
            try:
                self._prepared_recv_sock.close()
            except Exception:
                pass
            self._prepared_recv_sock = None

    def start_receiver(
        self,
        bind_port: int,
        pin: str,
        on_frame_ready: Callable,
        on_telemetry: Optional[Callable] = None,
        target_peer: Optional[Tuple[str, int]] = None,
        peer_info: Optional[dict] = None,
        my_public_ip: Optional[str] = None,
        relay_info: Optional[dict] = None,
        on_p2p_status: Optional[Callable] = None,
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
                        t.packets_received, t.frames_rendered,
                    )

            self._frame_cb_native = DavFrameReadyCallback(_native_frame_bridge)
            self._telemetry_cb_native = DavTelemetryCallback(_native_telemetry_bridge)
            res = self._dll.dav_start_receiver(
                bind_port,
                pin.encode("utf-8"),
                self._frame_cb_native,
                self._telemetry_cb_native,
                None,
            )
            return res == 0

        return self._start_fallback_receiver(
            bind_port=bind_port,
            pin=pin,
            target_peer=target_peer,
            peer_info=peer_info,
            my_public_ip=my_public_ip,
            relay_info=relay_info,
            on_p2p_status=on_p2p_status,
        )

    def stop(self):
        self._close_prepared_recv_sock()
        if self._is_native:
            self._dll.dav_stop()
            return

        self._fallback_running = False
        if hasattr(self, "_sender_stop_event") and self._sender_stop_event is not None:
            try:
                self._sender_stop_event.set()
            except Exception:
                pass
        if hasattr(self, "_sender_process") and self._sender_process is not None:
            try:
                self._sender_process.join(timeout=0.6)
                if self._sender_process.is_alive():
                    self._sender_process.terminate()
            except Exception:
                pass
            self._sender_process = None

        for t in self._fallback_threads:
            if t.is_alive():
                t.join(timeout=0.35)
        self._fallback_threads.clear()

    # ========================================================================
    # Implementações Internas do Motor Unificado (Windows & Linux)
    # ========================================================================

    def _start_fallback_sender(
        self,
        target_ip: str,
        target_port: int,
        pin: str,
        width: int,
        height: int,
        fps: int,
        bitrate_kbps: int = 12000,
        codec_type: str = "h264_nvenc",
        monitor_index: int = 0,
        bind_port: Optional[int] = None,
    ) -> bool:
        import multiprocessing as mp
        from scripts.dav_sender_worker import _sender_subprocess

        target_fps = fps if fps > 0 else 60
        ctx = mp.get_context("spawn")
        self._sender_stats_queue: "mp.Queue" = ctx.Queue(maxsize=16)
        self._sender_cmd_queue: "mp.Queue" = ctx.Queue(maxsize=16)
        self._sender_evt_queue: "mp.Queue" = ctx.Queue(maxsize=16)
        self._sender_stop_event: "mp.Event" = ctx.Event()

        self._sender_process = ctx.Process(
            target=_sender_subprocess,
            name="DAV-Sender-Engine",
            daemon=True,
            args=(
                target_ip,
                target_port,
                pin,
                width,
                height,
                target_fps,
                bitrate_kbps,
                self._sender_stats_queue,
                self._sender_stop_event,
                codec_type,
                monitor_index,
                self._sender_cmd_queue,
                self._sender_evt_queue,
                bind_port,
            ),
        )
        self._sender_process.start()
        self._fallback_running = True

        def _stats_poller():
            while self._fallback_running:
                try:
                    item = self._sender_stats_queue.get(timeout=0.12)
                    frames_sent, cur_fps, cur_mbps, packets_sent, quality, frame_kb = item
                    if self._user_sender_stats_callback:
                        try:
                            self._user_sender_stats_callback(
                                frames_sent, cur_fps, cur_mbps, packets_sent, quality, frame_kb
                            )
                        except TypeError:
                            self._user_sender_stats_callback(frames_sent, cur_fps, cur_mbps, packets_sent)
                except Exception:
                    pass

        def _evt_poller():
            while self._fallback_running:
                try:
                    evt = self._sender_evt_queue.get(timeout=0.15)
                    if not evt:
                        continue
                    if evt[0] == "ENDPOINT_READY":
                        self._sender_endpoint_info = evt[1]
                        self._sender_endpoint_ready.set()
                    elif evt[0] == "P2P_LOCKED" and self._user_p2p_event_callback:
                        self._user_p2p_event_callback(evt[1], evt[2], evt[3])
                    elif evt[0] == "log":
                        if getattr(self, "_user_log_callback", None):
                            try:
                                self._user_log_callback(evt[1], evt[2])
                            except Exception:
                                pass
                except Exception:
                    pass

        t_stats = threading.Thread(target=_stats_poller, daemon=True, name="DAV-Sender-Stats")
        t_evts = threading.Thread(target=_evt_poller, daemon=True, name="DAV-Sender-Events")
        self._fallback_threads = [t_stats, t_evts]
        t_stats.start()
        t_evts.start()
        return True

    def _start_fallback_receiver(
        self,
        bind_port: int,
        pin: str,
        target_peer: Optional[Tuple[str, int]] = None,
        peer_info: Optional[dict] = None,
        my_public_ip: Optional[str] = None,
        relay_info: Optional[dict] = None,
        on_p2p_status: Optional[Callable] = None,
    ) -> bool:
        self._fallback_running = True

        # Reaproveita o socket pré-vinculado (STUN Single-Socket) ou cria um novo em modo LAN direto
        sock = self._prepared_recv_sock
        self._prepared_recv_sock = None
        if sock is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32 * 1024 * 1024)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 * 1024 * 1024)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            _disable_win_udp_connreset(sock)
            try:
                sock.bind(("0.0.0.0", int(bind_port)))
            except OSError as exc:
                print(f"[Receiver] Falha ao vincular porta UDP {bind_port}: {exc}")
                sock.close()
                self._fallback_running = False
                return False

        clean_pin = normalize_pin(pin)
        syn_pkt = f"DAV_P2P_SYN:{clean_pin}".encode("ascii")
        ack_pkt = f"DAV_P2P_ACK:{clean_pin}".encode("ascii")

        candidates = build_peer_candidates(peer_info, my_public_ip=my_public_ip) if peer_info else []
        if not candidates and target_peer:
            candidates = [(str(target_peer[0]), int(target_peer[1]), "direct")]

        relay_addr: Optional[Tuple[str, int]] = None
        if relay_info and relay_info.get("host") and relay_info.get("port"):
            relay_addr = (str(relay_info["host"]), int(relay_info["port"]))

        def _receiver_loop():
            _set_thread_perf(priority=2, core_affinity_mask=0)
            sock.settimeout(0.08)

            # Dispara rajada inicial concorrente de perfuração de NAT em todos os candidatos
            for _ in range(4):
                for cip, cport, _ in candidates:
                    try:
                        sock.sendto(syn_pkt, (cip, cport))
                    except Exception:
                        pass
                if candidates:
                    time.sleep(0.015)

            raw_key = f"dav-secret-{clean_pin}-key-salt-2026".encode("utf-8")
            key_bytes = bytes([raw_key[i % len(raw_key)] ^ ((i * 37) & 0xFF) for i in range(32)])
            key_buf_size = 16777216
            key_vec = np.frombuffer(
                (key_bytes * ((key_buf_size // 32) + 2))[:key_buf_size], dtype=np.uint8
            )

            pending_frames: dict = {}
            packets_received = 0
            frames_rendered = 0
            total_bytes = 0
            latencies_ms: list = []
            clock_offset_us: Optional[int] = None

            start_mono = time.monotonic()
            last_punch_mono = start_mono
            last_relay_bind_mono = 0.0
            last_pli_mono = 0.0
            has_seen_keyframe = False
            reported_route = False

            active_sender_addr: Optional[Tuple[str, int]] = (
                (candidates[0][0], candidates[0][1]) if candidates else None
            )
            using_relay = False

            last_stat_time = time.perf_counter()
            last_bytes = 0
            last_frames_stat = 0

            while self._fallback_running:
                try:
                    data, addr = sock.recvfrom(65536)
                    if not data:
                        continue

                    # 1. Tratamento de pacotes de controle P2P e Blind Relay (< 32 bytes)
                    if data.startswith(MAGIC_SYN):
                        for _ in range(3):
                            try:
                                sock.sendto(ack_pkt, addr)
                            except Exception:
                                pass
                        active_sender_addr = addr
                        using_relay = False
                        if not reported_route and on_p2p_status:
                            reported_route = True
                            on_p2p_status(addr[0], addr[1], "P2P Direto")
                        continue

                    if data.startswith(MAGIC_ACK):
                        active_sender_addr = addr
                        using_relay = False
                        if not reported_route and on_p2p_status:
                            reported_route = True
                            on_p2p_status(addr[0], addr[1], "P2P Direto")
                        continue

                    if data in (b"DAV_RLY_ACK", b"DAV_RLY_PEER_READY"):
                        if packets_received == 0 and relay_addr:
                            using_relay = True
                            if not reported_route and on_p2p_status:
                                reported_route = True
                                on_p2p_status(relay_addr[0], relay_addr[1], "Blind Relay UDP")
                        continue

                    # 2. Validação estrita do cabeçalho binário DA-V de 32 bytes
                    if len(data) < 32:
                        continue

                    unpacked = struct.unpack("!BBBBIIQIIHH", data[:32])
                    version = unpacked[0]
                    flags = unpacked[2]
                    ssrc = unpacked[5]
                    ts_us = unpacked[6]
                    frame_id = unpacked[7]
                    payload_len = unpacked[8]
                    frag_idx = unpacked[9]
                    frag_tot = unpacked[10]

                    if (
                        version != 1
                        or ssrc != 0xDA0001
                        or frag_tot == 0
                        or frag_tot > 4096
                        or frag_idx >= frag_tot
                        or (32 + payload_len) > len(data)
                    ):
                        continue

                    now_us = int(time.time_ns() // 1000)
                    packets_received += 1
                    total_bytes += len(data)

                    if relay_addr and addr == relay_addr:
                        using_relay = True
                    else:
                        active_sender_addr = addr
                        using_relay = False

                    if not reported_route and on_p2p_status:
                        reported_route = True
                        route_name = "Blind Relay UDP" if using_relay else "P2P Direto"
                        on_p2p_status(addr[0], addr[1], route_name)

                    raw_diff = now_us - ts_us
                    if clock_offset_us is None or raw_diff < clock_offset_us:
                        clock_offset_us = raw_diff

                    latencies_ms.append(max(0.5, (raw_diff - clock_offset_us) / 1000.0))
                    enc_payload = data[32 : 32 + payload_len]

                    # Janela resiliente de remontagem fora de ordem (40 quadros / 350 ms)
                    now_t = time.perf_counter()
                    if frame_id not in pending_frames:
                        if len(pending_frames) >= 40:
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

                        is_kf = bool(frame_flags & 0x01)
                        if is_kf:
                            has_seen_keyframe = True
                        elif not has_seen_keyframe:
                            # Recebeu P-frame sem SPS/PPS/IDR inicial: pede keyframe imediato via PLI
                            mono_now = time.monotonic()
                            if mono_now - last_pli_mono >= 0.20:
                                last_pli_mono = mono_now
                                try:
                                    if using_relay and relay_addr:
                                        sock.sendto(wrap_relay_packet(clean_pin, b"R", MAGIC_PLI), relay_addr)
                                    elif active_sender_addr:
                                        sock.sendto(MAGIC_PLI, active_sender_addr)
                                except Exception:
                                    pass

                        is_encrypted = (frame_flags & 0x02) != 0
                        if is_encrypted:
                            if len(assembled_data) > len(key_vec):
                                key_vec = np.frombuffer(
                                    (key_bytes * ((len(assembled_data) // 32) + 2))[: len(assembled_data)],
                                    dtype=np.uint8,
                                )
                            frame_arr = np.frombuffer(assembled_data, dtype=np.uint8)
                            full_frame = np.bitwise_xor(frame_arr, key_vec[: len(assembled_data)]).tobytes()
                        else:
                            full_frame = assembled_data

                        if self._user_frame_callback:
                            self._user_frame_callback(full_frame, 1920, 1080, ts_us, is_kf)

                    cur_now = time.perf_counter()
                    if cur_now - last_stat_time >= 0.5:
                        elapsed = cur_now - last_stat_time
                        sec_bytes = total_bytes - last_bytes
                        frame_delta = frames_rendered - last_frames_stat
                        cur_fps = frame_delta / elapsed
                        cur_mbps = (sec_bytes * 8.0) / (elapsed * 1_000_000.0)
                        cur_lat = sum(latencies_ms[-30:]) / len(latencies_ms[-30:]) if latencies_ms else 1.5
                        if len(latencies_ms) > 120:
                            del latencies_ms[:-60]

                        if self._user_telemetry_callback:
                            self._user_telemetry_callback(
                                cur_fps, cur_mbps, cur_lat, packets_received, frames_rendered
                            )

                        try:
                            _rx_msg = json.dumps({
                                "role": "rx",
                                "fps": round(cur_fps, 2),
                                "mbps": round(cur_mbps, 2),
                                "lat": round(cur_lat, 2),
                                "frames": frames_rendered,
                                "packets": packets_received,
                            }).encode("utf-8")
                            sock.sendto(_rx_msg, ("127.0.0.1", 19901))
                        except Exception:
                            pass

                        last_stat_time = cur_now
                        last_bytes = total_bytes
                        last_frames_stat = frames_rendered

                except socket.timeout:
                    if packets_received == 0:
                        mono_now = time.monotonic()
                        # Re-sonda candidatos diretos enquanto aguarda o primeiro pacote de vídeo
                        if candidates and (mono_now - last_punch_mono >= 0.12):
                            for cip, cport, _ in candidates:
                                try:
                                    sock.sendto(syn_pkt, (cip, cport))
                                except Exception:
                                    pass
                            last_punch_mono = mono_now

                        # Após 0.85s sem tráfego direto, habilita simultaneamente o Blind Relay
                        if relay_addr and (mono_now - start_mono >= 0.85) and (mono_now - last_relay_bind_mono >= 0.35):
                            try:
                                sock.sendto(wrap_relay_packet(clean_pin, b"R", b"BIND"), relay_addr)
                            except Exception:
                                pass
                            last_relay_bind_mono = mono_now
                    continue
                except (ConnectionResetError, OSError):
                    if not self._fallback_running:
                        break
                    continue
                except Exception:
                    continue

            try:
                sock.close()
            except Exception:
                pass

        t_rec = threading.Thread(target=_receiver_loop, daemon=True, name="DAV-Receiver-Loop")
        self._fallback_threads.append(t_rec)
        t_rec.start()
        return True
