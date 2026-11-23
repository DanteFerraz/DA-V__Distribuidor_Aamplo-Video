# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Shim de Compatibilidade — Redireciona para `src.dav.modules.telemetry.tupa_checker`.
Autor: Dante Ferraz (MonoTech)
"""

from src.dav.modules.telemetry.tupa_checker import HAS_TUPA, TupaHealthChecker, TupaMetricsSnapshot

__all__ = ["HAS_TUPA", "TupaHealthChecker", "TupaMetricsSnapshot"]
