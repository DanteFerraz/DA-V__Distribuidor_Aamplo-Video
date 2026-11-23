# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Testes Unitários do Módulo Comercial, Governança AGPLv3 Seção 7 e Compliance — DA-V
Autor: Dante Ferraz (MonoTech)
"""

import pytest

from src.dav.modules.commercial.service import CommercialService
from src.dav.modules.commercial.author_showcase import get_author_showcase
from src.dav.modules.commercial.license_verifier import LicenseVerifier


def test_author_showcase_metadata():
    showcase = get_author_showcase()
    assert showcase["author_name"] == "Dante Ferraz"
    assert showcase["organization"] == "MonoTech"
    assert showcase["license_spdx"] == "AGPL-3.0-or-later"
    assert "Dante Ferraz Oliveira Paiva" in showcase["copyright_notice"]
    assert "https://github.com/DanteFerraz" in showcase["github_profile"]
    ecosystem_names = [item["name"] for item in showcase["ecosystem"]]
    assert "DA-V" in ecosystem_names
    assert "TUPÃ" in ecosystem_names
    assert "SDE" in ecosystem_names


def test_community_edition_policy_unlimited():
    service = CommercialService()
    caps = service.get_edition_capabilities()
    assert caps["is_free"] is True
    assert caps["requires_activation_key"] is False
    assert caps["license_spdx"] == "AGPL-3.0-or-later"
    assert caps["mandatory_notice_section7"] is True
    assert caps["unlimited_duration"] is True
    assert caps["max_fps"] >= 60
    assert "p2p_direct_stun" in caps["features"]
    assert "nvenc_hardware_accel" in caps["features"]


def test_license_verifier_free_and_enterprise():
    verifier = LicenseVerifier()

    # Modelo 100% Gratuito sem chaves de ativação sob GNU AGPLv3 + Seção 7 (NOTICE)
    res_free = verifier.verify_token("")
    assert res_free.is_success
    assert res_free.value["tier"] == "COMMUNITY_UNLIMITED"
    assert res_free.value["license_spdx"] == "AGPL-3.0-or-later"
    assert res_free.value["section7_notice_mandatory"] is True
    assert res_free.value["requires_activation_key"] is False

    # Qualquer string de consulta confirma o modo gratuito livre sem bloqueios
    res_any = verifier.verify_token("FREE")
    assert res_any.is_success
    assert res_any.value["features_unlocked"] is True


def test_mandatory_notice_and_third_party_compliance_files():
    service = CommercialService()
    audit = service.audit_compliance()
    assert audit.is_success, f"Falha de compliance: {audit.error}"
    assert audit.value["compliant"] is True
    assert audit.value["license_spdx"] == "AGPL-3.0-or-later"

    notice_text = service.get_notice_text()
    assert "Dante Ferraz" in notice_text
    assert "MonoTech" in notice_text
    assert "Seção 7" in notice_text or "Section 7" in notice_text

    tp_text = service.get_third_party_notices()
    assert "PySide6" in tp_text
    assert "FFmpeg" in tp_text
    assert "x264" in tp_text
    assert "KCP" in tp_text
