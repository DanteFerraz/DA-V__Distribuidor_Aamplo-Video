# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Exportador de Telemetria para o Hub SDE v2.0 — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, Optional

from src.dav.kernel.circuit_breaker import CircuitBreaker
from src.dav.kernel.result import ServiceResult

logger = logging.getLogger("DAV.Telemetry.SDE")

DEFAULT_SDE_ENDPOINT = "http://129.148.26.150:5001/sde/live/telemetry/dav"


class SDETelemetryExporter:
    """
    Exportador assíncrono de telemetria para o painel de observabilidade SDE.
    Protegido por CircuitBreaker para garantir impacto zero na latência do streaming
    mesmo quando a nuvem estiver indisponível.
    """

    def __init__(
        self,
        endpoint_url: str = DEFAULT_SDE_ENDPOINT,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        self.endpoint_url = endpoint_url
        self.breaker = circuit_breaker or CircuitBreaker(
            name="SDE_Telemetry_Exporter",
            failure_threshold=3,
            recovery_timeout=30.0,
        )

    def export_metric(self, metric_data: Dict[str, Any]) -> ServiceResult[bool]:
        """Envia métricas formatadas para o Hub SDE."""
        if not self.breaker.can_execute():
            return ServiceResult.fail("CircuitBreaker ABERTO: SDE Hub offline", code="CIRCUIT_OPEN")

        def _send() -> bool:
            body = json.dumps(metric_data).encode("utf-8")
            req = urllib.request.Request(
                self.endpoint_url,
                data=body,
                headers={"Content-Type": "application/json", "User-Agent": "DA-V/4.0-MonoTech"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                return resp.status in (200, 201, 204)

        try:
            success = self.breaker.execute(_send)
            return ServiceResult.ok(success, code="EXPORTED")
        except Exception as exc:
            return ServiceResult.fail(str(exc), code="EXPORT_ERROR")

