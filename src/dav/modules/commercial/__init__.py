# -*- coding: utf-8 -*-
"""Módulo Comercial & Governança Autoral — DA-V v4.0"""

from src.dav.modules.commercial.service import CommercialService
from src.dav.modules.commercial.author_showcase import get_author_showcase, AUTHOR_METADATA
from src.dav.modules.commercial.edition_policy import EditionPolicy, COMMUNITY_CAPABILITIES

__all__ = ["CommercialService", "get_author_showcase", "AUTHOR_METADATA", "EditionPolicy", "COMMUNITY_CAPABILITIES"]

