# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
MonoTech Core Kernel — Registro e Descoberta Dinâmica de Módulos (ModuleRegistry)
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("DAV.Kernel.Registry")


@dataclass
class ModuleManifest:
    """Metadados e ganchos de ciclo de vida de uma fatia vertical (módulo)."""
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = "Dante Ferraz (MonoTech)"
    dependencies: List[str] = field(default_factory=list)
    enabled: bool = True
    service_factory: Optional[Callable[[], Any]] = None
    on_startup: Optional[Callable[[Any], None]] = None
    on_shutdown: Optional[Callable[[Any], None]] = None
    exports: Dict[str, Any] = field(default_factory=dict)


class ModuleRegistry:
    """
    Controlador central de módulos plug-and-play.
    Detecta, instancia e gerencia o ciclo de vida dos módulos do DA-V.
    """

    def __init__(self, kernel_context: Optional[Any] = None):
        self._kernel = kernel_context
        self._modules: Dict[str, ModuleManifest] = {}
        self._services: Dict[str, Any] = {}
        self._started_modules: List[str] = []

    def register(self, manifest: ModuleManifest) -> bool:
        """Registra explicitamente um manifesto de módulo."""
        if manifest.name in self._modules:
            logger.warning(f"Módulo '{manifest.name}' já registrado. Substituindo...")
        self._modules[manifest.name] = manifest
        self._services.pop(manifest.name, None)
        logger.info(f"Módulo '{manifest.name}' v{manifest.version} registrado no Kernel.")
        return True

    def get(self, name: str) -> Optional[ModuleManifest]:
        return self._modules.get(name)

    def get_service(self, name: str) -> Optional[Any]:
        """Resolve e retorna a instancia singleton do servico da fatia `name`."""
        if name in self._services:
            return self._services[name]
        manifest = self._modules.get(name)
        if manifest is None or not manifest.enabled:
            return None
        instance = None
        if callable(manifest.service_factory):
            instance = manifest.service_factory()
        elif "service" in manifest.exports:
            svc_target = manifest.exports["service"]
            instance = svc_target() if isinstance(svc_target, type) else svc_target
        if instance is not None:
            self._services[name] = instance
        return instance

    def get_export(self, module_name: str, symbol: str) -> Optional[Any]:
        """Retorna um simbolo publico exportado pelo manifesto de `module_name`."""
        manifest = self._modules.get(module_name)
        if manifest is None or not manifest.enabled:
            return None
        return manifest.exports.get(symbol)

    def is_registered(self, name: str) -> bool:
        return name in self._modules

    def list_modules(self) -> List[str]:
        return list(self._modules.keys())

    def discover(self, modules_package: str = "src.dav.modules", base_dir: Optional[Path] = None) -> int:
        """
        Descobre automaticamente fatias verticais buscando arquivos manifest.py.
        """
        count = 0
        if base_dir is None:
            # Caminho relativo padrão para src/dav/modules
            base_dir = Path(__file__).resolve().parent.parent / "modules"

        if not base_dir.is_dir():
            logger.debug(f"Diretório de módulos '{base_dir}' não encontrado.")
            return 0

        for child in sorted(base_dir.iterdir()):
            if child.is_dir() and (child / "manifest.py").is_file():
                mod_pkg = f"{modules_package}.{child.name}.manifest"
                try:
                    mod = importlib.import_module(mod_pkg)
                    manifest_obj = getattr(mod, "MANIFEST", getattr(mod, "manifest", None))
                    if isinstance(manifest_obj, ModuleManifest):
                        self.register(manifest_obj)
                        count += 1
                    elif callable(getattr(mod, "get_manifest", None)):
                        self.register(mod.get_manifest())
                        count += 1
                except Exception as exc:
                    logger.error(f"Erro ao carregar manifesto de '{child.name}': {exc}")

        if count == 0:
            # Fallback estático para ambiente congelado (PyInstaller) onde o filesystem não expõe .py
            static_modules = [
                "src.dav.modules.capture.manifest",
                "src.dav.modules.codec.manifest",
                "src.dav.modules.transport_p2p.manifest",
                "src.dav.modules.audio.manifest",
                "src.dav.modules.remote_desktop.manifest",
                "src.dav.modules.universal_input.manifest",
                "src.dav.modules.stream_engine.manifest",
                "src.dav.modules.commercial.manifest",
                "src.dav.modules.telemetry.manifest",
                "src.dav.modules.presentation.manifest",
                "src.dav.modules.updater.manifest",
            ]
            for mod_pkg in static_modules:
                try:
                    mod = importlib.import_module(mod_pkg)
                    manifest_obj = getattr(mod, "MANIFEST", getattr(mod, "manifest", None))
                    if isinstance(manifest_obj, ModuleManifest):
                        self.register(manifest_obj)
                        count += 1
                except Exception as exc:
                    logger.debug(f"Fallback estático para '{mod_pkg}' não carregado: {exc}")

        return count

    def startup_all(self) -> None:
        """Executa os hooks on_startup respeitando as dependências declaradas."""
        resolved: List[str] = []
        unresolved = set(self._modules.keys())

        # Resolução simples de dependências
        iterations = 0
        while unresolved and iterations < 50:
            iterations += 1
            progress = False
            for mod_name in list(unresolved):
                manifest = self._modules[mod_name]
                if not manifest.enabled:
                    unresolved.remove(mod_name)
                    progress = True
                    continue
                # Se todas as dependências já estão resolvidas
                if all(dep in resolved for dep in manifest.dependencies if dep in self._modules):
                    resolved.append(mod_name)
                    unresolved.remove(mod_name)
                    progress = True
            if not progress:
                # Dependência circular ou ausente; adiciona o restante
                resolved.extend(unresolved)
                break

        for mod_name in resolved:
            manifest = self._modules[mod_name]
            if manifest.enabled and manifest.on_startup and mod_name not in self._started_modules:
                try:
                    manifest.on_startup(self._kernel)
                    self._started_modules.append(mod_name)
                    logger.info(f"Módulo '{mod_name}' inicializado.")
                except Exception as exc:
                    logger.error(f"Falha ao inicializar módulo '{mod_name}': {exc}")

    def shutdown_all(self) -> None:
        """Executa os hooks on_shutdown em ordem reversa da inicialização."""
        for mod_name in reversed(self._started_modules):
            manifest = self._modules.get(mod_name)
            if manifest and manifest.on_shutdown:
                try:
                    manifest.on_shutdown(self._kernel)
                    logger.info(f"Módulo '{mod_name}' encerrado.")
                except Exception as exc:
                    logger.error(f"Falha ao encerrar módulo '{mod_name}': {exc}")
        self._started_modules.clear()
