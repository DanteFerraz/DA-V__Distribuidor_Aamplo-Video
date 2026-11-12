# -*- coding: utf-8 -*-
"""
Verificador de Atualizações Remotas (GitHub Releases API) — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.dav.kernel.circuit_breaker import CircuitBreaker
from src.dav.kernel.result import ServiceResult
from src.dav.modules.updater.version_comparator import is_newer_version

logger = logging.getLogger("DAV.Updater.Checker")

DEFAULT_GITHUB_REPO = "DanteFerraz/DA-V__Distribuidor_Aamplo-Video"
DEFAULT_RELEASES_API = f"https://api.github.com/repos/{DEFAULT_GITHUB_REPO}/releases/latest"


@dataclass
class UpdateInfo:
    """Informações estruturadas sobre uma versão remota disponível."""
    has_update: bool
    current_version: str
    latest_version: str
    release_title: str
    release_notes: str
    download_url: str
    asset_name: str
    published_at: str = ""


class UpdateChecker:
    """
    Consulta o repositório oficial por novas versões e localiza o instalador correto
    para a plataforma operacional do usuário. Protegido por CircuitBreaker.
    """

    def __init__(
        self,
        api_url: str = DEFAULT_RELEASES_API,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        self.api_url = api_url
        self.breaker = circuit_breaker or CircuitBreaker(
            name="GitHub_Release_Checker",
            failure_threshold=2,
            recovery_timeout=60.0,
        )

    def check(self, current_version: str = "4.0.0") -> ServiceResult[UpdateInfo]:
        """Consulta assincronamente ou diretamente se há versão mais recente."""
        if not self.breaker.can_execute():
            return ServiceResult.fail("CircuitBreaker ABERTO: verificação de atualizações suspensa", code="CIRCUIT_OPEN")

        def _fetch() -> Dict[str, Any]:
            req = urllib.request.Request(
                self.api_url,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": f"DA-V-Updater/{current_version} (MonoTech)",
                },
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = resp.read()
                return json.loads(data.decode("utf-8"))

        try:
            payload = self.breaker.execute(_fetch)
        except Exception as exc:
            logger.debug(f"[Updater] Falha na consulta de atualizações: {exc}")
            return ServiceResult.fail(str(exc), code="FETCH_ERROR")

        tag_name = payload.get("tag_name", "").strip().lstrip("v")
        if not tag_name:
            return ServiceResult.fail("Release remota sem tag_name identificável", code="INVALID_PAYLOAD")

        has_update = is_newer_version(tag_name, current_version)
        release_title = payload.get("name", f"DA-V v{tag_name}")
        release_notes = payload.get("body", "Melhorias de desempenho e estabilidade.")
        published_at = payload.get("published_at", "")

        # Localização do asset compatível com o SO atual
        download_url = ""
        asset_name = ""
        assets: List[Dict[str, Any]] = payload.get("assets", [])

        if sys.platform == "win32":
            # Prioridade para o instalador .exe do Windows
            for a in assets:
                name = a.get("name", "")
                if name.endswith(".exe") and ("installer" in name.lower() or "instalador" in name.lower() or "windows" in name.lower() or "da-v" in name.lower()):
                    download_url = a.get("browser_download_url", "")
                    asset_name = name
                    break
            if not download_url:
                for a in assets:
                    if a.get("name", "").endswith(".zip") and "windows" in a.get("name", "").lower():
                        download_url = a.get("browser_download_url", "")
                        asset_name = a.get("name", "")
                        break
        else:
            # Linux x86_64
            for a in assets:
                name = a.get("name", "")
                if "linux" in name.lower() and ("instalador" in name.lower() or "tar.gz" in name.lower() or not "." in name):
                    download_url = a.get("browser_download_url", "")
                    asset_name = name
                    break

        # Fallback genérico se nenhum asset binário for explicitado
        if not download_url and assets:
            download_url = assets[0].get("browser_download_url", "")
            asset_name = assets[0].get("name", "")

        info = UpdateInfo(
            has_update=has_update,
            current_version=current_version,
            latest_version=tag_name,
            release_title=release_title,
            release_notes=release_notes,
            download_url=download_url,
            asset_name=asset_name,
            published_at=published_at,
        )

        return ServiceResult.ok(info, code="CHECK_COMPLETED")
