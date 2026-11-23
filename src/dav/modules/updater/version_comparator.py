# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Comparador Semântico de Versões (SemVer) — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import re
from typing import Tuple


def parse_semver(ver_str: str) -> Tuple[int, int, int]:
    """Extrai tupla (major, minor, patch) de uma string de versão (ex: 'v4.1.0' -> (4, 1, 0))."""
    clean = (ver_str or "").strip().lower().lstrip("v")
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", clean)
    if not match:
        return (0, 0, 0)
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3)) if match.group(3) is not None else 0
    return (major, minor, patch)


def is_newer_version(remote_ver: str, current_ver: str) -> bool:
    """Retorna True se remote_ver for estritamente mais recente que current_ver."""
    r_tuple = parse_semver(remote_ver)
    c_tuple = parse_semver(current_ver)
    return r_tuple > c_tuple

