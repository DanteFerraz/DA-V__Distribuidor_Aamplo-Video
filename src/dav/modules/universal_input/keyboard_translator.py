# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Tradutor Universal de Teclado Orientado ao Layout do Cliente — DA-V v5.1
Autor: Dante Ferraz (MonoTech)

Principio de Projeto:
- Na transmissao interativa, o teclado fisico e o idioma/layout do CLIENTE conectado sao a
  fonte canonica da verdade.
- Teclas de movimento, jogos (`WASD`, setas, `Space`, `F1-F12`), modificadores e atalhos
  (`Ctrl+C`, `Alt+Tab`, `Ctrl+~`) usam `mode='hid'` (ScanCode de sub-milissegundo).
- Todo simbolo, acento, pontuacao, tecla `~` (isolada ou em composicao `~/`, `ã`, `õ`), `ç`,
  `/`, `?`, `\\`, `|` e combinacoes `AltGr` gerados pelo teclado do cliente sao emitidos
  via `mode='unicode'` (`codepoint` UTF-32) e reproduzidos de forma identica no Host remoto,
  independentemente do idioma configurado no Windows ou Linux do Host.
"""

from __future__ import annotations

import ctypes
import locale
import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Set, Tuple

from src.dav.modules.remote_desktop.keymap import qt_key_to_hid
from src.dav.modules.universal_input.models import (
    ClientKeyboardProfileDTO,
    UniversalKeyActionDTO,
)

# Mascaras canonicas de modificadores (identicas a KeyMod em remote_desktop.protocol)
MOD_SHIFT = 0x01
MOD_CTRL = 0x02
MOD_ALT = 0x04
MOD_META = 0x08

# Codigos inteiros Qt::Key de teclas mortas (Dead Keys) em teclados ABNT2 / ISO / US-Intl
QT_DEAD_KEYS: Dict[int, str] = {
    0x01001250: "`",  # Key_Dead_Grave
    0x01001251: "´",  # Key_Dead_Acute
    0x01001252: "^",  # Key_Dead_Circumflex
    0x01001253: "~",  # Key_Dead_Tilde
    0x01001257: "¨",  # Key_Dead_Diaeresis
}

# Teclas especiais que sempre trafegam como HID fisico (navegacao, edicao, F-keys, modificadores)
_PURE_HID_QT_KEYS: Set[int] = {
    0x01000000,  # Escape
    0x01000001,  # Tab
    0x01000002,  # Backtab
    0x01000003,  # Backspace
    0x01000004,  # Return
    0x01000005,  # Enter (Keypad)
    0x01000006,  # Insert
    0x01000007,  # Delete
    0x01000008,  # Pause
    0x01000009,  # Print
    0x01000010,  # Home
    0x01000011,  # End
    0x01000012,  # Left
    0x01000013,  # Up
    0x01000014,  # Right
    0x01000015,  # Down
    0x01000016,  # PageUp
    0x01000017,  # PageDown
    0x01000020,  # Shift
    0x01000021,  # Control
    0x01000022,  # Meta
    0x01000023,  # Alt
    0x01001103,  # AltGr
    0x01000024,  # CapsLock
    0x01000025,  # NumLock
    0x01000026,  # ScrollLock
    0x01000053,  # Super_L
    0x01000054,  # Super_R
    0x20,        # Space
}


def detect_local_keyboard_profile() -> ClientKeyboardProfileDTO:
    """Inspeciona o layout de teclado ativo na maquina local (Windows HKL ou Linux XKB)."""
    if sys.platform == "win32":
        try:
            u32 = ctypes.windll.user32
            tid = u32.GetWindowThreadProcessId(u32.GetForegroundWindow(), None)
            hkl = u32.GetKeyboardLayout(tid) & 0xFFFFFFFF
            lang_id = hkl & 0xFFFF
            dev_id = (hkl >> 16) & 0xFFFF
            if lang_id == 0x0416:
                variant = "abnt2" if dev_id in (0x0416, 0x001D, 0xF010) else "br"
                return ClientKeyboardProfileDTO("pt-BR", "windows", variant, f"0x{hkl:08X}")
            if lang_id == 0x0409:
                variant = "us-intl" if dev_id in (0xF001, 0x0409) and hkl > 0x04090409 else "us"
                return ClientKeyboardProfileDTO("en-US", "windows", variant, f"0x{hkl:08X}")
            return ClientKeyboardProfileDTO(f"lang-0x{lang_id:04X}", "windows", "standard", f"0x{hkl:08X}")
        except Exception:
            return ClientKeyboardProfileDTO("pt-BR", "windows", "standard", "0x0")

    layout = "us"
    variant = "standard"
    if shutil.which("setxkbmap"):
        try:
            res = subprocess.run(
                ["setxkbmap", "-query"],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            for ln in (res.stdout or "").splitlines():
                if ln.startswith("layout:"):
                    layout = ln.split(":", 1)[1].strip().split(",")[0] or layout
                elif ln.startswith("variant:"):
                    variant = ln.split(":", 1)[1].strip().split(",")[0] or variant
        except Exception:
            pass
    elif os.path.isfile("/etc/default/keyboard"):
        try:
            with open("/etc/default/keyboard", "r", encoding="utf-8", errors="ignore") as fh:
                for ln in fh:
                    if ln.startswith("XKBLAYOUT="):
                        layout = ln.split("=", 1)[1].strip().strip('"').split(",")[0] or layout
                    elif ln.startswith("XKBVARIANT="):
                        variant = ln.split("=", 1)[1].strip().strip('"') or variant
        except Exception:
            pass
    else:
        loc = (locale.getdefaultlocale()[0] or os.environ.get("LANG", "")).lower()
        if "pt_br" in loc:
            layout, variant = "br", "abnt2"

    code = "pt-BR" if layout == "br" else layout
    return ClientKeyboardProfileDTO(code, "linux", variant or ("abnt2" if layout == "br" else "standard"), "xkb")


def unicode_to_xkb_keysym(codepoint: int) -> int:
    """
    Converte codepoint UTF-32 para X11/XKB KeySym oficial:
    - ASCII imprimivel (0x20..0x7E, incluindo '~' = 0x007E) e Latin-1 (0xA0..0xFF, 'ã' = 0x00E3, 'ç' = 0x00E7)
      mapeiam diretamente para o mesmo inteiro;
    - Demais caracteres Unicode usam o padrao XKB `0x01000000 | codepoint`.
    """
    cp = int(codepoint)
    if 0x20 <= cp <= 0x7E or 0xA0 <= cp <= 0xFF:
        return cp
    if cp > 0xFF:
        return 0x01000000 | (cp & 0x00FFFFFF)
    return 0


# Sequencias Linux evdev para sintetizar simbolos/acentos em `/dev/uinput` conforme o XKB do Host
# Formato: codepoint -> lista de tuplas (evdev_keycode, press_1_or_0)
# Linux evdev codes: LEFTSHIFT=42, RIGHTALT=100, GRAVE=41, APOSTROPHE=40, SPACE=57, LEFTBRACE=26,
# RIGHTBRACE=27, SEMICOLON=39, SLASH=53, BACKSLASH=43, RO(ABNT_/)=89, 102ND(ABNT_\)=86, EQUAL=13, MINUS=12
_UINPUT_TAP = lambda k: [(k, 1), (k, 0)]
_UINPUT_SHIFT_TAP = lambda k: [(42, 1), (k, 1), (k, 0), (42, 0)]
_UINPUT_ALTGR_TAP = lambda k: [(100, 1), (k, 1), (k, 0), (100, 0)]

_UINPUT_US_MAP: Dict[int, List[Tuple[int, int]]] = {
    ord("~"): _UINPUT_SHIFT_TAP(41),
    ord("`"): _UINPUT_TAP(41),
    ord("!"): _UINPUT_SHIFT_TAP(2),
    ord("@"): _UINPUT_SHIFT_TAP(3),
    ord("#"): _UINPUT_SHIFT_TAP(4),
    ord("$"): _UINPUT_SHIFT_TAP(5),
    ord("%"): _UINPUT_SHIFT_TAP(6),
    ord("^"): _UINPUT_SHIFT_TAP(7),
    ord("&"): _UINPUT_SHIFT_TAP(8),
    ord("*"): _UINPUT_SHIFT_TAP(9),
    ord("("): _UINPUT_SHIFT_TAP(10),
    ord(")"): _UINPUT_SHIFT_TAP(11),
    ord("-"): _UINPUT_TAP(12),
    ord("_"): _UINPUT_SHIFT_TAP(12),
    ord("="): _UINPUT_TAP(13),
    ord("+"): _UINPUT_SHIFT_TAP(13),
    ord("["): _UINPUT_TAP(26),
    ord("{"): _UINPUT_SHIFT_TAP(26),
    ord("]"): _UINPUT_TAP(27),
    ord("}"): _UINPUT_SHIFT_TAP(27),
    ord("\\"): _UINPUT_TAP(43),
    ord("|"): _UINPUT_SHIFT_TAP(43),
    ord(";"): _UINPUT_TAP(39),
    ord(":"): _UINPUT_SHIFT_TAP(39),
    ord("'"): _UINPUT_TAP(40),
    ord('"'): _UINPUT_SHIFT_TAP(40),
    ord(","): _UINPUT_TAP(51),
    ord("<"): _UINPUT_SHIFT_TAP(51),
    ord("."): _UINPUT_TAP(52),
    ord(">"): _UINPUT_SHIFT_TAP(52),
    ord("/"): _UINPUT_TAP(53),
    ord("?"): _UINPUT_SHIFT_TAP(53),
}

# No layout XKB `br` (ABNT2):
# - Tecla 40 (ao lado de Ç) e dead_tilde (`~`) sem Shift e dead_circumflex (`^`) com Shift!
#   Pressionar 40 + Space (57) produz `~` literal limpo! 40 + A (30) produz `ã`!
# - Tecla 26 (ao lado de P) e dead_acute (`´`) sem Shift e dead_grave (`` ` ``) com Shift!
# - Tecla 41 (acima de Tab) produz `'` sem Shift e `"` com Shift!
# - Tecla 39 produz `ç` / `Ç`; Tecla 89 (ou AltGr+16 Q) produz `/` / `?`; Tecla 86 produz `\` / `|`!
_UINPUT_BR_ABNT2_MAP: Dict[int, List[Tuple[int, int]]] = {
    ord("~"): [(40, 1), (40, 0), (57, 1), (57, 0)],
    ord("^"): [(42, 1), (40, 1), (40, 0), (42, 0), (57, 1), (57, 0)],
    ord("´"): [(26, 1), (26, 0), (57, 1), (57, 0)],
    ord("`"): [(42, 1), (26, 1), (26, 0), (42, 0), (57, 1), (57, 0)],
    ord("'"): _UINPUT_TAP(41),
    ord('"'): _UINPUT_SHIFT_TAP(41),
    ord("ç"): _UINPUT_TAP(39),
    ord("Ç"): _UINPUT_SHIFT_TAP(39),
    ord("/"): _UINPUT_TAP(89),
    ord("?"): _UINPUT_SHIFT_TAP(89),
    ord("\\"): _UINPUT_TAP(86),
    ord("|"): _UINPUT_SHIFT_TAP(86),
    ord("["): _UINPUT_TAP(27),
    ord("{"): _UINPUT_SHIFT_TAP(27),
    ord("]"): _UINPUT_TAP(43),
    ord("}"): _UINPUT_SHIFT_TAP(43),
    ord(";"): _UINPUT_TAP(53),
    ord(":"): _UINPUT_SHIFT_TAP(53),
    ord("ã"): [(40, 1), (40, 0), (30, 1), (30, 0)],
    ord("Ã"): [(40, 1), (40, 0), (42, 1), (30, 1), (30, 0), (42, 0)],
    ord("õ"): [(40, 1), (40, 0), (24, 1), (24, 0)],
    ord("Õ"): [(40, 1), (40, 0), (42, 1), (24, 1), (24, 0), (42, 0)],
    ord("á"): [(26, 1), (26, 0), (30, 1), (30, 0)],
    ord("é"): [(26, 1), (26, 0), (18, 1), (18, 0)],
    ord("í"): [(26, 1), (26, 0), (23, 1), (23, 0)],
    ord("ó"): [(26, 1), (26, 0), (24, 1), (24, 0)],
    ord("ú"): [(26, 1), (26, 0), (22, 1), (22, 0)],
    ord("â"): [(42, 1), (40, 1), (40, 0), (42, 0), (30, 1), (30, 0)],
    ord("ê"): [(42, 1), (40, 1), (40, 0), (42, 0), (18, 1), (18, 0)],
    ord("ô"): [(42, 1), (40, 1), (40, 0), (42, 0), (24, 1), (24, 0)],
    ord("à"): [(42, 1), (26, 1), (26, 0), (42, 0), (30, 1), (30, 0)],
}


class ClientKeyboardTranslator:
    """
    Traduz eventos de teclado gerados na maquina do CLIENTE em acoes universais:
    - Mantem rastreamento das teclas enviadas via HID fisico (`_active_hid_keys`) para
      emitir `KEY_UP` simetrico sem vazar solturas orfas para teclas enviadas como Unicode;
    - Suporta integralmente o ciclo de Dead Keys (`~`, `´`, `` ` ``, `^`, `¨`) do sistema do cliente.
    """

    def __init__(self, profile: Optional[ClientKeyboardProfileDTO] = None):
        self.profile = profile or detect_local_keyboard_profile()
        self._active_hid_keys: Dict[int, int] = {}  # (qt_key_or_scancode) -> hid_code

    @staticmethod
    def _is_plain_ascii_alnum(ch: str) -> bool:
        if len(ch) != 1:
            return False
        o = ord(ch)
        return (0x30 <= o <= 0x39) or (0x41 <= o <= 0x5A) or (0x61 <= o <= 0x7A)

    def translate_ime_commit(self, commit_string: str, modifiers_mask: int = 0) -> List[UniversalKeyActionDTO]:
        """
        Processa string confirmada pelo IME / maquina de Dead Keys do sistema do cliente
        (ex: usuario digitou `~` + `Espaco` -> `"~"`, `~` + `a` -> `"ã"`, `~` + `/` -> `"~/"`).
        """
        actions: List[UniversalKeyActionDTO] = []
        if not commit_string:
            return actions
        for ch in commit_string:
            cp = ord(ch)
            if cp >= 0x20 and cp != 0x7F:
                actions.append(
                    UniversalKeyActionDTO(
                        mode="unicode",
                        codepoint=cp,
                        modifiers_mask=modifiers_mask,
                    )
                )
        return actions

    def translate_key_press(
        self,
        qt_key: int,
        modifiers_mask: int = 0,
        text: str = "",
        native_scancode: int = 0,
        native_vk: int = 0,
        is_auto_repeat: bool = False,
    ) -> List[UniversalKeyActionDTO]:
        k = int(qt_key)

        # 1. Dead key inicial em espera de composicao pelo SO do cliente (sem texto emitido ainda):
        #    a composicao entregara o caractere resolvido em `inputMethodEvent` ou no proximo `text`.
        if k in QT_DEAD_KEYS and not text:
            # Excecao: se for atalho com Ctrl/Alt/Meta (ex: Ctrl + ~), envia tecla fisica correspondente!
            if modifiers_mask & (MOD_CTRL | MOD_ALT | MOD_META):
                return [
                    UniversalKeyActionDTO(
                        mode="hid",
                        hid_code=0x35,
                        is_up=False,
                        modifiers_mask=modifiers_mask,
                    )
                ]
            return []

        has_ctrl = bool(modifiers_mask & MOD_CTRL)
        has_alt = bool(modifiers_mask & MOD_ALT)
        has_meta = bool(modifiers_mask & MOD_META)
        # No Windows, AltGr chega como Ctrl+Alt + caractere imprimivel!
        is_altgr_char = bool(has_ctrl and has_alt and not has_meta and text and any(ord(c) >= 0x21 for c in text))
        is_shortcut = bool((has_ctrl or has_alt or has_meta) and not is_altgr_char)

        # 2. Teclas puras de navegacao, F1..F12, modificadores ou atalhos de comando (Ctrl+C, Alt+Tab, Ctrl+~)
        is_fkey = 0x01000030 <= k <= 0x01000047
        if k in _PURE_HID_QT_KEYS or is_fkey or is_shortcut:
            if is_auto_repeat:
                return []
            hid = qt_key_to_hid(k, native_scancode=native_scancode, native_vk=native_vk)
            if hid == 0 and k in (0x7E, 0x01001253):
                hid = 0x35
            if hid > 0:
                track_id = native_scancode if native_scancode > 0 else k
                self._active_hid_keys[track_id] = hid
                return [
                    UniversalKeyActionDTO(
                        mode="hid",
                        hid_code=hid,
                        is_up=False,
                        modifiers_mask=modifiers_mask,
                    )
                ]
            return []

        # 3. Letras ASCII A-Z e digitos 0-9 simples (sem AltGr e com len(text) <= 1):
        #    usam HID para suportar segurar WASD em jogos com latencia zero!
        if len(text) == 1 and self._is_plain_ascii_alnum(text) and not is_altgr_char:
            if is_auto_repeat:
                return []
            hid = qt_key_to_hid(ord(text.upper()), native_scancode=0, native_vk=0)
            if hid > 0:
                track_id = native_scancode if native_scancode > 0 else k
                self._active_hid_keys[track_id] = hid
                return [
                    UniversalKeyActionDTO(
                        mode="hid",
                        hid_code=hid,
                        is_up=False,
                        modifiers_mask=modifiers_mask,
                    )
                ]

        # 4. Qualquer simbolo/pontuacao/acento resolvido pelo layout do cliente (`~`, `~/`, `ã`, `ç`, `/`, `?`, `|`, etc.)!
        if text:
            printable = [ord(ch) for ch in text if ord(ch) >= 0x20 and ord(ch) != 0x7F]
            if printable:
                return [
                    UniversalKeyActionDTO(
                        mode="unicode",
                        codepoint=cp,
                        modifiers_mask=modifiers_mask,
                    )
                    for cp in printable
                ]

        # 5. Fallback explicito para Key_AsciiTilde (0x7E) caso `text` venha vazio em algum backend X11/Wayland
        if k == 0x7E:
            return [UniversalKeyActionDTO(mode="unicode", codepoint=0x007E, modifiers_mask=modifiers_mask)]

        # 6. Fallback HID generico para demais teclas especiais (Numpad, etc.)
        if not is_auto_repeat:
            hid = qt_key_to_hid(k, native_scancode=native_scancode, native_vk=native_vk)
            if hid > 0:
                track_id = native_scancode if native_scancode > 0 else k
                self._active_hid_keys[track_id] = hid
                return [
                    UniversalKeyActionDTO(
                        mode="hid",
                        hid_code=hid,
                        is_up=False,
                        modifiers_mask=modifiers_mask,
                    )
                ]
        return []

    def translate_key_release(
        self,
        qt_key: int,
        modifiers_mask: int = 0,
        native_scancode: int = 0,
        native_vk: int = 0,
        is_auto_repeat: bool = False,
    ) -> List[UniversalKeyActionDTO]:
        if is_auto_repeat:
            return []
        k = int(qt_key)
        track_id = native_scancode if native_scancode > 0 else k
        hid = self._active_hid_keys.pop(track_id, 0)
        if hid == 0 and k in _PURE_HID_QT_KEYS:
            hid = qt_key_to_hid(k, native_scancode=native_scancode, native_vk=native_vk)
        if hid > 0:
            return [
                UniversalKeyActionDTO(
                    mode="hid",
                    hid_code=hid,
                    is_up=True,
                    modifiers_mask=modifiers_mask,
                )
            ]
        return []

    def reset(self) -> None:
        self._active_hid_keys.clear()


class HostKeyboardReproducer:
    """
    Auxiliar agnostico de layout no Host para traduzir `codepoint` UTF-32 em:
    - Unidades UTF-16LE para `SendInput(KEYEVENTF_UNICODE)` no Windows;
    - KeySyms XKB (`NotifyKeyboardKeysym` / `XChangeKeyboardMapping`) no Wayland e X11;
    - Sequencias `evdev` cientes do layout do Host no `/dev/uinput`.
    """

    def __init__(self, host_profile: Optional[ClientKeyboardProfileDTO] = None):
        self.host_profile = host_profile or detect_local_keyboard_profile()

    @staticmethod
    def codepoint_to_utf16_units(codepoint: int) -> List[int]:
        """Retorna 1 ou 2 code units UTF-16 (suporta BMP e pares substitutos emoji/simbolos)."""
        cp = int(codepoint)
        if cp <= 0 or cp > 0x10FFFF:
            return []
        raw = chr(cp).encode("utf-16-le")
        return [int.from_bytes(raw[i : i + 2], "little") for i in range(0, len(raw), 2)]

    def codepoint_to_uinput_sequence(self, codepoint: int) -> List[Tuple[int, int]]:
        """Traduz um codepoint para sequencia atomica `(evdev_code, state)` no layout ativo do Host Linux."""
        cp = int(codepoint)
        is_br = self.host_profile.layout_code.lower().startswith("pt") or self.host_profile.variant == "abnt2"
        if is_br and cp in _UINPUT_BR_ABNT2_MAP:
            return list(_UINPUT_BR_ABNT2_MAP[cp])
        if cp in _UINPUT_US_MAP:
            return list(_UINPUT_US_MAP[cp])
        if is_br and cp == ord("@"):
            return _UINPUT_SHIFT_TAP(3)
        # Letras ASCII basicas caso cheguem via Unicode
        ch = chr(cp) if 0x20 <= cp <= 0x7E else ""
        if "a" <= ch <= "z":
            hid = 0x04 + (ord(ch) - ord("a"))
            from src.dav.modules.remote_desktop.keymap import hid_to_linux_evdev

            ev = hid_to_linux_evdev(hid)
            return _UINPUT_TAP(ev) if ev > 0 else []
        if "A" <= ch <= "Z":
            hid = 0x04 + (ord(ch) - ord("A"))
            from src.dav.modules.remote_desktop.keymap import hid_to_linux_evdev

            ev = hid_to_linux_evdev(hid)
            return _UINPUT_SHIFT_TAP(ev) if ev > 0 else []
        return []
