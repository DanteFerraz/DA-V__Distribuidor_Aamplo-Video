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

from scripts.qt_compat import (
    QColor, QFont, QHBoxLayout, QLabel, QLineEdit, QPainter, QPalette, QPushButton, QRectF,
    QScrollArea, QSize, QSizePolicy, QVBoxLayout, QWidget, Qt, Signal,
)
from src.ui.glass import paint
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


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------
class GlassLabel(QLabel):
    """Rotulo branco de vidro; o tamanho de fonte acompanha a escala da janela."""

    def __init__(self, text: str = "", design_px: int = T.FONT_LABEL, weight: int = 600,
                 color: str = "#ffffff", wrap: bool = False, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._design_px = design_px
        self._weight = weight
        self._color = color
        self._last_px = -1
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(wrap)
        if wrap:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.apply_scale(1.0)

    def set_color(self, color: str) -> None:
        self._color = color
        self._last_px = -1
        self.apply_scale(getattr(self, "_scale", 1.0))

    def apply_scale(self, scale: float) -> None:
        self._scale = scale
        px_size = T.px(self._design_px, scale, 9)
        if px_size != self._last_px:
            self._last_px = px_size
            self.setStyleSheet(font_css(px_size, self._weight, self._color))


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
        p.setFont(self.font())
        color = QColor(255, 255, 255, 255 if self.isEnabled() else 120)
        p.setPen(color)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())
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
            p.setPen(QColor(255, 255, 255, 255 if i == self._current else 205))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._items[i])
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
