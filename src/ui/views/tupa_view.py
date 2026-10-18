# -*- coding: utf-8 -*-
"""
DA-V TUPÃ System Telemetry & Live Benchmark View
Real-time hardware observability (AMD Ryzen 12-core SMT, RAM, DA-V process footprint, and stage latencies).
"""

import time
import socket
import threading
import json
import statistics

from scripts.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QProgressBar, QGroupBox, QFrame, QTimer, Qt, Slot
)
from src.ui.theme import Theme
from src.telemetry.tupa_checker import TupaMetricsSnapshot


class TupaView(QWidget):
    """View dedicated to TUPÃ hardware observability and pipeline latency benchmarking."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cur_fps = 0.0

        # Stage probe collector data
        self._probe_stage_samples = {
            "capture": [], "encode": [], "send": [],
            "recv": [], "decode": [], "render": [],
        }
        self._probe_lock = threading.Lock()
        self._bench_fps_history = []

        self._init_ui()
        self._start_probe_collector()

        # Update timer for live benchmark bars (every 1 second)
        self._bench_timer = QTimer(self)
        self._bench_timer.setInterval(1000)
        self._bench_timer.timeout.connect(self._update_bench_panel)
        self._bench_timer.start()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD)
        layout.setSpacing(Theme.SPACE_MD)

        # ── 1. Health Status Banner ──
        self.tupa_health_card = QFrame()
        self.tupa_health_card.setStyleSheet(f"""
            QFrame {{
                background-color: {Theme.SYS["bg_surface_card"]};
                border-radius: {Theme.RADIUS_MD}px;
                border: 1px solid {Theme.SYS["status_success"]};
            }}
        """)
        health_layout = QHBoxLayout(self.tupa_health_card)
        health_layout.setContentsMargins(Theme.SPACE_LG, Theme.SPACE_MD, Theme.SPACE_LG, Theme.SPACE_MD)

        v_info = QVBoxLayout()
        self.lbl_tupa_health_badge = QLabel("SAÚDE DO SISTEMA: ÓTIMO")
        self.lbl_tupa_health_badge.setStyleSheet(f"font-size: 14px; font-weight: 800; color: {Theme.SYS['status_success']};")
        self.lbl_tupa_health_desc = QLabel("Sistema e hardware operando em condições ideais para 60-120 FPS.")
        self.lbl_tupa_health_desc.setStyleSheet(f"font-size: 12px; color: {Theme.SYS['text_muted']};")
        v_info.addWidget(self.lbl_tupa_health_badge)
        v_info.addWidget(self.lbl_tupa_health_desc)
        health_layout.addLayout(v_info)
        health_layout.addStretch()

        lbl_tupa_tag = QLabel("TUPÃ TELEMETRY v2.0")
        lbl_tupa_tag.setStyleSheet(f"""
            background: {Theme.SYS["bg_canvas"]};
            padding: 6px 14px;
            border-radius: 6px;
            font-weight: 800;
            color: {Theme.SYS["accent_primary"]};
            border: 1px solid {Theme.SYS["border_subtle"]};
        """)
        health_layout.addWidget(lbl_tupa_tag)
        layout.addWidget(self.tupa_health_card)

        # ── 2. Hardware Resource Grid ──
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(Theme.SPACE_MD)

        # Left Column: CPU & 12 Cores
        cpu_box = QGroupBox("Processador AMD Ryzen (Carga Global e 12 Núcleos)")
        cpu_layout = QVBoxLayout(cpu_box)
        cpu_layout.setContentsMargins(Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD, Theme.SPACE_MD)

        top_cpu = QHBoxLayout()
        top_cpu.addWidget(QLabel("Carga Global da CPU:"))
        self.lbl_cpu_global = QLabel("0.0%")
        self.lbl_cpu_global.setStyleSheet(f"font-weight: 800; color: {Theme.SYS['accent_primary']};")
        top_cpu.addWidget(self.lbl_cpu_global)
        top_cpu.addStretch()
        cpu_layout.addLayout(top_cpu)

        self.pbar_cpu_global = QProgressBar()
        self.pbar_cpu_global.setRange(0, 100)
        self.pbar_cpu_global.setValue(0)
        self.pbar_cpu_global.setStyleSheet(f"""
            QProgressBar {{ height: 14px; border-radius: 4px; background: {Theme.SYS["bg_canvas"]}; text-align: center; }}
            QProgressBar::chunk {{ background: {Theme.SYS["accent_primary"]}; border-radius: 4px; }}
        """)
        cpu_layout.addWidget(self.pbar_cpu_global)

        cpu_layout.addWidget(QLabel("Uso Individual por Núcleo:"))
        cores_grid = QGridLayout()
        cores_grid.setSpacing(6)
        self.pbar_cores = []
        self.lbl_cores = []
        for i in range(12):
            lbl_c = QLabel(f"C{i+1}: 0%")
            lbl_c.setStyleSheet(f"font-size: 11px; color: {Theme.SYS['text_muted']};")
            pb = QProgressBar()
            pb.setRange(0, 100)
            pb.setValue(0)
            pb.setTextVisible(False)
            pb.setFixedHeight(8)
            pb.setStyleSheet(f"""
                QProgressBar {{ border-radius: 3px; background: {Theme.SYS["bg_canvas"]}; }}
                QProgressBar::chunk {{ background: {Theme.SYS["status_success"]}; border-radius: 3px; }}
            """)
            row = i % 6
            col = (i // 6) * 2
            cores_grid.addWidget(lbl_c, row, col)
            cores_grid.addWidget(pb, row, col + 1)
            self.lbl_cores.append(lbl_c)
            self.pbar_cores.append(pb)
        cpu_layout.addLayout(cores_grid)
        cards_layout.addWidget(cpu_box, stretch=1)

        # Right Column: RAM, Process Footprint & Network I/O
        right_box = QVBoxLayout()
        right_box.setSpacing(Theme.SPACE_MD)

        mem_group = QGroupBox("Memória RAM do Sistema")
        mem_layout = QVBoxLayout(mem_group)
        mem_top = QHBoxLayout()
        mem_top.addWidget(QLabel("Uso de RAM:"))
        self.lbl_ram_text = QLabel("0.0 GB / 16.0 GB (0%)")
        self.lbl_ram_text.setStyleSheet(f"font-weight: 800; color: {Theme.SYS['status_info']};")
        mem_top.addWidget(self.lbl_ram_text)
        mem_top.addStretch()
        mem_layout.addLayout(mem_top)

        self.pbar_ram = QProgressBar()
        self.pbar_ram.setRange(0, 100)
        self.pbar_ram.setValue(0)
        self.pbar_ram.setStyleSheet(f"""
            QProgressBar {{ height: 14px; border-radius: 4px; background: {Theme.SYS["bg_canvas"]}; text-align: center; }}
            QProgressBar::chunk {{ background: {Theme.SYS["status_info"]}; border-radius: 4px; }}
        """)
        mem_layout.addWidget(self.pbar_ram)
        right_box.addWidget(mem_group)

        # Process Footprint
        proc_group = QGroupBox("Pegada dos Processos DA-V")
        proc_layout = QGridLayout(proc_group)
        self.lbl_proc_gui_ram = QLabel("Interface GUI: -- MB")
        self.lbl_proc_gui_cpu = QLabel("Interface CPU: --%")
        self.lbl_proc_snd_ram = QLabel("Transmissor: -- MB")
        self.lbl_proc_snd_cpu = QLabel("Transmissor CPU: --%")

        for l in (self.lbl_proc_gui_ram, self.lbl_proc_gui_cpu, self.lbl_proc_snd_ram, self.lbl_proc_snd_cpu):
            l.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {Theme.SYS['text_primary']};")

        proc_layout.addWidget(self.lbl_proc_gui_ram, 0, 0)
        proc_layout.addWidget(self.lbl_proc_gui_cpu, 0, 1)
        proc_layout.addWidget(self.lbl_proc_snd_ram, 1, 0)
        proc_layout.addWidget(self.lbl_proc_snd_cpu, 1, 1)
        right_box.addWidget(proc_group)

        # Network I/O
        net_group = QGroupBox("Tráfego de Rede Local (I/O)")
        net_layout = QHBoxLayout(net_group)
        self.lbl_net_tx = QLabel("Envio: 0.0 KB/s")
        self.lbl_net_rx = QLabel("Recepção: 0.0 KB/s")
        self.lbl_net_tx.setStyleSheet(f"font-weight: 700; color: {Theme.SYS['status_success']};")
        self.lbl_net_rx.setStyleSheet(f"font-weight: 700; color: {Theme.SYS['accent_primary']};")
        net_layout.addWidget(self.lbl_net_tx)
        net_layout.addWidget(self.lbl_net_rx)
        right_box.addWidget(net_group)

        cards_layout.addLayout(right_box, stretch=1)
        layout.addLayout(cards_layout)

        # ── 3. Live Pipeline Stage Benchmark Panel ──
        bench_group = QGroupBox("Benchmark do Pipeline ao Vivo — Latência por Estágio (Janela Gráfica Real)")
        bench_layout = QVBoxLayout(bench_group)
        bench_layout.setContentsMargins(Theme.SPACE_LG, Theme.SPACE_MD, Theme.SPACE_LG, Theme.SPACE_MD)
        bench_layout.setSpacing(Theme.SPACE_SM)

        self._bench_stage_bars = {}
        stages_cfg = [
            ("capture", "WGC GPU Captura (Direct3D)", 5.0,  Theme.SYS["status_success"]),
            ("encode",  "NVENC H.264 Encode",        10.0, Theme.SYS["accent_primary"]),
            ("send",    "UDP Envio Fragmentado",     3.0,  Theme.SYS["status_info"]),
            ("recv",    "UDP Recebimento",            3.0,  Theme.SYS["status_warning"]),
            ("decode",  "Ryzen Slice Decode (4T)",   12.0, "#f472b6"),
            ("render",  "Qt paintEvent Render",      8.0,  "#fbbf24"),
        ]
        bench_grid = QGridLayout()
        bench_grid.setSpacing(8)

        for row_idx, (stage_key, stage_name, limit_ms, bar_color) in enumerate(stages_cfg):
            lbl_name = QLabel(stage_name)
            lbl_name.setStyleSheet(f"font-size: 11px; color: {Theme.SYS['text_secondary']}; min-width: 175px;")
            lbl_name.setFixedWidth(175)

            pb = QProgressBar()
            pb.setRange(0, int(limit_ms * 2 * 10))
            pb.setValue(0)
            pb.setTextVisible(False)
            pb.setFixedHeight(10)
            pb.setStyleSheet(f"""
                QProgressBar {{ border-radius: 4px; background: {Theme.SYS["bg_canvas"]}; }}
                QProgressBar::chunk {{ background: {bar_color}; border-radius: 4px; }}
            """)

            lbl_ms = QLabel("—")
            lbl_ms.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {Theme.SYS['text_primary']}; min-width: 70px;")
            lbl_ms.setFixedWidth(70)

            lbl_limit = QLabel(f"limite {limit_ms:.0f}ms")
            lbl_limit.setStyleSheet(f"font-size: 10px; color: {Theme.SYS['text_muted']};")

            bench_grid.addWidget(lbl_name,  row_idx, 0)
            bench_grid.addWidget(pb,        row_idx, 1)
            bench_grid.addWidget(lbl_ms,    row_idx, 2)
            bench_grid.addWidget(lbl_limit, row_idx, 3)

            self._bench_stage_bars[stage_key] = {
                "bar": pb, "label": lbl_ms, "limit": limit_ms, "color_ok": bar_color
            }

        bench_layout.addLayout(bench_grid)

        # FPS mini-histogram (last 10 samples)
        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel("Histórico FPS (últimas 10 amostras):"))
        self._fps_hist_labels = []
        for _ in range(10):
            sq = QLabel("—")
            sq.setFixedSize(40, 22)
            sq.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sq.setStyleSheet(f"""
                border-radius: 4px; font-size: 10px; font-weight: 700;
                background: {Theme.SYS["bg_surface_elevated"]}; color: {Theme.SYS["text_muted"]};
            """)
            fps_row.addWidget(sq)
            self._fps_hist_labels.append(sq)
        fps_row.addStretch()
        bench_layout.addLayout(fps_row)

        layout.addWidget(bench_group)

    @Slot(object)
    def update_tupa_metrics(self, snap: TupaMetricsSnapshot):
        """Update TUPÃ Diagnostics widgets from background sampler snapshot."""
        if not snap:
            return

        # 1. Health Badge
        self.lbl_tupa_health_badge.setText(f"SAÚDE DO SISTEMA: {snap.health_status}")
        health_col = Theme.SYS["status_success"] if "OTIMO" in snap.health_status or "ÓTIMO" in snap.health_status else (Theme.SYS["status_warning"] if "MODERADO" in snap.health_status else Theme.SYS["status_danger"])
        self.lbl_tupa_health_badge.setStyleSheet(f"font-size: 14px; font-weight: 800; color: {health_col};")
        self.lbl_tupa_health_desc.setText(snap.health_alert)
        self.tupa_health_card.setStyleSheet(f"background-color: {Theme.SYS['bg_surface_card']}; border-radius: {Theme.RADIUS_MD}px; border: 1px solid {health_col};")

        # 2. CPU Global
        self.lbl_cpu_global.setText(f"{snap.cpu_global_percent:.1f}%")
        self.pbar_cpu_global.setValue(int(snap.cpu_global_percent))

        # 3. CPU Cores
        for i, val in enumerate(snap.cpu_cores_percent):
            if i < len(self.pbar_cores):
                self.pbar_cores[i].setValue(int(val))
                self.lbl_cores[i].setText(f"C{i+1}: {val:.0f}%")
                c_col = Theme.SYS["status_success"] if val < 60 else (Theme.SYS["status_warning"] if val < 85 else Theme.SYS["status_danger"])
                self.pbar_cores[i].setStyleSheet(f"QProgressBar {{ border-radius: 3px; background: {Theme.SYS['bg_canvas']}; }} QProgressBar::chunk {{ background: {c_col}; border-radius: 3px; }}")

        # 4. RAM
        self.lbl_ram_text.setText(f"{snap.ram_used_gb:.2f} GB / {snap.ram_total_gb:.2f} GB ({snap.ram_percent:.1f}%)")
        self.pbar_ram.setValue(int(snap.ram_percent))

        # 5. Process Footprint
        self.lbl_proc_gui_ram.setText(f"Interface GUI: {snap.dav_gui_mem_mb:.1f} MB")
        self.lbl_proc_gui_cpu.setText(f"Interface CPU: {snap.dav_gui_cpu_percent:.1f}%")
        self.lbl_proc_snd_ram.setText(f"Transmissor: {snap.dav_sender_mem_mb:.1f} MB")
        self.lbl_proc_snd_cpu.setText(f"Transmissor CPU: {snap.dav_sender_cpu_percent:.1f}%")

        # 6. Network I/O
        tx_kb = snap.network_bytes_sent_sec / 1024.0
        rx_kb = snap.network_bytes_recv_sec / 1024.0
        self.lbl_net_tx.setText(f"Envio: {tx_kb:.1f} KB/s ({tx_kb * 8 / 1024:.2f} Mbps)")
        self.lbl_net_rx.setText(f"Recepção: {rx_kb:.1f} KB/s ({rx_kb * 8 / 1024:.2f} Mbps)")

    def set_current_fps(self, fps: float):
        self.cur_fps = fps

    @Slot()
    def _update_bench_panel(self):
        """Updates the live benchmark panel bars from collected probe samples."""
        try:
            with self._probe_lock:
                stage_data = {k: list(v[-30:]) for k, v in self._probe_stage_samples.items()}

            for stage_key, cfg in self._bench_stage_bars.items():
                samples = stage_data.get(stage_key, [])
                if not samples:
                    cfg["label"].setText("aguardando...")
                    cfg["label"].setStyleSheet(f"font-size: 11px; color: {Theme.SYS['text_muted']}; min-width: 70px;")
                    continue

                avg_ms  = statistics.mean(samples)
                p95_ms  = statistics.quantiles(samples, n=20)[18] if len(samples) >= 20 else max(samples)
                limit   = cfg["limit"]
                bar_max = int(limit * 2 * 10)

                bar_val = min(bar_max, int(p95_ms * 10))
                cfg["bar"].setValue(bar_val)

                ratio = avg_ms / limit
                if ratio < 0.8:
                    bar_color = cfg["color_ok"]
                    txt_color = Theme.SYS["status_success"]
                    status = "✓"
                elif ratio < 1.0:
                    bar_color = Theme.SYS["status_warning"]
                    txt_color = Theme.SYS["status_warning"]
                    status = "~"
                else:
                    bar_color = Theme.SYS["status_danger"]
                    txt_color = Theme.SYS["status_danger"]
                    status = "⚠"

                cfg["bar"].setStyleSheet(f"""
                    QProgressBar {{ border-radius: 4px; background: {Theme.SYS["bg_canvas"]}; }}
                    QProgressBar::chunk {{ background: {bar_color}; border-radius: 4px; }}
                """)
                cfg["label"].setText(f"{status} {avg_ms:.1f}ms")
                cfg["label"].setStyleSheet(f"font-size: 11px; font-weight: 700; color: {txt_color}; min-width: 70px;")

            if self.cur_fps > 0:
                self._bench_fps_history.append(self.cur_fps)
                if len(self._bench_fps_history) > 10:
                    self._bench_fps_history = self._bench_fps_history[-10:]

            hist = self._bench_fps_history
            offset = len(self._fps_hist_labels) - len(hist)
            for i, lbl in enumerate(self._fps_hist_labels):
                if i >= offset:
                    fps_val = hist[i - offset]
                    if fps_val >= 58:
                        bg, fg = Theme.SYS["status_success_bg"], Theme.SYS["status_success"]
                    elif fps_val >= 45:
                        bg, fg = Theme.SYS["status_warning_bg"], Theme.SYS["status_warning"]
                    else:
                        bg, fg = Theme.SYS["status_danger_bg"], Theme.SYS["status_danger"]
                    lbl.setText(f"{fps_val:.0f}")
                    lbl.setStyleSheet(f"border-radius: 4px; font-size: 10px; font-weight: 700; background: {bg}; color: {fg};")
                else:
                    lbl.setText("—")
                    lbl.setStyleSheet(f"border-radius: 4px; font-size: 10px; font-weight: 700; background: {Theme.SYS['bg_surface_elevated']}; color: {Theme.SYS['text_muted']};")
        except Exception:
            pass

    def _start_probe_collector(self):
        """Thread that listens on the probe UDP port and populates _probe_stage_samples."""
        def _collector_run():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", 19900))
            except Exception:
                return
            sock.settimeout(0.5)

            while True:
                try:
                    raw, _ = sock.recvfrom(4096)
                    msg = json.loads(raw.decode("utf-8"))
                    stage = msg.get("stage", "")
                    t_s = float(msg.get("t_start", 0))
                    t_e = float(msg.get("t_end", 0))
                    dur_ms = (t_e - t_s) * 1000.0
                    if stage in self._probe_stage_samples and 0 < dur_ms < 2000:
                        with self._probe_lock:
                            self._probe_stage_samples[stage].append(dur_ms)
                            if len(self._probe_stage_samples[stage]) > 300:
                                self._probe_stage_samples[stage] = self._probe_stage_samples[stage][-300:]
                except socket.timeout:
                    continue
                except Exception:
                    continue

        t = threading.Thread(target=_collector_run, daemon=True, name="DAV-ProbeCollector")
        t.start()
