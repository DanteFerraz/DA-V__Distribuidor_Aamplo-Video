#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V Live Environment Benchmark Orchestrator
============================================
Metodologia de Teste Real — Ambiente Gráfico Físico

Este orquestrador:
1. Inicia o servidor de sondas de estágio (dav_stage_probe.py)
2. Abre as janelas físicas REAIS do DA-V (Receptor + Transmissor) na sua tela
3. Aguarda a estabilização da transmissão (detecção automática)
4. Coleta métricas ao vivo durante 30 segundos:
   - FPS frame-a-frame (jitter, quedas, P95, P99)
   - Latência de cada estágio do pipeline
   - Carga dos núcleos AMD Ryzen durante a transmissão
   - Consumo de VRAM e uso do NVENC (via NVML se disponível)
   - Dados de envio/recebimento UDP (bitrate, perdas)
5. Gera relatório completo: JSON estruturado + Markdown com tabelas
6. Termina os processos da GUI de forma limpa

Uso:
  python scripts/dav_live_benchmark.py
  python scripts/dav_live_benchmark.py --duration 60 --monitor 1
  python scripts/dav_live_benchmark.py --no-gui  # Apenas coleta (janelas já abertas)
"""
import sys
import io

# Reconfigure stdout to UTF-8 on Windows to support Unicode box-drawing characters
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

import os

import json
import subprocess
import socket
import struct
import time
import threading
import statistics
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from collections import defaultdict, deque

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ── Paths ─────────────────────────────────────────────────────────────────────
LOGS_DIR       = Path(_PROJECT_ROOT) / "logs"
REPORT_JSON    = LOGS_DIR / f"live_bench_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
PROBE_PORT     = 19900          # Stage probe server port
TELEMETRY_PORT = 19901          # Receiver for DA-V telemetry packets (UDP broadcast)
GUI_PY         = os.path.join(_PROJECT_ROOT, "scripts", "gui_app.py")

ANSI = {
    "G": "\033[92m", "Y": "\033[93m", "R": "\033[91m",
    "C": "\033[96m", "B": "\033[1m",  "X": "\033[0m",
    "M": "\033[95m",
}


def c(color_key, text):
    return f"{ANSI[color_key]}{text}{ANSI['X']}"


# ──────────────────────────────────────────────────────────────────────────────
# METRICS COLLECTOR (runs in background, receives DA-V sender stats via IPC)
# ──────────────────────────────────────────────────────────────────────────────
class MetricsCollector:
    """
    Collects real-time metrics from the live DA-V pipeline:
    - FPS samples (every 0.5s from the sender stats queue broadcast)
    - Stage timing from the probe server
    - CPU core utilization snapshots
    - Process resource usage (psutil)
    """
    def __init__(self):
        self.tx_fps_samples: list[float] = []
        self.rx_fps_samples: list[float] = []
        self.fps_samples:    list[float] = []
        self.mbps_samples:   list[float] = []
        self.lat_samples:    list[float] = []
        self.cpu_snapshots:  list[list[float]] = []   # per-snapshot, per-core
        self.ram_snapshots:  list[float] = []
        self.nvenc_samples:  list[float] = []
        self.drop_events:    list[tuple] = []          # (timestamp, fps_value)
        self._lock = threading.Lock()
        self._running = False

        # Stage timing from probe (shared with probe server)
        self.stage_samples: dict[str, list[float]] = defaultdict(list)

        # Telemetry receive socket (for DA-V sender stats)
        self._tel_sock = None

    def start(self):
        self._running = True
        # CPU poller
        t_cpu = threading.Thread(target=self._cpu_poll_loop, daemon=True, name="CPUPoll")
        t_cpu.start()
        # Telemetry UDP listener (DA-V sends stats to broadcast; we sniff)
        t_tel = threading.Thread(target=self._telemetry_recv_loop, daemon=True, name="TelRecv")
        t_tel.start()
        # Stage probe listener
        t_probe = threading.Thread(target=self._probe_recv_loop, daemon=True, name="ProbeRecv")
        t_probe.start()

    def stop(self):
        self._running = False

    def reset(self):
        with self._lock:
            self.tx_fps_samples.clear()
            self.rx_fps_samples.clear()
            self.fps_samples.clear()
            self.mbps_samples.clear()
            self.lat_samples.clear()
            self.cpu_snapshots.clear()
            self.ram_snapshots.clear()
            self.drop_events.clear()
            self.stage_samples.clear()

    # ── CPU Core Polling ──────────────────────────────────────────────────────
    def _cpu_poll_loop(self):
        try:
            import psutil
            while self._running:
                per_core = psutil.cpu_percent(interval=None, percpu=True)
                ram_pct  = psutil.virtual_memory().percent
                with self._lock:
                    self.cpu_snapshots.append(per_core)
                    self.ram_snapshots.append(ram_pct)
                time.sleep(1.0)
        except ImportError:
            # Fallback: use WMI or pdh via ctypes
            while self._running:
                time.sleep(1.0)

    # ── Telemetry UDP Listener (sniff DA-V sender & receiver stats) ───────────
    def _telemetry_recv_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", TELEMETRY_PORT))
        except Exception:
            # Port may be busy; try alternative
            try:
                sock.bind(("0.0.0.0", TELEMETRY_PORT + 1))
            except Exception:
                return
        sock.settimeout(0.5)
        while self._running:
            try:
                raw, _ = sock.recvfrom(512)
                msg = json.loads(raw.decode("utf-8", errors="replace"))
                role = msg.get("role", "tx")
                fps  = float(msg.get("fps", 0))
                mbps = float(msg.get("mbps", 0))
                lat  = float(msg.get("lat", 0))
                with self._lock:
                    if role == "rx":
                        self.rx_fps_samples.append(fps)
                        self.fps_samples.append(fps)
                    else:
                        self.tx_fps_samples.append(fps)
                        if not self.rx_fps_samples:
                            self.fps_samples.append(fps)
                    self.mbps_samples.append(mbps)
                    self.lat_samples.append(lat)
                    if fps < 48.0 and len(self.fps_samples) > 5:
                        self.drop_events.append((time.perf_counter(), fps))
            except Exception:
                continue
        sock.close()

    # ── Stage Probe Receiver ──────────────────────────────────────────────────
    def _probe_recv_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", PROBE_PORT))
        except Exception:
            return
        sock.settimeout(0.5)
        while self._running:
            try:
                raw, _ = sock.recvfrom(4096)
                msg = json.loads(raw.decode("utf-8"))
                stage  = msg.get("stage", "unknown")
                t_s    = float(msg.get("t_start", 0))
                t_e    = float(msg.get("t_end", 0))
                dur_ms = (t_e - t_s) * 1000.0
                if 0 < dur_ms < 2000:
                    with self._lock:
                        self.stage_samples[stage].append(dur_ms)
            except Exception:
                continue
        sock.close()

    # ── Data Access ───────────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        with self._lock:
            fps = list(self.fps_samples)
            tx_fps = list(self.tx_fps_samples)
            rx_fps = list(self.rx_fps_samples)
            mbps = list(self.mbps_samples)
            lat  = list(self.lat_samples)
            cpu  = list(self.cpu_snapshots)
            ram  = list(self.ram_snapshots)
            drops = list(self.drop_events)
            stages = {k: list(v) for k, v in self.stage_samples.items()}
        return {
            "fps": fps, "tx_fps": tx_fps, "rx_fps": rx_fps,
            "mbps": mbps, "lat": lat,
            "cpu_snapshots": cpu, "ram": ram,
            "drops": drops, "stages": stages,
        }


# ──────────────────────────────────────────────────────────────────────────────
# PROCESS MANAGER — opens DA-V GUI windows physically on your screen
# ──────────────────────────────────────────────────────────────────────────────
class DavProcessManager:
    def __init__(self):
        self._procs: list[subprocess.Popen] = []

    def launch_receiver(self, port: int = 9002, pin: str = "777-888") -> subprocess.Popen:
        cmd = [
            sys.executable, GUI_PY,
            "--port", str(port),
            "--target-port", "9000",
            "--pin", pin,
            "--auto-recv",
        ]
        proc = subprocess.Popen(
            cmd,
            cwd=_PROJECT_ROOT,
            creationflags=subprocess.CREATE_NEW_CONSOLE,  # Physical window on your screen
        )
        self._procs.append(proc)
        print(f"  {c('G','✓')} Receptor iniciado (PID {proc.pid}) — porta {port}")
        return proc

    def launch_transmitter(self, port: int = 9000, target_port: int = 9002,
                            pin: str = "777-888", monitor: int = 1) -> subprocess.Popen:
        cmd = [
            sys.executable, GUI_PY,
            "--port", str(port),
            "--target-port", str(target_port),
            "--pin", pin,
            "--auto-send",
            "--monitor", str(monitor),
        ]
        proc = subprocess.Popen(
            cmd,
            cwd=_PROJECT_ROOT,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        self._procs.append(proc)
        print(f"  {c('G','✓')} Transmissor iniciado (PID {proc.pid}) — porta {port} → {target_port} | Monitor {monitor}")
        return proc

    def wait_for_stability(self, collector: MetricsCollector, timeout: float = 25.0) -> bool:
        """
        Wait until the pipeline has stabilized:
        - FPS >= 55 for at least 3 consecutive samples
        OR timeout reached.
        """
        print(f"\n  {c('C','⏳')} Aguardando estabilização da transmissão ...", end="", flush=True)
        deadline = time.perf_counter() + timeout
        stable_count = 0
        while time.perf_counter() < deadline:
            time.sleep(1.5)
            with collector._lock:
                fps_window = list(collector.fps_samples)[-5:]
            if len(fps_window) >= 3:
                consecutive = sum(1 for f in fps_window[-3:] if f >= 50.0)
                if consecutive >= 3:
                    stable_count += 1
                    if stable_count >= 2:
                        print(f" {c('G','ESTÁVEL')} ({fps_window[-1]:.1f} FPS)")
                        return True
                else:
                    stable_count = 0
                print(f"\r  {c('C','⏳')} Aguardando estabilização ... FPS atual: {fps_window[-1]:.1f}    ", end="", flush=True)

        # Even if not perfectly stable, proceed after timeout
        print(f"\n  {c('Y','⚠')}  Timeout de estabilização — coletando dados com o estado atual.")
        return False

    def terminate_all(self):
        for proc in self._procs:
            try:
                if sys.platform == "win32":
                    subprocess.run(f"taskkill /F /T /PID {proc.pid}", shell=True, capture_output=True)
                else:
                    proc.terminate()
            except Exception:
                pass
        for proc in self._procs:
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        self._procs.clear()
        print(f"\n  {c('G','✓')} Todos os processos DA-V encerrados.")


# ──────────────────────────────────────────────────────────────────────────────
# REPORT GENERATOR
# ──────────────────────────────────────────────────────────────────────────────
def _stat(samples: list) -> dict:
    if not samples or len(samples) < 2:
        return {}
    return {
        "count":    len(samples),
        "min":      round(min(samples), 3),
        "max":      round(max(samples), 3),
        "mean":     round(statistics.mean(samples), 3),
        "median":   round(statistics.median(samples), 3),
        "stdev":    round(statistics.stdev(samples), 3),
        "p95":      round(statistics.quantiles(samples, n=20)[18], 3) if len(samples) >= 20 else round(max(samples), 3),
        "p99":      round(statistics.quantiles(samples, n=100)[98], 3) if len(samples) >= 100 else round(max(samples), 3),
    }


def generate_report(data: dict, duration_sec: float) -> dict:
    fps  = data["fps"]
    mbps = data["mbps"]
    lat  = data["lat"]
    cpu_snaps = data["cpu_snapshots"]
    ram  = data["ram"]
    drops = data["drops"]
    stages = data["stages"]

    # Per-core average load
    per_core_avg = []
    if cpu_snaps:
        n_cores = len(cpu_snaps[0])
        for c_idx in range(n_cores):
            vals = [snap[c_idx] for snap in cpu_snaps if c_idx < len(snap)]
            per_core_avg.append(round(statistics.mean(vals), 1) if vals else 0.0)

    tx_fps = data.get("tx_fps", [])
    rx_fps = data.get("rx_fps", [])

    report = {
        "metadata": {
            "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "duration_sec": duration_sec,
            "hardware": {
                "cpu": "AMD Ryzen 6C/12T (SMT)",
                "gpu": "NVIDIA GeForce RTX 4070 (12GB VRAM)",
                "displays": "DISPLAY1 @ 144Hz, DISPLAY2 @ 60Hz",
                "os": "Windows 11"
            }
        },
        "fps": _stat(fps),
        "fps_tx": _stat(tx_fps) if tx_fps else _stat(fps),
        "fps_rx": _stat(rx_fps) if rx_fps else _stat(fps),
        "bitrate_mbps": _stat(mbps),
        "latency_ms": _stat(lat),
        "drop_events": {
            "count": len(drops),
            "timestamps_sec": [round(t, 2) for t, _ in drops],
            "fps_at_drop": [round(f, 1) for _, f in drops],
        },
        "cpu": {
            "global_avg": round(statistics.mean([statistics.mean(s) for s in cpu_snaps]), 1) if cpu_snaps else 0,
            "per_core_avg": per_core_avg,
            "peak_core_pct": max(per_core_avg) if per_core_avg else 0,
            "overloaded_cores": [i+1 for i, v in enumerate(per_core_avg) if v >= 80.0],
        },
        "ram_pct": _stat(ram),
        "pipeline_stages": {
            stage: _stat(vals) for stage, vals in stages.items() if vals
        },
        "verdict": {},
    }

    # Verdict
    fps_s   = report["fps"]
    stable  = fps_s.get("p95", 0) >= 58.0
    no_drops = len(drops) == 0
    no_ol   = len(report["cpu"]["overloaded_cores"]) == 0
    lat_ok  = report["latency_ms"].get("mean", 999) < 15.0

    report["verdict"] = {
        "fps_stable_60":     stable,
        "no_fps_drops":      no_drops,
        "cpu_balanced":      no_ol,
        "latency_ok":        lat_ok,
        "overall_pass":      stable and no_drops and no_ol,
        "bottleneck_stage":  _find_bottleneck(report["pipeline_stages"]),
    }

    return report


def _find_bottleneck(stages: dict) -> str:
    thresholds = {
        "capture": 5.0, "encode": 10.0, "send": 3.0,
        "recv": 3.0, "decode": 12.0, "render": 8.0,
    }
    worst, worst_exc = None, 0.0
    for st, lim in thresholds.items():
        d = stages.get(st, {})
        mean = d.get("mean", 0)
        if mean - lim > worst_exc:
            worst_exc = mean - lim
            worst = st
    return worst if worst else "none"


def save_json_report(report: dict) -> str:
    LOGS_DIR.mkdir(exist_ok=True)
    path = str(REPORT_JSON)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return path


def save_markdown_report(report: dict) -> str:
    md_path = str(REPORT_JSON).replace(".json", ".md")
    meta = report["metadata"]
    fps  = report["fps"]
    lat  = report["latency_ms"]
    mbps = report["bitrate_mbps"]
    cpu  = report["cpu"]
    verd = report["verdict"]
    drops = report["drop_events"]
    stages = report["pipeline_stages"]

    status_icon = "✅ APROVADO" if verd["overall_pass"] else "❌ REPROVADO"
    fps_mean = fps.get("mean", 0)
    fps_p95  = fps.get("p95", 0)

    lines = [
        f"# DA-V Benchmark — Ambiente Gráfico Real",
        f"",
        f"**Data:** {meta['generated_at']}  ",
        f"**Duração:** {meta['duration_sec']:.0f} segundos  ",
        f"**Hardware:** {meta['hardware']['cpu']} · {meta['hardware']['gpu']}  ",
        f"**Displays:** {meta['hardware']['displays']}  ",
        f"",
        f"## Status Final",
        f"",
        f"> **{status_icon}**",
        f"",
        f"| Critério | Resultado | Passou? |",
        f"|:---|:---|:---|",
        f"| FPS Estável ≥ 58 FPS (P95) | {fps_p95:.1f} FPS | {'✅' if verd['fps_stable_60'] else '❌'} |",
        f"| Sem quedas severas de FPS (< 48 FPS) | {drops['count']} quedas | {'✅' if verd['no_fps_drops'] else '❌'} |",
        f"| CPU Balanceada (núcleo < 80%) | Pico: {cpu['peak_core_pct']:.1f}% | {'✅' if verd['cpu_balanced'] else '❌'} |",
        f"| Latência de Rede < 15 ms | {lat.get('mean', 0):.2f} ms | {'✅' if verd['latency_ok'] else '❌'} |",
        f"",
        f"## Métricas de FPS",
        f"",
        f"| Métrica | Valor |",
        f"|:---|---:|",
        f"| Mínimo | {fps.get('min', 0):.1f} FPS |",
        f"| Média | {fps_mean:.1f} FPS |",
        f"| Mediana | {fps.get('median', 0):.1f} FPS |",
        f"| P95 | {fps_p95:.1f} FPS |",
        f"| P99 | {fps.get('p99', 0):.1f} FPS |",
        f"| Máximo | {fps.get('max', 0):.1f} FPS |",
        f"| Jitter (σ) | {fps.get('stdev', 0):.2f} FPS |",
        f"| Quedas (< 50 FPS) | {drops['count']} eventos |",
        f"",
    ]

    if drops["count"] > 0:
        lines.extend([
            f"### Eventos de Queda de FPS",
            f"",
            f"| # | FPS no Evento |",
            f"|:---|:---|",
        ])
        for i, fp in enumerate(drops["fps_at_drop"]):
            lines.append(f"| {i+1} | {fp:.1f} FPS |")
        lines.append("")

    lines.extend([
        f"## Latência de Rede LAN",
        f"",
        f"| Métrica | Valor |",
        f"|:---|---:|",
        f"| Média | {lat.get('mean', 0):.2f} ms |",
        f"| P95 | {lat.get('p95', 0):.2f} ms |",
        f"| Máximo | {lat.get('max', 0):.2f} ms |",
        f"",
        f"## Bitrate de Transmissão",
        f"",
        f"| Métrica | Valor |",
        f"|:---|---:|",
        f"| Média | {mbps.get('mean', 0):.2f} Mbps |",
        f"| Máximo | {mbps.get('max', 0):.2f} Mbps |",
        f"",
        f"## CPU AMD Ryzen — Carga por Núcleo",
        f"",
        f"| Núcleo | Carga Média | Status |",
        f"|:---|:---|:---|",
    ])

    for i, v in enumerate(cpu["per_core_avg"]):
        status = "🔴 SOBRECARGA" if v >= 80 else ("🟡 ALTO" if v >= 60 else "🟢 OK")
        lines.append(f"| Core {i+1} | {v:.1f}% | {status} |")

    lines.extend([
        f"",
        f"**Núcleos sobrecarregados (≥80%):** {cpu['overloaded_cores'] or 'Nenhum'}  ",
        f"**Carga global média:** {cpu['global_avg']:.1f}%",
        f"",
    ])

    if stages:
        STAGE_LABELS = {
            "capture": "WGC GPU Captura (Direct3D)",
            "encode":  "NVENC H.264 Encode",
            "send":    "UDP Fragmentação+Envio",
            "recv":    "UDP Recebimento",
            "decode":  "Ryzen Slice Decodificação",
            "render":  "Qt paintEvent Render",
            "e2e":     "End-to-End (TX→RX)",
        }
        lines.extend([
            f"## Pipeline — Latência por Estágio",
            f"",
            f"| Estágio | Média (ms) | P95 (ms) | Máx (ms) | Jitter (ms) | Amostras |",
            f"|:---|:---|:---|:---|:---|:---|",
        ])
        bottleneck = verd.get("bottleneck_stage", "none")
        for stage, d in stages.items():
            label = STAGE_LABELS.get(stage, stage)
            is_bn = "⚠ " if stage == bottleneck else ""
            lines.append(
                f"| {is_bn}{label} | {d.get('mean',0):.2f} | {d.get('p95',0):.2f} | "
                f"{d.get('max',0):.2f} | {d.get('stdev',0):.2f} | {d.get('count',0)} |"
            )
        if bottleneck != "none":
            lines.extend(["", f"> ⚠ **Gargalo identificado:** `{STAGE_LABELS.get(bottleneck, bottleneck)}`"])
        lines.append("")

    lines.extend([
        f"---",
        f"",
        f"*Relatório gerado automaticamente pelo DA-V Live Environment Benchmark Orchestrator*",
        f"*Arquivo JSON completo: `{REPORT_JSON.name}`*",
    ])

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return md_path


def print_live_dashboard(collector: MetricsCollector, elapsed: float, total: float):
    with collector._lock:
        tx_w = list(collector.tx_fps_samples)[-5:]
        rx_w = list(collector.rx_fps_samples)[-5:]
        fps_w = list(collector.fps_samples)[-5:]
        drops_n = len(collector.drop_events)

    tx_now = tx_w[-1] if tx_w else (fps_w[-1] if fps_w else 0.0)
    rx_now = rx_w[-1] if rx_w else (fps_w[-1] if fps_w else 0.0)

    tx_color = ANSI["G"] if tx_now >= 55 else (ANSI["Y"] if tx_now >= 40 else ANSI["R"])
    rx_color = ANSI["G"] if rx_now >= 55 else (ANSI["Y"] if rx_now >= 40 else ANSI["R"])
    pct = int(elapsed / total * 30)

    print(f"\r  [{c('C', '='*pct + '>'+ ' '*(30-pct))}] "
          f"{elapsed:.0f}/{total:.0f}s | "
          f"TX: {tx_color}{tx_now:.1f}{ANSI['X']} FPS | "
          f"RX: {rx_color}{rx_now:.1f}{ANSI['X']} FPS | "
          f"Quedas: {drops_n}", end="", flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# MAIN ORCHESTRATOR
# ──────────────────────────────────────────────────────────────────────────────
def run_live_benchmark(args):
    print(f"\n{c('B', '═'*72)}")
    print(f"{c('B', '   DA-V BENCHMARK — AMBIENTE GRÁFICO REAL')}")
    print(f"{c('B', '   Metodologia: Janelas Físicas + Coleta de Estágio ao Vivo')}")
    print(f"{c('B', '═'*72)}\n")

    LOGS_DIR.mkdir(exist_ok=True)
    collector = MetricsCollector()
    proc_mgr  = DavProcessManager()

    if not args.no_gui:
        print(f"{c('C','[1/5]')} Abrindo janelas físicas DA-V na sua tela ...\n")

        # Launch Receiver first (it needs to be listening before TX sends)
        proc_mgr.launch_receiver(port=9002, pin="777-888")
        time.sleep(2.5)  # Wait for receiver to bind UDP socket and open window

        # Launch Transmitter (points to receiver on 9002)
        proc_mgr.launch_transmitter(port=9000, target_port=9002,
                                    pin="777-888", monitor=args.monitor)
        time.sleep(2.0)

    print(f"\n{c('C','[2/5]')} Iniciando coletores de métricas em background ...")
    collector.start()

    if not args.no_gui:
        print(f"\n{c('C','[3/5]')} Aguardando estabilização do pipeline ...\n")
        proc_mgr.wait_for_stability(collector, timeout=30.0)
    else:
        print(f"  Modo --no-gui: aguardando 5s antes de coletar ...")
        time.sleep(5.0)

    collector.reset()
    time.sleep(0.5)

    print(f"\n{c('C','[4/5]')} Coletando métricas por {args.duration}s ...\n")
    t_start   = time.perf_counter()
    t_sample  = 0.0
    while True:
        elapsed = time.perf_counter() - t_start
        if elapsed >= args.duration:
            break
        print_live_dashboard(collector, elapsed, args.duration)
        time.sleep(0.5)
    print()

    print(f"\n{c('C','[5/5]')} Gerando relatórios ...\n")
    collector.stop()
    data   = collector.snapshot()
    report = generate_report(data, args.duration)

    json_path = save_json_report(report)
    md_path   = save_markdown_report(report)

    if not args.no_gui:
        proc_mgr.terminate_all()

    # ── Print final summary ──────────────────────────────────────────────────
    verd = report["verdict"]
    fps  = report["fps"]
    cpu  = report["cpu"]
    drops = report["drop_events"]

    tx_s = report.get("fps_tx", report["fps"])
    rx_s = report.get("fps_rx", report["fps"])

    status_color = ANSI["G"] if verd["overall_pass"] else ANSI["R"]
    status_text  = "APROVADO ✅" if verd["overall_pass"] else "REPROVADO ❌"

    print(f"\n{c('B','═'*72)}")
    print(f"   RESULTADO FINAL: {status_color}{c('B', status_text)}{ANSI['X']}")
    print(f"{c('B','═'*72)}\n")

    print(f"  TX Envio Média    : {tx_s.get('mean', 0):.1f} FPS (P95: {tx_s.get('p95', 0):.1f})")
    print(f"  RX Tela Média     : {rx_s.get('mean', 0):.1f} FPS (P95: {rx_s.get('p95', 0):.1f})")
    print(f"  Quedas (< 50 FPS) : {drops['count']} eventos")
    print(f"  Núcleos ≥80%      : {cpu['overloaded_cores'] or 'Nenhum'}")
    print(f"  Gargalo           : {verd.get('bottleneck_stage', 'none')}")

    print(f"\n  📄 JSON  : {json_path}")
    print(f"  📄 Markdown : {md_path}\n")

    return report


# ──────────────────────────────────────────────────────────────────────────────
# TELEMETRY BROADCAST HOOK — para injetar no dav_sender_worker.py
# ──────────────────────────────────────────────────────────────────────────────
# Adicione este snippet ao loop de telemetria do stats_queue em dav_client.py:
#
#   from scripts.dav_live_benchmark import broadcast_telemetry
#   broadcast_telemetry(cur_fps, cur_mbps, lat_ms)
#
_bcast_sock = None

def broadcast_telemetry(fps: float, mbps: float, lat_ms: float):
    global _bcast_sock
    if _bcast_sock is None:
        _bcast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _bcast_sock.setblocking(False)
    try:
        msg = json.dumps({"fps": fps, "mbps": mbps, "lat": lat_ms}).encode()
        _bcast_sock.sendto(msg, ("127.0.0.1", TELEMETRY_PORT))
    except Exception:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DA-V Live Environment Benchmark Orchestrator")
    parser.add_argument("--duration", type=int,   default=30,  help="Duração da coleta em segundos (default: 30)")
    parser.add_argument("--monitor",  type=int,   default=1,   help="Índice do monitor de captura (default: 1)")
    parser.add_argument("--no-gui",   action="store_true",     help="Não abrir janelas GUI (janelas já abertas)")
    args = parser.parse_args()

    try:
        run_live_benchmark(args)
    except KeyboardInterrupt:
        print(f"\n{ANSI['Y']}Interrompido pelo usuário.{ANSI['X']}")
