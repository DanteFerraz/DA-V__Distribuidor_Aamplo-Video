# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Fachada de Dominio do Modulo de Compartilhamento de Area de Trabalho (`RemoteDesktopService`) — DA-V v5.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable, Optional

from src.dav.kernel.result import ServiceResult
from src.dav.modules.remote_desktop.elevation import (
    is_process_elevated,
    request_elevated_injector,
)
from src.dav.modules.remote_desktop.injector_base import (
    BaseInputInjector,
    MonitorBounds,
    NullSyntheticInjector,
)
from src.dav.modules.remote_desktop.keymap import qt_key_to_hid
from src.dav.modules.remote_desktop.security_gate import SecurityGate, WorkspacePermissions
from src.dav.modules.remote_desktop.workspace_agent import WorkspaceAgent


class RemoteDesktopService:
    """Implementacao oficial de `IRemoteDesktopService` no MonoTech Core Kernel."""

    def __init__(self) -> None:
        self._elevated_proxy: Optional[BaseInputInjector] = None

    def is_admin_elevated(self) -> bool:
        if self._elevated_proxy is not None and self._elevated_proxy.is_elevated:
            return True
        return is_process_elevated()

    def request_admin_elevation(
        self,
        bounds: Optional[MonitorBounds] = None,
        timeout_sec: float = 25.0,
        launcher_fn: Optional[Callable] = None,
    ) -> ServiceResult[BaseInputInjector]:
        if is_process_elevated():
            inj_res = self.create_injector(prefer_elevated=False, bounds=bounds)
            return inj_res

        if self._elevated_proxy is not None and self._elevated_proxy.is_elevated:
            return ServiceResult.ok(self._elevated_proxy)

        res = request_elevated_injector(bounds=bounds, timeout_sec=timeout_sec, launcher_fn=launcher_fn)
        if res.is_success and res.data is not None:
            self._elevated_proxy = res.data
            return ServiceResult.ok(self._elevated_proxy)
        return ServiceResult.fail(res.error or "Elevacao administrativa nao autorizada.")

    def create_injector(
        self,
        force_synthetic: bool = False,
        prefer_elevated: bool = False,
        bounds: Optional[MonitorBounds] = None,
        wayland_cmd_fn: Optional[Callable[[str], bool]] = None,
    ) -> ServiceResult[BaseInputInjector]:
        if force_synthetic or os.environ.get("DAV_HEADLESS_SYNTHETIC") == "1":
            return ServiceResult.ok(NullSyntheticInjector(bounds=bounds))

        if prefer_elevated and self._elevated_proxy is not None and self._elevated_proxy.is_elevated:
            if bounds is not None:
                self._elevated_proxy.update_monitor_bounds(
                    bounds.left, bounds.top, bounds.width, bounds.height
                )
            return ServiceResult.ok(self._elevated_proxy)

        if sys.platform == "win32":
            try:
                from src.dav.modules.remote_desktop.injector_win32 import Win32InputInjector

                return ServiceResult.ok(Win32InputInjector(bounds=bounds))
            except Exception as exc:
                return ServiceResult.fail(f"Falha ao inicializar Win32InputInjector: {exc}")

        from src.dav.modules.remote_desktop.injector_linux import (
            LinuxUInputInjector,
            WaylandPortalInputInjector,
            X11XTestInjector,
        )

        # 1. Tenta `/dev/uinput` se o processo ou grupo `input` tiver acesso direto
        try:
            return ServiceResult.ok(LinuxUInputInjector(bounds=bounds))
        except Exception:
            pass

        # 2. Se houver ponte ativa do XDG Portal Wayland RemoteDesktop
        if wayland_cmd_fn is not None:
            return ServiceResult.ok(WaylandPortalInputInjector(send_cmd_fn=wayland_cmd_fn, bounds=bounds))

        # 3. Sessao X11 XTest nativa
        try:
            return ServiceResult.ok(X11XTestInjector(bounds=bounds))
        except Exception:
            return ServiceResult.ok(NullSyntheticInjector(bounds=bounds))

    def create_security_gate(self, **initial_perms: bool) -> SecurityGate:
        perms = WorkspacePermissions.from_dict(initial_perms)
        return SecurityGate(initial_perms=perms)

    def create_workspace_agent(
        self,
        gate: SecurityGate,
        download_dir: Optional[str] = None,
        **kwargs: Any,
    ) -> WorkspaceAgent:
        return WorkspaceAgent(gate=gate, download_dir=download_dir, **kwargs)

    def translate_qt_key(
        self,
        qt_key: int,
        native_scancode: int = 0,
        native_vk: int = 0,
    ) -> int:
        return qt_key_to_hid(qt_key, native_scancode=native_scancode, native_vk=native_vk)

    def close(self) -> None:
        if self._elevated_proxy is not None:
            try:
                self._elevated_proxy.close()
            except Exception:
                pass
            self._elevated_proxy = None
