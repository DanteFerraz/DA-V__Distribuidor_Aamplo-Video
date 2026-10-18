#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V Stage Probe — Servidor de Telemetria por Estágio (Ambiente Gráfico Real)
==============================================================================
Recebe timestamps de cada etapa do pipeline DA-V (captura, encode, envio,
decodificação, render Qt) via UDP e calcula histogramas de latência,
jitter de cadência e identificação de gargalos — ENQUANTO a GUI está viva.

Protocolo: UDP datagrama JSON simples na porta 19900
  {"stage": "capture|encode|send|decode|render|e2e", "t_start": float, "t_end": float,
   "frame_id": int, "extra": {}}

Uso:
  python scripts/dav_stage_probe.py               # Servidor de coleta
  python scripts/dav_stage_probe.py --report      # Exibe relatório do arquivo salvo
"""
import sys
import os
import json
import socket
import threading
import time
import statistics
import argparse
from collections import defaultdict, deque
from pathlib import Path

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE_PORT = 19900
REPORT_FILE = os.path.join(_PROJECT_ROOT, "logs", "dav_stage_probe_report.json")

STAGE_NAMES = {
    "capture": "BitBlt GDI Captura",
    "encode":  "NVENC H.264 Encode",
    "send":    "UDP Fragmentação+Envio",
    "recv":    "UDP Recebimento+Reassembly",
    "decode":  "Ryzen Slice Decodificação",
    "render":  "Qt paintEvent Render",
    "e2e":     "End-to-End (TX→RX)",
    "cadence": "Jitter de Cadência",
}

ANSI_GREEN  = "\033[92m"
ANSI_YELLOW = "\033[93m"
ANSI_RED    = "\033[91m"
ANSI_CYAN   = "\033[96m"
ANSI_RESET  = "\033[0m"
ANSI_BOLD   = "\033[1m"


def color_ms(ms: float, good: float = 10.0, warn: float = 16.6) -> str:
    if ms <= good:
        return f"{ANSI_GREEN}{ms:.3f} ms{ANSI_RESET}"
    elif ms <= warn:
        return f"{ANSI_YELLOW}{ms:.3f} ms{ANSI_RESET}"
    else:
        return f"{ANSI_RED}{ms:.3f} ms{ANSI_RESET}"


class StageProbeServer:
    def __init__(self, port: int = PROBE_PORT, window_sec: float = 5.0):
        self.port = port
        self.window_sec = window_sec
        self._sock = None
        self._running = False
        # stage → deque of (t_start, duration_ms, frame_id)
        self._samples: dict[str, deque] = defaultdict(lambda: deque(maxlen=3600))
        self._lock = threading.Lock()
        self._total_frames: dict[str, int] = defaultdict(int)

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("0.0.0.0", self.port))
        self._sock.settimeout(0.5)
        self._running = True
        t = threading.Thread(target=self._recv_loop, daemon=True, name="ProbeRecv")
        t.start()
        print(f"{ANSI_CYAN}[DA-V Stage Probe]{ANSI_RESET} Ouvindo na porta UDP {self.port} ...")
        return t

    def stop(self):
        self._running = False
        if self._sock:
            self._sock.close()

    def _recv_loop(self):
        while self._running:
            try:
                raw, _ = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except Exception:
                continue
            try:
                msg = json.loads(raw.decode("utf-8"))
                stage = msg.get("stage", "unknown")
                t_start = float(msg.get("t_start", 0.0))
                t_end   = float(msg.get("t_end", 0.0))
                fid     = int(msg.get("frame_id", 0))
                dur_ms  = (t_end - t_start) * 1000.0
                if dur_ms < 0 or dur_ms > 5000:
                    continue
                now = time.perf_counter()
                with self._lock:
                    self._samples[stage].append((now, dur_ms, fid))
                    self._total_frames[stage] += 1
            except Exception:
                continue

    def get_window_samples(self, stage: str) -> list:
        cutoff = time.perf_counter() - self.window_sec
        with self._lock:
            return [dur for (ts, dur, _) in self._samples[stage] if ts >= cutoff]

    def get_all_samples(self, stage: str) -> list:
        with self._lock:
            return [dur for (_, dur, _) in self._samples[stage]]

    def print_live_report(self):
        print("\033[2J\033[H", end="")  # Clear screen
        now_str = time.strftime("%H:%M:%S")
        print(f"{ANSI_BOLD}{ANSI_CYAN}{'═'*72}")
        print(f"   DA-V PIPELINE TELEMETRIA AO VIVO — {now_str}  (janela {self.window_sec:.0f}s)")
        print(f"{'═'*72}{ANSI_RESET}")

        all_stages = list(STAGE_NAMES.keys())
        header = f"{'Estágio':<30} {'Amostras':>8} {'Mín':>9} {'Média':>9} {'Máx':>9} {'P95':>9} {'Jitter':>9}"
        print(f"{ANSI_BOLD}{header}{ANSI_RESET}")
        print("─" * 72)

        fps_e2e = 0.0
        for stage in all_stages:
            samples = self.get_window_samples(stage)
            if len(samples) < 2:
                print(f"{STAGE_NAMES[stage]:<30} {'—':>8}  {'—':>9} {'—':>9} {'—':>9} {'—':>9} {'—':>9}")
                continue

            mn  = min(samples)
            mx  = max(samples)
            avg = statistics.mean(samples)
            try:
                p95 = statistics.quantiles(samples, n=20)[18]  # 95th percentile
            except Exception:
                p95 = mx
            jitter = statistics.stdev(samples) if len(samples) > 1 else 0.0

            name_col = STAGE_NAMES[stage]
            ms_avg   = color_ms(avg)
            ms_p95   = color_ms(p95)

            print(f"{name_col:<30} {len(samples):>8}  {mn:>8.2f}  {ms_avg:>18}  {mx:>8.2f}  {ms_p95:>18}  {jitter:>8.2f}")

            if stage == "e2e" and avg > 0:
                fps_e2e = 1000.0 / avg

        print("─" * 72)
        if fps_e2e > 0:
            fps_color = ANSI_GREEN if fps_e2e >= 58 else (ANSI_YELLOW if fps_e2e >= 45 else ANSI_RED)
            print(f"\n{ANSI_BOLD}Taxa End-to-End estimada: {fps_color}{fps_e2e:.1f} FPS{ANSI_RESET}")

        # Bottleneck detection
        bottleneck = self._detect_bottleneck()
        if bottleneck:
            print(f"\n{ANSI_YELLOW}⚠  GARGALO DETECTADO: {bottleneck}{ANSI_RESET}")
        else:
            print(f"\n{ANSI_GREEN}✓  Nenhum gargalo crítico detectado na janela atual.{ANSI_RESET}")

        print(f"\n{ANSI_CYAN}Ctrl+C para encerrar e salvar relatório final.{ANSI_RESET}")

    def _detect_bottleneck(self) -> str:
        thresholds = {
            "capture": 5.0,
            "encode":  10.0,
            "send":    3.0,
            "recv":    3.0,
            "decode":  12.0,
            "render":  8.0,
            "e2e":     18.0,
        }
        worst_stage = None
        worst_excess = 0.0
        for stage, limit in thresholds.items():
            samples = self.get_window_samples(stage)
            if not samples:
                continue
            avg = statistics.mean(samples)
            excess = avg - limit
            if excess > worst_excess:
                worst_excess = excess
                worst_stage = stage

        if worst_stage and worst_excess > 0:
            return f"{STAGE_NAMES[worst_stage]} → avg {statistics.mean(self.get_window_samples(worst_stage)):.2f} ms (limite: {thresholds[worst_stage]:.1f} ms, excesso: +{worst_excess:.2f} ms)"
        return ""

    def save_report(self):
        os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
        report = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "window_sec": self.window_sec,
            "stages": {}
        }
        for stage in STAGE_NAMES:
            samples = self.get_all_samples(stage)
            if len(samples) < 2:
                continue
            report["stages"][stage] = {
                "name": STAGE_NAMES[stage],
                "count": len(samples),
                "min_ms":  round(min(samples), 4),
                "max_ms":  round(max(samples), 4),
                "mean_ms": round(statistics.mean(samples), 4),
                "stdev_ms": round(statistics.stdev(samples), 4),
                "p50_ms":  round(statistics.median(samples), 4),
                "p95_ms":  round(statistics.quantiles(samples, n=20)[18], 4) if len(samples) >= 20 else round(max(samples), 4),
                "p99_ms":  round(statistics.quantiles(samples, n=100)[98], 4) if len(samples) >= 100 else round(max(samples), 4),
            }

        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n{ANSI_GREEN}Relatório salvo em: {REPORT_FILE}{ANSI_RESET}")
        return report


def print_saved_report():
    if not os.path.exists(REPORT_FILE):
        print(f"Nenhum relatório encontrado em {REPORT_FILE}")
        return
    with open(REPORT_FILE, encoding="utf-8") as f:
        r = json.load(f)
    print(f"\n{'═'*72}")
    print(f"   DA-V RELATÓRIO DE ETAPAS DO PIPELINE — {r.get('generated_at', '?')}")
    print(f"{'═'*72}")
    for stage, data in r.get("stages", {}).items():
        print(f"\n  {ANSI_BOLD}{data['name']}{ANSI_RESET}")
        print(f"    Amostras : {data['count']}")
        print(f"    Mínimo   : {color_ms(data['min_ms'])}")
        print(f"    Média    : {color_ms(data['mean_ms'])}")
        print(f"    P95      : {color_ms(data['p95_ms'])}")
        print(f"    P99      : {color_ms(data['p99_ms'])}")
        print(f"    Máximo   : {color_ms(data['max_ms'])}")
        print(f"    Jitter   : {data['stdev_ms']:.3f} ms")
    print(f"\n{'═'*72}\n")


# ──────────────────────────────────────────────────────────────────────────────
# PROBE CLIENT — Inject from inside the DA-V process
# ──────────────────────────────────────────────────────────────────────────────
_probe_sock = None
_probe_addr = ("127.0.0.1", PROBE_PORT)

def probe_init():
    """Call once at startup of each DA-V process to enable stage probing."""
    global _probe_sock
    _probe_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _probe_sock.setblocking(False)

def probe_send(stage: str, t_start: float, t_end: float, frame_id: int = 0, extra: dict = None):
    """Send a stage timing event to the probe server (non-blocking, fire-and-forget)."""
    if _probe_sock is None:
        return
    try:
        msg = json.dumps({
            "stage": stage,
            "t_start": t_start,
            "t_end": t_end,
            "frame_id": frame_id,
            "extra": extra or {}
        }).encode("utf-8")
        _probe_sock.sendto(msg, _probe_addr)
    except Exception:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DA-V Stage Probe Server")
    parser.add_argument("--report", action="store_true", help="Exibir relatório salvo e sair")
    parser.add_argument("--port", type=int, default=PROBE_PORT, help="Porta UDP do servidor de sonda")
    parser.add_argument("--window", type=float, default=5.0, help="Janela de análise em segundos")
    args = parser.parse_args()

    if args.report:
        print_saved_report()
        sys.exit(0)

    server = StageProbeServer(port=args.port, window_sec=args.window)
    server.start()

    try:
        while True:
            time.sleep(2.0)
            server.print_live_report()
    except KeyboardInterrupt:
        print("\nEncerrando...")
        server.stop()
        server.save_report()
