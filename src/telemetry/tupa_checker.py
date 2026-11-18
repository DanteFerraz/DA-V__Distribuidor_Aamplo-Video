# -*- coding: utf-8 -*-
"""
Shim de Compatibilidade — Redireciona para `src.dav.modules.telemetry.tupa_checker`.
Autor: Dante Ferraz (MonoTech)
"""

from src.dav.modules.telemetry.tupa_checker import HAS_TUPA, TupaHealthChecker, TupaMetricsSnapshot

__all__ = ["HAS_TUPA", "TupaHealthChecker", "TupaMetricsSnapshot"]
