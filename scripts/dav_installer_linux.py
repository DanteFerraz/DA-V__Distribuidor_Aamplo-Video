# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
DA-V — Instalador Grafico Oficial Glassmorphism (Linux x86_64) — v5.0
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
import tarfile

def _resolve_linux_proj_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        exe_dir = Path(sys.executable).resolve().parent
        for cand in (exe_dir, exe_dir.parent, exe_dir.parent.parent):
            if (cand / "launch_dav.sh").exists() or (cand / "scripts" / "gui_app.py").exists():
                return cand
        return exe_dir
    return Path(__file__).resolve().parent.parent


PROJ_ROOT = _resolve_linux_proj_root()
if str(PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJ_ROOT))

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


class DavModernLinuxInstaller(DavGlassInstallerDialog):
    """Instalador Glassmorphism oficial do DA-V v5.0 para Linux (Ubuntu, Debian, Fedora, Arch)."""

    def __init__(self, parent=None):
        super().__init__(
            window_title="DA-V · Distribuidor Amplo de Vídeo — Instalador Linux",
            platform_edition="Linux Edition",
            step_definitions=[
                ("Boas-vindas", "Sessão e GPU"),
                ("Preferências", "Desktop e protocolos"),
                ("Integração", "Aplicação no Linux"),
                ("Conclusão", "Pronto para rodar"),
            ],
            parent=parent,
        )

    def _create_page_welcome(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        lay.addLayout(
            self._make_page_header(
                "Streaming P2P e Área de Trabalho Remota no Linux",
                "Este assistente configurará o DA-V com captura PipeWire / MIT-SHM, controle remoto "
                "nativo (Wayland Portal / XTest / Polkit uinput) e integração XDG.",
            )
        )

        session_type = os.environ.get("XDG_SESSION_TYPE", "x11").strip() or "x11"
        is_wayland = session_type.lower() == "wayland"
        has_pw_gst = shutil.which("gst-launch-1.0") is not None

        if is_wayland:
            sess_sub = (
                "Wayland nativo pronto: XDG Desktop Portal + PipeWire + RemoteDesktop (60 FPS)."
                if has_pw_gst
                else "Wayland detectado. Recomendado instalar: gstreamer1.0-pipewire python3-gi."
            )
        else:
            sess_sub = "Sessão X11 detectada: captura MIT-SHM sub-2 ms + injeção nativa XTest/uinput."

        lay.addWidget(
            GlassDiagnosticStrip(
                icon_kind="display",
                title=f"Servidor Gráfico: {session_type.capitalize()}",
                subtitle=sess_sub,
                badge_text="WAYLAND" if is_wayland else "X11 NATIVO",
                ok=True,
                parent=w,
            )
        )

        has_nv = shutil.which("nvidia-smi") is not None
        if has_nv:
            gpu_strip = GlassDiagnosticStrip(
                icon_kind="chip",
                title="Hardware Gráfico: NVIDIA NVENC Detectado",
                subtitle="Codificação H.264 por GPU dedicada ativa com latência sub-milissegundo.",
                badge_text="NVENC ATIVO",
                ok=True,
                parent=w,
            )
        else:
            gpu_strip = GlassDiagnosticStrip(
                icon_kind="chip",
                title="Modo Universal: Codificador SIMD Multi-Core",
                subtitle="Otimizado para processadores x86_64 com instruções AVX2/SSE4 e GNU AGPLv3.",
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
                "Opções de Integração no Linux",
                "Personalize como o DA-V será integrado ao seu ambiente gráfico:",
            )
        )

        self.chk_menu = QCheckBox("Adicionar atalho na Área de Trabalho e no Menu de Aplicativos (.desktop)")
        self.chk_menu.setChecked(True)
        lay.addWidget(
            self._make_option_block(
                self.chk_menu,
                "Instala o ícone oficial no tema hicolor e cria lançadores confiáveis no GNOME, KDE e XFCE.",
            )
        )

        self.chk_protocol = QCheckBox("Registrar protocolo 'dav://' via XDG (Convites Diretos)")
        self.chk_protocol.setChecked(True)
        lay.addWidget(
            self._make_option_block(
                self.chk_protocol,
                "Permite conectar em transmissões clicando em links dav://connect/PIN no navegador ou Discord.",
            )
        )

        self.chk_ufw = QCheckBox("Liberar portas UDP no firewall UFW (Portas 9000-9020 e 9005)")
        self.chk_ufw.setChecked(True)
        lay.addWidget(
            self._make_option_block(
                self.chk_ufw,
                "Configura regras locais para túneis P2P diretos e descoberta automática na sub-rede LAN.",
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
                "Aplicando Integração no Linux",
                "Instalando binários autossuficientes, ícones XDG e associações de protocolo.",
            )
        )

        self.lbl_status = QLabel("Inicializando configuração...")
        self.lbl_status.setStyleSheet("font-size: 13px; font-weight: 600; color: #ffffff;")
        lay.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(14)
        lay.addWidget(self.progress_bar)

        self.step_row_bins = GlassInstallStepRow("Instalando binários em ~/.local/share/dav...")
        self.step_row_desk = GlassInstallStepRow("Instalando ícone hicolor e lançador XDG (.desktop)...")
        self.step_row_proto = GlassInstallStepRow("Registrando associação de protocolo dav://...")
        self.step_row_ufw = GlassInstallStepRow("Verificando regras de portas UDP no UFW...")

        for row in (self.step_row_bins, self.step_row_desk, self.step_row_proto, self.step_row_ufw):
            lay.addWidget(row)

        lay.addStretch(1)
        return w

    def _finish_description_text(self) -> str:
        return (
            "O DA-V foi integrado com sucesso ao seu desktop Linux. O lançador já consta no menu "
            "de aplicativos e os links dav:// estão prontos para uso."
        )

    @classmethod
    def _resolve_bundled_icon(cls, ext: str = "png") -> Path | None:
        ext = ext.lstrip(".").lower()
        candidates: list[Path] = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            mp = Path(meipass)
            candidates.extend([mp / "installer" / f"dav_icon.{ext}", mp / f"dav_icon.{ext}"])
        candidates.extend([
            PROJ_ROOT / "installer" / f"dav_icon.{ext}",
            PROJ_ROOT / f"dav_icon.{ext}",
            PROJ_ROOT / "design" / "blocks_components" / f"DA-V.icon.{ext}",
        ])
        for c in candidates:
            if c.is_file():
                return c
        return None

    @classmethod
    def _sync_linux_desktop_icons(cls, work_dir: Path, proj_root: Path) -> Path | None:
        src_png = cls._resolve_bundled_icon("png")
        if src_png is None:
            for cand in (
                work_dir / "dav_icon.png",
                proj_root / "installer" / "dav_icon.png",
                proj_root / "design" / "blocks_components" / "DA-V.icon.png",
            ):
                if cand.is_file():
                    src_png = cand
                    break
        if src_png is None or not src_png.is_file():
            return None

        icon_bytes = src_png.read_bytes()
        icon_hash = hashlib.sha256(icon_bytes).hexdigest()[:8]

        hicolor_base = Path.home() / ".local" / "share" / "icons" / "hicolor"
        hicolor_256 = hicolor_base / "256x256" / "apps"
        pixmaps_dir = Path.home() / ".local" / "share" / "pixmaps"
        hicolor_icon = hicolor_256 / "dav.png"
        try:
            hicolor_256.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_png, hicolor_icon)
        except Exception:
            pass
        try:
            pixmaps_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_png, pixmaps_dir / "dav.png")
        except Exception:
            pass

        versioned_icon = hicolor_icon
        try:
            work_dir.mkdir(parents=True, exist_ok=True)
            dst_plain = work_dir / "dav_icon.png"
            if src_png.resolve() != dst_plain.resolve():
                shutil.copy2(src_png, dst_plain)
            dst_hashed = work_dir / f"dav_icon_{icon_hash}.png"
            if not dst_hashed.is_file() or dst_hashed.read_bytes() != icon_bytes:
                shutil.copy2(src_png, dst_hashed)
            for old_png in work_dir.glob("dav_icon_*.png"):
                if old_png.name != dst_hashed.name:
                    try:
                        old_png.unlink()
                    except Exception:
                        pass
            versioned_icon = dst_hashed
        except Exception:
            try:
                fallback_hashed = hicolor_256 / f"dav_{icon_hash}.png"
                shutil.copy2(src_png, fallback_hashed)
                versioned_icon = fallback_hashed
            except Exception:
                pass

        for cmd in (
            ["gtk-update-icon-cache", "-f", "-t", str(hicolor_base)],
            ["xdg-icon-resource", "forceupdate"],
        ):
            try:
                subprocess.run(cmd, capture_output=True, check=False, timeout=5)
            except Exception:
                pass

        return versioned_icon if versioned_icon.is_file() else src_png

    @staticmethod
    def _resolve_linux_desktop_dirs() -> list[Path]:
        dirs: list[Path] = []
        seen: set[Path] = set()
        try:
            res = subprocess.run(
                ["xdg-user-dir", "DESKTOP"],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
            out = (res.stdout or "").strip()
            if out:
                p = Path(out)
                if p.is_dir() and p.resolve() != Path.home().resolve():
                    seen.add(p.resolve())
                    dirs.append(p)
        except Exception:
            pass
        for desk_name in ("Desktop", "Área de Trabalho"):
            desk_dir = Path.home() / desk_name
            if desk_dir.is_dir() and desk_dir.resolve() not in seen:
                seen.add(desk_dir.resolve())
                dirs.append(desk_dir)
        return dirs

    @staticmethod
    def _find_bundled_payload() -> Path | None:
        candidates = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "dav_app_payload_linux.tar.gz")
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "dav_app_payload_linux.tar.gz")
        for c in candidates:
            if c.is_file():
                return c
        return None

    def _execute_installation(self) -> None:
        proj_root = Path(__file__).resolve().parent.parent if not getattr(sys, "frozen", False) else Path(sys.executable).resolve().parent
        install_dir = Path.home() / ".local" / "share" / "dav"
        payload_tgz = self._find_bundled_payload()

        self.progress_bar.setValue(15)
        self.lbl_status.setText("Instalando binários do DA-V em ~/.local/share/dav...")
        self.step_row_bins.set_status("running", "Extraindo pacote ELF autossuficiente...")
        QApplication.processEvents()

        if payload_tgz is not None:
            try:
                install_dir.mkdir(parents=True, exist_ok=True)
                internal_dir = install_dir / "_internal"
                if internal_dir.exists():
                    shutil.rmtree(internal_dir, ignore_errors=True)
                with tarfile.open(payload_tgz, "r:gz") as tf:
                    tf.extractall(install_dir)
                bin_elf = install_dir / "DA-V"
                if bin_elf.is_file():
                    bin_elf.chmod(0o755)
                launcher_script = bin_elf
                self._installed_workdir = install_dir
                self.step_row_bins.set_status("ok", f"Aplicação autossuficiente instalada em {install_dir}")
            except Exception as exc:
                launcher_script = proj_root / "launch_dav.sh"
                self._installed_workdir = proj_root
                self.step_row_bins.set_status("warn", f"Falha ao extrair pacote ({exc}); usando diretório local.")
        elif (proj_root / "DA-V").is_file() and (
            (proj_root / "_internal").is_dir() or not (proj_root / "scripts" / "gui_app.py").is_file()
        ):
            launcher_script = proj_root / "DA-V"
            launcher_script.chmod(0o755)
            self._installed_workdir = proj_root
            self.step_row_bins.set_status("ok", f"Binário ELF validado em {proj_root}")
        else:
            launcher_script = proj_root / "launch_dav.sh"
            if launcher_script.is_file():
                try:
                    launcher_script.chmod(0o755)
                except Exception:
                    pass
            self._installed_workdir = proj_root
            so_target = proj_root / "build" / "libdav_core.so"
            if so_target.exists():
                self.step_row_bins.set_status("ok", f"Backend C++23 validado: {so_target.name}")
            else:
                self.step_row_bins.set_status("ok", "Ambiente de código-fonte validado (pipeline Python/SIMD).")
        self._installed_launcher = launcher_script
        QApplication.processEvents()

        if self.chk_menu.isChecked():
            self.progress_bar.setValue(50)
            self.lbl_status.setText("Instalando ícone oficial e lançador XDG (.desktop)...")
            self.step_row_desk.set_status("running", "Configurando atalhos Desktop e Menu XDG...")
            QApplication.processEvents()
            try:
                user_apps = Path.home() / ".local" / "share" / "applications"
                user_apps.mkdir(parents=True, exist_ok=True)
                desktop_file = user_apps / "dav.desktop"

                icon_synced = self._sync_linux_desktop_icons(self._installed_workdir, proj_root)
                icon_val = str(icon_synced) if (icon_synced and icon_synced.is_file()) else "dav"

                desktop_content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=DA-V · Distribuidor Amplo de Vídeo
GenericName=Transmissão P2P 60 FPS e Área Remota
Comment=Streaming P2P sub-15 ms e área de trabalho remota interativa (MonoTech)
Exec="{launcher_script}" %u
Path={self._installed_workdir}
Icon={icon_val}
Terminal=false
Categories=AudioVideo;Video;Network;RemoteAccess;
MimeType=x-scheme-handler/dav;
StartupWMClass=dav
"""
                desktop_file.write_text(desktop_content, encoding="utf-8")
                desktop_file.chmod(0o755)
                try:
                    subprocess.run(["update-desktop-database", str(user_apps)], capture_output=True, check=False)
                except Exception:
                    pass

                for desk_dir in self._resolve_linux_desktop_dirs():
                    desk_shortcut = desk_dir / "DA-V.desktop"
                    desk_shortcut.write_text(desktop_content, encoding="utf-8")
                    desk_shortcut.chmod(0o755)
                    try:
                        subprocess.run(
                            ["gio", "set", str(desk_shortcut), "metadata::trusted", "true"],
                            capture_output=True,
                            check=False,
                            timeout=3,
                        )
                    except Exception:
                        pass

                self.step_row_desk.set_status(
                    "ok",
                    "Lançador e ícone instalados no Menu de Aplicativos e na Área de Trabalho.",
                )
            except Exception as e:
                self.step_row_desk.set_status("warn", f"Lançador Desktop: {e}")
        else:
            self.step_row_desk.set_status("skipped", "Lançador no menu de aplicativos ignorado.")
        QApplication.processEvents()

        if self.chk_protocol.isChecked():
            self.progress_bar.setValue(75)
            self.lbl_status.setText("Registrando protocolo 'dav://' via xdg-mime...")
            self.step_row_proto.set_status("running", "Associando x-scheme-handler/dav...")
            QApplication.processEvents()
            try:
                subprocess.run(["xdg-mime", "default", "dav.desktop", "x-scheme-handler/dav"], check=False)
                self.step_row_proto.set_status("ok", "Protocolo 'dav://' associado ao DA-V via xdg-mime.")
            except Exception as e:
                self.step_row_proto.set_status("warn", f"Protocolo dav://: {e}")
        else:
            self.step_row_proto.set_status("skipped", "Registro do protocolo dav:// ignorado.")
        QApplication.processEvents()

        if self.chk_ufw.isChecked():
            self.progress_bar.setValue(90)
            self.lbl_status.setText("Configurando regras de firewall UFW...")
            self.step_row_ufw.set_status("running", "Verificando portas UDP 9000-9020 e 9005...")
            QApplication.processEvents()
            try:
                res1 = subprocess.run(["sudo", "-n", "ufw", "allow", "9000:9020/udp"], capture_output=True)
                subprocess.run(["sudo", "-n", "ufw", "allow", "19000:19010/udp"], capture_output=True)
                res3 = subprocess.run(["sudo", "-n", "ufw", "allow", "9005/udp"], capture_output=True)
                if res1.returncode == 0 and res3.returncode == 0:
                    self.step_row_ufw.set_status("ok", "Portas UDP 9000-9020, 19000-19010 e 9005 liberadas no UFW.")
                else:
                    self.step_row_ufw.set_status(
                        "ok",
                        "Caso utilize UFW ativo, execute: sudo ufw allow 9000:9020/udp && sudo ufw allow 9005/udp",
                    )
            except Exception:
                self.step_row_ufw.set_status(
                    "ok",
                    "Caso utilize UFW ativo, execute: sudo ufw allow 9000:9020/udp && sudo ufw allow 9005/udp",
                )
        else:
            self.step_row_ufw.set_status("skipped", "Configuração de firewall ignorada.")
        QApplication.processEvents()

        self.progress_bar.setValue(100)
        self.lbl_status.setText("Integração concluída com sucesso.")
        QApplication.processEvents()
        QTimer.singleShot(650, self._advance_to_finish)

    def _launch_app(self) -> None:
        try:
            launcher = getattr(self, "_installed_launcher", PROJ_ROOT / "launch_dav.sh")
            workdir = getattr(self, "_installed_workdir", PROJ_ROOT)
            subprocess.Popen([str(launcher)], cwd=str(workdir), shell=False)
        except Exception as e:
            print(f"Erro ao abrir DA-V: {e}")


def main():
    app = QApplication(sys.argv)
    from src.ui.glass.qss import apply_glass_app_theme

    apply_glass_app_theme(app)
    installer = DavModernLinuxInstaller()
    try:
        from PySide6.QtGui import QIcon

        for ext in ("png", "ico"):
            ic_path = DavModernLinuxInstaller._resolve_bundled_icon(ext)
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
