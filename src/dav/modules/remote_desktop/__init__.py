# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Fatia Vertical `remote_desktop` — Compartilhamento Completo de Area de Trabalho (DA-V v5.0)
Autor: Dante Ferraz (MonoTech)
"""

from src.dav.modules.remote_desktop.elevation import (
    ElevatedProxyInjector,
    is_process_elevated,
    request_elevated_injector,
    run_elevated_broker_cli,
)
from src.dav.modules.remote_desktop.injector_base import (
    BaseInputInjector,
    MonitorBounds,
    NullSyntheticInjector,
    StuckKeyWatchdog,
)
from src.dav.modules.remote_desktop.keymap import (
    hid_to_linux_evdev,
    hid_to_win32_scancode,
    hid_to_x11_keycode,
    qt_key_to_hid,
)
from src.dav.modules.remote_desktop.protocol import (
    EvType,
    InputEventPacket,
    KeyMod,
    MouseBtn,
    WorkspaceChannel,
    WorkspaceMessage,
    WsMsgType,
    pack_input_echo,
    pack_wheel_deltas,
    unpack_input_echo,
    unpack_wheel_deltas,
)
from src.dav.modules.remote_desktop.security_gate import SecurityGate, WorkspacePermissions
from src.dav.modules.remote_desktop.service import RemoteDesktopService
from src.dav.modules.remote_desktop.workspace_agent import (
    PtyShellManager,
    WorkspaceAgent,
    sanitize_filename,
)

__all__ = [
    "BaseInputInjector",
    "ElevatedProxyInjector",
    "EvType",
    "InputEventPacket",
    "KeyMod",
    "MonitorBounds",
    "MouseBtn",
    "NullSyntheticInjector",
    "PtyShellManager",
    "RemoteDesktopService",
    "SecurityGate",
    "StuckKeyWatchdog",
    "WorkspaceAgent",
    "WorkspaceChannel",
    "WorkspaceMessage",
    "WorkspacePermissions",
    "WsMsgType",
    "hid_to_linux_evdev",
    "hid_to_win32_scancode",
    "hid_to_x11_keycode",
    "is_process_elevated",
    "pack_input_echo",
    "pack_wheel_deltas",
    "qt_key_to_hid",
    "request_elevated_injector",
    "run_elevated_broker_cli",
    "sanitize_filename",
    "unpack_input_echo",
    "unpack_wheel_deltas",
]
