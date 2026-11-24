# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Contrato Base de Injecao de Input, StuckKeyWatchdog e Injetor Sintetico — DA-V v5.0
Autor: Dante Ferraz (MonoTech)

Garante que nenhuma tecla modificadora (Ctrl/Alt/Shift/Win) nem botao de mouse permaneca
preso no sistema operacional hospedeiro caso a rede sofra perda abrupta, desconexao ou
revogacao de emergencia.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import collections
from dataclasses import dataclass
import threading
import time
from typing import Deque, List, Optional, Set, Tuple

from src.dav.modules.remote_desktop.protocol import EvType, InputEventPacket, MouseBtn


@dataclass
class MonitorBounds:
    left: int = 0
    top: int = 0
    width: int = 1920
    height: int = 1080


class StuckKeyWatchdog:
    """Rastreador de teclas e botoes pressionados com soltura automatica por timeout."""

    def __init__(self, timeout_sec: float = 0.45):
        self.timeout_sec = max(0.10, float(timeout_sec))
        self._lock = threading.Lock()
        self._pressed_keys: Set[int] = set()
        self._pressed_buttons: int = 0
        self._last_activity_mono: float = time.monotonic()

    @property
    def pressed_keys(self) -> Set[int]:
        with self._lock:
            return set(self._pressed_keys)

    @property
    def pressed_buttons(self) -> int:
        with self._lock:
            return int(self._pressed_buttons)

    def record_event(self, pkt: InputEventPacket, now_mono: Optional[float] = None) -> None:
        now = now_mono if now_mono is not None else time.monotonic()
        with self._lock:
            self._last_activity_mono = now
            if pkt.ev_type == EvType.KEY_DOWN and pkt.key_or_wheel > 0:
                self._pressed_keys.add(int(pkt.key_or_wheel))
            elif pkt.ev_type == EvType.KEY_UP and pkt.key_or_wheel > 0:
                self._pressed_keys.discard(int(pkt.key_or_wheel))
            elif pkt.ev_type == EvType.BTN_DOWN:
                self._pressed_buttons |= int(pkt.buttons_mask)
            elif pkt.ev_type == EvType.BTN_UP:
                self._pressed_buttons &= ~int(pkt.buttons_mask)
            elif pkt.ev_type == EvType.HEARTBEAT:
                # Sincroniza mascara real de botoes com o cliente; se o cliente soltou todos, limpa
                if pkt.buttons_mask == 0 and self._pressed_buttons != 0:
                    self._pressed_buttons = 0
            elif pkt.ev_type == EvType.RELEASE_ALL:
                self._pressed_keys.clear()
                self._pressed_buttons = 0

    def drain_release_all(self) -> List[InputEventPacket]:
        """Gera eventos explicitos de soltura para todas as teclas e botoes atualmente retidos."""
        with self._lock:
            keys = sorted(self._pressed_keys)
            btns = self._pressed_buttons
            self._pressed_keys.clear()
            self._pressed_buttons = 0
        return self._build_release_packets(keys, btns)

    def check_timeout(self, now_mono: Optional[float] = None) -> List[InputEventPacket]:
        now = now_mono if now_mono is not None else time.monotonic()
        with self._lock:
            if not self._pressed_keys and self._pressed_buttons == 0:
                return []
            if (now - self._last_activity_mono) < self.timeout_sec:
                return []
            keys = sorted(self._pressed_keys)
            btns = self._pressed_buttons
            self._pressed_keys.clear()
            self._pressed_buttons = 0
        return self._build_release_packets(keys, btns)

    @staticmethod
    def _build_release_packets(keys: List[int], btns_mask: int) -> List[InputEventPacket]:
        out: List[InputEventPacket] = []
        for bit in (MouseBtn.LEFT, MouseBtn.RIGHT, MouseBtn.MIDDLE, MouseBtn.BACK, MouseBtn.FORWARD):
            if btns_mask & int(bit):
                out.append(InputEventPacket(ev_type=EvType.BTN_UP, buttons_mask=int(bit)))
        for hid_key in keys:
            out.append(InputEventPacket(ev_type=EvType.KEY_UP, key_or_wheel=int(hid_key)))
        return out


class BaseInputInjector(ABC):
    """Interface comum para injetores nativos de eventos de mouse e teclado."""

    def __init__(self, bounds: Optional[MonitorBounds] = None):
        self.bounds = bounds or MonitorBounds()
        self.watchdog = StuckKeyWatchdog()

    @property
    @abstractmethod
    def backend_name(self) -> str:
        ...

    @property
    def is_elevated(self) -> bool:
        return False

    def update_monitor_bounds(self, left: int, top: int, width: int, height: int) -> None:
        self.bounds = MonitorBounds(
            left=int(left),
            top=int(top),
            width=max(1, int(width)),
            height=max(1, int(height)),
        )

    def inject(self, pkt: InputEventPacket) -> bool:
        if pkt.ev_type == EvType.RELEASE_ALL:
            self.release_all()
            return True
        if pkt.ev_type == EvType.HEARTBEAT:
            # Se o heartbeat indicar zero botoes mas algum botao ficou preso, libera
            if pkt.buttons_mask == 0 and self.watchdog.pressed_buttons != 0:
                for rel in self.watchdog._build_release_packets([], self.watchdog.pressed_buttons):
                    self._inject_native(rel)
            self.watchdog.record_event(pkt)
            return True

        self.watchdog.record_event(pkt)
        return self._inject_native(pkt)

    def tick_watchdog(self, now_mono: Optional[float] = None) -> int:
        releases = self.watchdog.check_timeout(now_mono=now_mono)
        for rel in releases:
            self._inject_native(rel)
        return len(releases)

    def release_all(self) -> int:
        releases = self.watchdog.drain_release_all()
        for rel in releases:
            self._inject_native(rel)
        return len(releases)

    @abstractmethod
    def _inject_native(self, pkt: InputEventPacket) -> bool:
        ...

    def close(self) -> None:
        try:
            self.release_all()
        except Exception:
            pass


class NullSyntheticInjector(BaseInputInjector):
    """Injetor sintetico deterministico em memoria para CI headless e benchmarks."""

    def __init__(self, bounds: Optional[MonitorBounds] = None, elevated: bool = False):
        super().__init__(bounds=bounds)
        self._elevated = bool(elevated)
        self.events: Deque[Tuple[float, InputEventPacket]] = collections.deque(maxlen=2048)

    @property
    def backend_name(self) -> str:
        return "synthetic_memory"

    @property
    def is_elevated(self) -> bool:
        return self._elevated

    def _inject_native(self, pkt: InputEventPacket) -> bool:
        self.events.append((time.perf_counter(), pkt))
        return True
