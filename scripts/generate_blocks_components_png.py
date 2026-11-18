# -*- coding: utf-8 -*-
"""
Gerador de Componentes Visuais Blocks.so em PNG de Alta Definição — DA-V v4.0
Autor: Dante Ferraz (MonoTech)

Renderiza os componentes do Design System Blocks.so em imagens PNG nítidas (2x Retina)
para permitir a diagramação, recorte e montagem no Photocraft.
"""

import os
import sys

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QGuiApplication, QImage, QPainter, QColor, QFont, QPen, QBrush, QPainterPath, QLinearGradient
)

# Diretório de destino
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "design", "blocks_components")
os.makedirs(OUT_DIR, exist_ok=True)

# Paleta Blocks.so + Azul MonoTech
C_CANVAS   = QColor("#09090b")
C_SURFACE  = QColor("#121215")
C_CARD     = QColor("#18181b")
C_CARD_HOV = QColor("#222227")
C_BORDER   = QColor("#27272a")
C_BORDER_SUBTLE = QColor(255, 255, 255, 22)
C_ACCENT   = QColor("#0066FF")  # Azul MonoTech
C_ACCENT_HOV = QColor("#2575fc")
C_SUCCESS  = QColor("#10b981")
C_SUCCESS_BG = QColor(16, 185, 129, 25)
C_TEXT_PRI = QColor("#f4f4f5")
C_TEXT_SEC = QColor("#a1a1aa")
C_TEXT_MUT = QColor("#71717a")


def setup_painter(painter: QPainter):
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)


# -----------------------------------------------------------------------------
# 1. HEADER / NAVBAR COMPONENT
# -----------------------------------------------------------------------------
def render_header(path: str):
    w, h = 960, 64
    img = QImage(w * 2, h * 2, QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2.0)
    img.fill(Qt.transparent)

    p = QPainter(img)
    setup_painter(p)

    # Fundo do Header
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(C_SURFACE)
    rect = QRectF(0, 0, w, h)
    p.drawRoundedRect(rect, 10, 10)

    # Logo + Versão
    f_brand = QFont("Segoe UI", 13, QFont.Bold)
    p.setFont(f_brand)
    p.setPen(C_TEXT_PRI)
    p.drawText(20, 38, "DA-V")

    # Pill de Versão
    pill_ver = QRectF(66, 21, 56, 22)
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(C_CARD)
    p.drawRoundedRect(pill_ver, 4, 4)
    p.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
    p.setPen(C_ACCENT)
    p.drawText(pill_ver, Qt.AlignCenter, "v4.0.0")

    # Subtítulo institucional
    p.setFont(QFont("Segoe UI", 10, QFont.Normal))
    p.setPen(C_TEXT_MUT)
    p.drawText(130, 37, "Distribuidor Amplo de Vídeo")

    # Centro: Status e PIN
    pin_rect = QRectF(400, 14, 150, 36)
    p.setPen(QPen(C_SUCCESS, 1))
    p.setBrush(C_SUCCESS_BG)
    p.drawRoundedRect(pin_rect, 6, 6)
    p.setFont(QFont("Segoe UI", 11, QFont.Bold))
    p.setPen(C_SUCCESS)
    p.drawText(pin_rect, Qt.AlignCenter, "PIN: 300-631")

    # Botões à direita
    buttons = [("Copiar PIN", 565), ("Copiar Convite", 670), ("Modo Claro", 790), ("Buscar Updates", 880)]
    for label, x in buttons:
        btn_r = QRectF(x, 17, 95 if len(label) > 12 else 85, 30)
        p.setPen(QPen(C_BORDER, 1))
        p.setBrush(C_CARD)
        p.drawRoundedRect(btn_r, 6, 6)
        p.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        p.setPen(C_TEXT_PRI)
        p.drawText(btn_r, Qt.AlignCenter, label)

    p.end()
    img.save(path, "PNG")


# -----------------------------------------------------------------------------
# 2. SIDEBAR EXPANDIDA
# -----------------------------------------------------------------------------
def render_sidebar_expanded(path: str):
    w, h = 240, 520
    img = QImage(w * 2, h * 2, QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2.0)
    img.fill(Qt.transparent)

    p = QPainter(img)
    setup_painter(p)

    # Fundo da Sidebar
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(C_SURFACE)
    p.drawRoundedRect(QRectF(0, 0, w, h), 12, 12)

    # Topo: Logo
    p.setFont(QFont("Segoe UI", 13, QFont.Bold))
    p.setPen(C_TEXT_PRI)
    p.drawText(20, 38, "NAVEGAÇÃO")

    # Itens de Menu
    items = [
        ("▶", "Assistir / Receptor", True),
        ("●", "Compartilhar Tela", False),
        ("◈", "Diagnóstico TUPÃ", False),
        ("◎", "Dispositivos LAN", False),
        ("≡", "Troubleshooting", False),
    ]

    y = 60
    for icon, label, is_active in items:
        item_r = QRectF(12, y, w - 24, 40)
        if is_active:
            p.setPen(QPen(C_ACCENT, 1))
            p.setBrush(QColor(0, 102, 255, 30))
            p.drawRoundedRect(item_r, 6, 6)
            # Indicador de barra ativa na esquerda
            p.setPen(Qt.NoPen)
            p.setBrush(C_ACCENT)
            p.drawRoundedRect(QRectF(12, y + 8, 3, 24), 2, 2)
            text_color = C_TEXT_PRI
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(Qt.transparent)
            p.drawRoundedRect(item_r, 6, 6)
            text_color = C_TEXT_SEC

        # Ícone
        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
        p.setPen(C_ACCENT if is_active else C_TEXT_MUT)
        p.drawText(24, y + 25, icon)

        # Label
        p.setFont(QFont("Segoe UI", 10, QFont.DemiBold if is_active else QFont.Normal))
        p.setPen(text_color)
        p.drawText(46, y + 25, label)

        y += 48

    # Rodapé da Sidebar
    # Botão "Sobre o Autor"
    btn_auth = QRectF(12, h - 85, w - 24, 34)
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(C_CARD)
    p.drawRoundedRect(btn_auth, 6, 6)
    p.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
    p.setPen(C_TEXT_PRI)
    p.drawText(btn_auth, Qt.AlignCenter, "Sobre o Autor")

    # Botão "Recolher Menu"
    btn_col = QRectF(12, h - 45, w - 24, 32)
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.transparent)
    p.drawRoundedRect(btn_col, 6, 6)
    p.setFont(QFont("Segoe UI", 9, QFont.Normal))
    p.setPen(C_TEXT_MUT)
    p.drawText(btn_col, Qt.AlignCenter, "«  Recolher Menu")

    p.end()
    img.save(path, "PNG")


# -----------------------------------------------------------------------------
# 3. SIDEBAR RECOLHIDA (MODO COMPACTO)
# -----------------------------------------------------------------------------
def render_sidebar_collapsed(path: str):
    w, h = 64, 520
    img = QImage(w * 2, h * 2, QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2.0)
    img.fill(Qt.transparent)

    p = QPainter(img)
    setup_painter(p)

    # Fundo
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(C_SURFACE)
    p.drawRoundedRect(QRectF(0, 0, w, h), 12, 12)

    # Top Icon
    p.setFont(QFont("Segoe UI", 11, QFont.Bold))
    p.setPen(C_ACCENT)
    p.drawText(QRectF(0, 16, w, 30), Qt.AlignCenter, "DA-V")

    # Ícones Centrais
    icons = [("▶", True), ("●", False), ("◈", False), ("◎", False), ("≡", False)]
    y = 60
    for icon, is_active in icons:
        r = QRectF(12, y, 40, 40)
        if is_active:
            p.setPen(QPen(C_ACCENT, 1))
            p.setBrush(QColor(0, 102, 255, 30))
            p.drawRoundedRect(r, 8, 8)
            p.setPen(C_TEXT_PRI)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(Qt.transparent)
            p.drawRoundedRect(r, 8, 8)
            p.setPen(C_TEXT_SEC)

        p.setFont(QFont("Segoe UI", 11, QFont.Bold))
        p.drawText(r, Qt.AlignCenter, icon)
        y += 48

    # Expand button
    btn_exp = QRectF(12, h - 45, 40, 32)
    p.setFont(QFont("Segoe UI", 11, QFont.Bold))
    p.setPen(C_TEXT_MUT)
    p.drawText(btn_exp, Qt.AlignCenter, "»")

    p.end()
    img.save(path, "PNG")


# -----------------------------------------------------------------------------
# 4. BARRA DE CONTROLE FLUTUANTE (FLOATING CONTROL BAR)
# -----------------------------------------------------------------------------
def render_floating_control_bar(path: str):
    w, h = 860, 68
    img = QImage(w * 2, h * 2, QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2.0)
    img.fill(Qt.transparent)

    p = QPainter(img)
    setup_painter(p)

    # Container Card com Sombra Sutil e Borda Fina
    card_r = QRectF(0, 0, w, h)
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(QColor("#101014"))
    p.drawRoundedRect(card_r, 10, 10)

    # Input: IP do Transmissor
    lbl_ip = QRectF(16, 12, 110, 16)
    p.setFont(QFont("Segoe UI", 8, QFont.Bold))
    p.setPen(C_TEXT_MUT)
    p.drawText(lbl_ip, Qt.AlignLeft, "IP DO TRANSMISSOR")

    inp_ip = QRectF(16, 28, 240, 30)
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(C_CARD)
    p.drawRoundedRect(inp_ip, 6, 6)
    p.setFont(QFont("Segoe UI", 9, QFont.Normal))
    p.setPen(C_TEXT_SEC)
    p.drawText(inp_ip.adjusted(10, 0, 0, 0), Qt.AlignVCenter, "Deixe vazio para pareamento P2P...")

    # Input: Porta UDP
    lbl_port = QRectF(270, 12, 70, 16)
    p.setFont(QFont("Segoe UI", 8, QFont.Bold))
    p.setPen(C_TEXT_MUT)
    p.drawText(lbl_port, Qt.AlignLeft, "PORTA UDP")

    inp_port = QRectF(270, 28, 80, 30)
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(C_CARD)
    p.drawRoundedRect(inp_port, 6, 6)
    p.setFont(QFont("Segoe UI", 9, QFont.Bold))
    p.setPen(C_TEXT_PRI)
    p.drawText(inp_port, Qt.AlignCenter, "9000")

    # Input: PIN de Acesso
    lbl_pin = QRectF(365, 12, 90, 16)
    p.setFont(QFont("Segoe UI", 8, QFont.Bold))
    p.setPen(C_TEXT_MUT)
    p.drawText(lbl_pin, Qt.AlignLeft, "PIN DE ACESSO")

    inp_pin = QRectF(365, 28, 120, 30)
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(C_CARD)
    p.drawRoundedRect(inp_pin, 6, 6)
    p.setFont(QFont("Segoe UI", 9, QFont.Bold))
    p.setPen(C_TEXT_PRI)
    p.drawText(inp_pin, Qt.AlignCenter, "300-631")

    # Botão de Ação Primária: Conectar e Assistir (Azul MonoTech)
    btn_conn = QRectF(505, 24, 180, 36)
    p.setPen(Qt.NoPen)
    p.setBrush(C_ACCENT)
    p.drawRoundedRect(btn_conn, 6, 6)
    p.setFont(QFont("Segoe UI", 10, QFont.Bold))
    p.setPen(Qt.white)
    p.drawText(btn_conn, Qt.AlignCenter, "Conectar e Assistir")

    # Switch: HUD Telemetria
    lbl_hud = QRectF(705, 20, 140, 20)
    p.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
    p.setPen(C_TEXT_PRI)
    p.drawText(705, 45, "HUD Telemetria")

    # Pill switch ativo
    switch_r = QRectF(800, 27, 36, 18)
    p.setPen(Qt.NoPen)
    p.setBrush(C_ACCENT)
    p.drawRoundedRect(switch_r, 9, 9)
    # Circle do switch
    p.setBrush(Qt.white)
    p.drawEllipse(QRectF(819, 29, 14, 14))

    p.end()
    img.save(path, "PNG")


# -----------------------------------------------------------------------------
# 5. CARDS DE MÉTRICAS (STAT CARDS BLOCKS.SO)
# -----------------------------------------------------------------------------
def render_stat_cards(path: str):
    w, h = 860, 100
    img = QImage(w * 2, h * 2, QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2.0)
    img.fill(Qt.transparent)

    p = QPainter(img)
    setup_painter(p)

    card_data = [
        ("TAXA DE QUADROS", "60.0 FPS", "Alvo: 60 FPS estável", C_SUCCESS),
        ("VAZÃO DE SAÍDA", "8.52 Mbps", "Transporte P2P Universal", C_ACCENT),
        ("LATÊNCIA LAN (RTT)", "2.40 ms", "Sub-15ms Ultra-Baixa", C_SUCCESS),
        ("QUADROS TRANSMITIDOS", "4,820", "H.264 NAL Units", C_TEXT_PRI),
    ]

    card_w = (w - (len(card_data) - 1) * 16) / len(card_data)
    for i, (title, val, sub, color) in enumerate(card_data):
        x = i * (card_w + 16)
        r = QRectF(x, 0, card_w, h)

        # Card Surface
        p.setPen(QPen(C_BORDER, 1))
        p.setBrush(C_SURFACE)
        p.drawRoundedRect(r, 8, 8)

        # Title
        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        p.setPen(C_TEXT_MUT)
        p.drawText(r.adjusted(14, 14, -14, 0), Qt.AlignLeft, title)

        # Value
        p.setFont(QFont("Segoe UI", 16, QFont.Bold))
        p.setPen(color)
        p.drawText(r.adjusted(14, 34, -14, 0), Qt.AlignLeft, val)

        # Sub
        p.setFont(QFont("Segoe UI", 8, QFont.Normal))
        p.setPen(C_TEXT_MUT)
        p.drawText(r.adjusted(14, 68, -14, -10), Qt.AlignLeft, sub)

    p.end()
    img.save(path, "PNG")


# -----------------------------------------------------------------------------
# 6. VIEWPORT / CANVAS (EMPTY STATE + HUD FLUTUANTE)
# -----------------------------------------------------------------------------
def render_canvas_viewport(path: str):
    w, h = 860, 480
    img = QImage(w * 2, h * 2, QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2.0)
    img.fill(Qt.transparent)

    p = QPainter(img)
    setup_painter(p)

    # Área de Vídeo (Fundo Preto com Borda Suave de 1px)
    viewport_r = QRectF(0, 0, w, h)
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(QColor("#040406"))
    p.drawRoundedRect(viewport_r, 10, 10)

    # Empty State Central Card
    center_w, center_h = 360, 140
    center_r = QRectF((w - center_w) / 2, (h - center_h) / 2, center_w, center_h)
    p.setPen(QPen(C_BORDER_SUBTLE, 1))
    p.setBrush(QColor(18, 18, 22, 180))
    p.drawRoundedRect(center_r, 12, 12)

    # Ícone Monitor Central
    p.setFont(QFont("Segoe UI", 20, QFont.Bold))
    p.setPen(C_ACCENT)
    p.drawText(QRectF(center_r.left(), center_r.top() + 16, center_w, 32), Qt.AlignCenter, "▣")

    # Mensagem de Estado
    p.setFont(QFont("Segoe UI", 11, QFont.Bold))
    p.setPen(C_TEXT_PRI)
    p.drawText(QRectF(center_r.left(), center_r.top() + 54, center_w, 24), Qt.AlignCenter, "RECEPTOR EM ESPERA")

    p.setFont(QFont("Segoe UI", 9, QFont.Normal))
    p.setPen(C_TEXT_MUT)
    p.drawText(QRectF(center_r.left(), center_r.top() + 82, center_w, 40), Qt.AlignCenter, "Informe o PIN ou IP acima para iniciar\na transmissão em tempo real.")

    # HUD Flutuante no Canto Superior Direito (Pill Compacta)
    hud_r = QRectF(w - 270, 16, 254, 32)
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(QColor(12, 12, 16, 210))
    p.drawRoundedRect(hud_r, 16, 16)

    # Indicador de Status Verde
    p.setPen(Qt.NoPen)
    p.setBrush(C_SUCCESS)
    p.drawEllipse(QRectF(hud_r.left() + 12, hud_r.top() + 12, 8, 8))

    # Chips de Métricas no HUD
    p.setFont(QFont("Segoe UI", 8, QFont.DemiBold))
    p.setPen(C_TEXT_PRI)
    p.drawText(QRectF(hud_r.left() + 26, hud_r.top(), hud_r.width() - 30, hud_r.height()), Qt.AlignVCenter, "60.0 FPS   |   8.5 Mbps   |   2.4 ms")

    p.end()
    img.save(path, "PNG")


# -----------------------------------------------------------------------------
# 7. MODAL DIALOG (ATUALIZAÇÃO / CONSENTIMENTO)
# -----------------------------------------------------------------------------
def render_modal_dialog(path: str):
    w, h = 500, 420
    img = QImage(w * 2, h * 2, QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2.0)
    img.fill(Qt.transparent)

    p = QPainter(img)
    setup_painter(p)

    # Diálogo com Borda Elevada
    dlg_r = QRectF(0, 0, w, h)
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(C_SURFACE)
    p.drawRoundedRect(dlg_r, 12, 12)

    # Badge de Atualização
    badge_r = QRectF(24, 24, 150, 22)
    p.setPen(Qt.NoPen)
    p.setBrush(C_ACCENT)
    p.drawRoundedRect(badge_r, 4, 4)
    p.setFont(QFont("Segoe UI", 8, QFont.Bold))
    p.setPen(Qt.white)
    p.drawText(badge_r, Qt.AlignCenter, "NOVA VERSÃO DISPONÍVEL")

    # Comparativo de Versão
    p.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
    p.setPen(C_ACCENT)
    p.drawText(QRectF(w - 180, 24, 156, 22), Qt.AlignRight, "v4.0.0  ->  v4.1.0")

    # Título do Release
    p.setFont(QFont("Segoe UI", 14, QFont.Bold))
    p.setPen(C_TEXT_PRI)
    p.drawText(24, 76, "DA-V v4.1.0 — Modo Ultra-Desempenho")

    # Card de Notas de Versão
    notes_r = QRectF(24, 96, w - 48, 200)
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(C_CARD)
    p.drawRoundedRect(notes_r, 8, 8)

    p.setFont(QFont("Segoe UI", 9, QFont.Bold))
    p.setPen(C_TEXT_SEC)
    p.drawText(40, 122, "Novidades e Melhorias:")

    notes = [
        "• Arquitetura modular desvinculada com MonoTech Core Kernel.",
        "• Nova UI baseada em blocos limpos inspirada no Blocks.so.",
        "• Suporte a transmissão fluida até 120 FPS sem paywall.",
        "• Atualizador automático integrado com consentimento explícito.",
    ]
    y = 148
    p.setFont(QFont("Segoe UI", 9, QFont.Normal))
    p.setPen(C_TEXT_MUT)
    for note in notes:
        p.drawText(40, y, note)
        y += 26

    # Texto de Pergunta
    p.setFont(QFont("Segoe UI", 9, QFont.Normal))
    p.setPen(C_TEXT_SEC)
    p.drawText(24, 330, "Deseja baixar e instalar esta atualização agora?")

    # Botões
    btn_cancel = QRectF(w - 270, 360, 130, 36)
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(C_CARD)
    p.drawRoundedRect(btn_cancel, 6, 6)
    p.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
    p.setPen(C_TEXT_PRI)
    p.drawText(btn_cancel, Qt.AlignCenter, "Lembrar Mais Tarde")

    btn_ok = QRectF(w - 130, 360, 106, 36)
    p.setPen(Qt.NoPen)
    p.setBrush(C_ACCENT)
    p.drawRoundedRect(btn_ok, 6, 6)
    p.setFont(QFont("Segoe UI", 9, QFont.Bold))
    p.setPen(Qt.white)
    p.drawText(btn_ok, Qt.AlignCenter, "Atualizar Agora")

    p.end()
    img.save(path, "PNG")


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    print("Gerando componentes PNG Blocks.so em alta definicao (Retina 2x)...")
    
    files = [
        ("01_header_navbar.png", render_header),
        ("02_sidebar_expanded.png", render_sidebar_expanded),
        ("03_sidebar_collapsed.png", render_sidebar_collapsed),
        ("04_floating_controls_bar.png", render_floating_control_bar),
        ("05_stat_cards_metrics.png", render_stat_cards),
        ("06_canvas_viewport_empty.png", render_canvas_viewport),
        ("07_dialog_modal_consent.png", render_modal_dialog),
    ]

    for fname, func in files:
        full_path = os.path.join(OUT_DIR, fname)
        func(full_path)
        print(f"Gerado: {full_path}")

    print("\nTodos os componentes foram gerados com sucesso em design/blocks_components/!")


if __name__ == "__main__":
    main()
