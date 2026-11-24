#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Gerador Reprodutivel do Pacote Portatil Linux (.tar.gz) — DA-V
Autor: Dante Ferraz (MonoTech)

Empacota o codigo-fonte, scripts Linux, CMake, manifests, testes e guias com
finais de linha POSIX (LF) e permissoes executaveis (+x nos scripts .sh).
"""

from __future__ import annotations

import io
import os
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ROOT_FILES = (
    "VERSION",
    "README.md",
    "LEIA-ME_LINUX.md",
    "GUIA_RAPIDO_LINUX.md",
    "CHANGELOG.md",
    "CMakeLists.txt",
    "requirements.txt",
    "install_linux.sh",
    "launch_dav.sh",
    "build_linux.sh",
    "dav.toml",
    "LICENSE",
    "NOTICE",
    "TRADEMARK.md",
    "THIRD_PARTY_LICENSES.md",
)

INCLUDE_DIRS = (
    "src",
    "scripts",
    "include",
    "installer",
    "tests",
    "cmake",
    "deploy",
    "third_party",
    "LICENSES",
)

TEXT_EXTS = {
    ".py", ".sh", ".md", ".txt", ".hpp", ".cpp", ".h", ".c",
    ".cmake", ".yml", ".yaml", ".toml", ".iss", ".desktop",
    ".service", ".json", ".ini", ".cfg",
}

TEXT_EXACT = {"VERSION", "CMakeLists.txt", "LICENSE", "NOTICE"}

SKIP_DIR_NAMES = {"__pycache__", ".pytest_cache", ".git", ".venv", ".venv-build", "build", "dist"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".obj", ".o", ".zip", ".exe"}


def _is_text_file(path: Path) -> bool:
    return path.name in TEXT_EXACT or path.suffix.lower() in TEXT_EXTS


def _add_file(tar: tarfile.TarFile, src_path: Path, arc_name: str, now_ts: int) -> None:
    raw = src_path.read_bytes()
    if _is_text_file(src_path):
        raw = raw.replace(b"\r\n", b"\n")

    info = tarfile.TarInfo(name=arc_name)
    info.size = len(raw)
    info.mtime = now_ts
    info.mode = 0o755 if src_path.suffix.lower() == ".sh" else 0o644
    info.uid = 1000
    info.gid = 1000
    info.uname = "dav"
    info.gname = "dav"
    tar.addfile(info, io.BytesIO(raw))


def build_linux_source_tarball() -> Path:
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    release_dir = ROOT / "release_assets"
    release_dir.mkdir(parents=True, exist_ok=True)

    out_path = release_dir / f"DA-V_v{ver}_Linux_Source_Portable.tar.gz"
    prefix = f"DA-V-v{ver}-Linux-Source"
    now_ts = int(time.time())

    entries = 0
    with tarfile.open(out_path, "w:gz", compresslevel=9) as tar:
        for rel_name in ROOT_FILES:
            fp = ROOT / rel_name
            if fp.is_file():
                _add_file(tar, fp, f"{prefix}/{rel_name}", now_ts)
                entries += 1

        for dir_name in INCLUDE_DIRS:
            base = ROOT / dir_name
            if not base.is_dir():
                continue
            for root_str, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIR_NAMES)
                cur = Path(root_str)
                for fname in sorted(filenames):
                    fp = cur / fname
                    if fp.suffix.lower() in SKIP_SUFFIXES:
                        continue
                    rel = fp.relative_to(ROOT).as_posix()
                    _add_file(tar, fp, f"{prefix}/{rel}", now_ts)
                    entries += 1

    print(f"[OK] Pacote Linux gerado: {out_path} ({out_path.stat().st_size} bytes, {entries} arquivos)")
    return out_path


if __name__ == "__main__":
    build_linux_source_tarball()
