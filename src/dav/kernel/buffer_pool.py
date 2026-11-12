# -*- coding: utf-8 -*-
"""
MonoTech Core Kernel — Pool de Buffers de Mídia L1 (Zero-Copy Buffer Pool)
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
from queue import Empty, Queue
from threading import Lock
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger("DAV.Kernel.BufferPool")


class L1BufferPool:
    """
    Gerenciador de ring buffer em memória contígua.
    Permite aquisição e devolução não-bloqueante de slots de imagem,
    eliminando re-alocações dinâmicas de 8.3 MB a cada quadro.
    """

    def __init__(
        self,
        num_slots: int = 4,
        width: int = 1920,
        height: int = 1080,
        channels: int = 4,
        dtype: np.dtype = np.uint8,
        use_shared_memory: bool = False,
    ):
        self.num_slots = max(2, num_slots)
        self.width = width
        self.height = height
        self.channels = channels
        self.dtype = dtype
        self.slot_shape = (height, width, channels)
        self.frame_bytes = height * width * channels * np.dtype(dtype).itemsize

        self._lock = Lock()
        self._free_queue: Queue[int] = Queue()
        self._buffers: List[np.ndarray] = []
        self._shm_objects: List[Any] = []
        self._use_shm = use_shared_memory

        self._init_slots()

    def _init_slots(self) -> None:
        """Aloca os buffers contíguos na memória."""
        for slot_idx in range(self.num_slots):
            if self._use_shm:
                try:
                    from multiprocessing import shared_memory
                    shm = shared_memory.SharedMemory(create=True, size=self.frame_bytes)
                    self._shm_objects.append(shm)
                    arr = np.ndarray(self.slot_shape, dtype=self.dtype, buffer=shm.buf)
                    self._buffers.append(arr)
                except Exception as exc:
                    logger.warning(f"SharedMemory falhou ({exc}); caindo para alocação direta em RAM.")
                    arr = np.zeros(self.slot_shape, dtype=self.dtype)
                    self._buffers.append(arr)
            else:
                arr = np.zeros(self.slot_shape, dtype=self.dtype)
                self._buffers.append(arr)

            self._free_queue.put(slot_idx)

    def acquire(self, timeout: float = 0.05) -> Optional[int]:
        """
        Adquire um slot de buffer livre em tempo hábil.
        Retorna o índice do slot ou None caso esgotado.
        """
        try:
            return self._free_queue.get(timeout=timeout)
        except Empty:
            return None

    def release(self, slot_idx: int) -> None:
        """Devolve o slot ao pool livre."""
        if 0 <= slot_idx < self.num_slots:
            self._free_queue.put(slot_idx)

    def get_slot(self, slot_idx: int) -> np.ndarray:
        """Obtém a visão contígua NumPy do slot especificado."""
        return self._buffers[slot_idx]

    def resize(self, width: int, height: int, channels: int = 4) -> None:
        """Reconfigura a resolução dos slots quando o monitor/resolução de saída muda."""
        with self._lock:
            self.close()
            self.width = width
            self.height = height
            self.channels = channels
            self.slot_shape = (height, width, channels)
            self.frame_bytes = height * width * channels * np.dtype(self.dtype).itemsize
            self._free_queue = Queue()
            self._buffers = []
            self._shm_objects = []
            self._init_slots()

    def close(self) -> None:
        """Libera buffers e fecha blocos de SharedMemory."""
        while not self._free_queue.empty():
            try:
                self._free_queue.get_nowait()
            except Empty:
                break

        for shm in self._shm_objects:
            try:
                shm.close()
                shm.unlink()
            except Exception:
                pass
        self._shm_objects.clear()
        self._buffers.clear()

