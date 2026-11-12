# -*- coding: utf-8 -*-
"""
Testes Unitários do Módulo de Apresentação — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

import pytest

from src.dav.modules.presentation.service import PresentationService
from src.dav.modules.presentation.author_dialog import AuthorShowcaseDialog
from scripts.qt_compat import QApplication


def test_presentation_author_dialog_instantiation():
    app = QApplication.instance() or QApplication([])

    dialog = AuthorShowcaseDialog()
    assert dialog.windowTitle() == "Sobre o Autor & Tecnologias — DA-V"
    assert dialog.isModal() is True
    dialog.close()


def test_presentation_service_creation():
    service = PresentationService()
    assert service is not None
