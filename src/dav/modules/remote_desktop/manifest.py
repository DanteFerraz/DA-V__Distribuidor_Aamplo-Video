# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Manifesto da Fatia `remote_desktop` — MonoTech Core Kernel v2.0 (DA-V v5.0)
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.remote_desktop.service import RemoteDesktopService

_SERVICE_SINGLETON: RemoteDesktopService | None = None


def _get_service() -> RemoteDesktopService:
    global _SERVICE_SINGLETON
    if _SERVICE_SINGLETON is None:
        _SERVICE_SINGLETON = RemoteDesktopService()
    return _SERVICE_SINGLETON


def _on_shutdown() -> None:
    global _SERVICE_SINGLETON
    if _SERVICE_SINGLETON is not None:
        _SERVICE_SINGLETON.close()
        _SERVICE_SINGLETON = None


MANIFEST = ModuleManifest(
    name="remote_desktop",
    version="5.0.0",
    description="Compartilhamento interativo de area de trabalho (Input HID sub-ms, UAC/Polkit Broker, Clipboard, Arquivos e PTY)",
    dependencies=["transport_p2p"],
    service_factory=_get_service,
    on_shutdown=_on_shutdown,
    exports={"service": _get_service},
)
