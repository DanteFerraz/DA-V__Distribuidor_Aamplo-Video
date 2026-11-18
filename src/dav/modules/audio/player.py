# -*- coding: utf-8 -*-
"""
Shim de Compatibilidade — Redireciona para `src.ui.audio_sink.DesktopAudioPlayer`.
Autor: Dante Ferraz (MonoTech)
"""

from src.ui.audio_sink import DesktopAudioPlayer, QtAudioSinkPlayer

__all__ = ["DesktopAudioPlayer", "QtAudioSinkPlayer"]
