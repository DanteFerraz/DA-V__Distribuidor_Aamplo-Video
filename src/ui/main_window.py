# -*- coding: utf-8 -*-
"""
DA-V — Janela Principal da Aplicação (v2.0)
Autor: Dante Ferraz (MonoTech)

Integra o cabeçalho de controle, a barra de navegação lateral e as cinco visões
operacionais (Receptor, Transmissor, Diagnóstico TUPÃ, Descoberta LAN e Logs)
ao motor unificado de transporte P2P Single-Socket e decodificação assíncrona.
"""

import os
import sys
import time
import random
import socket
import platform
import threading
from typing import Optional

from scripts.qt_compat import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    Qt,
    QTimer,
    QVBoxLayout,
    QWidget,
    Signal,
    Slot,
)

from src.ui.theme import Theme
from src.ui.bridge import DecodeWorker, EngineBridge, find_available_port
from src.ui.widgets.header import TopHeaderBar
from src.ui.widgets.sidebar import SidebarNavigation
from src.ui.views.viewer_view import ViewerView
from src.ui.views.sender_view import SenderView
from src.ui.views.tupa_view import TupaView
from src.ui.views.discovery_view import DiscoveryView
from src.ui.views.troubleshoot_view import TroubleshootView

from src.discovery.lan_beacon import LanBeaconService, get_local_ip
from src.discovery.p2p_channel import P2PChannelClient, normalize_pin
from scripts.dav_client import DavCoreEngine
from src.telemetry.tupa_checker import TupaHealthChecker, TupaMetricsSnapshot

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _detect_engine_badge(is_native: bool) -> str:
    if is_native:
        return "Nativo C-ABI (dav_core)"
    os_tag = "Windows" if sys.platform == "win32" else f"Linux ({platform.machine()})"
    return f"Unificado SIMD + H.264 ULL · {os_tag}"


class DavMainWindow(QMainWindow):
    """Shell principal da interface desktop PySide6 do DA-V."""

    peers_updated_signal = Signal(list)
    tupa_metrics_signal = Signal(object)
    target_updated_signal = Signal(str, int, str)

    def __init__(
        self,
        custom_port: Optional[int] = None,
        custom_target_port: Optional[int] = None,
        auto_recv: bool = False,
        auto_send: bool = False,
        monitor_idx: int = 1,
        custom_pin: Optional[str] = None,
        p2p_uri_mode: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("DA-V v3.1.0 — Distribuidor Amplo de Vídeo")
        self.setMinimumSize(1120, 740)

        self.local_ip = get_local_ip()
        self.hostname = socket.gethostname()
        self.default_port = custom_port if custom_port else find_available_port(9000)
        self.target_default_port = custom_target_port if custom_target_port else (
            9002 if self.default_port == 9000 else 9000
        )

        if custom_pin:
            self.my_pin = custom_pin
        elif auto_recv or auto_send:
            self.my_pin = "777-888"
        else:
            self.my_pin = f"{random.randint(100, 999)}-{random.randint(100, 999)}"

        self.is_receiving = False
        self.is_sending = False
        self.cur_fps = 0.0
        self.cur_mbps = 0.0
        self.cur_lat = 0.0
        self.pkts_count = 0
        self.frames_count = 0
        self._last_rx_log_time = 0.0
        self._last_rx_log_frames = 0
        self._last_tx_log_time = 0.0
        self._last_tx_log_frames = 0
        self._active_p2p_client: Optional[P2PChannelClient] = None

        self.engine = DavCoreEngine()
        self.bridge = EngineBridge()

        self.bridge.frame_ready.connect(self._on_frame_rendered)
        self.bridge.telemetry_ready.connect(self._on_telemetry_updated)
        self.bridge.sender_stats.connect(self._on_sender_stats_updated)
        self.bridge.log_message.connect(self._append_log)

        self._decode_worker = DecodeWorker(self.bridge)
        self._decode_worker.decoded.connect(self._on_decoded_frame)
        self._decode_worker.start()

        self.peers_updated_signal.connect(self._on_peers_discovered)
        self.beacon_service = LanBeaconService(
            self.hostname, stream_port=self.default_port, pin=self.my_pin
        )
        self.beacon_service.on_peers_updated = lambda peers: self.peers_updated_signal.emit(peers)
        self.beacon_service.start()

        self.tupa_checker = TupaHealthChecker(sample_interval_sec=1.0)
        self.tupa_metrics_signal.connect(self._on_tupa_metrics_updated)
        self.target_updated_signal.connect(self._on_target_updated)
        self.tupa_checker.start(lambda snap: self.tupa_metrics_signal.emit(snap))

        self.setStyleSheet(Theme.build_stylesheet())
        self._init_ui()

        backend_tag = _detect_engine_badge(self.engine.is_native_backend)
        self._append_log(
            "INFO",
            f"DA-V v3.1.0 pronto em {self.local_ip}:{self.default_port} ({backend_tag}).",
        )
        QTimer.singleShot(1000, self._check_firewall_status)

        if auto_recv:
            recv_auto_ip = "" if p2p_uri_mode else "127.0.0.1"
            self.view_viewer.set_target(recv_auto_ip, self.default_port, self.my_pin)
            self.sidebar.set_active_page(0)
            self._on_page_changed(0)
            QTimer.singleShot(600, self._toggle_receiver)

        if auto_send:
            self.view_sender.txt_send_ip.setText("127.0.0.1")
            self.view_sender.spn_send_port.setValue(self.target_default_port)
            self.view_sender.txt_send_pin.setText(self.my_pin)
            if monitor_idx < self.view_sender.cmb_monitor.count():
                self.view_sender.cmb_monitor.setCurrentIndex(monitor_idx)
            self.sidebar.set_active_page(1)
            self._on_page_changed(1)
            QTimer.singleShot(800, self._toggle_sender)

    def _init_ui(self):
        root_widget = QWidget(self)
        root_layout = QVBoxLayout(root_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        backend_desc = _detect_engine_badge(self.engine.is_native_backend)
        self.top_header = TopHeaderBar(
            local_ip=self.local_ip,
            default_port=self.default_port,
            initial_pin=self.my_pin,
            engine_tag=backend_desc,
            parent=self,
        )
        self.top_header.pin_regenerated.connect(self._regenerate_pin)
        root_layout.addWidget(self.top_header)

        content_container = QWidget(root_widget)
        content_layout = QHBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.sidebar = SidebarNavigation(parent=content_container)
        content_layout.addWidget(self.sidebar)

        self.stacked_views = QStackedWidget(content_container)
        self.stacked_views.setStyleSheet(f"background-color: {Theme.SYS['bg_canvas']};")

        self.view_viewer = ViewerView(
            initial_ip="",
            default_port=self.default_port,
            initial_pin=self.my_pin,
            parent=self.stacked_views,
        )
        self.view_viewer.connect_toggled.connect(self._toggle_receiver)
        self.stacked_views.addWidget(self.view_viewer)

        self.view_sender = SenderView(
            initial_target_ip="",
            default_target_port=self.target_default_port,
            initial_pin=self.my_pin,
            parent=self.stacked_views,
        )
        self.view_sender.send_toggled.connect(self._toggle_sender)
        self.stacked_views.addWidget(self.view_sender)

        self.view_tupa = TupaView(parent=self.stacked_views)
        self.stacked_views.addWidget(self.view_tupa)

        self.view_discovery = DiscoveryView(parent=self.stacked_views)
        self.view_discovery.connect_peer_requested.connect(self._quick_connect_peer)
        self.view_discovery.refresh_requested.connect(self._manual_refresh_peers)
        self.stacked_views.addWidget(self.view_discovery)

        self.view_troubleshoot = TroubleshootView(parent=self.stacked_views)
        self.view_troubleshoot.loopback_requested.connect(self._run_loopback_diagnostic)
        self.view_troubleshoot.fix_firewall_requested.connect(self._fix_firewall)
        self.view_troubleshoot.check_firewall_requested.connect(self._check_firewall_status)
        self.stacked_views.addWidget(self.view_troubleshoot)

        self.sidebar.page_changed.connect(self._on_page_changed)
        self.top_header.set_receiver_mode(True)

        content_layout.addWidget(self.stacked_views, stretch=1)
        root_layout.addWidget(content_container, stretch=1)
        self.setCentralWidget(root_widget)

    def _on_page_changed(self, page_index: int):
        self.stacked_views.setCurrentIndex(page_index)
        self.top_header.set_receiver_mode(page_index == 0)

    # ------------------------------------------------------------------------
    # CONTROLADOR DO RECEPTOR (VIEWER) — P2P SINGLE-SOCKET & LAN DIRETO
    # ------------------------------------------------------------------------
    def _toggle_receiver(self):
        if self.is_receiving:
            self.engine.stop()
            self.is_receiving = False
            self.view_viewer.set_connection_state(False)
            self._append_log("INFO", "Receptor desconectado pelo usuário.")
            return

        target_ip = self.view_viewer.txt_recv_ip.text().strip()
        port = self.view_viewer.spn_recv_port.value()
        pin = self.view_viewer.txt_recv_pin.text().strip()
        clean_pin = normalize_pin(pin)

        def _is_valid_ipv4(ip_str: str) -> bool:
            parts = ip_str.split(".")
            return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)

        if target_ip and not _is_valid_ipv4(target_ip):
            if clean_pin:
                self._append_log(
                    "WARN",
                    f"[P2P] IP '{target_ip}' inválido ou incompleto. Alternando para Modo PIN Universal ('{pin}')...",
                )
                target_ip = ""
                self.view_viewer.txt_recv_ip.setText("")
            else:
                self._append_log(
                    "ERROR",
                    f"O IP '{target_ip}' é inválido. Informe um IPv4 completo ou deixe vazio e use o PIN.",
                )
                return

        target_peer = None
        peer_info = None
        my_pub_ip = None
        relay_info = None
        eff_bind_port = port

        if not target_ip:
            if not clean_pin:
                self._append_log("ERROR", "Informe o PIN de Acesso (6 dígitos) ou o IP do Transmissor.")
                return

            self._append_log("INFO", f"[P2P] Alocando socket UDP e consultando STUN RFC 5389 para o PIN '{pin}'...")
            p2p = P2PChannelClient()
            recv_ep = self.engine.prepare_receiver_socket(
                port, rendezvous_host=p2p.rendezvous_host, stun_port=p2p.stun_port
            )
            eff_bind_port = int(recv_ep.get("local_port") or port)
            my_pub_ip = str(recv_ep.get("public_ip") or "")

            res = p2p.resolve_receiver_target(
                clean_pin,
                eff_bind_port,
                node_name=self.hostname,
                endpoint_info=recv_ep,
            )

            if res and res.get("status") == "paired":
                peer_info = res["peer"]
                relay_info = res.get("relay")
                my_pub_ip = str(res.get("your_public_ip") or my_pub_ip or "")
                peer_name = peer_info.get("node_name", "Transmissor")
                self._append_log(
                    "SUCCESS",
                    f"[P2P] PIN '{pin}' pareado com '{peer_name}' (WAN {peer_info.get('public_ip')}:{peer_info.get('public_port')} | LAN {peer_info.get('local_ip')}:{peer_info.get('local_port')}).",
                )
            else:
                local_peer = self.beacon_service.find_peer_by_pin(clean_pin)
                if local_peer:
                    peer_target_ip = local_peer["ip"]
                    peer_target_port = int(local_peer.get("port", port))
                    target_peer = (peer_target_ip, peer_target_port)
                    self._append_log(
                        "SUCCESS",
                        f"[P2P Local] Transmissor localizado via Beacon LAN: {local_peer.get('node_name')} em {peer_target_ip}:{peer_target_port}",
                    )
                else:
                    self.engine._close_prepared_recv_sock()
                    self._append_log(
                        "WARN",
                        f"[P2P] PIN '{pin}' não encontrado no servidor Rendezvous nem na rede local. Confirme se o Transmissor já iniciou o compartilhamento.",
                    )
                    return
        else:
            target_peer = (target_ip, port)

        def _on_raw_frame(frame_data, width, height, ts, is_kf):
            if isinstance(frame_data, bytes):
                self._decode_worker.submit(frame_data, width, height)

        def _on_telem(fps, mbps, lat, pkts, frames):
            self.cur_fps = fps
            self.cur_mbps = mbps
            self.cur_lat = lat
            self.pkts_count = pkts
            self.frames_count = frames
            self.bridge.telemetry_ready.emit(fps, mbps, lat, pkts, frames)

        def _on_rx_p2p_status(remote_ip: str, remote_port: int, route_label: str):
            self.bridge.log_message.emit(
                "SUCCESS",
                f"[{route_label}] Fluxo estabelecido com {remote_ip}:{remote_port}.",
            )

        success = self.engine.start_receiver(
            eff_bind_port,
            pin,
            _on_raw_frame,
            _on_telem,
            target_peer=target_peer,
            peer_info=peer_info,
            my_public_ip=my_pub_ip or None,
            relay_info=relay_info,
            on_p2p_status=_on_rx_p2p_status,
        )
        if success:
            self.is_receiving = True
            self.view_viewer.set_connection_state(True)
            mode_str = f"PIN Universal {pin}" if not target_ip else f"LAN Direto {target_ip}:{port}"
            self._append_log("INFO", f"Receptor ativo na porta UDP {eff_bind_port} ({mode_str}).")
        else:
            self._append_log("ERROR", f"Não foi possível iniciar o Receptor na porta UDP {eff_bind_port}.")

    # ------------------------------------------------------------------------
    # CONTROLADOR DO TRANSMISSOR (SENDER) — P2P SINGLE-SOCKET & STANDBY
    # ------------------------------------------------------------------------
    def _toggle_sender(self):
        if self.is_sending:
            if self._active_p2p_client:
                self._active_p2p_client.stop()
                self._active_p2p_client = None
            self.engine.stop()
            self.is_sending = False
            self.view_sender.set_sending_state(False)
            self.beacon_service.update_status(False)
            self._append_log("INFO", "Compartilhamento de tela encerrado.")
            return

        target_ip = self.view_sender.txt_send_ip.text().strip()
        target_port = self.view_sender.spn_send_port.value()
        pin = self.view_sender.txt_send_pin.text().strip()

        res_text = self.view_sender.cmb_res.currentText()
        w, h = (
            (1280, 720)
            if "1280x720" in res_text
            else ((1920, 1080) if "1920x1080" in res_text else (640, 360))
        )
        fps = 60 if "60 FPS" in self.view_sender.cmb_fps.currentText() else 30

        bitrate_text = self.view_sender.cmb_bitrate.currentText()
        bitrate_kbps = 12000
        if "25000" in bitrate_text:
            bitrate_kbps = 25000
        elif "16000" in bitrate_text:
            bitrate_kbps = 16000
        elif "8000" in bitrate_text:
            bitrate_kbps = 8000

        codec_text = self.view_sender.cmb_codec.currentText()
        codec_type = (
            "h264_nvenc"
            if "H.264" in codec_text
            else ("hevc_nvenc" if "HEVC" in codec_text else ("raw" if "RAW" in codec_text else "jpeg"))
        )
        monitor_index = self.view_sender.cmb_monitor.currentIndex()

        # Em modo P2P (sem IP fixo), vincula na porta padrão anunciada do host
        sender_bind_port = self.default_port if not target_ip else target_port

        def _on_sender_stats(frames_sent, cur_fps, cur_mbps, packets, codec="NVENC", frame_kb=24):
            self.bridge.sender_stats.emit(frames_sent, cur_fps, cur_mbps, packets, 75, frame_kb)

        def _on_tx_p2p_locked(remote_ip: str, remote_port: int, mode_tag: str):
            self.bridge.log_message.emit(
                "SUCCESS",
                f"[{mode_tag}] Túnel de transmissão confirmado -> {remote_ip}:{remote_port}",
            )
            self.target_updated_signal.emit(remote_ip, remote_port, mode_tag)

        success = self.engine.start_sender(
            target_ip,
            target_port,
            pin,
            width=w,
            height=h,
            fps=fps,
            bitrate_kbps=bitrate_kbps,
            on_sender_stats=_on_sender_stats,
            codec_type=codec_type,
            monitor_index=monitor_index,
            bind_port=sender_bind_port,
            on_p2p_event=_on_tx_p2p_locked,
        )
        if not success:
            self._append_log("ERROR", f"Falha ao iniciar o Transmissor ({target_ip}:{target_port}).")
            return

        self.is_sending = True
        if target_ip:
            details = f"{w}x{h} @ {fps}fps [{codec_type.upper()}] -> {target_ip}:{target_port}"
        else:
            details = f"{w}x{h} @ {fps}fps [{codec_type.upper()}] (Standby · Aguardando PIN {pin})"
        self.view_sender.set_sending_state(True, details)
        self.beacon_service.update_status(True, pin=pin)
        dest_str = f"{target_ip}:{target_port}" if target_ip else f"Modo P2P Universal (PIN: {pin})"
        self._append_log("INFO", f"Transmissor iniciado ({dest_str}).")

        # Registra no Rendezvous usando o endpoint STUN descoberto pelo próprio socket do Sender Worker
        def _bg_register_sender():
            try:
                ep_info = self.engine.wait_sender_endpoint(timeout=3.0)
                if not self.is_sending:
                    return

                p2p = P2PChannelClient()
                self._active_p2p_client = p2p
                clean_pin = normalize_pin(pin)
                eff_local_port = int((ep_info or {}).get("local_port") or sender_bind_port)
                if eff_local_port != self.beacon_service.stream_port:
                    self.beacon_service.stream_port = eff_local_port

                reg_holder = {}

                def _on_receiver_paired(peer: dict):
                    my_pub_ip = reg_holder.get("your_public_ip") or (ep_info or {}).get("public_ip")
                    node_name = peer.get("node_name", "Receptor Remoto")
                    self.bridge.log_message.emit(
                        "INFO",
                        f"[P2P] Receptor '{node_name}' solicitou conexão via PIN '{pin}'. Iniciando Hole-Punching...",
                    )
                    self.engine.pair_sender_peer(
                        peer_info=peer,
                        my_public_ip=str(my_pub_ip) if my_pub_ip else None,
                        relay_info=peer.get("_relay"),
                    )

                reg = p2p.register_as_sender(
                    clean_pin,
                    eff_local_port,
                    node_name=self.hostname,
                    on_paired_callback=_on_receiver_paired,
                    endpoint_info=ep_info,
                )
                if reg:
                    reg_holder.update(reg)
                    pub_ep_str = f"{reg.get('your_public_ip')}:{(ep_info or {}).get('public_port', eff_local_port)}"
                    nat_str = (ep_info or {}).get("nat_type", "auto")
                    self.bridge.log_message.emit(
                        "SUCCESS",
                        f"[P2P] PIN '{pin}' ativo no Rendezvous (Endpoint Público: {pub_ep_str} · NAT: {nat_str}).",
                    )
                else:
                    self.bridge.log_message.emit(
                        "WARN",
                        f"[P2P] Servidor Rendezvous indisponível no momento; pareamento por PIN permanece ativo na rede local (Beacon LAN).",
                    )
            except Exception as exc:
                self.bridge.log_message.emit("DEBUG", f"[P2P] Aviso no registro assíncrono: {exc}")

        threading.Thread(target=_bg_register_sender, daemon=True, name=f"P2P-Reg-{pin}").start()

    # ------------------------------------------------------------------------
    # SINAIS E ATUALIZAÇÕES DE TELEMETRIA DA INTERFACE
    # ------------------------------------------------------------------------
    @Slot(object, float, float, float, int, int)
    def _on_frame_rendered(self, img, fps: float, mbps: float, lat: float, pkts: int, frames: int):
        self.cur_fps = fps
        self.cur_mbps = mbps
        self.cur_lat = lat
        self.pkts_count = pkts
        self.frames_count = frames
        self.view_viewer.video_canvas.update_frame(img, fps, mbps, lat, pkts, frames)
        self.view_tupa.cur_fps = fps

    @Slot(object)
    def _on_decoded_frame(self, img):
        self.view_viewer.video_canvas.update_frame(
            img, self.cur_fps, self.cur_mbps, self.cur_lat,
            self.pkts_count, self.frames_count,
        )

    @Slot(str, int, str)
    def _on_target_updated(self, ip: str, port: int, mode_tag: str):
        self.view_sender.txt_send_ip.setText(ip)
        self.view_sender.spn_send_port.setValue(port)
        res_txt = self.view_sender.cmb_res.currentText().split()[0]
        fps_txt = self.view_sender.cmb_fps.currentText().split()[0]
        details = f"{res_txt} @ {fps_txt} [{mode_tag} -> {ip}:{port}]"
        self.view_sender.set_sending_state(True, details)

    @Slot(float, float, float, int, int)
    def _on_telemetry_updated(self, fps: float, mbps: float, lat: float, pkts: int, frames: int):
        self.cur_fps = fps
        self.cur_mbps = mbps
        self.cur_lat = lat
        self.pkts_count = pkts
        self.frames_count = frames
        self.view_viewer.video_canvas.update_telemetry_only(fps, mbps, lat, pkts, frames)
        self.view_tupa.cur_fps = fps

        now = time.perf_counter()
        if now - self._last_rx_log_time >= 2.0:
            elapsed = now - self._last_rx_log_time
            d_frames = frames - self._last_rx_log_frames
            smooth_fps = d_frames / elapsed if elapsed > 0 else fps
            self._last_rx_log_time = now
            self._last_rx_log_frames = frames
            self._append_log(
                "TELEMETRY-RX",
                f"Recepção: {smooth_fps:.1f} FPS | {mbps:.2f} Mbps | Latência: {lat:.2f} ms | Quadros: {frames} | Pacotes: {pkts}",
            )

    @Slot(int, float, float, int, int, int)
    def _on_sender_stats_updated(
        self, frames: int, fps: float, mbps: float, packets: int,
        quality: int = 75, frame_kb: int = 32,
    ):
        self.cur_fps = fps
        self.cur_mbps = mbps
        self.frames_count = frames
        self.pkts_count = packets

        self.view_sender.update_stats(fps, mbps, frames, packets)
        self.view_viewer.video_canvas.sender_quality = quality
        self.view_viewer.video_canvas.sender_frame_kb = frame_kb
        self.view_tupa.cur_fps = fps

        now = time.perf_counter()
        if now - self._last_tx_log_time >= 2.0:
            elapsed = now - self._last_tx_log_time
            d_frames = frames - self._last_tx_log_frames
            smooth_fps = d_frames / elapsed if elapsed > 0 else fps
            self._last_tx_log_time = now
            self._last_tx_log_frames = frames
            self._append_log(
                "TELEMETRY-TX",
                f"Envio: {smooth_fps:.1f} FPS | {mbps:.2f} Mbps | {frame_kb} KB/quadro | Quadros: {frames} | Pacotes: {packets}",
            )

    @Slot(object)
    def _on_tupa_metrics_updated(self, snap: TupaMetricsSnapshot):
        self.view_tupa.update_tupa_metrics(snap)

    @Slot(list)
    def _on_peers_discovered(self, peers: list):
        self.view_discovery.update_peers(peers)
        active_count = len(peers)
        self.sidebar.buttons[3].set_badge(str(active_count) if active_count > 0 else "")

    def _quick_connect_peer(self, ip: str, port: int):
        self.view_viewer.set_target(ip, port)
        self.sidebar.set_active_page(0)
        self._on_page_changed(0)
        self._append_log("INFO", f"Conectando diretamente a {ip}:{port} na rede local...")
        QTimer.singleShot(150, self._toggle_receiver)

    def _manual_refresh_peers(self):
        self._append_log("INFO", "Executando varredura ativa na sub-rede local (Beacon UDP 9005)...")
        self.beacon_service.trigger_subnet_sweep()
        peers = self.beacon_service.get_peers()
        self._on_peers_discovered(peers)
        if not peers:
            self._append_log("WARN", "Nenhum host ativo respondeu na sub-rede local.")

    def _regenerate_pin(self):
        self.my_pin = f"{random.randint(100, 999)}-{random.randint(100, 999)}"
        self.top_header.update_pin(self.my_pin)
        self.view_viewer.txt_recv_pin.setText(self.my_pin)
        self.view_sender.txt_send_pin.setText(self.my_pin)
        self.beacon_service.update_status(self.is_sending, self.my_pin)
        self._append_log("INFO", f"Novo código PIN gerado: {self.my_pin}")

    def _check_firewall_status(self):
        try:
            import subprocess
            if sys.platform == "win32":
                res = subprocess.run(
                    'netsh advfirewall firewall show rule name="DA-V Video Streaming"',
                    shell=True,
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0:
                    self._append_log(
                        "SUCCESS",
                        "Windows Firewall: Regras de entrada UDP (9000-9020 / 9005) ativas.",
                    )
                else:
                    self._append_log(
                        "WARN",
                        "Windows Firewall: Regra UDP não encontrada. Use 'Liberar Portas no Firewall' na aba Troubleshooting.",
                    )
            else:
                res = subprocess.run(["which", "ufw"], capture_output=True)
                if res.returncode == 0:
                    st = subprocess.run(["sudo", "-n", "ufw", "status"], capture_output=True, text=True)
                    if "9000:9020/udp" in st.stdout or "ALLOW" in st.stdout:
                        self._append_log("SUCCESS", "Firewall Linux (UFW): Portas UDP 9000-9020 liberadas.")
                        return
                self._append_log(
                    "INFO",
                    "Linux: Caso utilize UFW ativo, libere as portas com 'sudo ufw allow 9000:9020/udp'.",
                )
        except Exception as exc:
            self._append_log("WARN", f"Verificação de Firewall ignorada: {exc}")

    def _fix_firewall(self):
        if sys.platform == "win32":
            self._append_log("INFO", "Solicitando elevação UAC para liberar portas UDP 9000-9020 e 9005...")
            try:
                import ctypes
                ps_script = os.path.join(_PROJECT_ROOT, "scripts", "setup_firewall.ps1")
                params = f'-NoProfile -ExecutionPolicy Bypass -File "{ps_script}"'
                ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", params, None, 1)
                self._append_log("SUCCESS", "Confirme a janela de Administrador para concluir a liberação.")
                QTimer.singleShot(4000, self._check_firewall_status)
            except Exception as exc:
                self._append_log("ERROR", f"Falha ao abrir configurador de Firewall: {exc}")
        else:
            self._append_log("INFO", "No Linux, execute: sudo ufw allow 9000:9020/udp && sudo ufw allow 9005/udp")

    def _run_loopback_diagnostic(self):
        self._append_log("INFO", "Iniciando autodiagnóstico de Loopback em 127.0.0.1...")
        self.view_viewer.set_target("127.0.0.1", self.default_port, self.my_pin)
        self.view_sender.txt_send_ip.setText("127.0.0.1")
        self.view_sender.spn_send_port.setValue(self.default_port)
        self.view_sender.txt_send_pin.setText(self.my_pin)
        self._toggle_receiver()
        time.sleep(0.1)
        self._toggle_sender()

    def _append_log(self, level: str, text: str):
        self.view_troubleshoot.append_log(level, text)

    def closeEvent(self, event):
        if self._active_p2p_client:
            self._active_p2p_client.stop()
        if hasattr(self, "tupa_checker") and self.tupa_checker:
            self.tupa_checker.stop()
        if hasattr(self, "_decode_worker") and self._decode_worker:
            self._decode_worker.stop()
        if hasattr(self, "beacon_service") and self.beacon_service:
            self.beacon_service.stop()
        if hasattr(self, "engine") and self.engine:
            self.engine.stop()
        event.accept()
