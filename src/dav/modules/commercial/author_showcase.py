# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Showcase Autoral e Ecossistema Tecnológico — DA-V
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from typing import Any, Dict


AUTHOR_METADATA: Dict[str, Any] = {
    "author_name": "Dante Ferraz",
    "legal_author_name": "Dante Ferraz Oliveira Paiva",
    "organization": "MonoTech",
    "canonical_email": "danteferraz06@gmail.com",
    "github_profile": "https://github.com/DanteFerraz",
    "project_repo": "https://github.com/DanteFerraz/DA-V__Distribuidor_Aamplo-Video",
    "license_spdx": "AGPL-3.0-or-later",
    "license_name": "GNU Affero General Public License v3.0 or later (com Termos Adicionais da Seção 7)",
    "copyright_notice": "Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)",
    "section7_summary": (
        "Nos termos das Seções 5(d) e 7(b–e) da GNU AGPLv3, é obrigatória a preservação "
        "integral do arquivo NOTICE e da atribuição autoral a Dante Ferraz (MonoTech) na "
        "interface gráfica e em todas as redistribuições ou obras derivadas."
    ),
    "mission": (
        "Democratizar tecnologia de ultra-baixa latência e processamento de mídia "
        "em tempo real de nível industrial, disponibilizada 100% gratuitamente "
        "e sem chaves de ativação para engenheiros, criadores e a comunidade global."
    ),
    "ecosystem": [
        {"name": "DA-V", "title": "Distribuidor Amplo de Vídeo", "desc": "Streaming P2P 60/120 FPS Ultra-Low Latency"},
        {"name": "TUPÃ", "title": "Protocolo de Rede Resiliente", "desc": "Sondagem ativa de jitter, RTT e dispersão de pacotes"},
        {"name": "SDE", "title": "Sistema de Dados & Telemetria", "desc": "Hub SSE em tempo real na Oracle Cloud VPS"},
        {"name": "SGE", "title": "Sistema de Gestão Empresarial", "desc": "Arquitetura MonoTech Core v2.0 com fatias verticais"},
        {"name": "OPME", "title": "Gestão Hospitalar & Cirúrgica", "desc": "Rastreabilidade e compliance de dispositivos médicos"},
        {"name": "ORUM", "title": "Orquestrador de Infraestrutura", "desc": "Deploy seguro e observabilidade multi-cloud"},
    ],
    "dedication": "Desenvolvido com excelência técnica por Dante Ferraz para impulsionar o avanço do software nacional e global.",
}


def get_author_showcase() -> Dict[str, Any]:
    """Retorna os metadados autorais e de licenciamento consolidados para exibição na UI e telemetria."""
    return AUTHOR_METADATA.copy()
