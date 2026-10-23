# -*- coding: utf-8 -*-
"""
DA-V Main Application Window
Assembles TopHeaderBar, SidebarNavigation rail, and specialized QStackedWidget views.
Integrates backend services (DavCoreEngine, LanBeaconService, TupaHealthChecker, DecodeWorker)
with responsive thread-safe Qt Signal Bridges.
"""

import sys
import os
import time
import socket
import random
import threading
from typing import Optional, List

from scripts.qt_compat import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QTimer, Signal, Slot, Qt
)

from src.ui.theme import Theme
from src.ui.bridge import EngineBridge, DecodeWorker, find_available_port
from src.ui.widgets.header import TopHeaderBar
from src.ui.widgets.sidebar import SidebarNavigation
from src.ui.views.viewer_view import ViewerView
from src.ui.views.sender_view import SenderView
from src.ui.views.tupa_view import TupaView
from src.ui.views.discovery_view import DiscoveryView
from src.ui.views.troubleshoot_view import TroubleshootView

from src.discovery.lan_beacon import LanBeaconService, get_local_ip
from src.discovery.p2p_channel import P2PChannelClient
from scripts.dav_client import DavCoreEngine
from src.telemetry.tupa_checker import TupaHealthChecker, TupaMetricsSnapshot

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DavMainWindow(QMainWindow):
    """
    Main application shell for DA-V.
    Combines TopHeaderBar, Sidebar navigation, and 5 decoupled views.
    """
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
        parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("DA-V — Distribuidor Aamplo · Video Distribution Hub")
        self.setMinimumSize(1120, 740)

        # ── Network & Identity Configuration ──
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

        # ── State Trackers ──
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

        # ── Core Engine & Bridges ──
        self.engine = DavCoreEngine()
        self.bridge = EngineBridge()

        self.bridge.frame_ready.connect(self._on_frame_rendered)
        self.bridge.telemetry_ready.connect(self._on_telemetry_updated)
        self.bridge.sender_stats.connect(self._on_sender_stats_updated)
        self.bridge.log_message.connect(self._append_log)

        # ── Dedicated Decode Worker (Keeps UDP recv loop 100% unblocked) ──
        self._decode_worker = DecodeWorker(self.bridge)
        self._decode_worker.decoded.connect(self._on_decoded_frame)
        self._decode_worker.start()

        # ── LAN Beacon Service ──
        self.peers_updated_signal.connect(self._on_peers_discovered)
        self.beacon_service = LanBeaconService(
            self.hostname, stream_port=self.default_port, pin=self.my_pin
        )
        self.beacon_service.on_peers_updated = lambda peers: self.peers_updated_signal.emit(peers)
        self.beacon_service.start()

        # ── TUPÃ Telemetry & Health Checker ──
        self.tupa_checker = TupaHealthChecker(sample_interval_sec=1.0)
        self.tupa_metrics_signal.connect(self._on_tupa_metrics_updated)
        self.target_updated_signal.connect(self._on_target_updated)
        self.tupa_checker.start(lambda snap: self.tupa_metrics_signal.emit(snap))

        # ── Build Layout & Apply Theme ──
        self.setStyleSheet(Theme.build_stylesheet())
        self._init_ui(monitor_idx)

        # ── Log Startup Status ──
        backend_tag = (
            "Backend Nativo C-ABI (dav_core.dll)"
            if self.engine.is_native_backend
            else "Backend Acelerado SIMD + NVENC RTX 4070"
        )
        self._append_log(
            "INFO",
            f"DA-V Hub inicializado em {self.local_ip}:{self.default_port} ({backend_tag})."
        )
        QTimer.singleShot(1000, self._check_firewall_status)

        # ── Automated Test Triggers ──
        if auto_recv:
            self.view_viewer.set_target("127.0.0.1", self.default_port, self.my_pin)
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

    def _init_ui(self, initial_monitor_idx: int):
        root_widget = QWidget(self)
        root_layout = QVBoxLayout(root_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── 1. Top Header Bar ──
        backend_desc = (
            "Nativo C-ABI (dav_core.dll)"
            if self.engine.is_native_backend
            else "SIMD + NVENC RTX 4070"
        )
        self.top_header = TopHeaderBar(
            local_ip=self.local_ip,
            default_port=self.default_port,
            initial_pin=self.my_pin,
            engine_tag=backend_desc,
            parent=self
        )
        self.top_header.pin_regenerated.connect(self._regenerate_pin)
        root_layout.addWidget(self.top_header)

        # ── 2. Content Row: Sidebar + Stacked Views ──
        content_container = QWidget(root_widget)
        content_layout = QHBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Sidebar Rail
        self.sidebar = SidebarNavigation(parent=content_container)
        content_layout.addWidget(self.sidebar)

        # Stacked Views Container
        self.stacked_views = QStackedWidget(content_container)
        self.stacked_views.setStyleSheet(f"background-color: {Theme.SYS['bg_canvas']};")

        # View 0: Viewer / Receiver
        self.view_viewer = ViewerView(
            initial_ip="",
            default_port=self.default_port,
            initial_pin=self.my_pin,
            parent=self.stacked_views
        )
        self.view_viewer.connect_toggled.connect(self._toggle_receiver)
        self.stacked_views.addWidget(self.view_viewer)

        # View 1: Sender / Screen Sharing
        self.view_sender = SenderView(
            initial_target_ip="",
            default_target_port=self.target_default_port,
            initial_pin=self.my_pin,
            parent=self.stacked_views
        )
        self.view_sender.send_toggled.connect(self._toggle_sender)
        self.stacked_views.addWidget(self.view_sender)

        # View 2: TUPÃ Telemetry & Benchmark
        self.view_tupa = TupaView(parent=self.stacked_views)
        self.stacked_views.addWidget(self.view_tupa)

        # View 3: LAN Discovery
        self.view_discovery = DiscoveryView(parent=self.stacked_views)
        self.view_discovery.connect_peer_requested.connect(self._quick_connect_peer)
        self.view_discovery.refresh_requested.connect(self._manual_refresh_peers)
        self.stacked_views.addWidget(self.view_discovery)

        # View 4: Troubleshooting & Logs
        self.view_troubleshoot = TroubleshootView(parent=self.stacked_views)
        self.view_troubleshoot.loopback_requested.connect(self._run_loopback_diagnostic)
        self.view_troubleshoot.fix_firewall_requested.connect(self._fix_firewall)
        self.view_troubleshoot.check_firewall_requested.connect(self._check_firewall_status)
        self.stacked_views.addWidget(self.view_troubleshoot)

        # Connect Sidebar page changes to Stacked Views and Header Mode
        self.sidebar.page_changed.connect(self._on_page_changed)
        self.top_header.set_receiver_mode(True)

        content_layout.addWidget(self.stacked_views, stretch=1)
        root_layout.addWidget(content_container, stretch=1)

        self.setCentralWidget(root_widget)

    def _on_page_changed(self, page_index: int):
        self.stacked_views.setCurrentIndex(page_index)
        self.top_header.set_receiver_mode(page_index == 0)

    # ------------------------------------------------------------------------
    # CONTROLLER: RECEIVER / VIEWER
    # ------------------------------------------------------------------------
    def _toggle_receiver(self):
        if self.is_receiving:
            self.engine.stop()
            self.is_receiving = False
            self.view_viewer.set_connection_state(False)
            self._append_log("INFO", "Receptor desconectado pelo usuário.")
        else:
            target_ip = self.view_viewer.txt_recv_ip.text().strip()
            port = self.view_viewer.spn_recv_port.value()
            pin = self.view_viewer.txt_recv_pin.text().strip()

            target_peer = None
            # P2P Universal PIN Mode: If IP is omitted, resolve peer via Rendezvous
            if not target_ip:
                self._append_log("INFO", f"[P2P] Modo PIN Universal ativo: Resolvendo '{pin}' no Rendezvous...")
                try:
                    p2p = P2PChannelClient()
                    res = p2p.resolve_receiver_target(pin, port, node_name=self.hostname)
                    if res and res.get("status") == "paired":
                        peer = res["peer"]
                        peer_target_ip = peer.get("public_ip") or peer.get("local_ip")
                        peer_target_port = int(peer.get("public_port") or peer.get("local_port"))
                        target_peer = (peer_target_ip, peer_target_port)
                        self._append_log("SUCCESS", f"[P2P WAN] Transmissor localizado: {peer.get('node_name')} em {peer_target_ip}:{peer_target_port}")
                    else:
                        self._append_log("WARN", f"[P2P] Não foi possível parear o PIN '{pin}' no Rendezvous. Verifique se o Transmissor está ativo.")
                        return
                except Exception as e:
                    self._append_log("WARN", f"[P2P] Falha ao consultar Rendezvous: {e}")
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

            success = self.engine.start_receiver(port, pin, _on_raw_frame, _on_telem, target_peer=target_peer)
            if success:
                self.is_receiving = True
                self.view_viewer.set_connection_state(True)
                mode_str = f"P2P WAN -> {target_peer[0]}:{target_peer[1]}" if not target_ip else f"LAN {target_ip}"
                self._append_log("INFO", f"Receptor ouvindo na porta UDP {port} ({mode_str} / PIN {pin})")
            else:
                self._append_log("ERROR", f"Falha ao iniciar receptor na porta {port}")

    # ------------------------------------------------------------------------
    # CONTROLLER: SENDER / SCREEN SHARING
    # ------------------------------------------------------------------------
    def _toggle_sender(self):
        if self.is_sending:
            self.engine.stop()
            self.is_sending = False
            self.view_sender.set_sending_state(False)
            self.beacon_service.update_status(False)
            self._append_log("INFO", "Compartilhamento de tela encerrado.")
        else:
            target_ip = self.view_sender.txt_send_ip.text().strip()
            target_port = self.view_sender.spn_send_port.value()
            pin = self.view_sender.txt_send_pin.text().strip()

            res_text = self.view_sender.cmb_res.currentText()
            w, h = (1280, 720) if "1280x720" in res_text else ((1920, 1080) if "1920x1080" in res_text else (640, 360))
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
                "h264_nvenc" if "H.264" in codec_text
                else ("hevc_nvenc" if "HEVC" in codec_text
                else ("raw" if "RAW" in codec_text else "jpeg"))
            )
            monitor_index = self.view_sender.cmb_monitor.currentIndex()

            def _on_sender_stats(frames_sent, fps, mbps, packets, codec="NVENC", frame_kb=24):
                self.bridge.sender_stats.emit(frames_sent, fps, mbps, packets, 75, frame_kb)

            success = self.engine.start_sender(
                target_ip, target_port, pin,
                width=w, height=h, fps=fps,
                bitrate_kbps=bitrate_kbps,
                on_sender_stats=_on_sender_stats,
                codec_type=codec_type,
                monitor_index=monitor_index
            )
            if success:
                self.is_sending = True
                if target_ip:
                    details = f"{w}x{h} @ {fps}fps [{codec_type.upper()}] -> {target_ip}:{target_port}"
                else:
                    details = f"{w}x{h} @ {fps}fps [{codec_type.upper()}] (Aguardando Receptor PIN {pin})"
                self.view_sender.set_sending_state(True, details)
                self.beacon_service.update_status(True)
                dest_str = f"{target_ip}:{target_port}" if target_ip else f"P2P WAN (PIN: {pin})"
                self._append_log("INFO", f"Transmissão iniciada ({dest_str} - {details})")

                # Background registration in Rendezvous for remote P2P PIN access
                def _bg_register_sender():
                    try:
                        p2p = P2PChannelClient()
                        def _on_receiver_paired(peer):
                            recv_ip = peer.get("public_ip") or peer.get("local_ip")
                            recv_port = int(peer.get("public_port") or peer.get("local_port") or target_port)
                            node_name = peer.get("node_name", "Receptor Remoto")
                            self.bridge.log_message.emit(
                                "SUCCESS",
                                f"[P2P WAN] Receptor conectado ({node_name} em {recv_ip}:{recv_port})! Transmitindo vídeo..."
                            )
                            self.engine.update_sender_target(recv_ip, recv_port)
                            self.target_updated_signal.emit(recv_ip, recv_port, node_name)

                        reg = p2p.register_as_sender(pin, target_port, node_name=self.hostname, on_paired_callback=_on_receiver_paired)
                        if reg:
                            self.bridge.log_message.emit("SUCCESS", f"[P2P] PIN '{pin}' registrado no Rendezvous (Aguardando Receptor remoto).")
                    except Exception as e:
                        self.bridge.log_message.emit("DEBUG", f"[P2P] Registro no Rendezvous em background ignorado: {e}")

                threading.Thread(target=_bg_register_sender, daemon=True, name=f"P2P-Reg-{pin}").start()
            else:
                self._append_log("ERROR", f"Falha ao iniciar transmissão para {target_ip}:{target_port}")

    # ------------------------------------------------------------------------
    # SLOTS & BRIDGED SIGNALS
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
        """Called from DecodeWorker.decoded signal on Qt main GUI thread."""
        self.view_viewer.video_canvas.update_frame(
            img, self.cur_fps, self.cur_mbps, self.cur_lat,
            self.pkts_count, self.frames_count
        )

    @Slot(str, int, str)
    def _on_target_updated(self, ip: str, port: int, node_name: str):
        """Called when a remote receiver pairs with this sender."""
        self.view_sender.txt_send_ip.setText(ip)
        self.view_sender.spn_send_port.setValue(port)
        res_txt = self.view_sender.cmb_res.currentText().split()[0]
        fps_txt = self.view_sender.cmb_fps.currentText().split()[0]
        details = f"{res_txt} @ {fps_txt} [P2P -> {ip}:{port}]"
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
                f"Taxa: {smooth_fps:.1f} FPS | Vazão: {mbps:.2f} Mbps | Latência: {lat:.2f} ms | Quadros: {frames} | Pacotes: {pkts}"
            )

    @Slot(int, float, float, int, int, int)
    def _on_sender_stats_updated(
        self, frames: int, fps: float, mbps: float, packets: int,
        quality: int = 75, frame_kb: int = 32
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
                f"Saída: {smooth_fps:.1f} FPS | {mbps:.2f} Mbps | Q{quality} | {frame_kb}KB/frame | Quadros: {frames} | Pacotes: {packets}"
            )

    @Slot(object)
    def _on_tupa_metrics_updated(self, snap: TupaMetricsSnapshot):
        self.view_tupa.update_tupa_metrics(snap)

    @Slot(list)
    def _on_peers_discovered(self, peers: list):
        self.view_discovery.update_peers(peers)
        active_count = len(peers)
        if active_count > 0:
            self.sidebar.buttons[3].set_badge(str(active_count))
        else:
            self.sidebar.buttons[3].set_badge("")

    def _quick_connect_peer(self, ip: str, port: int):
        self.view_viewer.set_target(ip, port)
        self.sidebar.set_active_page(0)
        self._on_page_changed(0)
        self._append_log("INFO", f"Parâmetros de {ip}:{port} carregados no visualizador.")

    def _manual_refresh_peers(self):
        self._append_log("INFO", "Disparando varredura ativa de rede (Subnet Sweep & Broadcast)...")
        self.beacon_service.trigger_subnet_sweep()
        peers = self.beacon_service.get_peers()
        self._on_peers_discovered(peers)
        if not peers:
            self._append_log("WARN", "Nenhum peer respondeu ainda. Verifique se o DA-V está aberto no outro PC e se o Firewall permite UDP.")

    def _regenerate_pin(self):
        self.my_pin = f"{random.randint(100, 999)}-{random.randint(100, 999)}"
        self.top_header.update_pin(self.my_pin)
        self.view_viewer.txt_recv_pin.setText(self.my_pin)
        self.view_sender.txt_send_pin.setText(self.my_pin)
        self.beacon_service.update_status(self.is_sending, self.my_pin)
        self._append_log("INFO", f"Novo PIN de segurança gerado: {self.my_pin}")

    def _check_firewall_status(self):
        try:
            import subprocess
            if sys.platform == "win32":
                res = subprocess.run(
                    'netsh advfirewall firewall show rule name="DA-V Video Streaming"',
                    shell=True, capture_output=True, text=True
                )
                if res.returncode == 0:
                    self._append_log("SUCCESS", "Firewall do Windows: Portas do DA-V (UDP 19000-19005) estão liberadas e ativas!")
                else:
                    self._append_log("WARN", "Firewall do Windows: Regras para UDP não encontradas. Clique no botão 'Liberar Portas no Firewall'.")
            else:
                # Linux firewall check (UFW / iptables)
                res = subprocess.run(["which", "ufw"], capture_output=True)
                if res.returncode == 0:
                    st = subprocess.run(["sudo", "-n", "ufw", "status"], capture_output=True, text=True)
                    if "19000:19005/udp" in st.stdout or "ALLOW" in st.stdout:
                        self._append_log("SUCCESS", "Firewall Linux (UFW): Portas UDP 19000-19005 liberadas!")
                        return
                self._append_log("INFO", "Firewall Linux: Para liberar portas UDP no Ubuntu/Debian, execute: 'sudo ufw allow 19000:19005/udp'")
        except Exception as e:
            self._append_log("WARN", f"Não foi possível consultar o Firewall: {e}")

    def _fix_firewall(self):
        if sys.platform == "win32":
            self._append_log("INFO", "Solicitando permissão de Administrador para liberar Firewall (UDP 19000-19005)...")
            try:
                import ctypes
                ps_script = os.path.join(_PROJECT_ROOT, "scripts", "setup_firewall.ps1")
                params = f'-NoProfile -ExecutionPolicy Bypass -File "{ps_script}"'
                ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", params, None, 1)
                self._append_log("SUCCESS", "Janela de elevação aberta. Confirme 'Sim' para aplicar as regras.")
                QTimer.singleShot(4000, self._check_firewall_status)
            except Exception as e:
                self._append_log("ERROR", f"Falha ao solicitar elevação: {e}")
        else:
            self._append_log("INFO", "No Linux, execute no terminal: 'sudo ufw allow 19000:19005/udp'")

    def _run_loopback_diagnostic(self):
        self._append_log("INFO", "Disparando teste rápido de Loopback...")
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
        """Cleanly releases all background threads, sockets, and hardware workers."""
        if hasattr(self, 'tupa_checker') and self.tupa_checker:
            self.tupa_checker.stop()
        if hasattr(self, '_decode_worker') and self._decode_worker:
            self._decode_worker.stop()
        if hasattr(self, 'beacon_service') and self.beacon_service:
            self.beacon_service.stop()
        if hasattr(self, 'engine') and self.engine:
            self.engine.stop()
        event.accept()
