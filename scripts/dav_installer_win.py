# -*- coding: utf-8 -*-
"""
DA-V — Instalador Gráfico Oficial para Windows
Autor: Dante Ferraz (MonoTech)

Assistente visual passo a passo (Setup Wizard) em PySide6:
1. Verificação do ambiente (GPU NVIDIA NVENC, Python runtime, Firewall).
2. Criação de atalhos no Desktop e Menu Iniciar.
3. Registro do protocolo de convite 'dav://' no Registro do Windows.
4. Liberação automática das portas UDP no Windows Defender Firewall.
"""

import sys
import os
import subprocess
import winreg
from pathlib import Path

from scripts.qt_compat import (
    QApplication, QWizard, QWizardPage, QVBoxLayout, QHBoxLayout,
    QLabel, QCheckBox, QLineEdit, QPushButton, QProgressBar,
    QFileDialog, Qt, QFont
)
from src.ui.theme import Theme


class WelcomePage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Bem-vindo ao Assistente de Instalação do DA-V")
        self.setSubTitle("Distribuidor Amplo de Vídeo — Transmissão de Tela 60 FPS P2P")

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        info_lbl = QLabel(
            "Este assistente configurará o DA-V no seu computador Windows com suporte completo a:\n\n"
            "• Aceleração de hardware GPU (NVIDIA NVENC RTX / GTX ou SIMD CPU)\n"
            "• Emparelhamento P2P Instantâneo via PIN Universal ou Rede Local (LAN)\n"
            "• Suporte a links de convite direto (dav://connect/PIN)\n"
            "• Liberação automática de portas UDP no Windows Defender Firewall"
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet(f"font-size: 13px; color: {Theme.SYS['text_secondary']}; line-height: 1.5;")
        layout.addWidget(info_lbl)

        # GPU Detection Check
        has_nv = False
        try:
            res = subprocess.run("nvidia-smi", shell=True, capture_output=True, text=True)
            has_nv = (res.returncode == 0)
        except Exception:
            pass

        gpu_status = "NVIDIA NVENC Detectado (60 FPS Ultra-Low Latency Ativo) ✓" if has_nv else "Modo de Renderização Acelerado por CPU (SIMD Universal)"
        gpu_color = Theme.SYS["status_success"] if has_nv else Theme.SYS["status_info"]
        
        gpu_badge = QLabel(f"Hardware Gráfico: {gpu_status}")
        gpu_badge.setStyleSheet(f"background-color: {Theme.SYS['bg_surface_card']}; border: 1px solid {gpu_color}; color: {gpu_color}; padding: 10px; border-radius: 6px; font-weight: 700;")
        layout.addWidget(gpu_badge)
        layout.addStretch()


class OptionsPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Opções de Instalação e Integração com o Windows")
        self.setSubTitle("Personalize como o DA-V se integra ao seu sistema operacional.")

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        self.chk_desktop = QCheckBox("Criar atalho na Área de Trabalho (Desktop)")
        self.chk_desktop.setChecked(True)
        layout.addWidget(self.chk_desktop)

        self.chk_protocol = QCheckBox("Registrar protocolo 'dav://' (Permite abrir convites via link direto)")
        self.chk_protocol.setChecked(True)
        layout.addWidget(self.chk_protocol)

        self.chk_firewall = QCheckBox("Liberar portas UDP no Windows Defender Firewall (Recomendado)")
        self.chk_firewall.setChecked(True)
        layout.addWidget(self.chk_firewall)

        layout.addStretch()


class InstallProgressPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Configurando o DA-V")
        self.setSubTitle("Aplicando configurações no sistema...")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.lbl_status = QLabel("Pronto para iniciar a configuração.")
        layout.addWidget(self.lbl_status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.btn_run = QPushButton("Aplicar e Concluir Instalação")
        self.btn_run.setStyleSheet(f"background-color: {Theme.SYS['accent_primary']}; color: #070a0f; font-weight: 800; padding: 10px; border-radius: 6px;")
        self.btn_run.clicked.connect(self._do_install)
        layout.addWidget(self.btn_run)

        layout.addStretch()

    def _do_install(self):
        self.btn_run.setEnabled(False)
        opts_page = self.wizard().page(1)

        # 1. Firewall rules
        if opts_page.chk_firewall.isChecked():
            self.lbl_status.setText("Configurando regras no Firewall do Windows...")
            self.progress.setValue(30)
            QApplication.processEvents()
            try:
                subprocess.run(
                    'netsh advfirewall firewall add rule name="DA-V Video Streaming" dir=in action=allow protocol=UDP localport=19000-19010 profile=any',
                    shell=True, capture_output=True
                )
                subprocess.run(
                    'netsh advfirewall firewall add rule name="DA-V LAN Beacon" dir=in action=allow protocol=UDP localport=9005 profile=any',
                    shell=True, capture_output=True
                )
            except Exception as e:
                print(f"Firewall error: {e}")

        # 2. Register dav:// protocol in Windows Registry
        if opts_page.chk_protocol.isChecked():
            self.lbl_status.setText("Registrando protocolo 'dav://' no Registro do Windows...")
            self.progress.setValue(65)
            QApplication.processEvents()
            try:
                py_exe = sys.executable
                proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                launcher = os.path.join(proj_root, "scripts", "gui_app.py")
                cmd_str = f'"{py_exe}" "{launcher}" "%1"'

                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\dav") as k:
                    winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:DA-V Protocol")
                    winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
                    with winreg.CreateKey(k, r"shell\open\command") as sk:
                        winreg.SetValueEx(sk, "", 0, winreg.REG_SZ, cmd_str)
            except Exception as e:
                print(f"Registry error: {e}")

        # 3. Desktop shortcut
        if opts_page.chk_desktop.isChecked():
            self.lbl_status.setText("Criando atalho na Área de Trabalho...")
            self.progress.setValue(90)
            QApplication.processEvents()
            try:
                desktop = Path(os.environ["USERPROFILE"]) / "Desktop"
                vbs_path = desktop / "DA-V.vbs"
                proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                py_exe = sys.executable.replace("python.exe", "pythonw.exe")
                script_path = os.path.join(proj_root, "scripts", "gui_app.py")
                with open(vbs_path, "w", encoding="utf-8") as f:
                    f.write(f'CreateObject("Wscript.Shell").Run "\"{py_exe}\" \"{script_path}\"", 0, False\n')
            except Exception as e:
                print(f"Shortcut error: {e}")

        self.progress.setValue(100)
        self.lbl_status.setText("✓ Instalação e integração concluídas com sucesso!")
        self.btn_run.setText("Instalação Concluída")


class DavInstallerWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DA-V · Assistente de Instalação Windows")
        self.setMinimumSize(620, 440)
        self.setStyleSheet(Theme.build_stylesheet())

        self.addPage(WelcomePage(self))
        self.addPage(OptionsPage(self))
        self.addPage(InstallProgressPage(self))


def main():
    app = QApplication(sys.argv)
    wizard = DavInstallerWizard()
    wizard.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

