# -*- coding: utf-8 -*-
"""
Serviço Comercial e Governança do Ecossistema — DA-V v4.0
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
    Fachada para consulta de metadados autorais, política de gratuidade e
    suporte institucional aos projetos do Dante Ferraz.
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
        """Retorna os limites técnicos liberados da edição."""
        caps = self.policy.capabilities
        return {
            "edition_name": caps.edition_name,
            "is_free": caps.is_free,
            "max_resolution": f"{caps.max_resolution_width}x{caps.max_resolution_height}",
            "max_fps": caps.max_fps,
            "max_bitrate_kbps": caps.max_bitrate_kbps,
            "unlimited_duration": (caps.max_session_duration_sec == 0),
            "features": list(caps.unlocked_features),
        }

    def check_license(self, token: str = "") -> ServiceResult[Dict[str, Any]]:
        """Verifica a licença ou confirma a gratuidade plena."""
        return self.verifier.verify_token(token)

