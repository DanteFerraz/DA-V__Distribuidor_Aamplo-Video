# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Servico de Dominio da 11a Fatia Vertical (`UniversalInputService`) — DA-V v5.1
Autor: Dante Ferraz (MonoTech)

Implementa formalmente `IUniversalInputService` do MonoTech Core Kernel v2.0.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from src.dav.kernel.result import ServiceResult
from src.dav.modules.universal_input.gamepad_capturer import UniversalGamepadCapturer
from src.dav.modules.universal_input.gamepad_virtual_hub import (
    VirtualGamepadHub,
    check_host_gamepad_driver_status,
    install_vigembus_driver_win32,
)
from src.dav.modules.universal_input.keyboard_translator import (
    ClientKeyboardTranslator,
    HostKeyboardReproducer,
    detect_local_keyboard_profile,
)
from src.dav.modules.universal_input.models import (
    ClientKeyboardProfileDTO,
    GamepadStateDTO,
)


class UniversalInputService:
    """Fachada singleton da fatia `universal_input` (Teclado Multi-Layout + Multi-Gamepad)."""

    def detect_client_keyboard_profile(self) -> ServiceResult[ClientKeyboardProfileDTO]:
        try:
            prof = detect_local_keyboard_profile()
            return ServiceResult.ok(prof, code="CLIENT_KBD_PROFILE_READY")
        except Exception as exc:
            return ServiceResult.fail(str(exc), code="CLIENT_KBD_PROFILE_ERROR")

    def create_keyboard_translator(
        self,
        profile: Optional[ClientKeyboardProfileDTO] = None,
    ) -> ClientKeyboardTranslator:
        return ClientKeyboardTranslator(profile=profile)

    def create_keyboard_reproducer(
        self,
        host_profile: Optional[ClientKeyboardProfileDTO] = None,
    ) -> HostKeyboardReproducer:
        return HostKeyboardReproducer(host_profile=host_profile)

    def create_gamepad_capturer(
        self,
        on_state_packet: Optional[Callable[[GamepadStateDTO], None]] = None,
        prefer_synthetic: bool = False,
        poll_hz: int = 125,
    ) -> ServiceResult[UniversalGamepadCapturer]:
        try:
            cap = UniversalGamepadCapturer(
                on_state_changed=on_state_packet,
                poll_hz=poll_hz,
                prefer_synthetic=prefer_synthetic,
            )
            return ServiceResult.ok(cap, code="GAMEPAD_CAPTURER_READY")
        except Exception as exc:
            return ServiceResult.fail(str(exc), code="GAMEPAD_CAPTURER_ERROR")

    def create_virtual_gamepad_hub(
        self,
        on_rumble_to_peer: Optional[Callable[[str, bytes], None]] = None,
        on_roster_changed: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
        force_synthetic: bool = False,
    ) -> ServiceResult[VirtualGamepadHub]:
        try:
            hub = VirtualGamepadHub(
                on_rumble_to_peer=on_rumble_to_peer,
                on_roster_changed=on_roster_changed,
                force_synthetic=force_synthetic,
            )
            return ServiceResult.ok(hub, code="GAMEPAD_HUB_READY")
        except Exception as exc:
            return ServiceResult.fail(str(exc), code="GAMEPAD_HUB_ERROR")

    def get_host_driver_status(self) -> Dict[str, Any]:
        return check_host_gamepad_driver_status()

    def check_host_gamepad_driver(self) -> Dict[str, Any]:
        return check_host_gamepad_driver_status()

    def install_windows_vigembus(self) -> ServiceResult[str]:
        ok, msg = install_vigembus_driver_win32()
        if ok:
            return ServiceResult.ok(msg, code="VIGEMBUS_INSTALL_STARTED")
        return ServiceResult.fail(msg, code="VIGEMBUS_INSTALL_FAILED")

    def install_host_gamepad_driver(self) -> Tuple[bool, str]:
        return install_vigembus_driver_win32()
