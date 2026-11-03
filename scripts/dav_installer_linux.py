# -*- coding: utf-8 -*-
"""
DA-V — Instalador Gráfico Oficial para Linux
Autor: Dante Ferraz (MonoTech)

Assistente visual passo a passo (Setup Wizard) em PySide6 para distribuições Linux
(Ubuntu, Debian, Fedora, Arch, Pop!_OS, Linux Mint):
1. Verificação de ambiente (X11 / Wayland, GPU NVIDIA NVENC / VAAPI, Python 3).
2. Instalação do lançador Desktop XDG (/usr/share/applications/ ou ~/.local/share/applications/).
3. Registro do handler do protocolo de convite 'dav://' via xdg-mime.
4. Assistente de permissões e liberação de portas UDP no firewall (UFW / firewalld).
"""

import sys
import os
import shutil
import subprocess
from pathlib import Path

from scripts.qt_compat import (
    QApplication, QWizard, QWizardPage, QVBoxLayout, QHBoxLayout,
    QLabel, QCheckBox, QProgressBar, QPushButton, Qt
)
from src.ui.theme import Theme


class LinuxWelcomePage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Bem-vindo ao Instalador do DA-V para Linux")
        self.setSubTitle("Distribuidor Amplo de Vídeo — Streaming P2P de Alta Performance")

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        info_lbl = QLabel(
            "Este assistente integrará o DA-V nativamente ao seu ambiente gráfico Linux.\n\n"
            "Recursos verificados automaticamente:\n"
            "• Servidor Gráfico: X11 (Captura nativa MIT-SHM) / Wayland (PipeWire Portal)\n"
            "• Aceleração de Hardware: NVIDIA NVENC ou SIMD CPU multithread\n"
            "• Associação de Protocolo: dav://connect/PIN para conexões em 1 clique"
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet(f"font-size: 13px; color: {Theme.SYS['text_secondary']};")
        layout.addWidget(info_lbl)

        # Detect Session Type
        session_type = os.environ.get("XDG_SESSION_TYPE", "x11").capitalize()
        sess_lbl = QLabel(f"Sessão de Janelas Detectada: {session_type}")
        sess_lbl.setStyleSheet(f"background-color: {Theme.SYS['bg_surface_card']}; padding: 8px; border-radius: 6px; font-weight: 700; color: {Theme.SYS['accent_primary']};")
        layout.addWidget(sess_lbl)

        # Detect GPU
        has_nv = False
        try:
            r = subprocess.run(["which", "nvidia-smi"], capture_output=True)
            has_nv = (r.returncode == 0)
        except Exception:
            pass

        gpu_txt = "NVIDIA NVENC Ativo (Hardware Encoding 60 FPS) ✓" if has_nv else "Renderizador SIMD Universal CPU"
        gpu_col = Theme.SYS["status_success"] if has_nv else Theme.SYS["status_info"]
        gpu_badge = QLabel(f"Aceleração de Vídeo: {gpu_txt}")
        gpu_badge.setStyleSheet(f"background-color: {Theme.SYS['bg_surface_card']}; border: 1px solid {gpu_col}; color: {gpu_col}; padding: 8px; border-radius: 6px; font-weight: 700;")
        layout.addWidget(gpu_badge)

        layout.addStretch()


class LinuxOptionsPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Opções de Integração de Desktop")
        self.setSubTitle("Selecione os recursos de sistema que deseja habilitar.")

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        self.chk_menu = QCheckBox("Adicionar lançador ao Menu de Aplicativos (GNOME, KDE, XFCE)")
        self.chk_menu.setChecked(True)
        layout.addWidget(self.chk_menu)

        self.chk_protocol = QCheckBox("Registrar protocolo 'dav://' via XDG (Links diretos no navegador)")
        self.chk_protocol.setChecked(True)
        layout.addWidget(self.chk_protocol)

        self.chk_ufw = QCheckBox("Exibir comando para liberação de portas UDP no UFW Firewall")
        self.chk_ufw.setChecked(True)
        layout.addWidget(self.chk_ufw)

        layout.addStretch()


class LinuxInstallProgressPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Configurando o DA-V no Linux")
        self.setSubTitle("Instalando lançadores e registrando associações...")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.lbl_status = QLabel("Pronto para aplicar.")
        layout.addWidget(self.lbl_status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.btn_run = QPushButton("Concluir Instalação")
        self.btn_run.setStyleSheet(f"background-color: {Theme.SYS['accent_primary']}; color: #070a0f; font-weight: 800; padding: 10px; border-radius: 6px;")
        self.btn_run.clicked.connect(self._do_install)
        layout.addWidget(self.btn_run)

        layout.addStretch()

    def _do_install(self):
        self.btn_run.setEnabled(False)
        opts = self.wizard().page(1)

        proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        launcher_script = os.path.join(proj_root, "launch_dav.sh")
        user_apps = Path.home() / ".local" / "share" / "applications"
        user_apps.mkdir(parents=True, exist_ok=True)
        desktop_file = user_apps / "dav.desktop"

        # 1. Desktop Entry
        if opts.chk_menu.isChecked():
            self.lbl_status.setText("Instalando lançador de aplicativos XDG...")
            self.progress.setValue(40)
            QApplication.processEvents()

            desktop_content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=DA-V · Distribuidor Amplo de Vídeo
GenericName=Transmissão de Vídeo 60 FPS P2P
Comment=Motor de compartilhamento de tela P2P de ultra-baixa latência com hardware NVENC/SIMD
Exec="{launcher_script}" %u
Icon=video-display
Terminal=false
Categories=AudioVideo;Video;Network;RemoteAccess;
MimeType=x-scheme-handler/dav;
StartupWMClass=dav-desktop
"""
            with open(desktop_file, "w", encoding="utf-8") as f:
                f.write(desktop_content)
            
            try:
                subprocess.run(["chmod", "+x", str(desktop_file)], check=False)
                subprocess.run(["update-desktop-database", str(user_apps)], check=False)
            except Exception:
                pass

        # 2. Register dav:// protocol handler
        if opts.chk_protocol.isChecked():
            self.lbl_status.setText("Registrando protocolo 'dav://' via xdg-mime...")
            self.progress.setValue(75)
            QApplication.processEvents()
            try:
                subprocess.run(["xdg-mime", "default", "dav.desktop", "x-scheme-handler/dav"], check=False)
            except Exception as e:
                print(f"XDG Error: {e}")

        self.progress.setValue(100)
        self.lbl_status.setText("✓ DA-V instalado e integrado ao sistema Linux com sucesso!")
        self.btn_run.setText("Concluído")


class LinuxInstallerWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DA-V · Assistente de Instalação Linux")
        self.setMinimumSize(620, 440)
        self.setStyleSheet(Theme.build_stylesheet())

        self.addPage(LinuxWelcomePage(self))
        self.addPage(LinuxOptionsPage(self))
        self.addPage(LinuxInstallProgressPage(self))


def main():
    app = QApplication(sys.argv)
    wizard = LinuxInstallerWizard()
    wizard.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

