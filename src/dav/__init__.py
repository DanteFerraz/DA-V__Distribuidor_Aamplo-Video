# -*- coding: utf-8 -*-
"""
DA-V (Distribuidor Amplo de Vídeo) — Arquitetura Modular v4.9.0
MonoTech Core Blueprint v2.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import os
import sys

_FALLBACK_VERSION = "4.9.0"


def get_version() -> str:
    """Carrega a versao canonica da aplicacao a partir do arquivo VERSION."""
    pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    base_root = getattr(sys, "_MEIPASS", pkg_root)
    for root_dir in (base_root, pkg_root):
        ver_path = os.path.join(root_dir, "VERSION")
        if os.path.isfile(ver_path):
            try:
                with open(ver_path, "r", encoding="utf-8") as fh:
                    val = fh.read().strip()
                    if val:
                        return val
            except Exception:
                pass
    return _FALLBACK_VERSION


__version__ = get_version()
__author__ = "Dante Ferraz <danteferraz06@gmail.com>"
