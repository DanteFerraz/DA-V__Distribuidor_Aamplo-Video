# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Fatia Vertical `universal_input` — Universalizador de Teclado e Controles Multi-Acesso (v5.1)
Autor: Dante Ferraz (MonoTech)
"""

from src.dav.modules.universal_input.gamepad_capturer import (
    SyntheticGamepadBackend,
    UniversalGamepadCapturer,
)
from src.dav.modules.universal_input.gamepad_normalizer import (
    apply_radial_deadzone,
    classify_controller_kind,
    normalize_generic_joystick,
    pov_hat_degrees_to_dpad_mask,
    sdl_hat_to_dpad_mask,
)
from src.dav.modules.universal_input.gamepad_virtual_hub import (
    VirtualGamepadHub,
    check_host_gamepad_driver_status,
    install_vigembus_driver_win32,
)
from src.dav.modules.universal_input.keyboard_translator import (
    ClientKeyboardTranslator,
    HostKeyboardReproducer,
    detect_local_keyboard_profile,
    unicode_to_xkb_keysym,
)
from src.dav.modules.universal_input.models import (
    ClientKeyboardProfileDTO,
    ControllerKind,
    GamepadButtonMask,
    GamepadSlotDTO,
    GamepadStateDTO,
    RumbleAckDTO,
    RumbleRequestDTO,
    UniversalKeyActionDTO,
)
from src.dav.modules.universal_input.service import UniversalInputService

__all__ = [
    "UniversalInputService",
    "ControllerKind",
    "GamepadButtonMask",
    "ClientKeyboardProfileDTO",
    "UniversalKeyActionDTO",
    "GamepadStateDTO",
    "GamepadSlotDTO",
    "RumbleRequestDTO",
    "RumbleAckDTO",
    "ClientKeyboardTranslator",
    "HostKeyboardReproducer",
    "detect_local_keyboard_profile",
    "unicode_to_xkb_keysym",
    "classify_controller_kind",
    "apply_radial_deadzone",
    "pov_hat_degrees_to_dpad_mask",
    "sdl_hat_to_dpad_mask",
    "normalize_generic_joystick",
    "UniversalGamepadCapturer",
    "SyntheticGamepadBackend",
    "VirtualGamepadHub",
    "check_host_gamepad_driver_status",
    "install_vigembus_driver_win32",
]
