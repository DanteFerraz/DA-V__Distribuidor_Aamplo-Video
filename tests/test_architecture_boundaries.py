# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Governanca Arquitetural Automatizada via AST — DA-V v4.6
Autor: Dante Ferraz (MonoTech)

Garante invariantes estruturais da Arquitetura Hexagonal + Fatias Verticais:
1. Nenhum modulo em `src/` pode importar `scripts.*`.
2. `src/dav/kernel/` nao pode importar `src.dav.modules.*` nem `src.ui.*`.
3. As fatias de dominio puras nao podem importar `src.ui.*` nem `PySide6`.
4. Todos os 9 manifestos expoem `MANIFEST`, `service_factory` e `exports["service"]`,
   e `ModuleRegistry.get_service(name)` resolve singletons aderentes aos `Protocol`s.
5. `StreamEngineService` unifica `CaptureService`, `CodecService`, `TransportService` e `AudioService`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Set

from src.dav.kernel import (
    IAudioService,
    ICaptureService,
    ICodecService,
    IRemoteDesktopService,
    IStreamEngineService,
    ITelemetryService,
    ITransportService,
    IUniversalInputService,
    ModuleManifest,
    ModuleRegistry,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"


def _extract_imported_modules(py_file: Path) -> List[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    modules: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_no_src_imports_from_scripts():
    """Garante que nenhum arquivo dentro de `src/` importe qualquer modulo de `scripts/`."""
    violations: List[str] = []
    for py_file in sorted(SRC_ROOT.rglob("*.py")):
        for mod in _extract_imported_modules(py_file):
            if mod == "scripts" or mod.startswith("scripts."):
                rel = py_file.relative_to(PROJECT_ROOT).as_posix()
                violations.append(f"{rel} -> {mod}")

    assert not violations, f"Inversao de camada detectada (src -> scripts): {violations}"


def test_kernel_independence():
    """Garante que `src/dav/kernel/` nao importe `src.dav.modules` nem `src.ui`."""
    kernel_dir = SRC_ROOT / "dav" / "kernel"
    violations: List[str] = []
    for py_file in sorted(kernel_dir.rglob("*.py")):
        for mod in _extract_imported_modules(py_file):
            if mod.startswith(("src.dav.modules", "src.ui", "PySide6", "PyQt6")):
                rel = py_file.relative_to(PROJECT_ROOT).as_posix()
                violations.append(f"{rel} -> {mod}")

    assert not violations, f"Acoplamento indevido no Kernel: {violations}"


def test_domain_slices_do_not_import_ui():
    """Garante que as fatias de dominio puras nao importem `src.ui` nem `PySide6`."""
    pure_slices = (
        "capture",
        "codec",
        "transport_p2p",
        "audio",
        "remote_desktop",
        "universal_input",
        "stream_engine",
        "telemetry",
        "commercial",
    )
    allowed_compat_shims: Set[str] = {
        "src/dav/modules/audio/player.py",
    }

    violations: List[str] = []
    for slice_name in pure_slices:
        slice_dir = SRC_ROOT / "dav" / "modules" / slice_name
        for py_file in sorted(slice_dir.rglob("*.py")):
            rel = py_file.relative_to(PROJECT_ROOT).as_posix()
            if rel in allowed_compat_shims:
                continue
            for mod in _extract_imported_modules(py_file):
                if mod.startswith(("src.ui", "PySide6", "PyQt6")):
                    violations.append(f"{rel} -> {mod}")

    assert not violations, f"Vazamento de UI em fatia de dominio: {violations}"


def test_all_manifests_standardized_and_services_resolvable():
    """Valida padronizacao dos 11 manifestos e resolucao singleton via `ModuleRegistry.get_service`."""
    expected_slices = {
        "capture",
        "codec",
        "transport_p2p",
        "audio",
        "remote_desktop",
        "universal_input",
        "stream_engine",
        "telemetry",
        "commercial",
        "presentation",
        "updater",
    }
    registry = ModuleRegistry()
    discovered = registry.discover()
    assert discovered == len(expected_slices)
    assert set(registry.list_modules()) == expected_slices

    for name in expected_slices:
        manifest_mod = __import__(f"src.dav.modules.{name}.manifest", fromlist=["MANIFEST", "manifest"])
        assert hasattr(manifest_mod, "MANIFEST"), f"Fatia '{name}' nao define MANIFEST"
        assert isinstance(manifest_mod.MANIFEST, ModuleManifest)
        assert callable(manifest_mod.MANIFEST.service_factory), f"Fatia '{name}' sem service_factory"
        assert "service" in manifest_mod.MANIFEST.exports, f"Fatia '{name}' sem exports['service']"

        svc1 = registry.get_service(name)
        svc2 = registry.get_service(name)
        assert svc1 is not None, f"get_service('{name}') retornou None"
        assert svc1 is svc2, f"get_service('{name}') deve retornar singleton cacheado"

    assert isinstance(registry.get_service("capture"), ICaptureService)
    assert isinstance(registry.get_service("codec"), ICodecService)
    assert isinstance(registry.get_service("transport_p2p"), ITransportService)
    assert isinstance(registry.get_service("audio"), IAudioService)
    assert isinstance(registry.get_service("remote_desktop"), IRemoteDesktopService)
    assert isinstance(registry.get_service("universal_input"), IUniversalInputService)
    assert isinstance(registry.get_service("stream_engine"), IStreamEngineService)
    assert isinstance(registry.get_service("telemetry"), ITelemetryService)


def test_stream_engine_unifies_audio_and_desktop_api():
    """Verifica que `StreamEngineService` integra `AudioService` e expoe a API unificada."""
    registry = ModuleRegistry()
    registry.discover()
    engine = registry.get_service("stream_engine")

    assert engine is not None
    assert engine.audio_service is not None
    assert engine.transport_service is not None
    assert engine.capture_service is not None
    assert engine.codec_service is not None

    for method_name in (
        "start_transmission",
        "start_reception",
        "pair_peer",
        "stop_all",
        "start_sender",
        "start_receiver",
        "prepare_receiver_socket",
        "set_sender_audio_muted",
        "update_sender_target",
        "wait_sender_endpoint",
        "pair_sender_peer",
        "stop",
    ):
        assert callable(getattr(engine, method_name, None)), f"Metodo ausente no StreamEngineService: {method_name}"
