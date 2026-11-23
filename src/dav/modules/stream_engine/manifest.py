# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Manifesto do Modulo StreamEngine — DA-V v4.6
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.stream_engine.receiver_worker import ReceiverWorker
from src.dav.modules.stream_engine.sender_worker import SenderWorker
from src.dav.modules.stream_engine.service import DavCoreEngine, StreamEngineService

MANIFEST = ModuleManifest(
    name="stream_engine",
    version="4.6.0",
    description="Orquestrador unificado de transmissao e recepcao A/V em tempo real",
    author="Dante Ferraz (MonoTech)",
    dependencies=["capture", "codec", "transport_p2p", "audio"],
    enabled=True,
    service_factory=lambda: StreamEngineService(),
    exports={
        "service": StreamEngineService,
        "StreamEngineService": StreamEngineService,
        "DavCoreEngine": DavCoreEngine,
        "SenderWorker": SenderWorker,
        "ReceiverWorker": ReceiverWorker,
    },
)

manifest = MANIFEST
