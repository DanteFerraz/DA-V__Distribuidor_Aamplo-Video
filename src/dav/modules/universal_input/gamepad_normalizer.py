# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Normalizador Universal de Gamepads (DualShock 4, DualSense, Xbox, Switch Pro e Genericos HID) — DA-V v5.1
Autor: Dante Ferraz (MonoTech)

Responsabilidades:
- Identificar a familia real do controle por `(vendor_id, product_id, nome)`;
- Aplicar deadzone radial suave com reescalonamento continuo (eliminando stick drift sem degrau);
- Converter entradas cruas de controles DirectInput / USB HID genericos e PlayStation raw HID
  para a mascara canonica `GamepadButtonMask` + eixos `[-32768..32767]` e gatilhos `[0..255]`.
"""

from __future__ import annotations

import math
from typing import Sequence, Tuple

from src.dav.modules.universal_input.models import (
    ControllerKind,
    GamepadButtonMask,
    GamepadStateDTO,
)

SONY_VID = 0x054C
MICROSOFT_VID = 0x045E
NINTENDO_VID = 0x057E

DUALSENSE_PIDS = {0x0CE6, 0x0DF2, 0x0E5F}
DUALSHOCK4_PIDS = {0x05C4, 0x09CC, 0x0BA0}
SWITCH_PIDS = {0x2009, 0x2006, 0x2007}


def classify_controller_kind(vendor_id: int = 0, product_id: int = 0, name: str = "") -> ControllerKind:
    """Identifica o modelo do controle por VID:PID USB/Bluetooth ou assinatura de nome."""
    vid = int(vendor_id or 0) & 0xFFFF
    pid = int(product_id or 0) & 0xFFFF
    low_name = (name or "").lower()

    if vid == SONY_VID:
        if pid in DUALSENSE_PIDS or "dualsense" in low_name or "ps5" in low_name:
            return ControllerKind.DUALSENSE
        return ControllerKind.DUALSHOCK4

    if "dualsense" in low_name or "ps5" in low_name:
        return ControllerKind.DUALSENSE
    if "dualshock" in low_name or "ps4" in low_name or "wireless controller" in low_name:
        return ControllerKind.DUALSHOCK4

    if vid == NINTENDO_VID or pid in SWITCH_PIDS or "switch" in low_name or "joy-con" in low_name:
        return ControllerKind.SWITCH_PRO

    if vid == MICROSOFT_VID or "xbox" in low_name or "xinput" in low_name or "x-box" in low_name:
        return ControllerKind.XBOX

    return ControllerKind.GENERIC


def clamp_i16(val: float) -> int:
    return max(-32768, min(32767, int(round(val))))


def clamp_u8(val: float) -> int:
    return max(0, min(255, int(round(val))))


def apply_radial_deadzone(x_i16: int, y_i16: int, deadzone: float = 0.07) -> Tuple[int, int]:
    """
    Aplica zona morta radial proporcional a um par `(X, Y)` em `[-32768..32767]`,
    preservando diagonal circular fluida e zerando micro-oscilacoes de repouso.
    """
    dz = max(0.0, min(0.45, float(deadzone)))
    nx = float(x_i16) / (32768.0 if x_i16 < 0 else 32767.0)
    ny = float(y_i16) / (32768.0 if y_i16 < 0 else 32767.0)
    mag = math.hypot(nx, ny)
    if mag <= dz or mag <= 1e-6:
        return (0, 0)
    clamped_mag = min(1.0, mag)
    scaled = (clamped_mag - dz) / (1.0 - dz)
    ux = (nx / mag) * scaled
    uy = (ny / mag) * scaled
    return (clamp_i16(ux * 32767.0), clamp_i16(uy * 32767.0))


def pov_hat_degrees_to_dpad_mask(pov_hundredths_deg: int) -> int:
    """
    Converte valor DirectInput POV Hat (`0..35999` centesimos de grau; `65535` ou `< 0` = centro)
    em flags `GamepadButtonMask.DPAD_*`.
    """
    val = int(pov_hundredths_deg)
    if val < 0 or val >= 36000:
        return 0
    deg = (val // 100) % 360
    mask = 0
    if deg <= 67 or deg >= 293:
        mask |= int(GamepadButtonMask.DPAD_UP)
    if 23 <= deg <= 157:
        mask |= int(GamepadButtonMask.DPAD_RIGHT)
    if 113 <= deg <= 247:
        mask |= int(GamepadButtonMask.DPAD_DOWN)
    if 203 <= deg <= 337:
        mask |= int(GamepadButtonMask.DPAD_LEFT)
    return mask


def sdl_hat_to_dpad_mask(hat_val: int) -> int:
    """Converte mascara SDL_HAT_* (`UP=1, RIGHT=2, DOWN=4, LEFT=8`) em `GamepadButtonMask.DPAD_*`."""
    h = int(hat_val)
    mask = 0
    if h & 0x01:
        mask |= int(GamepadButtonMask.DPAD_UP)
    if h & 0x02:
        mask |= int(GamepadButtonMask.DPAD_RIGHT)
    if h & 0x04:
        mask |= int(GamepadButtonMask.DPAD_DOWN)
    if h & 0x08:
        mask |= int(GamepadButtonMask.DPAD_LEFT)
    return mask


def normalize_generic_joystick(
    local_slot: int,
    axes_i16: Sequence[int],
    buttons_pressed: Sequence[bool],
    hat_dpad_mask: int = 0,
    vendor_id: int = 0,
    product_id: int = 0,
    device_name: str = "",
    deadzone: float = 0.08,
) -> GamepadStateDTO:
    """
    Traduz controles DirectInput / USB HID genericos (incluindo DualShock 4 / DualSense quando
    abertos via interface Joystick crua sem GameControllerDB e gamepads Twin-Shock sem marca)
    para o `GamepadStateDTO` canonico.
    """
    kind = classify_controller_kind(vendor_id, product_id, device_name)
    btns = [bool(b) for b in buttons_pressed]
    axes = [int(a) for a in axes_i16]

    def _btn(idx: int) -> bool:
        return idx < len(btns) and btns[idx]

    def _axis(idx: int, default: int = 0) -> int:
        return axes[idx] if idx < len(axes) else default

    mask = int(hat_dpad_mask)
    lt_u8 = 0
    rt_u8 = 0

    if kind in (ControllerKind.DUALSHOCK4, ControllerKind.DUALSENSE):
        # Layout DirectInput classico Sony (0=Square, 1=Cross, 2=Circle, 3=Triangle, 4=L1, 5=R1,
        # 6=L2_dig, 7=R2_dig, 8=Share/Create, 9=Options, 10=L3, 11=R3, 12=PS, 13=Touchpad)
        if _btn(1):
            mask |= int(GamepadButtonMask.SOUTH)
        if _btn(2):
            mask |= int(GamepadButtonMask.EAST)
        if _btn(0):
            mask |= int(GamepadButtonMask.WEST)
        if _btn(3):
            mask |= int(GamepadButtonMask.NORTH)
        if _btn(4):
            mask |= int(GamepadButtonMask.LB)
        if _btn(5):
            mask |= int(GamepadButtonMask.RB)
        if _btn(8):
            mask |= int(GamepadButtonMask.BACK)
        if _btn(9):
            mask |= int(GamepadButtonMask.START)
        if _btn(10):
            mask |= int(GamepadButtonMask.LS)
        if _btn(11):
            mask |= int(GamepadButtonMask.RS)
        if _btn(12):
            mask |= int(GamepadButtonMask.GUIDE)
        if _btn(13):
            mask |= int(GamepadButtonMask.TOUCHPAD_CLICK)

        lx_raw, ly_raw = _axis(0, 0), _axis(1, 0)
        if len(axes) >= 6:
            # Eixos DS4/DualSense tipicos: 0=LX, 1=LY, 2=RX, 3=L2(-32768..32767), 4=R2, 5=RY (ou 2=L2,3=RX,4=RY,5=R2)
            rx_raw, ry_raw = _axis(2, 0), _axis(5, 0)
            lt_u8 = clamp_u8((_axis(3, -32768) + 32768) / 257.0)
            rt_u8 = clamp_u8((_axis(4, -32768) + 32768) / 257.0)
        else:
            rx_raw, ry_raw = _axis(2, 0), _axis(3, 0)
        if _btn(6) and lt_u8 < 200:
            lt_u8 = 255
        if _btn(7) and rt_u8 < 200:
            rt_u8 = 255
    else:
        # Layout Universal DirectInput / Twin-USB Generico:
        # Maioria dos gamepads USB genericos segue numeracao 1..12 (indices 0..11):
        # 0=North/West, 1=East, 2=South, 3=West/North OU padrao XInput-like 0=A, 1=B, 2=X, 3=Y.
        # Detectamos Twin-USB classico ("usb joystick" / "generic") vs padrao moderno:
        low = (device_name or "").lower()
        is_legacy_twin = ("twin" in low or "dragonrise" in low or "microntek" in low)
        if is_legacy_twin:
            # 0=Triangle(N), 1=Circle(E), 2=Cross(S), 3=Square(W)
            if _btn(2):
                mask |= int(GamepadButtonMask.SOUTH)
            if _btn(1):
                mask |= int(GamepadButtonMask.EAST)
            if _btn(3):
                mask |= int(GamepadButtonMask.WEST)
            if _btn(0):
                mask |= int(GamepadButtonMask.NORTH)
        else:
            if _btn(0):
                mask |= int(GamepadButtonMask.SOUTH)
            if _btn(1):
                mask |= int(GamepadButtonMask.EAST)
            if _btn(2):
                mask |= int(GamepadButtonMask.WEST)
            if _btn(3):
                mask |= int(GamepadButtonMask.NORTH)

        if _btn(4):
            mask |= int(GamepadButtonMask.LB)
        if _btn(5):
            mask |= int(GamepadButtonMask.RB)
        if _btn(6):
            lt_u8 = 255
        if _btn(7):
            rt_u8 = 255
        if _btn(8):
            mask |= int(GamepadButtonMask.BACK)
        if _btn(9):
            mask |= int(GamepadButtonMask.START)
        if _btn(10):
            mask |= int(GamepadButtonMask.LS)
        if _btn(11):
            mask |= int(GamepadButtonMask.RS)
        if _btn(12):
            mask |= int(GamepadButtonMask.GUIDE)

        lx_raw, ly_raw = _axis(0, 0), _axis(1, 0)
        rx_raw, ry_raw = _axis(2, 0), _axis(3, 0)
        if len(axes) >= 6 and lt_u8 == 0 and rt_u8 == 0:
            # Eixos Z/RZ como gatilhos analogicos
            a4, a5 = _axis(4, -32768), _axis(5, -32768)
            if a4 > -30000:
                lt_u8 = clamp_u8((a4 + 32768) / 257.0)
            if a5 > -30000:
                rt_u8 = clamp_u8((a5 + 32768) / 257.0)

    lx, ly = apply_radial_deadzone(lx_raw, ly_raw, deadzone=deadzone)
    rx, ry = apply_radial_deadzone(rx_raw, ry_raw, deadzone=deadzone)

    return GamepadStateDTO(
        local_slot=local_slot,
        kind=kind,
        connected=True,
        buttons_mask=mask,
        lt_u8=lt_u8,
        rt_u8=rt_u8,
        lx_i16=lx,
        ly_i16=ly,
        rx_i16=rx,
        ry_i16=ry,
        device_name=device_name or kind.display_label,
    )
