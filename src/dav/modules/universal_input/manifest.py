# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Manifesto da 11a Fatia Vertical `universal_input` — DA-V v5.1
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from src.dav.kernel.registry import ModuleManifest
from src.dav.modules.universal_input.gamepad_capturer import (
    SyntheticGamepadBackend,
    UniversalGamepadCapturer,
)
from src.dav.modules.universal_input.gamepad_normalizer import (
    apply_radial_deadzone,
    classify_controller_kind,
    normalize_generic_joystick,
)
from src.dav.modules.universal_input.gamepad_virtual_hub import (
    VirtualGamepadHub,
    check_host_gamepad_driver_status,
)
from src.dav.modules.universal_input.keyboard_translator import (
    ClientKeyboardTranslator,
    HostKeyboardReproducer,
    detect_local_keyboard_profile,
)
from src.dav.modules.universal_input.service import UniversalInputService

_SINGLETON: UniversalInputService | None = None


def _get_singleton() -> UniversalInputService:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = UniversalInputService()
    return _SINGLETON


MANIFEST = ModuleManifest(
    name="universal_input",
    version="5.1.0",
    description="Tradutor universal do teclado do cliente (~ / Dead Keys) e Hub Multi-Gamepad (DS4, DualSense, Xbox, Genericos + Rumble)",
    author="Dante Ferraz (MonoTech)",
    dependencies=["transport_p2p", "remote_desktop"],
    enabled=True,
    service_factory=_get_singleton,
    exports={
        "service": UniversalInputService,
        "ClientKeyboardTranslator": ClientKeyboardTranslator,
        "HostKeyboardReproducer": HostKeyboardReproducer,
        "detect_local_keyboard_profile": detect_local_keyboard_profile,
        "UniversalGamepadCapturer": UniversalGamepadCapturer,
        "SyntheticGamepadBackend": SyntheticGamepadBackend,
        "VirtualGamepadHub": VirtualGamepadHub,
        "classify_controller_kind": classify_controller_kind,
        "apply_radial_deadzone": apply_radial_deadzone,
        "normalize_generic_joystick": normalize_generic_joystick,
        "check_host_gamepad_driver_status": check_host_gamepad_driver_status,
    },
)

manifest = MANIFEST
