# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
DA-V Glass Design System - Widgets
Autor: Dante Ferraz (MonoTech)

Blocos de interface do visual "vidro": cada widget se desenha sozinho (QPainter) usando a
camada `paint`, e redimensiona tipografia/medidas a partir de um unico fator de escala
(`set_scale`) vindo da janela. Nenhum depende de QSS para a aparencia principal.
"""

from __future__ import annotations

from typing import List, Optional

from src.ui.qt_compat import (
    QColor, QFont, QHBoxLayout, QLabel, QLineEdit, QPainter, QPalette, QPen, QPointF, QPushButton,
    QRectF, QScrollArea, QSize, QSizePolicy, QToolTip, QVBoxLayout, QWidget, Qt, Signal,
)
from src.ui.glass import icons, paint
from src.ui.glass import tokens as T


def font_css(px_size: int, weight: int = 600, color: str = "#ffffff") -> str:
    """Folha de estilo de texto de vidro (sobrepoe o QSS global, que fixa font-size)."""
    families = ",".join(f"'{f}'" if " " in f else f for f in T.FONT_FAMILIES)
    return (f"background: transparent; border: none; color: {color}; "
            f"font-family: {families}; font-size: {int(px_size)}px; font-weight: {weight};")


def _apply_scale_to_children(root: QWidget, scale: float) -> None:
    for child in root.findChildren(QWidget):
        fn = getattr(child, "apply_scale", None)
        if callable(fn):
            fn(scale)


# ---------------------------------------------------------------------------
# Card de vidro
# ---------------------------------------------------------------------------
class GlassCard(QWidget):
    """Superficie de vidro com layout vertical interno. O tamanho inclui o halo luminoso."""

    def __init__(self, parent: Optional[QWidget] = None, dark: bool = False):
        super().__init__(parent)
        self._dark = dark
        self._scale = 1.0
        self.setAutoFillBackground(False)
        if parent is None:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setSpacing(0)
        self._apply_metrics()

    @property
    def scale(self) -> float:
        return self._scale

    def set_scale(self, scale: float) -> None:
        if abs(scale - self._scale) < 0.005:
            return
        self._scale = scale
        self._apply_metrics()
        _apply_scale_to_children(self, scale)
        self.update()

    def _apply_metrics(self) -> None:
        m = paint.glow_margin(self._scale)
        pad_x = T.px(40, self._scale, 8)
        pad_top = T.px(20, self._scale, 6)
        pad_bottom = T.px(34, self._scale, 8)
        self.content_layout.setContentsMargins(m + pad_x, m + pad_top, m + pad_x, m + pad_bottom)

    def body_rect(self) -> QRectF:
        m = paint.glow_margin(self._scale)
        return QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w < 4 or h < 4:
            return
        pix = paint.glass_card_pixmap(w, h, self._scale, self.devicePixelRatioF(), self._dark)
        p = QPainter(self)
        p.drawPixmap(0, 0, pix)
        p.end()


class CardPage(QWidget):
    """Pagina transparente que centraliza um GlassCard com a proporcao das referencias."""

    def __init__(self, parent: Optional[QWidget] = None, *, dark: bool = False,
                 frac: Optional[tuple] = None):
        super().__init__(parent)
        self._frac = frac          # (left, top, width, height) em fracao da pagina; None = card central
        self._ui_scale = 1.0
        self.card = GlassCard(self, dark=dark)

    def set_ui_scale(self, scale: float) -> None:
        self._ui_scale = scale
        self.card.set_scale(scale)
        self._place_card()

    def _place_card(self) -> None:
        w, h = self.width(), self.height()
        m = paint.glow_margin(self._ui_scale)
        if self._frac is None:
            bw, bh = w * T.CARD_W_FRAC, h * T.CARD_H_FRAC
            bx, by = (w - bw) / 2.0, (h - bh) / 2.0
        else:
            fx, fy, fw, fh = self._frac
            bx, by, bw, bh = w * fx, h * fy, w * fw, h * fh
        self.card.setGeometry(int(bx - m), int(by - m), int(bw + 2 * m), int(bh + 2 * m))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_card()


def _parse_css_color(css_color: str) -> QColor:
    """Converte cores hex, rgb() ou rgba() para QColor."""
    s = (css_color or "").strip()
    if s.startswith("rgba(") and s.endswith(")"):
        parts = [p.strip() for p in s[5:-1].split(",")]
        if len(parts) == 4:
            a_val = float(parts[3])
            alpha = int(a_val * 255) if a_val <= 1.0 else int(a_val)
            return QColor(int(parts[0]), int(parts[1]), int(parts[2]), max(0, min(255, alpha)))
    if s.startswith("rgb(") and s.endswith(")"):
        parts = [p.strip() for p in s[4:-1].split(",")]
        if len(parts) == 3:
            return QColor(int(parts[0]), int(parts[1]), int(parts[2]))
    c = QColor(s)
    return c if c.isValid() else QColor(255, 255, 255)


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------
class GlassLabel(QLabel):
    """Rotulo branco de vidro com sombreamento suave; escala acompanha a janela."""

    def __init__(self, text: str = "", design_px: int = T.FONT_LABEL, weight: int = 600,
                 color: str = "#ffffff", wrap: bool = False, shadow: bool = True,
                 parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._design_px = design_px
        self._weight = weight
        self._color = color
        self._qcolor = _parse_css_color(color)
        self._shadow = shadow
        self._last_px = -1
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(wrap)
        if wrap:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.apply_scale(1.0)

    def set_color(self, color: str) -> None:
        self._color = color
        self._qcolor = _parse_css_color(color)
        self._last_px = -1
        self.apply_scale(getattr(self, "_scale", 1.0))
        self.update()

    def apply_scale(self, scale: float) -> None:
        self._scale = scale
        px_size = T.px(self._design_px, scale, 9)
        bot_margin = max(3, T.px(4, scale, 3)) if self._shadow else 0
        self.setContentsMargins(2, 1, 2, bot_margin)
        if px_size != self._last_px:
            self._last_px = px_size
            f = QFont()
            f.setFamilies(T.FONT_FAMILIES)
            f.setPixelSize(px_size)
            f.setWeight(
                QFont.Weight.DemiBold if self._weight >= 600
                else (QFont.Weight.Medium if self._weight >= 500 else QFont.Weight.Normal)
            )
            self.setFont(f)
            self.setStyleSheet(font_css(px_size, self._weight, self._color))

    def paintEvent(self, event):
        if self._shadow and self.text():
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            flags = int(self.alignment())
            if self.wordWrap():
                flags |= int(Qt.TextFlag.TextWordWrap)
            m = self.contentsMargins()
            rect = QRectF(self.rect()).adjusted(m.left(), m.top(), -m.right(), -m.bottom())
            paint.paint_shadowed_text(
                p, rect, flags, self.text(), self.font(), self._qcolor, scale=self._scale
            )
            p.end()
            return
        super().paintEvent(event)


# ---------------------------------------------------------------------------
# Botao neon
# ---------------------------------------------------------------------------
class GlassButton(QPushButton):
    """Botao em pilula com contorno branco luminoso (largura e altura de design em px 1920x1080)."""

    def __init__(self, text: str = "", design_w: float = T.CONTROL_W, design_h: float = T.BUTTON_H,
                 design_font: int = T.FONT_BUTTON, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._dw, self._dh, self._df = design_w, design_h, design_font
        self._scale = 1.0
        self._hover = 0.0
        self._pad = 8
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.apply_scale(1.0)

    def apply_scale(self, scale: float) -> None:
        self._scale = scale
        self._pad = T.px(14, scale, 6)
        self.setFixedSize(T.px(self._dw, scale, 40) + 2 * self._pad,
                          T.px(self._dh, scale, 24) + 2 * self._pad)
        f = QFont()
        f.setFamilies(T.FONT_FAMILIES)
        f.setPixelSize(T.px(self._df, scale, 9))
        f.setWeight(QFont.Weight.DemiBold)
        self.setFont(f)
        self.update()

    def enterEvent(self, event):
        self._hover = 1.0
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = 0.0
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        rect = QRectF(self.rect()).adjusted(self._pad, self._pad, -self._pad, -self._pad)
        paint.paint_neon_pill(p, rect, self._scale, hover=self._hover or (0.6 if self.hasFocus() else 0.0),
                              pressed=self.isDown(), enabled=self.isEnabled())
        color = QColor(255, 255, 255, 255 if self.isEnabled() else 120)
        paint.paint_shadowed_text(
            p, rect, int(Qt.AlignmentFlag.AlignCenter), self.text(), self.font(), color, scale=self._scale
        )
        p.end()


# ---------------------------------------------------------------------------
# Campo de texto neon
# ---------------------------------------------------------------------------
class GlassLineEdit(QLineEdit):
    """Campo de texto em pilula com contorno luminoso, texto centralizado."""

    def __init__(self, text: str = "", design_w: float = T.CONTROL_W, design_h: float = T.INPUT_H,
                 design_font: int = T.FONT_INPUT, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._dw, self._dh, self._df = design_w, design_h, design_font
        self._scale = 1.0
        self._pad = 8
        self._last_css = ""
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(255, 255, 255, 140))
        self.setPalette(pal)
        self.apply_scale(1.0)

    def apply_scale(self, scale: float) -> None:
        self._scale = scale
        self._pad = T.px(14, scale, 6)
        w = T.px(self._dw, scale, 80) + 2 * self._pad
        h = T.px(self._dh, scale, 26) + 2 * self._pad
        self.setFixedSize(w, h)
        inner_pad = T.px(26, scale, 8)
        css = (
            f"QLineEdit {{ background: transparent; border: none; color: #ffffff; "
            f"selection-background-color: rgba(255,255,255,0.35); selection-color: #ffffff; "
            f"padding: 0px {inner_pad + self._pad}px; "
            f"font-family: {','.join(T.FONT_FAMILIES[:3])}; font-size: {T.px(self._df, scale, 9)}px; "
            f"font-weight: 600; placeholder-text-color: rgba(255,255,255,0.55); }}"
        )
        if css != self._last_css:
            self._last_css = css
            self.setStyleSheet(css)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        rect = QRectF(self.rect()).adjusted(self._pad, self._pad, -self._pad, -self._pad)
        hover = 1.0 if (self.hasFocus() or self.underMouse()) else 0.0
        paint.paint_neon_pill(p, rect, self._scale, hover=hover, fill_alpha=0.10)
        p.end()
        super().paintEvent(event)


# ---------------------------------------------------------------------------
# Seletor segmentado (abas das folhas)
# ---------------------------------------------------------------------------
class GlassSegmented(QWidget):
    """Grupo de opcoes em pilula; emite `selected(index)`."""

    selected = Signal(int)

    def __init__(self, items: List[str], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._items = list(items)
        self._current = 0
        self._hover = -1
        self._scale = 1.0
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_scale(1.0)

    def set_items(self, items: List[str]) -> None:
        self._items = list(items)
        self.update()

    def set_item_text(self, index: int, text: str) -> None:
        if 0 <= index < len(self._items):
            self._items[index] = text
            self.update()

    def current(self) -> int:
        return self._current

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._items) and index != self._current:
            self._current = index
            self.update()
            self.selected.emit(index)

    def apply_scale(self, scale: float) -> None:
        self._scale = scale
        self._pad = T.px(12, scale, 5)
        self.setFixedHeight(T.px(64, scale, 30) + 2 * self._pad)
        self.setMinimumWidth(T.px(260 * max(1, len(self._items)), scale, 120))
        f = QFont()
        f.setFamilies(T.FONT_FAMILIES)
        f.setPixelSize(T.px(T.FONT_STATUS, scale, 10))
        f.setWeight(QFont.Weight.DemiBold)
        self.setFont(f)
        self.update()

    def sizeHint(self):
        return QSize(T.px(300 * max(1, len(self._items)), self._scale, 140), self.minimumHeight() or 60)

    def _segment_rects(self):
        inner = QRectF(self.rect()).adjusted(self._pad, self._pad, -self._pad, -self._pad)
        n = max(1, len(self._items))
        seg_w = inner.width() / n
        return [QRectF(inner.left() + i * seg_w, inner.top(), seg_w, inner.height()) for i in range(n)]

    def _index_at(self, pos) -> int:
        for i, r in enumerate(self._segment_rects()):
            if r.contains(pos.x(), pos.y()):
                return i
        return -1

    def mouseMoveEvent(self, event):
        idx = self._index_at(event.position())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    def mousePressEvent(self, event):
        idx = self._index_at(event.position())
        if idx >= 0:
            self.set_current(idx)

    def paintEvent(self, event):
        p = QPainter(self)
        inner = QRectF(self.rect()).adjusted(self._pad, self._pad, -self._pad, -self._pad)
        paint.paint_neon_pill(p, inner, self._scale, fill_alpha=0.08)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setFont(self.font())
        for i, r in enumerate(self._segment_rects()):
            if i == self._current:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 70))
                p.drawRoundedRect(r.adjusted(3, 3, -3, -3), r.height() / 2 - 3, r.height() / 2 - 3)
            elif i == self._hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 28))
                p.drawRoundedRect(r.adjusted(3, 3, -3, -3), r.height() / 2 - 3, r.height() / 2 - 3)
            paint.paint_shadowed_text(
                p,
                r,
                int(Qt.AlignmentFlag.AlignCenter),
                self._items[i],
                self.font(),
                QColor(255, 255, 255, 255 if i == self._current else 205),
                scale=self._scale,
            )
        p.end()


# ---------------------------------------------------------------------------
# Espacador escalavel
# ---------------------------------------------------------------------------
class GlassSpacer(QWidget):
    """Espaco vertical em px de design; acompanha a escala da janela."""

    def __init__(self, design_h: float, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._dh = design_h
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.apply_scale(1.0)

    def apply_scale(self, scale: float) -> None:
        self.setFixedHeight(T.px(self._dh, scale, 2))


# ---------------------------------------------------------------------------
# Area rolavel transparente
# ---------------------------------------------------------------------------
class GlassScrollArea(QScrollArea):
    """QScrollArea transparente com barra fina; garante ajuste horizontal ao viewport."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.body = QWidget()
        self.body.setAutoFillBackground(False)
        self.body.setMinimumWidth(0)
        self.body.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, T.px(10, 1.0), 0)
        self.body_layout.setSpacing(T.px(14, 1.0))
        self.setWidget(self.body)
        self.body.setStyleSheet("background: transparent;")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        vw = self.viewport().width()
        if vw > 40:
            self.body.setMaximumWidth(vw)


# ---------------------------------------------------------------------------
# Switch deslizante em pilula neon (Modo Interativo)
# ---------------------------------------------------------------------------
class GlassToggleSwitch(QWidget):
    """Chave deslizante em pilula de vidro com rotulo sombreado e suporte a teclado."""

    toggled = Signal(bool)

    def __init__(
        self,
        text: str = "",
        design_w: float = T.CONTROL_W,
        design_h: float = 64.0,
        design_font: int = T.FONT_STATUS,
        checked: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._text = text
        self._dw, self._dh, self._df = design_w, design_h, design_font
        self._checked = bool(checked)
        self._hover = 0.0
        self._scale = 1.0
        self._pad = 8
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.apply_scale(1.0)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, emit_signal: bool = False) -> None:
        val = bool(checked)
        if val != self._checked:
            self._checked = val
            self.update()
            if emit_signal:
                self.toggled.emit(self._checked)

    def setText(self, text: str) -> None:
        self._text = text
        self.update()

    def text(self) -> str:
        return self._text

    def toggle(self) -> None:
        self.setChecked(not self._checked, emit_signal=True)

    def apply_scale(self, scale: float) -> None:
        self._scale = scale
        self._pad = T.px(10, scale, 4)
        self.setFixedSize(
            T.px(self._dw, scale, 160) + 2 * self._pad,
            T.px(self._dh, scale, 30) + 2 * self._pad,
        )
        f = QFont()
        f.setFamilies(T.FONT_FAMILIES)
        f.setPixelSize(T.px(self._df, scale, 10))
        f.setWeight(QFont.Weight.DemiBold)
        self.setFont(f)
        self.update()

    def enterEvent(self, event):
        self._hover = 1.0
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = 0.0
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.toggle()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.isEnabled():
            self.toggle()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer = QRectF(self.rect()).adjusted(self._pad, self._pad, -self._pad, -self._pad)
        hov = self._hover or (0.65 if self.hasFocus() else 0.0)
        paint.paint_neon_pill(
            p,
            outer,
            self._scale,
            hover=hov,
            fill_alpha=0.22 if self._checked else 0.10,
            enabled=self.isEnabled(),
        )
        if self._checked:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(52, 211, 153, 64))
            p.drawRoundedRect(outer.adjusted(2, 2, -2, -2), outer.height() / 2.0, outer.height() / 2.0)

        # Trilho do switch a esquerda dentro da pilula
        sw_h = max(16.0, outer.height() * 0.56)
        sw_w = sw_h * 1.82
        sw_x = outer.left() + T.px(22, self._scale, 10)
        sw_y = outer.center().y() - sw_h / 2.0
        track = QRectF(sw_x, sw_y, sw_w, sw_h)

        p.setPen(QPen(QColor(255, 255, 255, 225), max(1.2, 1.8 * self._scale)))
        p.setBrush(QColor(52, 211, 153, 185) if self._checked else QColor(8, 38, 52, 130))
        p.drawRoundedRect(track, sw_h / 2.0, sw_h / 2.0)

        knob_m = max(2.2, sw_h * 0.14)
        knob_d = sw_h - 2.0 * knob_m
        knob_x = (track.right() - knob_m - knob_d) if self._checked else (track.left() + knob_m)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 250))
        p.drawEllipse(QRectF(knob_x, track.top() + knob_m, knob_d, knob_d))

        txt_rect = QRectF(
            track.right() + T.px(16, self._scale, 8),
            outer.top(),
            max(20.0, outer.right() - track.right() - T.px(32, self._scale, 12)),
            outer.height(),
        )
        fg = QColor(255, 255, 255, 255 if self.isEnabled() else 130)
        paint.paint_shadowed_text(
            p,
            txt_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self._text,
            self.font(),
            fg,
            scale=self._scale,
        )
        p.end()


# ---------------------------------------------------------------------------
# Controles flutuantes do canto inferior direito (Controle Remoto, Audio & Tela Cheia)
# ---------------------------------------------------------------------------
class VideoOverlayControls(QWidget):
    """Botoes vetoriais flutuantes de Controle Remoto, Audio e Tela Cheia."""

    ZONE_AUDIO = 0
    ZONE_FULLSCREEN = 1
    ZONE_REMOTE = 2

    audio_toggled = Signal()
    fullscreen_toggled = Signal()
    remote_toggled = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._scale = 1.0
        self._audio_muted = False
        self._is_fullscreen = False
        self._show_remote = False
        self._remote_active = False
        self._remote_allowed = False
        self._hover_zone = -1
        self._relayout()

    @property
    def audio_muted(self) -> bool:
        return self._audio_muted

    @property
    def is_fullscreen(self) -> bool:
        return self._is_fullscreen

    @property
    def remote_active(self) -> bool:
        return self._remote_active

    def set_ui_scale(self, scale: float) -> None:
        if abs(scale - self._scale) >= 0.005:
            self._scale = scale
        self._relayout()
        self.update()

    def set_audio_muted(self, muted: bool) -> None:
        m = bool(muted)
        if m != self._audio_muted:
            self._audio_muted = m
            self.update()

    def set_fullscreen(self, is_fullscreen: bool) -> None:
        fs = bool(is_fullscreen)
        if fs != self._is_fullscreen:
            self._is_fullscreen = fs
            self.update()

    def set_remote_visible(self, visible: bool) -> None:
        v = bool(visible)
        if v != self._show_remote:
            self._show_remote = v
            self._relayout()
            self.update()

    def set_remote_state(self, active: bool, allowed_by_host: bool) -> None:
        a = bool(active and allowed_by_host)
        al = bool(allowed_by_host)
        if a != self._remote_active or al != self._remote_allowed:
            self._remote_active = a
            self._remote_allowed = al
            self.update()

    def _active_zones(self) -> List[int]:
        if self._show_remote:
            return [self.ZONE_REMOTE, self.ZONE_AUDIO, self.ZONE_FULLSCREEN]
        return [self.ZONE_AUDIO, self.ZONE_FULLSCREEN]

    def _btn_size(self) -> float:
        return float(T.px(48, self._scale, 30))

    def _gap(self) -> float:
        return float(T.px(10, self._scale, 4))

    def _zone_rect(self, zone: int) -> QRectF:
        zones = self._active_zones()
        if zone not in zones:
            return QRectF()
        idx = zones.index(zone)
        btn = self._btn_size()
        gap = self._gap()
        return QRectF(0.0, idx * (btn + gap), btn, btn)

    def _relayout(self) -> None:
        btn = int(round(self._btn_size()))
        gap = int(round(self._gap()))
        n = len(self._active_zones())
        self.resize(btn, btn * n + gap * max(0, n - 1))
        self.reposition()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        margin_r = T.px(22, self._scale, 10)
        margin_b = T.px(16, self._scale, 8)
        self.move(
            max(0, parent.width() - self.width() - margin_r),
            max(0, parent.height() - self.height() - margin_b),
        )

    def _zone_at(self, pos: QPointF) -> int:
        for zone in self._active_zones():
            if self._zone_rect(zone).contains(pos):
                return zone
        return -1

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        zone = self._zone_at(event.position())
        if zone == self.ZONE_REMOTE:
            self.remote_toggled.emit()
        elif zone == self.ZONE_AUDIO:
            self.audio_toggled.emit()
        elif zone == self.ZONE_FULLSCREEN:
            self.fullscreen_toggled.emit()

    def mouseMoveEvent(self, event):
        zone = self._zone_at(event.position())
        if zone != self._hover_zone:
            self._hover_zone = zone
            self.update()

    def leaveEvent(self, event):
        self._hover_zone = -1
        self.update()
        super().leaveEvent(event)

    def event(self, ev):
        if ev.type() == ev.Type.ToolTip:
            zone = self._zone_at(ev.pos().toPointF()) if hasattr(ev.pos(), "toPointF") else -1
            if zone == self.ZONE_REMOTE:
                if not self._remote_allowed:
                    text = "Controle remoto bloqueado pelo Transmissor (Modo Somente Vídeo)"
                elif self._remote_active:
                    text = "Pausar controle remoto de mouse e teclado (Ctrl+Alt+M: mouse relativo)"
                else:
                    text = "Ativar controle remoto de mouse e teclado"
            elif zone == self.ZONE_AUDIO:
                text = "Ativar áudio da transmissão" if self._audio_muted else "Desativar áudio da transmissão"
            elif zone == self.ZONE_FULLSCREEN:
                text = "Sair da tela cheia (Esc)" if self._is_fullscreen else "Tela cheia (F11)"
            else:
                text = ""
            if text:
                QToolTip.showText(ev.globalPos(), text, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(ev)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for zone in self._active_zones():
            r = self._zone_rect(zone)
            hovered = zone == self._hover_zone
            if zone == self.ZONE_REMOTE and self._remote_active:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(16, 185, 129, 110))
                p.drawEllipse(r.center(), r.width() * 0.46, r.height() * 0.46)
            if hovered:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(8, 28, 38, 72))
                p.drawEllipse(r.center(), r.width() * 0.48, r.height() * 0.48)
                p.setBrush(QColor(255, 255, 255, 42))
                p.drawEllipse(r.center(), r.width() * 0.46, r.height() * 0.46)

            icon_sz = r.width() * (0.78 if hovered else 0.72)
            icon_box = QRectF(
                r.center().x() - icon_sz / 2.0,
                r.center().y() - icon_sz / 2.0,
                icon_sz,
                icon_sz,
            )
            alpha = 1.0 if hovered else 0.94
            if zone == self.ZONE_REMOTE:
                eff_alpha = alpha if self._remote_allowed else 0.50
                icons.draw_cursor_control(p, icon_box, alpha=eff_alpha, active=self._remote_active)
            elif zone == self.ZONE_AUDIO:
                icons.draw_speaker(p, icon_box, alpha=alpha, muted=self._audio_muted)
            else:
                icons.draw_fullscreen_corners(p, icon_box, alpha=alpha, is_fullscreen=self._is_fullscreen)
        p.end()
