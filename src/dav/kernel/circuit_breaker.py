# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
MonoTech Core Kernel — Padrão Circuit Breaker (Isolamento de Falhas Externas)
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from threading import Lock
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")
logger = logging.getLogger("DAV.Kernel.CircuitBreaker")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenError(Exception):
    """Lançada quando uma chamada é bloqueada pelo circuito aberto."""
    pass


class CircuitBreaker:
    """
    Protege o sistema contra travamentos decorrentes de indisponibilidade em
    serviços remotos (Rendezvous Cloud, STUN, gateways externos e APIs).
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 3,
        recovery_timeout: float = 10.0,
    ):
        self.name = name
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_timeout = max(0.01, recovery_timeout)

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_state_change = time.monotonic()
        self._lock = Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if (time.monotonic() - self._last_state_change) >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._last_state_change = time.monotonic()
                    logger.info(f"[CircuitBreaker:{self.name}] Transicionando OPEN -> HALF_OPEN (sondagem).")
            return self._state

    def record_success(self) -> None:
        """Registra êxito de uma chamada remota e reseta contadores."""
        with self._lock:
            if self._state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
                logger.info(f"[CircuitBreaker:{self.name}] Serviço restabelecido! Circuito CLOSED.")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_state_change = time.monotonic()

    def record_failure(self, exc: Optional[Exception] = None) -> None:
        """Registra falha consecutiva de operação remota."""
        with self._lock:
            self._failure_count += 1
            logger.warning(
                f"[CircuitBreaker:{self.name}] Falha #{self._failure_count}/{self.failure_threshold}"
                + (f" ({exc})" if exc else "")
            )
            if self._state == CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._last_state_change = time.monotonic()
                logger.error(f"[CircuitBreaker:{self.name}] Limiar atingido! Circuito aberto (OPEN por {self.recovery_timeout}s).")

    def can_execute(self) -> bool:
        """Verifica se o circuito permite novas execuções (CLOSED ou HALF_OPEN)."""
        return self.state != CircuitState.OPEN

    def execute(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Alias para call()."""
        return self.call(func, *args, **kwargs)

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Executa a função através do circuito. Se o circuito estiver OPEN,
        falha imediatamente com CircuitBreakerOpenError sem esperar timeouts de rede.
        """
        current_state = self.state
        if current_state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(
                f"Circuito '{self.name}' está ABERTO. Operação remota bloqueada preventivamente."
            )

        try:
            res = func(*args, **kwargs)
            self.record_success()
            return res
        except Exception as exc:
            self.record_failure(exc)
            raise
