# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Serviço Comercial, Governança de Licença e Atribuição Autoral — DA-V
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.dav.kernel.result import ServiceResult
from src.dav.modules.commercial.author_showcase import get_author_showcase, AUTHOR_METADATA
from src.dav.modules.commercial.edition_policy import EditionPolicy, COMMUNITY_CAPABILITIES
from src.dav.modules.commercial.license_verifier import LicenseVerifier


class CommercialService:
    """
    Fachada para consulta de metadados autorais, política de gratuidade 100% livre,
    termos adicionais da Seção 7 (NOTICE obrigatório) e conformidade de terceiros.
    """

    def __init__(
        self,
        policy: Optional[EditionPolicy] = None,
        verifier: Optional[LicenseVerifier] = None,
    ):
        self.policy = policy or EditionPolicy()
        self.verifier = verifier or LicenseVerifier()

    def get_author_details(self) -> Dict[str, Any]:
        """Retorna as informações completas do autor Dante Ferraz e ecossistema MonoTech."""
        return get_author_showcase()

    def get_edition_capabilities(self) -> Dict[str, Any]:
        """Retorna os limites técnicos liberados e metadados da licença."""
        caps = self.policy.capabilities
        return {
            "edition_name": caps.edition_name,
            "is_free": caps.is_free,
            "requires_activation_key": caps.requires_activation_key,
            "license_spdx": caps.license_spdx,
            "mandatory_notice_section7": caps.mandatory_notice_section7,
            "max_resolution": f"{caps.max_resolution_width}x{caps.max_resolution_height}",
            "max_fps": caps.max_fps,
            "max_bitrate_kbps": caps.max_bitrate_kbps,
            "unlimited_duration": (caps.max_session_duration_sec == 0),
            "features": list(caps.unlocked_features),
        }

    def check_license(self, token: str = "") -> ServiceResult[Dict[str, Any]]:
        """Confirma a gratuidade plena sob GNU AGPLv3 + Seção 7 (sem chaves de ativação)."""
        return self.verifier.verify_token(token)

    def get_notice_text(self) -> str:
        """Retorna o texto integral do NOTICE obrigatório (Seção 7)."""
        return self.verifier.get_notice_text()

    def get_third_party_notices(self) -> str:
        """Retorna o inventário completo de licenças de terceiros."""
        return self.verifier.get_third_party_notices()

    def audit_compliance(self) -> ServiceResult[Dict[str, Any]]:
        """Verifica a integridade dos arquivos de licença e compliance da distribuição."""
        return self.verifier.audit_compliance_files()
