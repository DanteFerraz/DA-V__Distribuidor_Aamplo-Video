# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Testes Unitários do Módulo de Atualizações Automáticas (DA-V v4.0)
Autor: Dante Ferraz (MonoTech)
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from src.dav.kernel.circuit_breaker import CircuitBreaker
from src.dav.kernel.registry import ModuleRegistry
from src.dav.modules.updater.auto_installer import AutoInstaller
from src.dav.modules.updater.manifest import manifest
from src.dav.modules.updater.service import UpdaterService
from src.dav.modules.updater.update_checker import UpdateChecker, UpdateInfo
from src.dav.modules.updater.version_comparator import is_newer_version, parse_semver


class TestVersionComparator(unittest.TestCase):
    """Valida comparações SemVer de versões do DA-V."""

    def test_parse_semver(self):
        self.assertEqual(parse_semver("4.0.0"), (4, 0, 0))
        self.assertEqual(parse_semver("v4.2.1"), (4, 2, 1))
        self.assertEqual(parse_semver("4.1.0-beta2"), (4, 1, 0))
        self.assertEqual(parse_semver("invalid"), (0, 0, 0))

    def test_is_newer_version(self):
        # Versões maiores
        self.assertTrue(is_newer_version("4.1.0", "4.0.0"))
        self.assertTrue(is_newer_version("4.0.1", "4.0.0"))
        self.assertTrue(is_newer_version("5.0.0", "4.9.9"))
        self.assertTrue(is_newer_version("v4.2.0", "4.1.9"))

        # Versões iguais ou menores
        self.assertFalse(is_newer_version("4.0.0", "4.0.0"))
        self.assertFalse(is_newer_version("3.9.9", "4.0.0"))
        self.assertFalse(is_newer_version("4.0.0", "4.1.0"))
        self.assertFalse(is_newer_version("v4.0.0", "4.0.0"))


class TestUpdateChecker(unittest.TestCase):
    """Valida o verificador remoto com simulação de API GitHub."""

    def test_check_with_newer_release(self):
        checker = UpdateChecker()

        mock_payload = {
            "tag_name": "v4.1.0",
            "name": "DA-V v4.1.0 — Modo Ultra-Desempenho 120 FPS",
            "body": "- Otimizações AVX2\n- Interface Blocks.so refinada",
            "published_at": "2026-11-12T10:00:00Z",
            "assets": [
                {
                    "name": "DA-V_v4.1.0_Windows_Setup.exe",
                    "browser_download_url": "https://github.com/releases/download/v4.1.0/setup.exe",
                },
                {
                    "name": "DA-V_v4.1.0_Linux_x86_64.tar.gz",
                    "browser_download_url": "https://github.com/releases/download/v4.1.0/linux.tar.gz",
                },
            ],
        }

        with patch.object(checker.breaker, "execute", return_value=mock_payload):
            res = checker.check(current_version="4.0.0")

            self.assertTrue(res.is_success)
            info: UpdateInfo = res.value
            self.assertTrue(info.has_update)
            self.assertEqual(info.latest_version, "4.1.0")
            self.assertEqual(info.current_version, "4.0.0")
            self.assertIn("120 FPS", info.release_title)
            if sys.platform == "win32":
                self.assertEqual(info.asset_name, "DA-V_v4.1.0_Windows_Setup.exe")
            else:
                self.assertEqual(info.asset_name, "DA-V_v4.1.0_Linux_x86_64.tar.gz")

    def test_check_with_same_version(self):
        checker = UpdateChecker()
        mock_payload = {
            "tag_name": "v4.0.0",
            "name": "DA-V v4.0.0",
            "body": "Versão estável",
            "assets": [],
        }

        with patch.object(checker.breaker, "execute", return_value=mock_payload):
            res = checker.check(current_version="4.0.0")
            self.assertTrue(res.is_success)
            self.assertFalse(res.value.has_update)

    def test_circuit_breaker_open_handling(self):
        breaker = CircuitBreaker("TestBreaker", failure_threshold=1)
        breaker.record_failure()  # Abre o disjuntor
        self.assertFalse(breaker.can_execute())

        checker = UpdateChecker(circuit_breaker=breaker)
        res = checker.check()
        self.assertFalse(res.is_success)
        self.assertEqual(res.code, "CIRCUIT_OPEN")


class TestUpdaterService(unittest.TestCase):
    """Valida o orquestrador UpdaterService e background check."""

    def test_service_background_check(self):
        service = UpdaterService(current_version="4.0.0")

        mock_info = UpdateInfo(
            has_update=True,
            current_version="4.0.0",
            latest_version="4.1.0",
            release_title="Release Test",
            release_notes="Notas",
            download_url="http://test.url",
            asset_name="setup.exe",
        )

        with patch.object(service, "check_for_updates", return_value=MagicMock(is_success=True, value=mock_info)):
            results = []
            ev = unittest.mock.MagicMock()

            def _on_done(res):
                results.append(res)
                ev()

            ok = service.start_background_check(on_complete=_on_done)
            self.assertTrue(ok)
            # Aguarda a conclusão da thread daemon
            import time
            time.sleep(0.1)
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].is_success)

    def test_registry_integration(self):
        reg = ModuleRegistry()
        reg.register(manifest)
        self.assertTrue(reg.is_registered("updater"))
        m = reg.get("updater")
        self.assertIsNotNone(m)
        from src.dav import __version__ as _dav_ver
        self.assertEqual(m.version, _dav_ver)
        service = m.service_factory()
        self.assertIsInstance(service, UpdaterService)


class TestAutoInstaller(unittest.TestCase):
    """Valida validações seguras do instalador."""

    def test_invalid_url_download(self):
        res = AutoInstaller.download_asset("", "setup.exe")
        self.assertFalse(res.is_success)
        self.assertEqual(res.code, "INVALID_URL")

    def test_nonexistent_installer_launch(self):
        res = AutoInstaller.launch_installer_and_exit("/nonexistent/path/setup.exe")
        self.assertFalse(res.is_success)
        self.assertEqual(res.code, "FILE_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()

