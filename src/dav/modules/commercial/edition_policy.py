# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Política de Edição e Recursos Liberados — DA-V
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class EditionCapabilities:
    edition_name: str
    is_free: bool
    requires_activation_key: bool
    license_spdx: str
    mandatory_notice_section7: bool
    is_commercial_use_allowed: bool
    max_resolution_width: int
    max_resolution_height: int
    max_fps: int
    max_bitrate_kbps: int
    max_session_duration_sec: int  # 0 = Ilimitado
    unlocked_features: List[str]


# Política Canônica MonoTech: 100% Gratuito, Sem Chaves de Ativação, Sob GNU AGPLv3 + Seção 7 (NOTICE)
COMMUNITY_CAPABILITIES = EditionCapabilities(
    edition_name="MonoTech Open Edition (100% Free · GNU AGPLv3 + Section 7 Notice)",
    is_free=True,
    requires_activation_key=False,
    license_spdx="AGPL-3.0-or-later",
    mandatory_notice_section7=True,
    is_commercial_use_allowed=True,
    max_resolution_width=3840,   # 4K UHD Liberado
    max_resolution_height=2160,
    max_fps=120,                 # 120 FPS High Refresh Rate Liberado
    max_bitrate_kbps=50000,      # 50 Mbps Ultra Bitrate Liberado
    max_session_duration_sec=0,  # Duração Ilimitada
    unlocked_features=[
        "p2p_direct_stun",
        "blind_udp_relay",
        "e2e_aead_encryption",
        "nvenc_hardware_accel",
        "avx2_simd_fastpath",
        "wayland_pipewire_portal",
        "windows_graphics_capture",
        "hud_telemetry_tupa",
        "custom_port_binding",
        "unlimited_clients",
    ],
)


class EditionPolicy:
    """Gerencia a política de recursos 100% liberados e metadados da licença."""

    def __init__(self, capabilities: EditionCapabilities = COMMUNITY_CAPABILITIES):
        self._caps = capabilities

    @property
    def capabilities(self) -> EditionCapabilities:
        return self._caps

    def is_feature_enabled(self, feature_name: str) -> bool:
        """Todas as features técnicas são 100% liberadas sem chaves de ativação."""
        return feature_name in self._caps.unlocked_features or self._caps.is_free

    def get_summary(self) -> Dict[str, str]:
        return {
            "edition": self._caps.edition_name,
            "license": f"{self._caps.license_spdx} (Seção 7 NOTICE obrigatório)",
            "cost": "R$ 0,00 (100% Gratuito · Sem Chaves de Ativação)",
            "limits": "Sem limite de tempo, até 4K 120 FPS",
            "author": "Dante Ferraz (MonoTech)",
        }
