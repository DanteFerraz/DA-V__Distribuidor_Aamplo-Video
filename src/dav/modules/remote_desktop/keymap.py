# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Tabela Canonica Bidirecional de Teclado Baseada em USB HID Usage IDs — DA-V v5.0
Autor: Dante Ferraz (MonoTech)

Converte codigos de tecla do Qt / Windows VK / Linux XKB para USB HID Usage IDs (Page 0x07)
e traduz de USB HID para:
  - Win32 Set-1 Hardware ScanCode + flag Extended (`KEYEVENTF_SCANCODE`)
  - Linux `evdev` Keycode (`input-event-codes.h`) e X11 Keycode (`evdev + 8`)
"""

from __future__ import annotations

from typing import Dict, Tuple

# USB HID Usage IDs (Usage Page 0x07) -> (Win32 Set-1 ScanCode, is_extended, Linux evdev KEY_*)
_HID_TABLE: Dict[int, Tuple[int, bool, int]] = {
    # Letras A-Z (0x04..0x1D)
    0x04: (0x1E, False, 30),   # A
    0x05: (0x30, False, 48),   # B
    0x06: (0x2E, False, 46),   # C
    0x07: (0x20, False, 32),   # D
    0x08: (0x12, False, 18),   # E
    0x09: (0x21, False, 33),   # F
    0x0A: (0x22, False, 34),   # G
    0x0B: (0x23, False, 35),   # H
    0x0C: (0x17, False, 23),   # I
    0x0D: (0x24, False, 36),   # J
    0x0E: (0x25, False, 37),   # K
    0x0F: (0x26, False, 38),   # L
    0x10: (0x32, False, 50),   # M
    0x11: (0x31, False, 49),   # N
    0x12: (0x18, False, 24),   # O
    0x13: (0x19, False, 25),   # P
    0x14: (0x10, False, 16),   # Q
    0x15: (0x13, False, 19),   # R
    0x16: (0x1F, False, 31),   # S
    0x17: (0x14, False, 20),   # T
    0x18: (0x16, False, 22),   # U
    0x19: (0x2F, False, 47),   # V
    0x1A: (0x11, False, 17),   # W
    0x1B: (0x2D, False, 45),   # X
    0x1C: (0x15, False, 21),   # Y
    0x1D: (0x2C, False, 44),   # Z
    # Digitos 1-9, 0 (0x1E..0x27)
    0x1E: (0x02, False, 2),    # 1
    0x1F: (0x03, False, 3),    # 2
    0x20: (0x04, False, 4),    # 3
    0x21: (0x05, False, 5),    # 4
    0x22: (0x06, False, 6),    # 5
    0x23: (0x07, False, 7),    # 6
    0x24: (0x08, False, 8),    # 7
    0x25: (0x09, False, 9),    # 8
    0x26: (0x0A, False, 10),   # 9
    0x27: (0x0B, False, 11),   # 0
    # Controle e pontuacao
    0x28: (0x1C, False, 28),   # Enter
    0x29: (0x01, False, 1),    # Escape
    0x2A: (0x0E, False, 14),   # Backspace
    0x2B: (0x0F, False, 15),   # Tab
    0x2C: (0x39, False, 57),   # Space
    0x2D: (0x0C, False, 12),   # Minus (-)
    0x2E: (0x0D, False, 13),   # Equal (=)
    0x2F: (0x1A, False, 26),   # Left Bracket ([)
    0x30: (0x1B, False, 27),   # Right Bracket (])
    0x31: (0x2B, False, 43),   # Backslash (\)
    0x33: (0x27, False, 39),   # Semicolon / Ç ABNT2
    0x34: (0x28, False, 40),   # Apostrophe (')
    0x35: (0x29, False, 41),   # Grave (`)
    0x36: (0x33, False, 51),   # Comma (,)
    0x37: (0x34, False, 52),   # Period (.)
    0x38: (0x35, False, 53),   # Slash (/)
    0x39: (0x3A, False, 58),   # CapsLock
    # Teclas de funcao F1-F12 (0x3A..0x45)
    0x3A: (0x3B, False, 59),   # F1
    0x3B: (0x3C, False, 60),   # F2
    0x3C: (0x3D, False, 61),   # F3
    0x3D: (0x3E, False, 62),   # F4
    0x3E: (0x3F, False, 63),   # F5
    0x3F: (0x40, False, 64),   # F6
    0x40: (0x41, False, 65),   # F7
    0x41: (0x42, False, 66),   # F8
    0x42: (0x43, False, 67),   # F9
    0x43: (0x44, False, 68),   # F10
    0x44: (0x57, False, 87),   # F11
    0x45: (0x58, False, 88),   # F12
    # Navegacao
    0x46: (0x37, True, 99),    # PrintScreen
    0x47: (0x46, False, 70),   # ScrollLock
    0x48: (0x45, False, 119),  # Pause
    0x49: (0x52, True, 110),   # Insert
    0x4A: (0x47, True, 102),   # Home
    0x4B: (0x49, True, 104),   # PageUp
    0x4C: (0x53, True, 111),   # Delete
    0x4D: (0x4F, True, 107),   # End
    0x4E: (0x51, True, 109),   # PageDown
    0x4F: (0x4D, True, 106),   # Right Arrow
    0x50: (0x4B, True, 105),   # Left Arrow
    0x51: (0x50, True, 108),   # Down Arrow
    0x52: (0x48, True, 103),   # Up Arrow
    # Numpad / Internacional ABNT2
    0x53: (0x45, True, 69),    # NumLock
    0x54: (0x35, True, 98),    # KP Divide
    0x55: (0x37, False, 55),   # KP Multiply
    0x56: (0x4A, False, 74),   # KP Subtract
    0x57: (0x4E, False, 78),   # KP Add
    0x58: (0x1C, True, 96),    # KP Enter
    0x64: (0x56, False, 86),   # Non-US Backslash (\ | no ABNT2)
    0x87: (0x73, False, 89),   # IntlRo (/ ? no ABNT2)
    # Modificadores (0xE0..0xE7)
    0xE0: (0x1D, False, 29),   # Left Ctrl
    0xE1: (0x2A, False, 42),   # Left Shift
    0xE2: (0x38, False, 56),   # Left Alt
    0xE3: (0x5B, True, 125),   # Left Super / Windows
    0xE4: (0x1D, True, 97),    # Right Ctrl
    0xE5: (0x36, False, 54),   # Right Shift
    0xE6: (0x38, True, 100),   # Right Alt (AltGr)
    0xE7: (0x5C, True, 126),   # Right Super
}

# Mapeamento Qt::Key (valores inteiros estaveis em Qt5/Qt6) -> USB HID Usage ID
_QT_SPECIAL_TO_HID: Dict[int, int] = {
    0x01000000: 0x29,  # Key_Escape
    0x01000001: 0x2B,  # Key_Tab
    0x01000002: 0x2B,  # Key_Backtab
    0x01000003: 0x2A,  # Key_Backspace
    0x01000004: 0x28,  # Key_Return
    0x01000005: 0x58,  # Key_Enter (Keypad)
    0x01000006: 0x49,  # Key_Insert
    0x01000007: 0x4C,  # Key_Delete
    0x01000008: 0x48,  # Key_Pause
    0x01000009: 0x46,  # Key_Print
    0x01000010: 0x4A,  # Key_Home
    0x01000011: 0x4D,  # Key_End
    0x01000012: 0x50,  # Key_Left
    0x01000013: 0x52,  # Key_Up
    0x01000014: 0x4F,  # Key_Right
    0x01000015: 0x51,  # Key_Down
    0x01000016: 0x4B,  # Key_PageUp
    0x01000017: 0x4E,  # Key_PageDown
    0x01000020: 0xE1,  # Key_Shift
    0x01000021: 0xE0,  # Key_Control
    0x01000022: 0xE3,  # Key_Meta (Windows / Super)
    0x01000023: 0xE2,  # Key_Alt
    0x01001103: 0xE6,  # Key_AltGr
    0x01000024: 0x39,  # Key_CapsLock
    0x01000025: 0x53,  # Key_NumLock
    0x01000026: 0x47,  # Key_ScrollLock
    0x01000053: 0xE3,  # Key_Super_L
    0x01000054: 0xE7,  # Key_Super_R
    # Pontuacao ASCII e Dead Keys (atalhos como Ctrl+~)
    0x20: 0x2C,        # Space
    0x27: 0x34,        # '
    0x2C: 0x36,        # ,
    0x2D: 0x2D,        # -
    0x2E: 0x37,        # .
    0x2F: 0x38,        # /
    0x3B: 0x33,        # ;
    0x3D: 0x2E,        # =
    0x5B: 0x2F,        # [
    0x5C: 0x31,        # \
    0x5D: 0x30,        # ]
    0x60: 0x35,        # `
    0x7E: 0x35,        # ~ (Key_AsciiTilde)
    0xC7: 0x33,        # Key_CCedilla (Ç ABNT2)
    0x01001250: 0x35,  # Key_Dead_Grave (`)
    0x01001251: 0x2F,  # Key_Dead_Acute (´)
    0x01001252: 0x34,  # Key_Dead_Circumflex (^)
    0x01001253: 0x35,  # Key_Dead_Tilde (~)
    0x01001257: 0x23,  # Key_Dead_Diaeresis (¨)
}

# Simbolos Shiftados ASCII -> mesma tecla fisica base
_QT_SHIFTED_ASCII_TO_HID: Dict[int, int] = {
    0x21: 0x1E,  # ! -> 1
    0x40: 0x1F,  # @ -> 2
    0x23: 0x20,  # # -> 3
    0x24: 0x21,  # $ -> 4
    0x25: 0x22,  # % -> 5
    0x5E: 0x23,  # ^ -> 6
    0x26: 0x24,  # & -> 7
    0x2A: 0x25,  # * -> 8
    0x28: 0x26,  # ( -> 9
    0x29: 0x27,  # ) -> 0
    0x5F: 0x2D,  # _ -> -
    0x2B: 0x2E,  # + -> =
    0x7B: 0x2F,  # { -> [
    0x7D: 0x30,  # } -> ]
    0x7C: 0x31,  # | -> \
    0x3A: 0x33,  # : -> ;
    0x22: 0x34,  # " -> '
    0x7E: 0x35,  # ~ -> `
    0x3C: 0x36,  # < -> ,
    0x3E: 0x37,  # > -> .
    0x3F: 0x38,  # ? -> /
}

# Reverso: Win32 Set-1 ScanCode -> HID e Linux evdev -> HID
_WIN_SCAN_TO_HID: Dict[int, int] = {sc: hid for hid, (sc, ext, _) in _HID_TABLE.items() if not ext}
_LINUX_EVDEV_TO_HID: Dict[int, int] = {ev: hid for hid, (_, _, ev) in _HID_TABLE.items()}


def qt_key_to_hid(qt_key: int, native_scancode: int = 0, native_vk: int = 0) -> int:
    """
    Traduz um evento de teclado Qt `(qt_key, native_scancode, native_vk)` para USB HID Usage ID.
    Retorna `0` se a tecla nao for reconhecida.
    """
    k = int(qt_key)
    # Letras A-Z
    if 0x41 <= k <= 0x5A:
        return 0x04 + (k - 0x41)
    if 0x61 <= k <= 0x7A:
        return 0x04 + (k - 0x61)
    # Digitos 1-9, 0
    if 0x31 <= k <= 0x39:
        return 0x1E + (k - 0x31)
    if k == 0x30:
        return 0x27
    # F1-F12 (Qt::Key_F1 = 0x01000030 .. Key_F12 = 0x0100003B)
    if 0x01000030 <= k <= 0x0100003B:
        return 0x3A + (k - 0x01000030)

    if k in _QT_SPECIAL_TO_HID:
        return _QT_SPECIAL_TO_HID[k]
    if k in _QT_SHIFTED_ASCII_TO_HID:
        return _QT_SHIFTED_ASCII_TO_HID[k]

    # Fallback por Win32 VK
    vk = int(native_vk)
    if 0x41 <= vk <= 0x5A:
        return 0x04 + (vk - 0x41)
    if 0x31 <= vk <= 0x39:
        return 0x1E + (vk - 0x31)
    if vk == 0x30:
        return 0x27
    if vk == 0xC1:  # VK_ABNT_C1 (/ ? no teclado ABNT2)
        return 0x87
    if vk == 0xE2:  # VK_OEM_102 (\ | no teclado ABNT2)
        return 0x64
    if vk == 0xC0:  # VK_OEM_3 (` ~ US / ' " ABNT2)
        return 0x35
    if vk == 0xDE:  # VK_OEM_7 (~ ^ ABNT2 / ' " US)
        return 0x34

    # Fallback por ScanCode fisico (X11 keycode = evdev + 8 ou Win32 Set-1)
    sc = int(native_scancode)
    if sc > 8 and (sc - 8) in _LINUX_EVDEV_TO_HID:
        return _LINUX_EVDEV_TO_HID[sc - 8]
    if (sc & 0xFF) in _WIN_SCAN_TO_HID:
        return _WIN_SCAN_TO_HID[sc & 0xFF]

    return 0


def hid_to_win32_scancode(hid_code: int) -> Tuple[int, bool]:
    """Retorna `(win32_set1_scancode, is_extended)` para `SendInput`."""
    entry = _HID_TABLE.get(int(hid_code))
    if entry is None:
        return (0, False)
    return (entry[0], entry[1])


def hid_to_linux_evdev(hid_code: int) -> int:
    """Retorna o codigo `KEY_*` do subsistema `evdev` / `/dev/uinput` do kernel Linux."""
    entry = _HID_TABLE.get(int(hid_code))
    return entry[2] if entry is not None else 0


def hid_to_x11_keycode(hid_code: int) -> int:
    """Retorna o keycode X11 XKB padrao (`evdev + 8`) para `XTestFakeKeyEvent`."""
    ev = hid_to_linux_evdev(hid_code)
    return (ev + 8) if ev > 0 else 0


def supported_evdev_keycodes() -> Tuple[int, ...]:
    """Lista ordenada de todos os codigos `evdev` suportados para registrar em `/dev/uinput`."""
    return tuple(sorted({entry[2] for entry in _HID_TABLE.values() if entry[2] > 0}))
