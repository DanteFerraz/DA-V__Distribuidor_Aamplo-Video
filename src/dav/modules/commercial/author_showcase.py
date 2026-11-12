# -*- coding: utf-8 -*-
"""
Showcase Autoral e Ecossistema Tecnológico — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from typing import Any, Dict


AUTHOR_METADATA: Dict[str, Any] = {
    "author_name": "Dante Ferraz",
    "organization": "MonoTech",
    "canonical_email": "danteferraz06@gmail.com",
    "github_profile": "https://github.com/DanteFerraz",
    "project_repo": "https://github.com/DanteFerraz/DA-V__Distribuidor_Aamplo-Video",
    "mission": (
        "Democratizar tecnologia de ultra-baixa latência e processamento de mídia "
        "em tempo real de nível industrial, disponibilizada 100% gratuitamente "
        "para engenheiros, criadores e a comunidade global de software."
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
    """Retorna os metadados autorais consolidados para exibição na UI e telemetria."""
    return AUTHOR_METADATA.copy()

