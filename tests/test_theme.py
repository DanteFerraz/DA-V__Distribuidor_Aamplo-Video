# -*- coding: utf-8 -*-
"""
Testes Unitários do Design System Blocks.so e Temas — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

import pytest
from src.ui.theme import Theme


def test_theme_default_mode_and_monotech_blue():
    # Modo padrão
    Theme.set_theme("dark")
    assert Theme.current_mode == "dark"
    assert Theme.SYS["accent_primary"] == "#0066FF"  # Azul MonoTech
    assert Theme.SYS["bg_canvas"] == "#09090b"      # Zinc-950 Dark
    assert Theme.SYS["border_subtle"] == "#27272a"


def test_theme_toggle_to_light_mode():
    Theme.set_theme("dark")
    new_mode = Theme.toggle_theme()
    assert new_mode == "light"
    assert Theme.current_mode == "light"
    assert Theme.SYS["bg_canvas"] == "#f8fafc"       # Slate-50 Light
    assert Theme.SYS["bg_surface"] == "#ffffff"      # Pure White
    assert Theme.SYS["accent_primary"] == "#0066FF"  # Azul MonoTech preservado
    assert Theme.SYS["text_primary"] == "#0f172a"    # Slate-900 Dark text

    # Toggle de volta para dark
    back_mode = Theme.toggle_theme()
    assert back_mode == "dark"
    assert Theme.SYS["bg_canvas"] == "#09090b"


def test_theme_stylesheet_generation():
    # Testa geração do QSS no modo escuro
    Theme.set_theme("dark")
    qss_dark = Theme.build_stylesheet()
    assert "#09090b" in qss_dark
    assert "#0066FF" in qss_dark

    # Testa geração do QSS no modo claro
    Theme.set_theme("light")
    qss_light = Theme.build_stylesheet()
    assert "#f8fafc" in qss_light
    assert "#0066FF" in qss_light

    # Restaura tema escuro por padrão
    Theme.set_theme("dark")

