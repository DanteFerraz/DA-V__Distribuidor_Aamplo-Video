#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wrapper CLI e Shim de Compatibilidade para `src.dav.modules.stream_engine.subprocess_sender`.
Autor: Dante Ferraz (MonoTech)
"""

import argparse
import multiprocessing as mp
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.dav.modules.capture.service import enumerate_system_monitors
from src.dav.modules.stream_engine.subprocess_sender import (
    SenderTransportEndpoint,
    _sender_subprocess,
    run_sender_subprocess,
)

__all__ = [
    "enumerate_system_monitors",
    "SenderTransportEndpoint",
    "run_sender_subprocess",
    "_sender_subprocess",
]


def main():
    parser = argparse.ArgumentParser(description="DA-V — Daemon Transmissor de Video em Tempo Real")
    parser.add_argument("--ip", default="", help="IP de destino direto (vazio para modo PIN P2P)")
    parser.add_argument("--port", type=int, default=9000, help="Porta UDP local/alvo (padrao: 9000)")
    parser.add_argument("--pin", default="777-888", help="PIN de 6 digitos para autenticacao e P2P")
    parser.add_argument("--width", type=int, default=1920, help="Largura de saida")
    parser.add_argument("--height", type=int, default=1080, help="Altura de saida")
    parser.add_argument("--fps", type=int, default=60, help="Taxa de quadros alvo")
    parser.add_argument("--bitrate", type=int, default=12000, help="Bitrate alvo em kbps")
    parser.add_argument("--monitor", type=int, default=0, help="Indice do monitor (0 = principal)")
    parser.add_argument("--codec", default="h264_nvenc", help="Codec preferencial (h264_nvenc, libx264, jpeg)")
    parser.add_argument("--no-audio", action="store_true", help="Desativa captura/transmissao de audio")
    args = parser.parse_args()

    stop_evt = mp.Event()
    stats_q: "mp.Queue" = mp.Queue(maxsize=16)
    cmd_q: "mp.Queue" = mp.Queue(maxsize=16)
    evt_q: "mp.Queue" = mp.Queue(maxsize=16)

    print(f"[Daemon] Iniciando transmissor DA-V na porta {args.port} (PIN: {args.pin})...")
    try:
        run_sender_subprocess(
            args.ip,
            args.port,
            args.pin,
            args.width,
            args.height,
            args.fps,
            args.bitrate,
            stats_q,
            stop_evt,
            codec_type=args.codec,
            monitor_index=args.monitor,
            cmd_queue=cmd_q,
            evt_queue=evt_q,
            bind_port=args.port,
            audio_enabled=not args.no_audio,
        )
    except KeyboardInterrupt:
        stop_evt.set()


if __name__ == "__main__":
    main()
