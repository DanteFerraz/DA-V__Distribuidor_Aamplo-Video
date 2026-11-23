# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
MonoTech Core Kernel — Barramento de Eventos Assíncrono (EventBus)
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any, Callable, Dict, List, NamedTuple, Optional

logger = logging.getLogger("DAV.Kernel.EventBus")


class Subscription(NamedTuple):
    handler: Callable[[Any], None]
    is_async: bool


class EventBus:
    """
    Barramento thread-safe de eventos para desacoplamento de fatias verticais.
    Permite comunicação não-bloqueante entre captura, codec, rede e apresentação.
    """

    _global_instance: Optional[EventBus] = None
    _global_lock = Lock()

    @classmethod
    def get_instance(cls) -> EventBus:
        """Retorna a instância singleton do EventBus da aplicação."""
        with cls._global_lock:
            if cls._global_instance is None or cls._global_instance._is_shutdown:
                cls._global_instance = cls()
            return cls._global_instance

    def __init__(self, max_workers: int = 4):
        self._lock = Lock()
        self._subscribers: Dict[str, List[Subscription]] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="DAV-EventBus")
        self._is_shutdown = False

    def subscribe(self, topic: str, handler: Callable[[Any], None], is_async: bool = False) -> None:
        """Inscreve um ouvinte em um tópico de eventos."""
        with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = []
            sub = Subscription(handler=handler, is_async=is_async)
            if sub not in self._subscribers[topic]:
                self._subscribers[topic].append(sub)

    def unsubscribe(self, topic: str, handler: Callable[[Any], None]) -> bool:
        """Remove a inscrição de um ouvinte."""
        with self._lock:
            if topic in self._subscribers:
                initial_len = len(self._subscribers[topic])
                self._subscribers[topic] = [s for s in self._subscribers[topic] if s.handler != handler]
                return len(self._subscribers[topic]) < initial_len
        return False

    def publish(self, topic: str, data: Any = None) -> int:
        """
        Publica um evento para todos os ouvintes inscritos no tópico.
        Dispara handlers síncronos imediatamente na thread chamadora e
        handlers assíncronos no pool de threads dedicado.
        """
        if self._is_shutdown:
            return 0

        with self._lock:
            subs = list(self._subscribers.get(topic, []))
            # Suporte a wildcard simples tópico.* (opcional)
            wildcard_topic = topic.split(".")[0] + ".*"
            if wildcard_topic in self._subscribers:
                subs.extend(self._subscribers[wildcard_topic])

        dispatched = 0
        for sub in subs:
            if sub.is_async and not self._is_shutdown:
                try:
                    self._executor.submit(self._safe_invoke, sub.handler, data, topic)
                    dispatched += 1
                except RuntimeError:
                    pass
            else:
                self._safe_invoke(sub.handler, data, topic)
                dispatched += 1

        return dispatched

    def _safe_invoke(self, handler: Callable[[Any], None], data: Any, topic: str) -> None:
        try:
            handler(data)
        except Exception as exc:
            logger.error(f"Exceção em handler do tópico '{topic}': {exc}", exc_info=True)

    def shutdown(self, wait: bool = False) -> None:
        """Encerra o pool de threads do EventBus."""
        self._is_shutdown = True
        self._executor.shutdown(wait=wait, cancel_futures=True)
