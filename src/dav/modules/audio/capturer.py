# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Capturadores de Audio do Sistema Operacional (WASAPI Loopback / PipeWire / Synthetic)
Autor: Dante Ferraz (MonoTech)

Normaliza qualquer dispositivo fonte (ex.: DAC 192kHz, 96kHz, 44.1kHz, float32 ou s16)
para o formato canonico do protocolo DA-V: 48000 Hz, 2 canais estereo, int16, blocos de 10 ms (480 amostras).
"""

from __future__ import annotations

import logging
import math
import os
import queue
import select
import shutil
import struct
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional
import numpy as np

logger = logging.getLogger("DAV.Audio.Capturer")

AUDIO_SAMPLE_RATE = 48000
AUDIO_CHANNELS = 2
AUDIO_FRAME_SAMPLES = 480  # 10 ms @ 48 kHz
AUDIO_FRAME_BYTES = AUDIO_FRAME_SAMPLES * AUDIO_CHANNELS * 2  # 1920 bytes


def decode_raw_pcm_bytes_to_float32(
    raw_bytes: bytes,
    bits_per_sample: int,
    is_float: bool = False,
) -> np.ndarray:
    """
    Decodifica bytes PCM de dispositivos WASAPI/ALSA em qualquer profundidade (16-bit int,
    24-bit int empacotado em 3 bytes, 32-bit int ou 32-bit IEEE float) para float32 [-1.0, 1.0].
    """
    if not raw_bytes:
        return np.zeros(0, dtype=np.float32)

    if is_float and bits_per_sample == 32:
        usable = (len(raw_bytes) // 4) * 4
        if usable == 0:
            return np.zeros(0, dtype=np.float32)
        arr = np.frombuffer(raw_bytes[:usable], dtype=np.float32)
        return np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=-1.0)

    if bits_per_sample == 24:
        usable = (len(raw_bytes) // 3) * 3
        if usable == 0:
            return np.zeros(0, dtype=np.float32)
        triplets = np.frombuffer(raw_bytes[:usable], dtype=np.uint8).reshape(-1, 3)
        # Empacota 24-bit signed little-endian no MSB de int32 para preservar sinal em complemento de 2
        packed32 = (
            (triplets[:, 0].astype(np.uint32) << 8)
            | (triplets[:, 1].astype(np.uint32) << 16)
            | (triplets[:, 2].astype(np.uint32) << 24)
        ).view(np.int32)
        return packed32.astype(np.float32) / 2147483648.0

    if bits_per_sample == 32:
        usable = (len(raw_bytes) // 4) * 4
        if usable == 0:
            return np.zeros(0, dtype=np.float32)
        arr32 = np.frombuffer(raw_bytes[:usable], dtype=np.int32)
        return arr32.astype(np.float32) / 2147483648.0

    if bits_per_sample == 8:
        arr8 = np.frombuffer(raw_bytes, dtype=np.uint8)
        return (arr8.astype(np.float32) - 128.0) / 128.0

    usable = (len(raw_bytes) // 2) * 2
    if usable == 0:
        return np.zeros(0, dtype=np.float32)
    arr16 = np.frombuffer(raw_bytes[:usable], dtype=np.int16)
    return arr16.astype(np.float32) / 32768.0


def resample_to_48k_stereo_s16(
    pcm: np.ndarray,
    src_rate: int,
    src_channels: int,
    is_float: bool = False,
) -> np.ndarray:
    """
    Converte PCM de entrada (rate/canais arbitrarios, float32 ou int16) para
    matriz int16 shape=(N_out, 2) a 48000 Hz, com downmix seguro para 5.1 / 7.1.
    """
    if pcm.size == 0:
        return np.zeros((0, AUDIO_CHANNELS), dtype=np.int16)

    ch = max(1, int(src_channels))
    usable_elems = (pcm.size // ch) * ch
    if usable_elems == 0:
        return np.zeros((0, AUDIO_CHANNELS), dtype=np.int16)

    arr = pcm.reshape(-1)[:usable_elems].reshape(-1, ch)
    if is_float or arr.dtype in (np.float32, np.float64):
        arr_f = np.clip(arr.astype(np.float32, copy=False), -1.0, 1.0)
    elif arr.dtype == np.int32:
        arr_f = np.clip(arr.astype(np.float32) / 2147483648.0, -1.0, 1.0)
    else:
        arr_f = arr.astype(np.float32) / 32768.0

    # Normaliza para exatamente 2 canais (com downmix ITU para surround >= 6ch)
    if arr_f.shape[1] == 1:
        arr_f = np.repeat(arr_f, 2, axis=1)
    elif arr_f.shape[1] >= 6:
        left = arr_f[:, 0] + 0.707 * arr_f[:, 2] + 0.707 * arr_f[:, 4]
        right = arr_f[:, 1] + 0.707 * arr_f[:, 2] + 0.707 * arr_f[:, 5]
        arr_f = np.clip(np.column_stack((left, right)), -1.0, 1.0)
    elif arr_f.shape[1] > 2:
        arr_f = arr_f[:, :2]

    # Reamostragem rapida para 48000 Hz
    if src_rate == AUDIO_SAMPLE_RATE or src_rate <= 0:
        out_f = arr_f
    elif src_rate == 192000 and arr_f.shape[0] >= 4:
        usable = (arr_f.shape[0] // 4) * 4
        out_f = arr_f[:usable].reshape(-1, 4, 2).mean(axis=1)
    elif src_rate == 96000 and arr_f.shape[0] >= 2:
        usable = (arr_f.shape[0] // 2) * 2
        out_f = arr_f[:usable].reshape(-1, 2, 2).mean(axis=1)
    else:
        n_in = arr_f.shape[0]
        n_out = max(1, int(round(n_in * float(AUDIO_SAMPLE_RATE) / float(src_rate))))
        x_old = np.linspace(0.0, 1.0, n_in, endpoint=False)
        x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
        c0 = np.interp(x_new, x_old, arr_f[:, 0])
        c1 = np.interp(x_new, x_old, arr_f[:, 1])
        out_f = np.column_stack((c0, c1))

    return np.clip(out_f * 32767.0, -32768.0, 32767.0).astype(np.int16)


class BaseAudioCapturer(ABC):
    """Interface comum para captura em blocos exatos de 10 ms (480 amostras estereo s16)."""

    @abstractmethod
    def start(self) -> bool:
        pass

    @abstractmethod
    def read_frame(self, timeout: float = 0.025) -> Optional[np.ndarray]:
        """Retorna ndarray int16 shape (480, 2) ou None em timeout."""
        pass

    @abstractmethod
    def close(self) -> None:
        pass


class SyntheticAudioCapturer(BaseAudioCapturer):
    """Gerador sintetico 48 kHz (acorde suave / silencio controlado) para CI e testes."""

    def __init__(self, freq_hz: float = 440.0, amplitude: float = 0.15, silence: bool = False):
        self.freq_hz = freq_hz
        self.amplitude = amplitude
        self.silence = silence
        self._running = False
        self._sample_idx = 0
        self._next_t = 0.0

    def start(self) -> bool:
        self._running = True
        self._next_t = time.perf_counter()
        return True

    def read_frame(self, timeout: float = 0.025) -> Optional[np.ndarray]:
        if not self._running:
            return None
        self._next_t += AUDIO_FRAME_SAMPLES / float(AUDIO_SAMPLE_RATE)
        rem = self._next_t - time.perf_counter()
        if rem > 0.001:
            time.sleep(min(rem, timeout))

        if self.silence:
            self._sample_idx += AUDIO_FRAME_SAMPLES
            return np.zeros((AUDIO_FRAME_SAMPLES, AUDIO_CHANNELS), dtype=np.int16)

        idx = self._sample_idx + np.arange(AUDIO_FRAME_SAMPLES, dtype=np.float32)
        self._sample_idx += AUDIO_FRAME_SAMPLES
        t = idx / float(AUDIO_SAMPLE_RATE)
        ch_l = np.sin(2.0 * math.pi * self.freq_hz * t) * (32767.0 * self.amplitude)
        ch_r = np.sin(2.0 * math.pi * (self.freq_hz * 1.25) * t) * (32767.0 * self.amplitude)
        return np.column_stack((ch_l, ch_r)).astype(np.int16)

    def close(self) -> None:
        self._running = False


class WinWasapiLoopbackCapturer(BaseAudioCapturer):
    """
    Capturador nativo Windows WASAPI Loopback via COM (comtypes/ctypes).
    Emite silencio digital quando nenhum app toca som para manter o clock continuo.
    """

    def __init__(self):
        self._q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=24)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._ready_evt = threading.Event()
        self._ok = False

    def start(self) -> bool:
        if sys.platform != "win32":
            return False
        self._running = True
        self._ready_evt.clear()
        self._thread = threading.Thread(target=self._run_com_loop, daemon=True, name="DAV-WASAPI-Loopback")
        self._thread.start()
        self._ready_evt.wait(timeout=1.5)
        if not self._ok:
            self.close()
        return self._ok

    def _run_com_loop(self) -> None:
        import ctypes
        import comtypes
        from comtypes import COMMETHOD, GUID, IUnknown
        from ctypes import HRESULT, POINTER, byref, c_int, c_int64, c_ubyte, c_uint16, c_uint32, c_uint64, c_void_p

        class WAVEFORMATEX(ctypes.Structure):
            _fields_ = [
                ("wFormatTag", c_uint16),
                ("nChannels", c_uint16),
                ("nSamplesPerSec", c_uint32),
                ("nAvgBytesPerSec", c_uint32),
                ("nBlockAlign", c_uint16),
                ("wBitsPerSample", c_uint16),
                ("cbSize", c_uint16),
            ]

        class IMMDevice(IUnknown):
            _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
            _methods_ = [
                COMMETHOD([], HRESULT, "Activate",
                    (["in"], POINTER(GUID), "iid"),
                    (["in"], c_uint32, "dwClsCtx"),
                    (["in"], c_void_p, "pActivationParams"),
                    (["out"], POINTER(c_void_p), "ppInterface")),
            ]

        class IMMDeviceEnumerator(IUnknown):
            _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
            _methods_ = [
                COMMETHOD([], HRESULT, "EnumAudioEndpoints",
                    (["in"], c_int, "dataFlow"),
                    (["in"], c_uint32, "dwStateMask"),
                    (["out"], POINTER(c_void_p), "ppDevices")),
                COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint",
                    (["in"], c_int, "dataFlow"),
                    (["in"], c_int, "role"),
                    (["out"], POINTER(POINTER(IMMDevice)), "ppEndpoint")),
            ]

        class IAudioCaptureClient(IUnknown):
            _iid_ = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
            _methods_ = [
                COMMETHOD([], HRESULT, "GetBuffer",
                    (["out"], POINTER(POINTER(c_ubyte)), "ppData"),
                    (["out"], POINTER(c_uint32), "pNumFramesToRead"),
                    (["out"], POINTER(c_uint32), "pdwFlags"),
                    (["out"], POINTER(c_uint64), "pu64DevicePosition"),
                    (["out"], POINTER(c_uint64), "pu64QPCPosition")),
                COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "NumFramesRead")),
                COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "pNumFramesInNextPacket")),
            ]

        class IAudioClient(IUnknown):
            _iid_ = GUID("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
            _methods_ = [
                COMMETHOD([], HRESULT, "Initialize",
                    (["in"], c_int, "ShareMode"),
                    (["in"], c_uint32, "StreamFlags"),
                    (["in"], c_int64, "hnsBufferDuration"),
                    (["in"], c_int64, "hnsPeriodicity"),
                    (["in"], POINTER(WAVEFORMATEX), "pFormat"),
                    (["in"], c_void_p, "AudioSessionGuid")),
                COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(c_uint32), "pNumBufferFrames")),
                COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(c_int64), "phnsLatency")),
                COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(c_uint32), "pNumPaddingFrames")),
                COMMETHOD([], HRESULT, "IsFormatSupported",
                    (["in"], c_int, "ShareMode"),
                    (["in"], POINTER(WAVEFORMATEX), "pFormat"),
                    (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppClosestMatch")),
                COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppDeviceFormat")),
                COMMETHOD([], HRESULT, "GetDevicePeriod",
                    (["out"], POINTER(c_int64), "phnsDefaultDevicePeriod"),
                    (["out"], POINTER(c_int64), "phnsMinimumDevicePeriod")),
                COMMETHOD([], HRESULT, "Start"),
                COMMETHOD([], HRESULT, "Stop"),
                COMMETHOD([], HRESULT, "Reset"),
                COMMETHOD([], HRESULT, "SetEventHandle", (["in"], c_void_p, "eventHandle")),
                COMMETHOD([], HRESULT, "GetService",
                    (["in"], POINTER(GUID), "riid"),
                    (["out"], POINTER(c_void_p), "ppv")),
            ]

        try:
            comtypes.CoInitialize()
        except Exception as exc:
            logger.warning(f"[Audio] CoInitialize falhou ({exc}).")
            self._ok = False
            self._ready_evt.set()
            return

        first_attempt = True
        try:
            while self._running:
                ac = None
                fmt_ptr = None
                try:
                    enum = comtypes.CoCreateInstance(
                        GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}"), interface=IMMDeviceEnumerator
                    )
                    try:
                        dev = enum.GetDefaultAudioEndpoint(0, 0)  # eRender=0, eConsole=0 (jogos / desktop)
                    except Exception:
                        dev = enum.GetDefaultAudioEndpoint(0, 1)  # fallback eMultimedia=1
                    raw_ac = dev.Activate(byref(IAudioClient._iid_), comtypes.CLSCTX_ALL, None)
                    ac = ctypes.cast(raw_ac, POINTER(IAudioClient))
                    fmt_ptr = ac.GetMixFormat()
                    wfx = fmt_ptr.contents

                    src_rate = int(wfx.nSamplesPerSec)
                    src_ch = max(1, int(wfx.nChannels))
                    src_bits = int(wfx.wBitsPerSample)
                    block_align = max(1, int(wfx.nBlockAlign))
                    w_tag = int(wfx.wFormatTag)
                    is_float = (w_tag == 3)
                    if w_tag == 0xFFFE and int(wfx.cbSize) >= 22:
                        raw_fmt = ctypes.string_at(fmt_ptr, 40)
                        sub_tag = struct.unpack_from("<I", raw_fmt, 24)[0]
                        is_float = (sub_tag == 3)

                    ac.Initialize(0, 0x00020000, 200000, 0, fmt_ptr, None)  # LOOPBACK, 20ms
                    raw_cap = ac.GetService(byref(IAudioCaptureClient._iid_))
                    cap = ctypes.cast(raw_cap, POINTER(IAudioCaptureClient))
                    ac.Start()

                    if first_attempt:
                        self._ok = True
                        self._ready_evt.set()
                        first_attempt = False
                    logger.info(
                        f"[Audio] WASAPI Loopback ativo ({src_rate} Hz, {src_ch}ch, {src_bits}-bit float={is_float})."
                    )

                    pending_s16 = np.zeros((0, AUDIO_CHANNELS), dtype=np.int16)
                    last_emit = time.perf_counter()

                    while self._running:
                        got_audio = False
                        try:
                            pkt_frames = int(cap.GetNextPacketSize())
                        except Exception:
                            # Dispositivo invalidado (ex: Secure Desktop UAC ou troca de fone/HDMI) -> reabre!
                            break

                        session_broken = False
                        while pkt_frames > 0 and self._running:
                            try:
                                p_data, n_frames, dw_flags, _, _ = cap.GetBuffer()
                            except Exception:
                                session_broken = True
                                break
                            n_f = int(n_frames)
                            try:
                                if n_f > 0:
                                    got_audio = True
                                    if dw_flags & 0x2:  # AUDCLNT_BUFFERFLAGS_SILENT
                                        n_out = max(1, int(round(n_f * AUDIO_SAMPLE_RATE / max(1, src_rate))))
                                        chunk = np.zeros((n_out, AUDIO_CHANNELS), dtype=np.int16)
                                    else:
                                        raw_bytes = ctypes.string_at(p_data, n_f * block_align)
                                        arr_f32 = decode_raw_pcm_bytes_to_float32(
                                            raw_bytes, bits_per_sample=src_bits, is_float=is_float
                                        )
                                        chunk = resample_to_48k_stereo_s16(
                                            arr_f32, src_rate, src_ch, is_float=True
                                        )
                                    if chunk.shape[0] > 0:
                                        pending_s16 = (
                                            np.vstack((pending_s16, chunk)) if pending_s16.shape[0] > 0 else chunk
                                        )
                            finally:
                                try:
                                    cap.ReleaseBuffer(n_f)
                                except Exception:
                                    session_broken = True

                            if session_broken:
                                break
                            try:
                                pkt_frames = int(cap.GetNextPacketSize())
                            except Exception:
                                session_broken = True
                                break

                        if session_broken:
                            break

                        while pending_s16.shape[0] >= AUDIO_FRAME_SAMPLES:
                            out_blk = pending_s16[:AUDIO_FRAME_SAMPLES]
                            pending_s16 = pending_s16[AUDIO_FRAME_SAMPLES:]
                            self._push_frame(out_blk)
                            last_emit = time.perf_counter()

                        if not got_audio:
                            now = time.perf_counter()
                            if now - last_emit >= 0.012:
                                self._push_frame(np.zeros((AUDIO_FRAME_SAMPLES, AUDIO_CHANNELS), dtype=np.int16))
                                last_emit = now
                            time.sleep(0.004)
                except Exception as exc:
                    if first_attempt:
                        logger.warning(f"[Audio] WASAPI Loopback indisponivel ({exc}).")
                        self._ok = False
                        self._ready_evt.set()
                        return
                    logger.debug(f"[Audio] Reabrindo sessao WASAPI apos transicao ({exc})...")
                finally:
                    if ac is not None:
                        try:
                            ac.Stop()
                        except Exception:
                            pass
                    if fmt_ptr is not None:
                        try:
                            ctypes.windll.ole32.CoTaskMemFree(fmt_ptr)
                        except Exception:
                            pass

                if self._running:
                    # Durante reabertura (ex: prompt UAC), mantem clock de silencio para nao travar ASRC
                    self._push_frame(np.zeros((AUDIO_FRAME_SAMPLES, AUDIO_CHANNELS), dtype=np.int16))
                    time.sleep(0.20)
        finally:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass

    def _push_frame(self, blk: np.ndarray) -> None:
        try:
            self._q.put_nowait(blk)
        except queue.Full:
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(blk)
            except queue.Full:
                pass

    def read_frame(self, timeout: float = 0.025) -> Optional[np.ndarray]:
        if not self._running:
            return None
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        self._thread = None


class LinuxPipeWireAudioCapturer(BaseAudioCapturer):
    """Capturador Linux PipeWire/PulseAudio monitor via subprocesso sanitizado e leitura nao-bloqueante."""

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._running = False
        self._read_buf = bytearray()
        self._last_emit_mono = 0.0
        self._cmd_candidates: list[list[str]] = []
        self._cmd_idx = 0
        self._env: dict = {}

    def _build_candidates(self) -> list[list[str]]:
        cands: list[list[str]] = []
        if shutil.which("parec"):
            cands.append([
                "parec",
                "--raw",
                "--device=@DEFAULT_MONITOR@",
                "--format=s16le",
                "--rate=48000",
                "--channels=2",
                "--latency-msec=10",
            ])
        if shutil.which("pw-cat"):
            cands.append([
                "pw-cat",
                "--record",
                "--raw",
                "--format=s16",
                "--rate=48000",
                "--channels=2",
                "--latency=10ms",
                "-P",
                "{ stream.capture.sink=true }",
                "-",
            ])
        if shutil.which("pw-record"):
            cands.append([
                "pw-record",
                "--raw",
                "--format=s16",
                "--rate=48000",
                "--channels=2",
                "-P",
                "{ stream.capture.sink=true }",
                "-",
            ])
        return cands

    def _spawn_current(self) -> bool:
        while self._cmd_idx < len(self._cmd_candidates):
            cmd = self._cmd_candidates[self._cmd_idx]
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=self._env,
                )
                time.sleep(0.03)
                if proc.poll() is not None:
                    self._cmd_idx += 1
                    continue
                if proc.stdout is not None and hasattr(os, "set_blocking"):
                    try:
                        os.set_blocking(proc.stdout.fileno(), False)
                    except Exception:
                        pass
                self._proc = proc
                self._read_buf.clear()
                self._last_emit_mono = time.perf_counter()
                return True
            except Exception:
                self._cmd_idx += 1
        return False

    def start(self) -> bool:
        if sys.platform == "win32":
            return False
        env = os.environ.copy()
        if getattr(sys, "frozen", False):
            env.pop("PYTHONHOME", None)
            env.pop("PYTHONPATH", None)
            ld_path = env.get("LD_LIBRARY_PATH", "")
            meipass = getattr(sys, "_MEIPASS", "")
            if ld_path and meipass:
                env["LD_LIBRARY_PATH"] = ":".join(
                    p for p in ld_path.split(":") if p and meipass not in p
                )
        self._env = env
        self._cmd_candidates = self._build_candidates()
        self._cmd_idx = 0
        if not self._cmd_candidates:
            return False
        if not self._spawn_current():
            return False
        self._running = True
        return True

    def read_frame(self, timeout: float = 0.025) -> Optional[np.ndarray]:
        if not self._running:
            return None
        if self._proc is None or self._proc.poll() is not None or self._proc.stdout is None:
            self._cmd_idx = min(self._cmd_idx + 1, max(0, len(self._cmd_candidates) - 1))
            if not self._spawn_current():
                time.sleep(min(0.010, max(0.001, timeout)))
                return np.zeros((AUDIO_FRAME_SAMPLES, AUDIO_CHANNELS), dtype=np.int16)

        fd = self._proc.stdout.fileno()
        deadline = time.perf_counter() + max(0.002, float(timeout))
        while len(self._read_buf) < AUDIO_FRAME_BYTES and time.perf_counter() < deadline:
            rem = max(0.001, deadline - time.perf_counter())
            try:
                rlist, _, _ = select.select([fd], [], [], rem)
            except Exception:
                rlist = [fd]
            if not rlist:
                break
            try:
                chunk = os.read(fd, max(4096, AUDIO_FRAME_BYTES - len(self._read_buf)))
            except BlockingIOError:
                break
            except OSError:
                break
            if not chunk:
                break
            self._read_buf.extend(chunk)

        if len(self._read_buf) >= AUDIO_FRAME_BYTES:
            raw = bytes(self._read_buf[:AUDIO_FRAME_BYTES])
            del self._read_buf[:AUDIO_FRAME_BYTES]
            self._last_emit_mono = time.perf_counter()
            return np.frombuffer(raw, dtype=np.int16).reshape((AUDIO_FRAME_SAMPLES, AUDIO_CHANNELS)).copy()

        # PipeWire suspende monitores ociosos: emite silencio digital a cada 12 ms sem bloquear
        now = time.perf_counter()
        if (now - self._last_emit_mono) >= 0.012:
            self._last_emit_mono = now
            return np.zeros((AUDIO_FRAME_SAMPLES, AUDIO_CHANNELS), dtype=np.int16)
        return None

    def close(self) -> None:
        self._running = False
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=0.4)
            except Exception:
                pass
            self._proc = None


def create_audio_capturer(prefer_synthetic: bool = False) -> BaseAudioCapturer:
    """Fabrica multiplataforma com degradacao limpa para silencio sintetico em CI."""
    if prefer_synthetic or os.environ.get("DAV_HEADLESS_SYNTHETIC") == "1":
        cap = SyntheticAudioCapturer()
        cap.start()
        return cap

    if sys.platform == "win32":
        wasapi = WinWasapiLoopbackCapturer()
        if wasapi.start():
            return wasapi
    else:
        pw = LinuxPipeWireAudioCapturer()
        if pw.start():
            return pw

    fallback = SyntheticAudioCapturer(silence=True)
    fallback.start()
    return fallback
