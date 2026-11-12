# -*- coding: utf-8 -*-
"""
Testes Unitários do Módulo Comercial e Governança — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

import hashlib
import hmac
import pytest

from src.dav.modules.commercial.service import CommercialService
from src.dav.modules.commercial.author_showcase import get_author_showcase
from src.dav.modules.commercial.license_verifier import LicenseVerifier, MONOTECH_PUBLIC_SALT


def test_author_showcase_metadata():
    showcase = get_author_showcase()
    assert showcase["author_name"] == "Dante Ferraz"
    assert showcase["organization"] == "MonoTech"
    assert "https://github.com/DanteFerraz" in showcase["github_profile"]
    ecosystem_names = [item["name"] for item in showcase["ecosystem"]]
    assert "DA-V" in ecosystem_names
    assert "TUPÃ" in ecosystem_names
    assert "SDE" in ecosystem_names


def test_community_edition_policy_unlimited():
    service = CommercialService()
    caps = service.get_edition_capabilities()
    assert caps["is_free"] is True
    assert caps["unlimited_duration"] is True
    assert caps["max_fps"] >= 60
    assert "p2p_direct_stun" in caps["features"]
    assert "nvenc_hardware_accel" in caps["features"]


def test_license_verifier_free_and_enterprise():
    verifier = LicenseVerifier()

    # Teste 1: Default / Vazio -> Modo Community 100% Liberado
    res_free = verifier.verify_token("")
    assert res_free.is_success
    assert res_free.value["tier"] == "COMMUNITY_UNLIMITED"

    # Teste 2: Enterprise com assinatura HMAC válida
    org = "HospitalSantaClara"
    expected_sig = hmac.new(MONOTECH_PUBLIC_SALT, org.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
    valid_ent_token = f"ENT-{org}-{expected_sig}"

    res_ent = verifier.verify_token(valid_ent_token)
    assert res_ent.is_success
    assert res_ent.value["tier"] == "ENTERPRISE_CUSTOM"
    assert res_ent.value["holder"] == org

    # Teste 3: Token inválido reverte para fallback seguro sem travar
    res_invalid = verifier.verify_token("CHAVE_FALSA_123")
    assert res_invalid.is_error
    assert res_invalid.details["fallback"] == "COMMUNITY_UNLIMITED"
