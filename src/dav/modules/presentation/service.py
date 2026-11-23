# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Serviço de Apresentação e Telas — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("DAV.Presentation.Service")


class PresentationService:
    """Gerencia diálogos e integrações de UI."""

    def __init__(self):
        pass

    def show_author_dialog(self, parent=None) -> None:
        """Abre o diálogo modal de Sobre o Autor e Governança."""
        try:
            from src.dav.modules.presentation.author_dialog import AuthorShowcaseDialog
            dlg = AuthorShowcaseDialog(parent=parent)
            dlg.exec()
        except Exception as exc:
            logger.error(f"[Presentation] Falha ao exibir AuthorShowcaseDialog: {exc}")

