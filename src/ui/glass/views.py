# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
DA-V Glass Design System - Focal Views
Autor: Dante Ferraz (MonoTech)

As tres telas principais do visual "vidro":
- ViewerIdlePage: Modo Espectador aguardando chave de acesso (PIN, link dav:// ou IPv4[:porta])
- ViewerConnectingPage: Modo Espectador conectando ate a chegada do primeiro quadro de video
- SenderHomePage: Modo Transmissor com copia rapida de chave e inicio/parada da transmissao
"""

from __future__ import annotations

import ipaddress
import re
import urllib.parse
from typing import Optional, Tuple

from src.ui.qt_compat import Qt, QTimer, Signal
from src.dav.modules.transport_p2p.blind_relay import normalize_pin
from src.dav.modules.transport_p2p.dualstack import canonicalize_ip, is_valid_ip, parse_host_port
from src.ui.glass import tokens as T
from src.ui.glass.widgets import (
    CardPage,
    GlassButton,
    GlassLabel,
    GlassLineEdit,
    GlassSpacer,
    GlassToggleSwitch,
)

_IPV4_PORT_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?$")
_HOST_PORT_RE = re.compile(r"^([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(?::(\d{1,5}))?$")


def parse_access_input(raw: str) -> Tuple[str, Optional[int], str]:
    """Interpreta uma chave de acesso unica digitada pelo usuario.

    Aceita:
    - PIN numerico P2P (ex: '300-631', '300631')
    - URI 'dav://connect/300-631' ou 'dav://300-631'
    - URI Direta IPv6/IPv4 + PIN: 'dav://[2804:3690::1]:9000/300-631' ou '?pin=300-631'
    - IPv6 direto ou [IPv6]:porta (ex: '2804:3690::1', '[2804:3690::1]:9000', '::1')
    - IPv4 direto ou IPv4:porta (ex: '192.168.1.25' ou '192.168.1.25:9000')
    - Hostname[:porta] com registros A ou AAAA (ex: 'pc-sala.local:9000')

    Retorna `(target_ip, target_port, pin)`.
    """
    text = (raw or "").strip()
    if not text:
        return ("", None, "")

    lower = text.lower()
    if lower.startswith("dav://"):
        body = text[6:].strip().strip("/")
        if body.lower().startswith("connect/"):
            body = body[8:].strip("/")

        # Suporta query opcional ?pin=XXX e sufixo /PIN apos host:porta (ex: dav://[2804:...]:9000/423-391)
        pin_from_uri = ""
        if "?" in body:
            body, qs = body.split("?", 1)
            qmap = urllib.parse.parse_qs(qs)
            if "pin" in qmap and qmap["pin"]:
                pin_from_uri = normalize_pin(qmap["pin"][0])
        if "/" in body:
            host_seg, tail_seg = body.split("/", 1)
            if not pin_from_uri and tail_seg.strip():
                pin_from_uri = normalize_pin(tail_seg.strip().strip("/"))
            body = host_seg.strip()

        host_u, port_u = parse_host_port(body)
        if host_u and (is_valid_ip(host_u) or "." in host_u):
            return (canonicalize_ip(host_u) if is_valid_ip(host_u) else host_u, port_u, pin_from_uri)

        pin = pin_from_uri or normalize_pin(body)
        return ("", None, pin or body)

    # 1. IPv6 com colchetes `[2804:...]:9000` ou `[2804:...]`
    if text.startswith("["):
        ip_u, port_u = parse_host_port(text)
        if ip_u and is_valid_ip(ip_u):
            return (ip_u, port_u, "")
        return ("", None, "")

    # 2. Literal IPv6 puro sem colchetes (`2804:3690::1`, `::1`, `fe80::1%eth0`)
    if text.count(":") >= 2:
        if is_valid_ip(text):
            return (canonicalize_ip(text), None, "")
        return ("", None, "")

    m_ip = _IPV4_PORT_RE.match(text)
    if m_ip:
        ip_str = m_ip.group(1)
        port_str = m_ip.group(2)
        try:
            ipaddress.IPv4Address(ip_str)
            port: Optional[int] = None
            if port_str is not None:
                p_val = int(port_str)
                if 1 <= p_val <= 65535:
                    port = p_val
                else:
                    return (ip_str, None, "")
            return (ip_str, port, "")
        except ValueError:
            return (ip_str, None, "")

    m_host = _HOST_PORT_RE.match(text)
    if m_host and ".." not in text and not text.replace("-", "").isdigit():
        host = m_host.group(1)
        port_str = m_host.group(2)
        port = None
        if port_str is not None:
            p_val = int(port_str)
            if 1 <= p_val <= 65535:
                port = p_val
            else:
                return (host, None, "")
        return (host, port, "")

    if "." in text or ":" in text:
        return ("", None, "")

    pin = normalize_pin(text)
    if pin:
        return ("", None, pin)
    return ("", None, "")


class ViewerIdlePage(CardPage):
    """Tela inicial do Modo Espectador com entrada unica de chave de acesso."""

    connect_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, dark=False)
        lay = self.card.content_layout

        self.lbl_title = GlassLabel("Modo Espectador", design_px=T.FONT_TITLE, weight=600)
        lay.addWidget(self.lbl_title)

        lay.addStretch(9)

        self.lbl_prompt = GlassLabel("Insira a chave de acesso:", design_px=T.FONT_LABEL, weight=600)
        lay.addWidget(self.lbl_prompt)

        lay.addWidget(GlassSpacer(22))

        self.input_key = GlassLineEdit(
            design_w=T.CONTROL_W,
            design_h=T.INPUT_H,
            design_font=T.FONT_INPUT,
        )
        self.input_key.setToolTip(
            "Digite o PIN de acesso (ex: 300-631), link dav:// ou IP da rede local e pressione Enter"
        )
        self.input_key.returnPressed.connect(self._on_submit)
        self.input_key.textChanged.connect(self._on_text_edited)
        lay.addWidget(self.input_key, alignment=Qt.AlignmentFlag.AlignHCenter)

        lay.addWidget(GlassSpacer(16))

        self.lbl_status = GlassLabel(
            "",
            design_px=T.FONT_HINT,
            weight=500,
            color=f"rgb({T.TEXT_DIM[0]},{T.TEXT_DIM[1]},{T.TEXT_DIM[2]})",
            wrap=True,
        )
        lay.addWidget(self.lbl_status)

        lay.addStretch(8)

    def _on_submit(self) -> None:
        raw = self.input_key.text().strip()
        if not raw:
            self.set_status("Informe um PIN, link dav:// ou IP do transmissor.", error=True)
            return
        self.connect_submitted.emit(raw)

    def _on_text_edited(self, _text: str) -> None:
        if self.lbl_status.text():
            self.lbl_status.setText("")

    def set_status(self, message: str, error: bool = False) -> None:
        if error:
            col = f"rgb({T.DANGER[0]},{T.DANGER[1]},{T.DANGER[2]})"
        else:
            col = f"rgb({T.TEXT_DIM[0]},{T.TEXT_DIM[1]},{T.TEXT_DIM[2]})"
        self.lbl_status.set_color(col)
        self.lbl_status.setText(message)

    def set_access_key(self, text: str) -> None:
        self.input_key.setText(text)

    def access_key(self) -> str:
        return self.input_key.text().strip()

    def focus_input(self) -> None:
        self.input_key.setFocus()
        self.input_key.selectAll()


class ViewerConnectingPage(CardPage):
    """Tela intermediaria exibida enquanto aguarda o primeiro quadro decodificado."""

    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, dark=False)
        lay = self.card.content_layout

        lay.addStretch(10)

        self.lbl_connecting = GlassLabel("Conectando...", design_px=T.FONT_LABEL, weight=600)
        lay.addWidget(self.lbl_connecting)

        lay.addWidget(GlassSpacer(18))

        self.lbl_detail = GlassLabel(
            "",
            design_px=T.FONT_HINT,
            weight=500,
            color="rgba(255,255,255,0.78)",
            wrap=True,
        )
        lay.addWidget(self.lbl_detail)

        lay.addStretch(9)

    def set_detail(self, text: str) -> None:
        self.lbl_detail.setText(text)

    def reset(self) -> None:
        self.lbl_connecting.setText("Conectando...")
        self.lbl_detail.setText("")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class SenderHomePage(CardPage):
    """Tela principal do Modo Transmissor com controle de Modo Interativo e gatilho Admin."""

    copy_key_clicked = Signal()
    copy_ipv6_link_clicked = Signal()
    toggle_send_clicked = Signal()
    interactive_toggled = Signal(bool)
    admin_elevation_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, dark=False)
        self._is_sending = False
        self._admin_elevated = False
        self._base_status = ""
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._restore_status)

        lay = self.card.content_layout

        self.lbl_title = GlassLabel("Modo Transmissor", design_px=T.FONT_TITLE, weight=600)
        lay.addWidget(self.lbl_title)

        lay.addStretch(4)

        self.btn_copy_key = GlassButton(
            "Copiar Chave de acesso",
            design_w=T.CONTROL_W,
            design_h=96.0,
            design_font=42,
        )
        self.btn_copy_key.clicked.connect(self.copy_key_clicked.emit)
        lay.addWidget(self.btn_copy_key, alignment=Qt.AlignmentFlag.AlignHCenter)

        lay.addWidget(GlassSpacer(10))

        self.btn_copy_ipv6 = GlassButton(
            "Copiar Link Direto IPv6",
            design_w=T.CONTROL_W,
            design_h=50.0,
            design_font=22,
        )
        self.btn_copy_ipv6.setToolTip(
            "Copia o link direto dav://[IPv6]:porta/PIN para amigos em redes somente IPv6 sem depender de servidor"
        )
        self.btn_copy_ipv6.clicked.connect(self.copy_ipv6_link_clicked.emit)
        self.btn_copy_ipv6.setVisible(False)
        lay.addWidget(self.btn_copy_ipv6, alignment=Qt.AlignmentFlag.AlignHCenter)

        lay.addWidget(GlassSpacer(14))

        self.switch_interactive = GlassToggleSwitch(
            "Transmissão Interativa (Área de Trabalho)",
            design_w=T.CONTROL_W,
            design_h=62.0,
            design_font=24,
            checked=False,
        )
        self.switch_interactive.setToolTip(
            "Quando ativado, permite que o convidado controle mouse/teclado e sincronize área de trabalho"
        )
        self.switch_interactive.toggled.connect(self._on_interactive_switch_changed)
        lay.addWidget(self.switch_interactive, alignment=Qt.AlignmentFlag.AlignHCenter)

        lay.addWidget(GlassSpacer(10))

        self.btn_admin_privilege = GlassButton(
            "Autorizar Privilégio Admin (UAC / Polkit)",
            design_w=T.CONTROL_W,
            design_h=52.0,
            design_font=22,
        )
        self.btn_admin_privilege.setToolTip(
            "Solicita autorização de Administrador no Windows (UAC) ou Linux (Polkit) para controlar janelas de sistema"
        )
        self.btn_admin_privilege.clicked.connect(self.admin_elevation_requested.emit)
        self.btn_admin_privilege.setVisible(False)
        lay.addWidget(self.btn_admin_privilege, alignment=Qt.AlignmentFlag.AlignHCenter)

        lay.addWidget(GlassSpacer(18))

        self.btn_toggle_send = GlassButton(
            "Iniciar Transmissão",
            design_w=T.CONTROL_W,
            design_h=96.0,
            design_font=42,
        )
        self.btn_toggle_send.clicked.connect(self.toggle_send_clicked.emit)
        lay.addWidget(self.btn_toggle_send, alignment=Qt.AlignmentFlag.AlignHCenter)

        lay.addWidget(GlassSpacer(12))

        self.lbl_status = GlassLabel(
            "",
            design_px=T.FONT_HINT,
            weight=500,
            color=f"rgb({T.SUCCESS[0]},{T.SUCCESS[1]},{T.SUCCESS[2]})",
            wrap=True,
        )
        lay.addWidget(self.lbl_status)

        lay.addStretch(4)

    def _on_interactive_switch_changed(self, checked: bool) -> None:
        self.btn_admin_privilege.setVisible(bool(checked))
        self.interactive_toggled.emit(bool(checked))

    def set_ipv6_direct_available(self, available: bool, ipv6_addr: str = "") -> None:
        self.btn_copy_ipv6.setVisible(bool(available))
        if available and ipv6_addr:
            self.btn_copy_ipv6.setToolTip(
                f"Link direto IPv6 ({ipv6_addr}): conecta diretamente sem servidor mesmo em operadoras somente IPv6"
            )

    def set_interactive_state(self, interactive: bool, admin_elevated: bool = False) -> None:
        self._admin_elevated = bool(admin_elevated)
        self.switch_interactive.setChecked(bool(interactive), emit_signal=False)
        self.btn_admin_privilege.setVisible(bool(interactive))
        if self._admin_elevated:
            self.btn_admin_privilege.setText("Privilégio Admin Ativo (UAC / Polkit)")
            self.btn_admin_privilege.setEnabled(False)
        else:
            self.btn_admin_privilege.setText("Autorizar Privilégio Admin (UAC / Polkit)")
            self.btn_admin_privilege.setEnabled(True)

    def set_sending_state(self, sending: bool, detail: str = "") -> None:
        self._is_sending = bool(sending)
        self.btn_toggle_send.setText("Parar Transmissão" if sending else "Iniciar Transmissão")
        self._base_status = detail or ("Transmissão ativa" if sending else "")
        if not self._flash_timer.isActive():
            col = T.SUCCESS if sending else T.TEXT_DIM
            self.lbl_status.set_color(f"rgb({col[0]},{col[1]},{col[2]})")
            self.lbl_status.setText(self._base_status)

    def update_live_stats(self, fps: float, mbps: float) -> None:
        if not self._is_sending:
            return
        self._base_status = f"Transmitindo · {fps:.0f} FPS · {mbps:.1f} Mbps"
        if not self._flash_timer.isActive():
            col = T.SUCCESS
            self.lbl_status.set_color(f"rgb({col[0]},{col[1]},{col[2]})")
            self.lbl_status.setText(self._base_status)

    def flash_message(self, message: str, *, error: bool = False, duration_ms: int = 2200) -> None:
        self._flash_timer.stop()
        col = T.DANGER if error else T.SUCCESS
        self.lbl_status.set_color(f"rgb({col[0]},{col[1]},{col[2]})")
        self.lbl_status.setText(message)
        self._flash_timer.start(duration_ms)

    def flash_copied(self, message: str) -> None:
        self.flash_message(message, error=False, duration_ms=2200)

    def flash_warning(self, message: str, duration_ms: int = 3200) -> None:
        self.flash_message(message, error=True, duration_ms=duration_ms)

    def set_status(self, message: str, error: bool = False) -> None:
        self._flash_timer.stop()
        col = T.DANGER if error else T.TEXT_DIM
        self._base_status = message
        self.lbl_status.set_color(f"rgb({col[0]},{col[1]},{col[2]})")
        self.lbl_status.setText(message)

    def _restore_status(self) -> None:
        col = T.SUCCESS if self._is_sending else T.TEXT_DIM
        self.lbl_status.set_color(f"rgb({col[0]},{col[1]},{col[2]})")
        self.lbl_status.setText(self._base_status)
