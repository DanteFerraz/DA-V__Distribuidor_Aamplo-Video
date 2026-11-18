#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI & Shim de Compatibilidade para `src.dav.modules.telemetry.stage_probe`.
Autor: Dante Ferraz (MonoTech)
"""

import argparse
import os
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.dav.modules.telemetry.stage_probe import (
    PROBE_PORT,
    REPORT_FILE,
    STAGE_NAMES,
    StageProbeServer,
    color_ms,
    print_saved_report,
    probe_init,
    probe_send,
)

__all__ = [
    "PROBE_PORT",
    "REPORT_FILE",
    "STAGE_NAMES",
    "StageProbeServer",
    "color_ms",
    "print_saved_report",
    "probe_init",
    "probe_send",
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DA-V Stage Probe Server")
    parser.add_argument("--report", action="store_true", help="Exibir relatorio salvo e sair")
    parser.add_argument("--port", type=int, default=PROBE_PORT, help="Porta UDP do servidor de sonda")
    parser.add_argument("--window", type=float, default=5.0, help="Janela de analise em segundos")
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
