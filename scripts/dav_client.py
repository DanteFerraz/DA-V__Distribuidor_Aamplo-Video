#!/usr/bin/env python3
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
