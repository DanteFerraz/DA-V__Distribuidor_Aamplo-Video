# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Pacote de Atualizações Remotas do DA-V (v4.0)
Autor: Dante Ferraz (MonoTech)
"""

from src.dav.modules.updater.version_comparator import is_newer_version, parse_semver
from src.dav.modules.updater.update_checker import UpdateChecker, UpdateInfo
from src.dav.modules.updater.auto_installer import AutoInstaller
from src.dav.modules.updater.update_dialog import UpdateConsentDialog
from src.dav.modules.updater.service import UpdaterService
from src.dav.modules.updater.manifest import manifest

__all__ = [
    "is_newer_version",
    "parse_semver",
    "UpdateChecker",
    "UpdateInfo",
    "AutoInstaller",
    "UpdateConsentDialog",
    "UpdaterService",
    "manifest",
]

