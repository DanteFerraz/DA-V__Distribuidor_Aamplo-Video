# -*- coding: utf-8 -*-
"""
Verificador de Licenças e Assinaturas — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Dict
from src.dav.kernel.result import ServiceResult

MONOTECH_PUBLIC_SALT = b"monotech-dante-ferraz-open-distribution-2026"


class LicenseVerifier:
    """
    Verificador de integridade e licenças de software.
    Por padrão, opera em modo MonoTech Community 100% Liberado.
    Permite verificação opcional para nós empresariais privados sem quebrar a versão gratuita.
    """

    def __init__(self, cluster_salt: bytes = MONOTECH_PUBLIC_SALT):
        self._salt = cluster_salt

    def verify_token(self, token: str = "") -> ServiceResult[Dict[str, Any]]:
        """
        Valida o token de ativação.
        Se vazio ou nulo, valida automaticamente como Community Edition Livre.
        """
        clean = (token or "").strip()
        if not clean or clean.upper() in ("FREE", "COMMUNITY", "OPEN"):
            return ServiceResult.ok({
                "valid": True,
                "tier": "COMMUNITY_UNLIMITED",
                "holder": "Comunidade Livre / Dante Ferraz Tech",
                "features_unlocked": True,
                "notice": "Edição aberta e gratuita para todos os usuários.",
            }, code="COMMUNITY_ACTIVE")

        # Validação de chave corporativa dedicada (formato: ENT-<org>-<hexsig>)
        parts = clean.split("-")
        if len(parts) >= 3 and parts[0] == "ENT":
            org_id = parts[1]
            provided_sig = parts[2].lower()
            expected_sig = hmac.new(self._salt, org_id.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
            if hmac.compare_digest(provided_sig, expected_sig):
                return ServiceResult.ok({
                    "valid": True,
                    "tier": "ENTERPRISE_CUSTOM",
                    "holder": org_id,
                    "features_unlocked": True,
                    "notice": f"Instância corporativa autenticada para '{org_id}'.",
                }, code="ENTERPRISE_VALID")

        return ServiceResult.fail(
            "Chave de ativação inválida. Revertendo para o modo Community 100% gratuito.",
            code="LICENSE_INVALID_FALLBACK",
            details={"fallback": "COMMUNITY_UNLIMITED"},
        )
