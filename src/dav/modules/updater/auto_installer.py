# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Motor de Download e Instalação Automatizada — DA-V v4.0
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import logging
import os
import stat
import subprocess
import sys
import tempfile
import urllib.request
from typing import Callable, Optional

from src.dav.kernel.result import ServiceResult

logger = logging.getLogger("DAV.Updater.Installer")


class AutoInstaller:
    """Efetua o download do binário de atualização e inicia o processo de substituição."""

    @staticmethod
    def download_asset(
        download_url: str,
        asset_name: str,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> ServiceResult[str]:
        """
        Baixa o instalador remoto com acompanhamento de progresso em tempo real.
        Retorna o caminho do arquivo temporário pronto para execução.
        """
        if not download_url:
            return ServiceResult.fail("URL de download ausente ou inválida", code="INVALID_URL")

        try:
            temp_dir = tempfile.gettempdir()
            filename = asset_name if asset_name else "DA-V_Update_Setup.exe"
            target_path = os.path.join(temp_dir, filename)

            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "DA-V-AutoUpdater/4.0 (MonoTech)"},
                method="GET",
            )

            with urllib.request.urlopen(req, timeout=15.0) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 64 * 1024  # 64 KB

                with open(target_path, "wb") as out_file:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        if on_progress:
                            on_progress(downloaded, total_size)

            logger.info(f"[Updater] Download concluído com sucesso: {target_path} ({downloaded} bytes)")
            return ServiceResult.ok(target_path, code="DOWNLOAD_COMPLETE")

        except Exception as exc:
            logger.error(f"[Updater] Falha no download do instalador: {exc}", exc_info=True)
            return ServiceResult.fail(str(exc), code="DOWNLOAD_ERROR")

    @staticmethod
    def launch_installer_and_exit(installer_path: str, silent: bool = False) -> ServiceResult[bool]:
        """
        Dispara o executável do instalador em processo desacoplado e encerra o app atual.
        """
        if not os.path.isfile(installer_path):
            return ServiceResult.fail(f"Arquivo do instalador não encontrado: {installer_path}", code="FILE_NOT_FOUND")

        try:
            if sys.platform == "win32":
                args = [installer_path]
                if silent:
                    args.append("/SILENT")
                # Inicia o instalador em processo independente desvinculado do pai
                subprocess.Popen(
                    args,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                    close_fds=True,
                )
            else:
                # Linux: Concede permissão de execução e dispara desacoplado
                current_mode = os.stat(installer_path).st_mode
                os.chmod(installer_path, current_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
                subprocess.Popen(
                    [installer_path],
                    start_new_session=True,
                    close_fds=True,
                )

            logger.info(f"[Updater] Instalador disparado: {installer_path}. Aguardando encerramento do app.")
            return ServiceResult.ok(True, code="INSTALLER_LAUNCHED")

        except Exception as exc:
            logger.error(f"[Updater] Falha ao disparar instalador: {exc}", exc_info=True)
            return ServiceResult.fail(str(exc), code="LAUNCH_ERROR")

