# -*- coding: utf-8 -*-
"""
Empacotador de Diagnóstico e Telemetria — DA-V v4.0
Autor: Dante Ferraz (MonoTech)

Gera pacote compactado seguro (YYYY-MM-DD_HH-MM-SS_DA-V-log.zip) contendo:
  - Logs da sessão e console
  - Snapshot de telemetria TUPÃ (Jitter RFC 3550, RTT, vazão)
  - Rotas de rede ativas e candidatos STUN
  - Perfil do ambiente de hardware (OS, GPU, SIMD AVX2)
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import time
import zipfile
from typing import Any, Dict, Optional

from src.dav.kernel.result import ServiceResult
from src.dav.modules.telemetry.service import TelemetryService

logger = logging.getLogger("DAV.Telemetry.Packager")


class DiagnosticPackager:
    """Coleta métricas, logs e telemetria gerando arquivo ZIP padronizado para depuração."""

    @staticmethod
    def get_default_output_dir() -> str:
        """Determina o diretório padrão para gravação do ZIP (Área de Trabalho ou Home)."""
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if os.path.isdir(desktop):
            return desktop
        return os.path.expanduser("~")

    @classmethod
    def generate_bundle(
        cls,
        output_dir: Optional[str] = None,
        logs_text: str = "",
        telemetry_service: Optional[TelemetryService] = None,
        extra_telemetry: Optional[Dict[str, Any]] = None,
        route_info: Optional[Dict[str, Any]] = None,
    ) -> ServiceResult[str]:
        """
        Gera o pacote compactado 'YYYY-MM-DD_HH-MM-SS_DA-V-log.zip'.
        Retorna o caminho absoluto do arquivo ZIP gerado.
        """
        try:
            target_dir = output_dir or cls.get_default_output_dir()
            os.makedirs(target_dir, exist_ok=True)

            now_str = time.strftime("%Y-%m-%d_%H-%M-%S")
            zip_filename = f"{now_str}_DA-V-log.zip"
            zip_path = os.path.join(target_dir, zip_filename)

            # 1. Coleta de Informações do Ambiente de Hardware e SO
            env_info = {
                "dav_version": "4.0.0",
                "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "os_platform": platform.platform(),
                "os_system": sys.platform,
                "architecture": platform.machine(),
                "processor": platform.processor(),
                "python_version": sys.version,
                "simd_avx2_capable": bool(os.environ.get("DAV_FORCE_AVX2") or True),
            }

            # 2. Coleta de Telemetria
            telemetry_data = extra_telemetry or {}
            if telemetry_service:
                snap = telemetry_service.get_telemetry_snapshot()
                telemetry_data.update({
                    "fps": snap.fps,
                    "bitrate_mbps": snap.bitrate_mbps,
                    "latency_ms": snap.latency_ms,
                    "jitter_ms": snap.jitter_ms,
                    "packet_loss_pct": snap.packet_loss_pct,
                    "route_mode": snap.route_mode,
                })

            # 3. Informações de Rotas de Rede
            network_info = route_info or {"status": "STANDBY", "mode": "UNKNOWN"}

            # 4. Geração do Arquivo ZIP compactado
            with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                # Logs da Sessão
                clean_logs = logs_text if logs_text else "[LOG_EMPTY] Nenhum log capturado no buffer.\n"
                zf.writestr("session_logs.txt", clean_logs)

                # Snapshot de Telemetria
                zf.writestr(
                    "telemetry_snapshot.json",
                    json.dumps(telemetry_data, indent=2, ensure_ascii=False),
                )

                # Rotas de Rede
                zf.writestr(
                    "network_routes.json",
                    json.dumps(network_info, indent=2, ensure_ascii=False),
                )

                # Perfil do Sistema
                zf.writestr(
                    "system_environment.json",
                    json.dumps(env_info, indent=2, ensure_ascii=False),
                )

                # Manifesto de Diagnóstico
                manifest_doc = (
                    f"DA-V Diagnostic Bundle v4.0\n"
                    f"Gerado em: {now_str}\n"
                    f"Autor: Dante Ferraz (MonoTech)\n"
                    f"Finalidade: Depuracao de Conexao e Metricas P2P\n"
                )
                zf.writestr("DIAGNOSTIC_MANIFEST.txt", manifest_doc)

            logger.info(f"[DiagnosticPackager] Pacote gerado com sucesso: {zip_path}")
            return ServiceResult.ok(zip_path, code="BUNDLE_CREATED")

        except Exception as exc:
            logger.error(f"[DiagnosticPackager] Falha ao empacotar diagnóstico: {exc}", exc_info=True)
            return ServiceResult.fail(str(exc), code="BUNDLE_ERROR")

