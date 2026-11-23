# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Shim de Compatibilidade — Redireciona para `src.ui.audio_sink.DesktopAudioPlayer`.
Autor: Dante Ferraz (MonoTech)
"""

from src.ui.audio_sink import DesktopAudioPlayer, QtAudioSinkPlayer

__all__ = ["DesktopAudioPlayer", "QtAudioSinkPlayer"]
