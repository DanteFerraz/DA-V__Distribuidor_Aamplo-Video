# -*- coding: utf-8 -*-
"""
Testes Unitários do DiagnosticPackager — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

import json
import os
import tempfile
import zipfile
import pytest

from src.dav.modules.telemetry.diagnostic_packager import DiagnosticPackager
from src.dav.modules.telemetry.service import TelemetryService


def test_diagnostic_packager_generate_bundle_and_verify_zip_structure():
    with tempfile.TemporaryDirectory() as tmp_dir:
        sample_logs = "[12:00:01] [INFO] Transmissor conectado via LAN Direto\n[12:00:02] [TELEMETRY] 60.0 FPS"
        sample_route = {"ip": "192.168.10.108", "port": 9000, "mode": "LAN Direto"}
        sample_extra_telemetry = {"fps": 59.9, "bitrate_mbps": 11.8, "latency_ms": 2.1}

        res = DiagnosticPackager.generate_bundle(
            output_dir=tmp_dir,
            logs_text=sample_logs,
            extra_telemetry=sample_extra_telemetry,
            route_info=sample_route,
        )

        assert res.is_success
        zip_path = res.value
        assert os.path.isfile(zip_path)
        assert zip_path.endswith("_DA-V-log.zip")

        # Verifica se o ZIP contém os arquivos obrigatórios
        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()
            assert "session_logs.txt" in namelist
            assert "telemetry_snapshot.json" in namelist
            assert "network_routes.json" in namelist
            assert "system_environment.json" in namelist
            assert "DIAGNOSTIC_MANIFEST.txt" in namelist

            # Valida conteúdo dos logs
            logs_content = zf.read("session_logs.txt").decode("utf-8")
            assert "Transmissor conectado" in logs_content

            # Valida telemetria JSON
            telem_json = json.loads(zf.read("telemetry_snapshot.json").decode("utf-8"))
            assert telem_json["fps"] == 59.9

            # Valida rotas
            route_json = json.loads(zf.read("network_routes.json").decode("utf-8"))
            assert route_json["mode"] == "LAN Direto"

            # Valida ambiente do sistema
            env_json = json.loads(zf.read("system_environment.json").decode("utf-8"))
            assert env_json["dav_version"] == "4.0.0"

