# -*- coding: utf-8 -*-
"""
Adaptador Desktop de Audio Low-Latency (`QAudioSink` + `AudioJitterAsrcBuffer`) — DA-V v4.6
Autor: Dante Ferraz (MonoTech)

Reside na camada de apresentacao (`src.ui`), consumindo o buffer de dominio
`AudioJitterAsrcBuffer` fornecido por `AudioService`.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.dav.modules.audio.capturer import AUDIO_CHANNELS, AUDIO_SAMPLE_RATE
from src.dav.modules.audio.jitter_asrc import AudioJitterAsrcBuffer

logger = logging.getLogger("DAV.UI.AudioSink")


class DesktopAudioPlayer:
    """
    Alimenta a saida de som do sistema operacional via `PySide6.QtMultimedia.QAudioSink`
    a partir de um `AudioJitterAsrcBuffer`.
    """

    def __init__(self, parent=None, jitter_buffer: Optional[AudioJitterAsrcBuffer] = None):
        self.jitter_buffer = jitter_buffer or AudioJitterAsrcBuffer()
        self._parent = parent
        self._muted = False
        self._volume = 1.0
        self._active = False
        self._sink = None
        self._io_dev = None
        self._pump_timer = None

    def start(self) -> bool:
        if self._active:
            return True
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

            out_dev = QMediaDevices.defaultAudioOutput()
            if out_dev.isNull():
                logger.info("[Audio] Nenhum dispositivo de saida de audio encontrado; seguindo silencioso.")
                return False

            fmt = QAudioFormat()
            fmt.setSampleRate(AUDIO_SAMPLE_RATE)
            fmt.setChannelCount(AUDIO_CHANNELS)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)

            self._sink = QAudioSink(out_dev, fmt, self._parent)
            self._sink.setBufferSize(int(AUDIO_SAMPLE_RATE * AUDIO_CHANNELS * 2 * 0.045))
            self._sink.setVolume(0.0 if self._muted else self._volume)
            self._io_dev = self._sink.start()

            self._pump_timer = QTimer(self._parent)
            self._pump_timer.setInterval(8)
            self._pump_timer.timeout.connect(self._pump_to_hardware)
            self._pump_timer.start()
            self._active = True
            logger.info(f"[Audio] Reproducao ativa em '{out_dev.description()}' (48 kHz Estereo).")
            return True
        except Exception as exc:
            logger.warning(f"[Audio] Reproducao QAudioSink indisponivel ({exc}).")
            return False

    def push_network_packet(self, frame_id: int, tx_ts_us: int, payload: bytes) -> None:
        self.jitter_buffer.push_audio_packet(frame_id, tx_ts_us, payload)

    def _pump_to_hardware(self) -> None:
        if not self._active or self._io_dev is None or self._sink is None:
            return
        bytes_free = self._sink.bytesFree()
        if bytes_free < 1920:
            return
        max_frames = max(1, min(6, bytes_free // 1920))
        raw = self.jitter_buffer.pop_pcm_bytes(max_frames=max_frames)
        if raw:
            try:
                self._io_dev.write(raw)
            except Exception:
                pass

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        if self._sink is not None:
            self._sink.setVolume(0.0 if self._muted else self._volume)

    def set_volume(self, vol_0_to_1: float) -> None:
        self._volume = max(0.0, min(1.0, float(vol_0_to_1)))
        if self._sink is not None and not self._muted:
            self._sink.setVolume(self._volume)

    @property
    def is_muted(self) -> bool:
        return self._muted

    def stop(self) -> None:
        self._active = False
        if self._pump_timer is not None:
            try:
                self._pump_timer.stop()
            except Exception:
                pass
            self._pump_timer = None
        if self._sink is not None:
            try:
                self._sink.stop()
            except Exception:
                pass
            self._sink = None
            self._io_dev = None
        self.jitter_buffer.close()


QtAudioSinkPlayer = DesktopAudioPlayer
