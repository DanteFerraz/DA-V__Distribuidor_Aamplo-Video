# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
DA-V — Instalador Grafico Oficial Glassmorphism (Windows 10/11) — v5.0
Autor: Dante Ferraz (MonoTech)

Unificado sobre `src.ui.glass.installer_shell.DavGlassInstallerDialog`, compartilhando
o mesmo Design System de vidro translucido, pilulas neon e iconografia vetorial da aplicacao.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import winreg
import zipfile

def _bootstrap_proj_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


_BOOT_ROOT = _bootstrap_proj_root()
if str(_BOOT_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOT_ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from src.ui.glass.installer_shell import (
    DavGlassInstallerDialog,
    GlassDiagnosticStrip,
    GlassInstallStepRow,
)


class DavModernInstaller(DavGlassInstallerDialog):
    """Instalador Glassmorphism oficial do DA-V v5.0 para Windows 10/11."""

    def __init__(self, parent=None):
        super().__init__(
            window_title="DA-V · Distribuidor Amplo de Vídeo — Assistente de Instalação",
            platform_edition="Windows x64",
            step_definitions=[
                ("Boas-vindas", "Ambiente e GPU"),
                ("Preferências", "Firewall e atalhos"),
                ("Instalação", "Integração no Windows"),
                ("Conclusão", "Pronto para usar"),
            ],
            parent=parent,
        )

    def _create_page_welcome(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        lay.addLayout(
            self._make_page_header(
                "Streaming P2P e Área de Trabalho Remota",
                "Este assistente instalará o DA-V com aceleração Direct3D / NVENC, pareamento "
                "PAKE AEAD por PIN e compartilhamento interativo sub-15 ms no Windows.",
            )
        )

        highlights = [
            "Motor desacoplado a 60/120 FPS com FEC adaptativo GF(2^8) e latência sub-milissegundo.",
            "Compartilhamento completo de área de trabalho com chave de Modo Interativo e elevação UAC.",
            "Associação direta ao protocolo dav://connect/PIN e atalhos com ícone Glassmorphism.",
            "Software 100% gratuito sob licença GNU AGPLv3 + Seção 7 NOTICE · Dante Ferraz (MonoTech).",
        ]
        for line in highlights:
            lbl = QLabel(f"•  {line}")
            lbl.setWordWrap(True)
            lbl.setStyleSheet("font-size: 12px; color: #f2fbfb; padding-left: 4px;")
            lay.addWidget(lbl)

        has_nv = False
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            res = subprocess.run(
                ["nvidia-smi"],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=creationflags,
            )
            has_nv = res.returncode == 0
        except Exception:
            has_nv = False

        if has_nv:
            gpu_strip = GlassDiagnosticStrip(
                icon_kind="chip",
                title="Hardware Gráfico: NVIDIA NVENC Detectado",
                subtitle="Codificação H.264 Ultra-Low Latency por GPU dedicada ativa (zero carga na CPU).",
                badge_text="NVENC ATIVO",
                ok=True,
                parent=w,
            )
        else:
            gpu_strip = GlassDiagnosticStrip(
                icon_kind="chip",
                title="Modo Universal: Codificador SIMD Multi-Core",
                subtitle="Pipeline AVX2/SSE4 calibrado para baixa latência e captura Direct3D WGC.",
                badge_text="PRONTO",
                ok=False,
                parent=w,
            )
        lay.addWidget(gpu_strip)
        lay.addStretch(1)
        return w

    def _create_page_options(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        lay.addLayout(
            self._make_page_header(
                "Opções de Integração e Rede",
                "Escolha os recursos do Windows que devem ser configurados automaticamente:",
            )
        )

        self.chk_firewall = QCheckBox("Liberar portas UDP no Windows Defender Firewall (Recomendado)")
        self.chk_firewall.setChecked(True)
        lay.addWidget(
            self._make_option_block(
                self.chk_firewall,
                "Autoriza as faixas UDP 9000-9020, 19000-19010 e o Beacon LAN 9005 para túneis P2P diretos.",
            )
        )

        self.chk_protocol = QCheckBox("Associar links diretos 'dav://' no Registro do usuário")
        self.chk_protocol.setChecked(True)
        lay.addWidget(
            self._make_option_block(
                self.chk_protocol,
                "Permite conectar em sessões do DA-V com 1 clique pelo navegador, Discord ou WhatsApp.",
            )
        )

        self.chk_desktop = QCheckBox("Criar atalhos na Área de Trabalho e no Menu Iniciar")
        self.chk_desktop.setChecked(True)
        lay.addWidget(
            self._make_option_block(
                self.chk_desktop,
                "Instala o atalho oficial com atualização imediata do cache de ícones do Windows Explorer.",
            )
        )

        lay.addStretch(1)
        return w

    def _create_page_progress(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        lay.addLayout(
            self._make_page_header(
                "Instalando e Configurando o DA-V",
                "Aguarde enquanto os binários e integrações são aplicados ao sistema.",
            )
        )

        self.lbl_status = QLabel("Inicializando instalação...")
        self.lbl_status.setStyleSheet("font-size: 13px; font-weight: 600; color: #ffffff;")
        lay.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(14)
        lay.addWidget(self.progress_bar)

        self.step_row_bins = GlassInstallStepRow("Extraindo motor e bibliotecas em AppData\\Local\\Programs\\DA-V...")
        self.step_row_fw = GlassInstallStepRow("Configurando regras UDP no Windows Defender Firewall...")
        self.step_row_proto = GlassInstallStepRow("Registrando protocolo de convite dav://...")
        self.step_row_lnk = GlassInstallStepRow("Criando atalhos na Área de Trabalho e no Menu Iniciar...")

        for row in (self.step_row_bins, self.step_row_fw, self.step_row_proto, self.step_row_lnk):
            lay.addWidget(row)

        lay.addStretch(1)
        return w

    def _finish_description_text(self) -> str:
        return (
            "O DA-V foi instalado e integrado ao Windows com sucesso. O firewall para streaming P2P, "
            "os atalhos e os links dav:// já estão prontos para uso."
        )

    # ── Utilitarios de Sistema e Empacotamento Windows ───────────────────────
    @staticmethod
    def _get_proj_root() -> Path:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
            for cand in (base, base.parent, base.parent.parent):
                if (cand / "DA-V.exe").exists() or (cand / "scripts" / "gui_app.py").exists():
                    return cand
            return base
        return Path(__file__).resolve().parent.parent

    @staticmethod
    def _find_bundled_payload() -> Path | None:
        candidates = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "dav_app_payload.zip")
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "dav_app_payload.zip")
        candidates.append(Path(__file__).resolve().parent.parent / "dist_installer" / "dav_app_payload.zip")
        for c in candidates:
            if c.is_file():
                return c
        return None

    @staticmethod
    def _get_default_install_dir() -> Path:
        local_app = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local_app) / "Programs" / "DA-V"

    @staticmethod
    def _get_python_runtime() -> str:
        if not getattr(sys, "frozen", False):
            cand_same = Path(sys.executable).resolve().with_name("pythonw.exe")
            if cand_same.is_file():
                return str(cand_same)
        local_py = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"
        if local_py.exists():
            for cand in sorted(local_py.glob("Python3*/pythonw.exe"), reverse=True):
                if cand.is_file():
                    return str(cand)
        for cmd in ("pythonw", "pyw", "python"):
            found = shutil.which(cmd)
            if found and "WindowsApps" not in found:
                return found
        return "pythonw"

    @classmethod
    def _resolve_bundled_icon(cls, ext: str = "ico") -> Path | None:
        ext = ext.lstrip(".").lower()
        candidates: list[Path] = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            mp = Path(meipass)
            candidates.extend([mp / "installer" / f"dav_icon.{ext}", mp / f"dav_icon.{ext}"])
        proj_root = cls._get_proj_root()
        candidates.extend([
            proj_root / "installer" / f"dav_icon.{ext}",
            proj_root / f"dav_icon.{ext}",
            proj_root / "design" / "blocks_components" / f"DA-V.icon.{ext}",
        ])
        for c in candidates:
            if c.is_file():
                return c
        return None

    @classmethod
    def _sync_desktop_icon(cls, work_dir: Path) -> Path | None:
        work_dir.mkdir(parents=True, exist_ok=True)
        src_ico = cls._resolve_bundled_icon("ico")
        dst_ico = work_dir / "dav_icon.ico"
        if src_ico and src_ico.is_file():
            if not dst_ico.is_file() or src_ico.resolve() != dst_ico.resolve():
                shutil.copy2(src_ico, dst_ico)
        elif not dst_ico.is_file():
            return None

        src_png = cls._resolve_bundled_icon("png")
        dst_png = work_dir / "dav_icon.png"
        if src_png and src_png.is_file():
            if not dst_png.is_file() or src_png.resolve() != dst_png.resolve():
                shutil.copy2(src_png, dst_png)

        icon_bytes = dst_ico.read_bytes()
        icon_hash = hashlib.sha256(icon_bytes).hexdigest()[:8]
        versioned_ico = work_dir / f"dav_icon_{icon_hash}.ico"
        if not versioned_ico.is_file() or versioned_ico.read_bytes() != icon_bytes:
            shutil.copy2(dst_ico, versioned_ico)

        for old_ico in work_dir.glob("dav_icon_*.ico"):
            if old_ico.name != versioned_ico.name:
                try:
                    old_ico.unlink()
                except Exception:
                    pass
        return versioned_ico

    @staticmethod
    def _refresh_windows_icon_cache(shortcut_paths: list[Path], work_dir: Path) -> None:
        try:
            import ctypes

            shell32 = ctypes.windll.shell32
            SHCNE_UPDATEITEM = 0x00002000
            SHCNE_UPDATEDIR = 0x00001000
            SHCNE_ASSOCCHANGED = 0x08000000
            SHCNF_IDLIST = 0x0000
            SHCNF_PATHW = 0x0005
            for sp in shortcut_paths:
                if sp.exists():
                    shell32.SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW, str(sp), None)
                if sp.parent.exists():
                    shell32.SHChangeNotify(SHCNE_UPDATEDIR, SHCNF_PATHW, str(sp.parent), None)
            if work_dir.exists():
                shell32.SHChangeNotify(SHCNE_UPDATEDIR, SHCNF_PATHW, str(work_dir), None)
            shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
        except Exception:
            pass
        try:
            subprocess.run(
                ["ie4uinit.exe", "-show"],
                capture_output=True,
                creationflags=0x08000000,
                timeout=5,
            )
        except Exception:
            pass

    def _resolve_installed_target(self) -> tuple[Path, str, Path]:
        install_dir = self._get_default_install_dir()
        installed_exe = install_dir / "DA-V.exe"
        if installed_exe.is_file():
            return installed_exe, "", install_dir

        proj_root = self._get_proj_root()
        sibling_exe = proj_root / "DA-V.exe"
        if sibling_exe.is_file():
            return sibling_exe, "", proj_root

        launcher = proj_root / "scripts" / "gui_app.py"
        pyw_exe = Path(self._get_python_runtime())
        return pyw_exe, f'"{launcher}"', proj_root

    def _execute_installation(self) -> None:
        self.progress_bar.setValue(12)
        self.lbl_status.setText("Instalando binários autossuficientes do DA-V...")
        self.step_row_bins.set_status("running", "Extraindo binários do DA-V...")
        QApplication.processEvents()

        payload_zip = self._find_bundled_payload()
        install_dir = self._get_default_install_dir()

        if payload_zip is not None:
            try:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/IM", "DA-V.exe"],
                        capture_output=True,
                        creationflags=0x08000000,
                    )
                    import time as _time

                    _time.sleep(0.4)
                except Exception:
                    pass

                install_dir.mkdir(parents=True, exist_ok=True)
                internal_dir = install_dir / "_internal"
                if internal_dir.exists():
                    shutil.rmtree(internal_dir, ignore_errors=True)

                with zipfile.ZipFile(payload_zip, "r") as zf:
                    members = zf.infolist()
                    total = max(len(members), 1)
                    for idx, m in enumerate(members, 1):
                        zf.extract(m, install_dir)
                        if idx % 25 == 0 or idx == total:
                            pct = 12 + int((idx / total) * 33)
                            self.progress_bar.setValue(min(pct, 45))
                            QApplication.processEvents()

                self.step_row_bins.set_status("ok", f"Aplicação instalada em {install_dir}")
            except Exception as e:
                self.step_row_bins.set_status("warn", f"Falha ao extrair pacote ({e}); usando ambiente local.")
        else:
            proj_root = self._get_proj_root()
            if (proj_root / "DA-V.exe").is_file() or (proj_root / "scripts" / "gui_app.py").is_file():
                self.step_row_bins.set_status("ok", f"Ambiente local validado em {proj_root}")
            else:
                self.step_row_bins.set_status("warn", "Pacote de aplicação não localizado junto ao instalador.")
        QApplication.processEvents()

        # Etapa 2: Firewall
        if self.chk_firewall.isChecked():
            self.progress_bar.setValue(58)
            self.lbl_status.setText("Configurando regras no Windows Defender Firewall...")
            self.step_row_fw.set_status("running", "Aplicando regras de tráfego UDP P2P...")
            QApplication.processEvents()
            try:
                subprocess.run(
                    'netsh advfirewall firewall delete rule name="DA-V Video Streaming"',
                    shell=True,
                    capture_output=True,
                )
                r_fw = subprocess.run(
                    'netsh advfirewall firewall add rule name="DA-V Video Streaming" dir=in action=allow protocol=UDP localport=9000-9020,19000-19010 profile=any',
                    shell=True,
                    capture_output=True,
                )
                subprocess.run(
                    'netsh advfirewall firewall add rule name="DA-V LAN Beacon" dir=in action=allow protocol=UDP localport=9005 profile=any',
                    shell=True,
                    capture_output=True,
                )
                if r_fw.returncode == 0:
                    self.step_row_fw.set_status(
                        "ok",
                        "Portas UDP 9000-9020, 19000-19010 e 9005 liberadas no Firewall.",
                    )
                else:
                    import ctypes

                    fw_cmd = (
                        'netsh advfirewall firewall delete rule name="DA-V Video Streaming" | Out-Null; '
                        'netsh advfirewall firewall add rule name="DA-V Video Streaming" dir=in action=allow protocol=UDP localport=9000-9020,19000-19010 profile=any | Out-Null; '
                        'netsh advfirewall firewall add rule name="DA-V LAN Beacon" dir=in action=allow protocol=UDP localport=9005 profile=any | Out-Null'
                    )
                    ctypes.windll.shell32.ShellExecuteW(
                        None,
                        "runas",
                        "powershell.exe",
                        f'-NoProfile -WindowStyle Hidden -Command "{fw_cmd}"',
                        None,
                        0,
                    )
                    self.step_row_fw.set_status("ok", "Regras UDP solicitadas via Administrador (Windows Firewall).")
            except Exception as e:
                self.step_row_fw.set_status("warn", f"Aviso no Firewall: {e}")
        else:
            self.step_row_fw.set_status("skipped", "Configuração de Firewall ignorada pelo usuário.")
        QApplication.processEvents()

        target_exe, target_args, work_dir = self._resolve_installed_target()
        self._installed_target = (target_exe, target_args, work_dir)
        desktop_icon = self._sync_desktop_icon(work_dir)
        icon_loc = f"{desktop_icon},0" if (desktop_icon and desktop_icon.is_file()) else f"{target_exe},0"

        # Etapa 3: Protocolo dav://
        if self.chk_protocol.isChecked():
            self.progress_bar.setValue(75)
            self.lbl_status.setText("Registrando protocolo 'dav://' no Registro do Windows...")
            self.step_row_proto.set_status("running", "Associando URI dav://...")
            QApplication.processEvents()
            try:
                cmd_str = f'"{target_exe}" {target_args} "%1"' if target_args else f'"{target_exe}" "%1"'
                icon_reg_val = f'"{desktop_icon}",0' if (desktop_icon and desktop_icon.is_file()) else f'"{target_exe}",0'
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\dav") as k:
                    winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:DA-V Protocol")
                    winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
                    with winreg.CreateKey(k, r"DefaultIcon") as dik:
                        winreg.SetValueEx(dik, "", 0, winreg.REG_SZ, icon_reg_val)
                    with winreg.CreateKey(k, r"DisplayIcon") as ik:
                        winreg.SetValueEx(ik, "", 0, winreg.REG_SZ, icon_reg_val)
                    with winreg.CreateKey(k, r"shell\open\command") as sk:
                        winreg.SetValueEx(sk, "", 0, winreg.REG_SZ, cmd_str)
                self.step_row_proto.set_status("ok", "Protocolo 'dav://' associado ao executável instalado.")
            except Exception as e:
                self.step_row_proto.set_status("warn", f"Registro do protocolo: {e}")
        else:
            self.step_row_proto.set_status("skipped", "Registro do protocolo ignorado pelo usuário.")
        QApplication.processEvents()

        # Etapa 4: Atalho na Area de Trabalho e Menu Iniciar
        if self.chk_desktop.isChecked():
            self.progress_bar.setValue(92)
            self.lbl_status.setText("Criando atalhos na Área de Trabalho e Menu Iniciar...")
            self.step_row_lnk.set_status("running", "Atualizando atalhos e cache de ícones...")
            QApplication.processEvents()
            try:
                escaped_args = target_args.replace('"', '`"') if target_args else ""
                ps_cmd = (
                    '$ws = New-Object -ComObject WScript.Shell; '
                    '$desk = $ws.SpecialFolders("Desktop"); '
                    '$smenu = $ws.SpecialFolders("Programs"); '
                    'foreach ($dir in @($desk, $smenu)) { '
                    '  if ($dir -and (Test-Path $dir)) { '
                    '    $lnk = Join-Path $dir "DA-V.lnk"; '
                    '    if (Test-Path $lnk) { Remove-Item $lnk -Force -ErrorAction SilentlyContinue }; '
                    '    $s = $ws.CreateShortcut($lnk); '
                    f'    $s.TargetPath = "{target_exe}"; '
                    f'    $s.Arguments = "{escaped_args}"; '
                    f'    $s.WorkingDirectory = "{work_dir}"; '
                    f'    $s.IconLocation = "{icon_loc}"; '
                    '    $s.Description = "DA-V - Distribuidor Amplo de Vídeo (60 FPS P2P & Área Remota)"; '
                    '    $s.Save(); '
                    '    Write-Output $lnk '
                    '  } '
                    '}'
                )
                res_lnk = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                    capture_output=True,
                    text=True,
                    check=True,
                    creationflags=0x08000000,
                )
                created_shortcuts = [
                    Path(line.strip())
                    for line in (res_lnk.stdout or "").splitlines()
                    if line.strip()
                ]
                self._refresh_windows_icon_cache(created_shortcuts, work_dir)
                self.step_row_lnk.set_status(
                    "ok",
                    "Atalhos criados na Área de Trabalho e no Menu Iniciar (ícone atualizado).",
                )
            except Exception as e:
                self.step_row_lnk.set_status("warn", f"Atalho: {e}")
        else:
            self.step_row_lnk.set_status("skipped", "Criação de atalhos ignorada pelo usuário.")
        QApplication.processEvents()

        self.progress_bar.setValue(100)
        self.lbl_status.setText("Instalação concluída com sucesso.")
        QApplication.processEvents()
        QTimer.singleShot(650, self._advance_to_finish)

    def _launch_app(self) -> None:
        try:
            target_exe, target_args, work_dir = getattr(
                self, "_installed_target", self._resolve_installed_target()
            )
            cmd = [str(target_exe)]
            if target_args:
                cmd.append(target_args.strip('"'))
            subprocess.Popen(cmd, cwd=str(work_dir), shell=False)
        except Exception as e:
            print(f"Erro ao abrir DA-V: {e}")


def main():
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MonoTech.DAV.Installer")
        except Exception:
            pass
    app = QApplication(sys.argv)
    from src.ui.glass.qss import apply_glass_app_theme

    apply_glass_app_theme(app)
    installer = DavModernInstaller()
    try:
        from PySide6.QtGui import QIcon

        for ext in ("ico", "png"):
            ic_path = DavModernInstaller._resolve_bundled_icon(ext)
            if ic_path and ic_path.is_file():
                ic = QIcon(str(ic_path))
                app.setWindowIcon(ic)
                installer.setWindowIcon(ic)
                break
    except Exception:
        pass
    installer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
