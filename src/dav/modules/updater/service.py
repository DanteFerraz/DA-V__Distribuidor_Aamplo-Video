# -*- coding: utf-8 -*-
"""
Serviço de Gestão de Atualizações — DA-V v4.0
Autor: Dante Ferraz (MonoTech)

Orquestra a verificação assíncrona, diálogo de consentimento explícito
e disparo do processo de instalação automatizada.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from src.dav.kernel.result import ServiceResult
from src.dav.modules.updater.update_checker import UpdateChecker, UpdateInfo
from src.dav.modules.updater.update_dialog import UpdateConsentDialog

logger = logging.getLogger("DAV.Updater.Service")


class UpdaterService:
    """
    Serviço central de ciclo de vida de atualizações do DA-V.
    Executa verificações em segundo plano e apresenta o fluxo com consentimento.
    """

    def __init__(
        self,
        checker: Optional[UpdateChecker] = None,
        current_version: str = "4.0.0",
    ):
        self.checker = checker or UpdateChecker()
        self.current_version = current_version
        self._is_checking = False

    def check_for_updates(self) -> ServiceResult[UpdateInfo]:
        """Executa consulta síncrona/direta por atualizações."""
        return self.checker.check(current_version=self.current_version)

    def start_background_check(
        self,
        on_complete: Callable[[ServiceResult[UpdateInfo]], None],
    ) -> bool:
        """
        Dispara verificação de versão remota em thread desacoplada sem bloquear o app.
        Retorna False se uma verificação já estiver em andamento.
        """
        if self._is_checking:
            return False

        self._is_checking = True

        def _worker():
            try:
                res = self.check_for_updates()
                on_complete(res)
            except Exception as exc:
                logger.error(f"[UpdaterService] Exceção na verificação em background: {exc}")
                on_complete(ServiceResult.fail(str(exc), code="BG_CHECK_ERROR"))
            finally:
                self._is_checking = False

        t = threading.Thread(target=_worker, daemon=True, name="DAV-Updater-Check")
        t.start()
        return True

    def prompt_update_dialog(self, update_info: UpdateInfo, parent=None) -> bool:
        """
        Exibe o diálogo modal de consentimento Blocks.so.
        Retorna True se o usuário aceitou e disparou a atualização, False se rejeitou/postergou.
        """
        if not update_info.has_update:
            return False

        try:
            dialog = UpdateConsentDialog(update_info=update_info, parent=parent)
            result = dialog.exec()
            # QDialog.Accepted == 1
            return result == 1
        except Exception as exc:
            logger.error(f"[UpdaterService] Falha ao exibir diálogo de consentimento: {exc}", exc_info=True)
            return False
