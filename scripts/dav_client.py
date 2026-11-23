#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Wrapper CLI e Shim de Compatibilidade para `src.dav.modules.stream_engine.service.StreamEngineService`.
Autor: Dante Ferraz (MonoTech)
"""

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.dav.modules.stream_engine.service import (
    DavCoreEngine,
    DavFrameData,
    DavFrameReadyCallback,
    DavTelemetry,
    DavTelemetryCallback,
    StreamEngineService,
)

__all__ = [
    "DavCoreEngine",
    "StreamEngineService",
    "DavFrameData",
    "DavTelemetry",
    "DavFrameReadyCallback",
    "DavTelemetryCallback",
]
