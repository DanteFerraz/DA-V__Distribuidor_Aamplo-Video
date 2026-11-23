# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""Módulo Comercial & Governança Autoral — DA-V v4.0"""

from src.dav.modules.commercial.service import CommercialService
from src.dav.modules.commercial.author_showcase import get_author_showcase, AUTHOR_METADATA
from src.dav.modules.commercial.edition_policy import EditionPolicy, COMMUNITY_CAPABILITIES

__all__ = ["CommercialService", "get_author_showcase", "AUTHOR_METADATA", "EditionPolicy", "COMMUNITY_CAPABILITIES"]

