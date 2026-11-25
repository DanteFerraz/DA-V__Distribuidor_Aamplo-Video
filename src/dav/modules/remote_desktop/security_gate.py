# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Portao de Seguranca Zero-Trust e Limitador de Taxa para Area de Trabalho Remota — DA-V v5.0
Autor: Dante Ferraz (MonoTech)

Invariante de Seguranca:
- Toda sessao inicia estritamente em modo Somente Visualizacao (`allow_input=False`,
  `allow_clipboard=False`, `allow_files=False`, `allow_shell=False`).
- Eventos criticos duplicados (envio redundante 2x de cliques/teclas contra perda UDP) sao
  deduplicados de forma idempotente por `(ev_type, key_or_wheel, buttons_mask, client_ts_us)`.
- `panic_revoke_all()` bloqueia instantaneamente todos os canais interativos.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, Deque, Dict, Optional, Tuple

from src.dav.modules.remote_desktop.protocol import EvType, InputEventPacket, WsMsgType


@dataclass
class WorkspacePermissions:
    allow_input: bool = False
    allow_gamepad: bool = False
    allow_clipboard: bool = False
    allow_files: bool = False
    allow_shell: bool = False
    admin_elevated: bool = False

    @property
    def is_interactive(self) -> bool:
        return bool(
            self.allow_input
            or self.allow_gamepad
            or self.allow_clipboard
            or self.allow_files
            or self.allow_shell
        )

    def to_dict(self) -> Dict[str, bool]:
        return {
            "allow_input": bool(self.allow_input),
            "allow_gamepad": bool(self.allow_gamepad),
            "allow_clipboard": bool(self.allow_clipboard),
            "allow_files": bool(self.allow_files),
            "allow_shell": bool(self.allow_shell),
            "admin_elevated": bool(self.admin_elevated),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkspacePermissions":
        return cls(
            allow_input=bool(data.get("allow_input", False)),
            allow_gamepad=bool(data.get("allow_gamepad", False)),
            allow_clipboard=bool(data.get("allow_clipboard", False)),
            allow_files=bool(data.get("allow_files", False)),
            allow_shell=bool(data.get("allow_shell", False)),
            admin_elevated=bool(data.get("admin_elevated", False)),
        )


class SecurityGate:
    """Validador O(1) de permissoes, deduplicador de transicoes 2x e limitador Token-Bucket."""

    def __init__(
        self,
        initial_perms: Optional[WorkspacePermissions] = None,
        max_events_per_sec: float = 2400.0,
        burst_capacity: float = 240.0,
        on_revoke: Optional[Callable[[], None]] = None,
    ):
        self._lock = threading.Lock()
        self._perms = initial_perms or WorkspacePermissions()
        self._rate = max(50.0, float(max_events_per_sec))
        self._capacity = max(20.0, float(burst_capacity))
        self._tokens = self._capacity
        self._last_refill = time.monotonic()
        self._recent_transitions: Deque[Tuple[int, int, int, int]] = collections.deque(maxlen=128)
        self._recent_set = set()
        self._on_revoke = on_revoke
        self.blocked_packets: int = 0
        self.accepted_packets: int = 0
        self.revoke_count: int = 0

    @property
    def permissions(self) -> WorkspacePermissions:
        with self._lock:
            return WorkspacePermissions(**self._perms.to_dict())

    def update_permissions(self, **kwargs: Any) -> WorkspacePermissions:
        with self._lock:
            for key in (
                "allow_input",
                "allow_gamepad",
                "allow_clipboard",
                "allow_files",
                "allow_shell",
                "admin_elevated",
            ):
                if key in kwargs and kwargs[key] is not None:
                    setattr(self._perms, key, bool(kwargs[key]))
            return WorkspacePermissions(**self._perms.to_dict())

    def panic_revoke_all(self) -> WorkspacePermissions:
        """Revoga imediatamente todas as permissoes interativas (atalho Ctrl+Alt+Shift+Esc)."""
        with self._lock:
            self._perms.allow_input = False
            self._perms.allow_gamepad = False
            self._perms.allow_clipboard = False
            self._perms.allow_files = False
            self._perms.allow_shell = False
            self.revoke_count += 1
            snap = WorkspacePermissions(**self._perms.to_dict())
        if self._on_revoke is not None:
            try:
                self._on_revoke()
            except Exception:
                pass
        return snap

    def allow_input_packet(self, pkt: InputEventPacket) -> bool:
        with self._lock:
            if pkt.ev_type == EvType.GAMEPAD_STATE:
                if not self._perms.allow_gamepad:
                    self.blocked_packets += 1
                    return False
            else:
                if not self._perms.allow_input:
                    self.blocked_packets += 1
                    return False

            # Deduplicacao de pacotes criticos enviados 2x pelo cliente contra perda UDP
            if pkt.is_critical_transition and pkt.client_ts_us > 0:
                sig = (int(pkt.ev_type), int(pkt.key_or_wheel), int(pkt.buttons_mask), int(pkt.client_ts_us))
                if sig in self._recent_set:
                    return False
                if len(self._recent_transitions) == self._recent_transitions.maxlen:
                    old = self._recent_transitions.popleft()
                    self._recent_set.discard(old)
                self._recent_transitions.append(sig)
                self._recent_set.add(sig)

            now = time.monotonic()
            dt = max(0.0, now - self._last_refill)
            self._last_refill = now
            self._tokens = min(self._capacity, self._tokens + dt * self._rate)
            if self._tokens < 1.0:
                self.blocked_packets += 1
                return False
            self._tokens -= 1.0
            self.accepted_packets += 1
            return True

    def allow_workspace_msg(self, msg_type: int) -> bool:
        with self._lock:
            if msg_type in (
                WsMsgType.ACK,
                WsMsgType.PERM_UPDATE,
                WsMsgType.INPUT_ECHO,
                WsMsgType.CLIENT_INPUT_PROFILE,
                WsMsgType.GAMEPAD_ROSTER,
                WsMsgType.GAMEPAD_RUMBLE_ACK,
            ):
                return True
            if msg_type == WsMsgType.GAMEPAD_RUMBLE:
                ok = self._perms.allow_gamepad
            elif msg_type == WsMsgType.CLIPBOARD_TEXT:
                ok = self._perms.allow_clipboard
            elif msg_type in (WsMsgType.FILE_META, WsMsgType.FILE_CHUNK, WsMsgType.FILE_DONE):
                ok = self._perms.allow_files
            elif msg_type in (WsMsgType.SHELL_STDIN, WsMsgType.SHELL_STDOUT, WsMsgType.SHELL_RESIZE):
                ok = self._perms.allow_shell
            else:
                ok = False
            if not ok:
                self.blocked_packets += 1
            return ok
