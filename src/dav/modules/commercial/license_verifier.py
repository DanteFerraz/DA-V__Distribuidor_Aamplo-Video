# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Governança de Licença, Atribuição Obrigatória (Seção 7) e Avisos de Terceiros — DA-V
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

from src.dav.kernel.result import ServiceResult

DEFAULT_NOTICE_FALLBACK = (
    "DA-V — Distribuidor Amplo de Vídeo\n"
    "Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)\n"
    "Licença: GNU Affero General Public License v3.0 ou posterior (AGPL-3.0-or-later)\n"
    "com Termos Adicionais obrigatórios da Seção 7 (alíneas 7(b) a 7(e)) e Seção 5(d).\n"
    "Repositório Oficial: https://github.com/DanteFerraz/DA-V__Distribuidor_Aamplo-Video\n"
)


def _candidate_roots() -> List[Path]:
    roots: List[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "VERSION").is_file() or (parent / "LICENSE").is_file():
            roots.append(parent)
            break
    roots.append(Path.cwd())
    return roots


def _read_legal_file(rel_path: str, fallback: str = "") -> str:
    for root in _candidate_roots():
        cand = root / rel_path
        if cand.is_file():
            try:
                return cand.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
    return fallback


class LicenseVerifier:
    """
    Provedor de governança jurídica e conformidade de licenças do DA-V.
    Opera em modelo 100% gratuito e sem chaves de ativação sob GNU AGPLv3
    com Termos Adicionais da Seção 7 (NOTICE e atribuição obrigatórios).
    """

    def verify_token(self, token: str = "") -> ServiceResult[Dict[str, Any]]:
        """
        Confirma a política 100% gratuita e livre do DA-V (sem sistema de chaves de ativação).
        Mantém assinatura compatível com consumidores do serviço comercial.
        """
        return ServiceResult.ok({
            "valid": True,
            "tier": "COMMUNITY_UNLIMITED",
            "license_spdx": "AGPL-3.0-or-later",
            "section7_notice_mandatory": True,
            "requires_activation_key": False,
            "holder": "Dante Ferraz (MonoTech) — Edição 100% Gratuita & Aberta",
            "features_unlocked": True,
            "notice": (
                "Aplicação 100% gratuita sem chaves de ativação. Distribuída sob GNU AGPLv3 "
                "com preservação obrigatória do arquivo NOTICE e da atribuição autoral (Seção 7)."
            ),
        }, code="AGPLV3_SECTION7_ACTIVE")

    def get_notice_text(self) -> str:
        """Retorna o conteúdo integral do arquivo NOTICE obrigatório (Seção 7(b–e))."""
        return _read_legal_file("NOTICE", fallback=DEFAULT_NOTICE_FALLBACK)

    def get_third_party_notices(self) -> str:
        """Retorna o inventário completo de licenças de terceiros (THIRD_PARTY_LICENSES.md)."""
        return _read_legal_file(
            "THIRD_PARTY_LICENSES.md",
            fallback="Consulte THIRD_PARTY_LICENSES.md na raiz da distribuição para avisos de terceiros.",
        )

    def get_trademark_policy(self) -> str:
        """Retorna a política de marcas e identidade visual (TRADEMARK.md)."""
        return _read_legal_file(
            "TRADEMARK.md",
            fallback="As marcas DA-V e MonoTech e o ícone oficial são reservados a Dante Ferraz (Seção 7(e)).",
        )

    def get_license_text(self) -> str:
        """Retorna o texto completo da licença GNU AGPLv3 + Adendo da Seção 7 (LICENSE)."""
        return _read_legal_file("LICENSE", fallback=DEFAULT_NOTICE_FALLBACK)

    def audit_compliance_files(self) -> ServiceResult[Dict[str, Any]]:
        """Verifica se os artefatos normativos de licença estão presentes na distribuição."""
        required = (
            "LICENSE",
            "NOTICE",
            "TRADEMARK.md",
            "THIRD_PARTY_LICENSES.md",
            "LICENSES/AGPL-3.0.txt",
            "LICENSES/GPL-3.0.txt",
            "LICENSES/LGPL-3.0.txt",
            "third_party/kcp/LICENSE",
        )
        found: Dict[str, bool] = {}
        roots = _candidate_roots()
        for rel in required:
            found[rel] = any((r / rel).is_file() for r in roots)

        missing = [k for k, ok in found.items() if not ok]
        if missing:
            return ServiceResult.fail(
                f"Arquivos de compliance ausentes: {', '.join(missing)}",
                code="COMPLIANCE_FILES_MISSING",
                details={"files": found, "missing": missing},
            )
        return ServiceResult.ok(
            {"compliant": True, "license_spdx": "AGPL-3.0-or-later", "files": found},
            code="COMPLIANCE_VERIFIED",
        )
