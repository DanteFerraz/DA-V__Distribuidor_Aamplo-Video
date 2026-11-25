# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
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
import numpy as np

from src.dav.modules.audio.capturer import AUDIO_CHANNELS, AUDIO_SAMPLE_RATE
from src.dav.modules.audio.jitter_asrc import AudioJitterAsrcBuffer

logger = logging.getLogger("DAV.UI.AudioSink")


class DesktopAudioPlayer:
    """
    Alimenta a saida de som do sistema operacional via `PySide6.QtMultimedia.QAudioSink`
    a partir de um `AudioJitterAsrcBuffer`, com negociacao automatica de formato (Int16 / Float32),
    recuperacao de underrun e hot-swap de dispositivo padrao.
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
        self._media_devices = None
        self._use_float_output = False
        self._out_channels = AUDIO_CHANNELS
        self._out_rate = AUDIO_SAMPLE_RATE

    def _open_hardware_sink(self) -> bool:
        from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

        out_dev = QMediaDevices.defaultAudioOutput()
        if out_dev.isNull():
            logger.info("[Audio] Nenhum dispositivo de saida de audio encontrado; seguindo silencioso.")
            return False

        fmt = QAudioFormat()
        fmt.setSampleRate(AUDIO_SAMPLE_RATE)
        fmt.setChannelCount(AUDIO_CHANNELS)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self._use_float_output = False
        self._out_channels = AUDIO_CHANNELS
        self._out_rate = AUDIO_SAMPLE_RATE

        if not out_dev.isFormatSupported(fmt):
            fmt_flt = QAudioFormat()
            fmt_flt.setSampleRate(AUDIO_SAMPLE_RATE)
            fmt_flt.setChannelCount(AUDIO_CHANNELS)
            fmt_flt.setSampleFormat(QAudioFormat.SampleFormat.Float)
            if out_dev.isFormatSupported(fmt_flt):
                fmt = fmt_flt
                self._use_float_output = True
            else:
                pref = out_dev.preferredFormat()
                if pref.sampleFormat() in (QAudioFormat.SampleFormat.Int16, QAudioFormat.SampleFormat.Float):
                    fmt = pref
                    self._use_float_output = (pref.sampleFormat() == QAudioFormat.SampleFormat.Float)
                    self._out_channels = max(1, int(pref.channelCount()))
                    self._out_rate = max(8000, int(pref.sampleRate()))

        bytes_per_sample = 4 if self._use_float_output else 2
        self._sink = QAudioSink(out_dev, fmt, self._parent)
        self._sink.setBufferSize(int(self._out_rate * self._out_channels * bytes_per_sample * 0.050))
        self._sink.setVolume(0.0 if self._muted else self._volume)
        self._io_dev = self._sink.start()
        logger.info(
            f"[Audio] Reproducao ativa em '{out_dev.description()}' "
            f"({self._out_rate} Hz, {self._out_channels}ch, float={self._use_float_output})."
        )
        return self._io_dev is not None

    def _on_audio_outputs_changed(self) -> None:
        if not self._active:
            return
        try:
            if self._sink is not None:
                self._sink.stop()
        except Exception:
            pass
        self._sink = None
        self._io_dev = None
        try:
            self._open_hardware_sink()
        except Exception as exc:
            logger.debug(f"[Audio] Falha ao alternar dispositivo padrao ({exc}).")

    def start(self) -> bool:
        if self._active:
            self.jitter_buffer.reset()
            return True
        self.jitter_buffer.reset()
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtMultimedia import QMediaDevices

            if self._media_devices is None:
                self._media_devices = QMediaDevices(self._parent)
                self._media_devices.audioOutputsChanged.connect(self._on_audio_outputs_changed)

            if not self._open_hardware_sink():
                return False

            self._pump_timer = QTimer(self._parent)
            self._pump_timer.setInterval(8)
            self._pump_timer.timeout.connect(self._pump_to_hardware)
            self._pump_timer.start()
            self._active = True
            return True
        except Exception as exc:
            logger.warning(f"[Audio] Reproducao QAudioSink indisponivel ({exc}).")
            return False

    def push_network_packet(self, frame_id: int, tx_ts_us: int, payload: bytes) -> None:
        self.jitter_buffer.push_audio_packet(frame_id, tx_ts_us, payload)

    def _convert_s16_stereo_for_sink(self, raw_s16: bytes) -> bytes:
        if not self._use_float_output and self._out_channels == 2 and self._out_rate == AUDIO_SAMPLE_RATE:
            return raw_s16
        arr = np.frombuffer(raw_s16, dtype=np.int16).reshape(-1, 2)
        if self._out_rate != AUDIO_SAMPLE_RATE and arr.shape[0] > 1:
            n_in = arr.shape[0]
            n_out = max(1, int(round(n_in * float(self._out_rate) / float(AUDIO_SAMPLE_RATE))))
            x_old = np.linspace(0.0, 1.0, n_in, endpoint=False)
            x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
            c0 = np.interp(x_new, x_old, arr[:, 0].astype(np.float32))
            c1 = np.interp(x_new, x_old, arr[:, 1].astype(np.float32))
            arr_f = np.column_stack((c0, c1)) / 32768.0
        else:
            arr_f = arr.astype(np.float32) / 32768.0

        if self._out_channels == 1:
            arr_f = arr_f.mean(axis=1, keepdims=True)
        elif self._out_channels > 2:
            extra = np.zeros((arr_f.shape[0], self._out_channels - 2), dtype=np.float32)
            arr_f = np.hstack((arr_f, extra))

        if self._use_float_output:
            return np.clip(arr_f, -1.0, 1.0).astype(np.float32).tobytes()
        return np.clip(arr_f * 32767.0, -32768.0, 32767.0).astype(np.int16).tobytes()

    def _pump_to_hardware(self) -> None:
        if not self._active:
            return
        if self._sink is None or self._io_dev is None:
            try:
                self._open_hardware_sink()
            except Exception:
                return
            if self._sink is None or self._io_dev is None:
                return

        try:
            from PySide6.QtMultimedia import QAudio

            if self._sink.state() == QAudio.State.StoppedState and self.jitter_buffer.buffered_ms >= 10.0:
                self._io_dev = self._sink.start()
        except Exception:
            pass

        frame_out_bytes = int(round((self._out_rate * 0.010) * self._out_channels * (4 if self._use_float_output else 2)))
        bytes_free = self._sink.bytesFree()
        if bytes_free < max(512, frame_out_bytes):
            return
        max_frames = max(1, min(6, bytes_free // max(512, frame_out_bytes)))
        raw = self.jitter_buffer.pop_pcm_bytes(max_frames=max_frames)
        if raw:
            out_bytes = self._convert_s16_stereo_for_sink(raw)
            try:
                self._io_dev.write(out_bytes)
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

    def stop(self, destroy_codec: bool = False) -> None:
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
        if destroy_codec:
            self.jitter_buffer.close()
        else:
            self.jitter_buffer.reset()


QtAudioSinkPlayer = DesktopAudioPlayer
