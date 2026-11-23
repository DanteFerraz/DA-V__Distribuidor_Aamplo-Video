# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Testes Unitários do Módulo de Apresentação e Avisos Legais (Seção 5(d) & 7(b)) — DA-V
Autor: Dante Ferraz (MonoTech)
"""

import pytest

from src.dav.modules.presentation.service import PresentationService
from src.dav.modules.presentation.author_dialog import AuthorShowcaseDialog
from scripts.qt_compat import QApplication


def test_presentation_author_dialog_instantiation():
    app = QApplication.instance() or QApplication([])

    dialog = AuthorShowcaseDialog()
    try:
        assert dialog.windowTitle() == "Sobre o Autor & Tecnologias — DA-V"
        assert dialog.isModal() is True
        assert dialog.tabs.count() == 3
        assert "Dante Ferraz" in dialog.txt_notice.toPlainText()
        assert "PySide6" in dialog.txt_third_party.toPlainText()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_presentation_service_creation():
    service = PresentationService()
    assert service is not None
