# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
MonoTech Core Kernel — Gerenciador de Configuração (ConfigEngine)
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # Fallback
    except ImportError:
        tomllib = None


@dataclass
class VideoConfig:
    width: int = 1920
    height: int = 1080
    fps: int = 60
    bitrate_kbps: int = 12000
    codec: str = "H264"
    prefer_hardware: bool = True
    display_index: int = 0


@dataclass
class NetworkConfig:
    bind_port: int = 9000
    rendezvous_host: str = "129.148.26.150"
    rendezvous_http_port: int = 80
    rendezvous_udp_port: int = 8768
    stun_server: str = "stun.l.google.com"
    stun_port: int = 19302
    mtu: int = 1320


@dataclass
class CommercialConfig:
    edition: str = "Community"  # Community / Open Tech 100% Free
    author: str = "Dante Ferraz"
    organization: str = "MonoTech"
    enable_telemetry: bool = True
    watermark_enabled: bool = False


class ConfigEngine:
    """
    Carregador e orquestrador de configurações com suporte a dav.toml
    e sobrescritas por variáveis de ambiente.
    """

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or (Path(__file__).resolve().parent.parent.parent.parent / "dav.toml")
        self.video = VideoConfig()
        self.network = NetworkConfig()
        self.commercial = CommercialConfig()
        self.raw_data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Carrega e mescla a configuração de arquivo e variáveis de ambiente."""
        if self.config_path.is_file() and tomllib is not None:
            try:
                with open(self.config_path, "rb") as f:
                    self.raw_data = tomllib.load(f)
            except Exception:
                self.raw_data = {}

        # 1. Video
        c_cap = self.raw_data.get("capture", {})
        c_cod = self.raw_data.get("codec", {})
        self.video.width = int(c_cap.get("width", self.video.width))
        self.video.height = int(c_cap.get("height", self.video.height))
        self.video.fps = int(c_cap.get("fps", self.video.fps))
        self.video.display_index = int(c_cap.get("display_index", self.video.display_index))
        self.video.bitrate_kbps = int(c_cod.get("target_bitrate_kbps", self.video.bitrate_kbps))
        self.video.codec = str(c_cod.get("codec", self.video.codec))

        # 2. Network
        c_trans = self.raw_data.get("transport", {})
        self.network.bind_port = int(os.environ.get("DAV_BIND_PORT", c_trans.get("bind_port", self.network.bind_port)))
        self.network.rendezvous_host = os.environ.get("DAV_RENDEZVOUS_HOST", self.network.rendezvous_host)

        # 3. Commercial
        c_comm = self.raw_data.get("commercial", {})
        self.commercial.edition = str(c_comm.get("edition", self.commercial.edition))
        self.commercial.watermark_enabled = bool(c_comm.get("watermark_enabled", self.commercial.watermark_enabled))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "video": self.video.__dict__,
            "network": self.network.__dict__,
            "commercial": self.commercial.__dict__,
            "raw": self.raw_data,
        }

