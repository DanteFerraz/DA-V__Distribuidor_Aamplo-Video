# -*- coding: utf-8 -*-
"""
DA-V Glass Design System - Camada de pintura
Autor: Dante Ferraz (MonoTech)

Funcoes puras de desenho (QPainter) para o visual "vidro": fundo em gradiente, card
translucido com brilho nas bordas e contorno neon. As superficies grandes sao
renderizadas uma unica vez em QPixmap e reaproveitadas (cache), de modo que repintar a
janela custa um unico drawPixmap.
"""

from __future__ import annotations

from typing import Dict, Tuple

from src.ui.qt_compat import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QPointF, QRadialGradient, QRectF, Qt, QBrush,
)
from src.ui.glass import tokens as T

_CACHE: Dict[Tuple, QPixmap] = {}
_CACHE_LIMIT = 12


def _cache_get(key: Tuple):
    return _CACHE.get(key)


def _cache_put(key: Tuple, pix: QPixmap) -> QPixmap:
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = pix
    return pix


def clear_cache() -> None:
    _CACHE.clear()


def _new_pixmap(width: int, height: int, dpr: float) -> QPixmap:
    pix = QPixmap(max(1, int(width * dpr)), max(1, int(height * dpr)))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    return pix


def _color(rgb, alpha: float = 1.0) -> QColor:
    c = QColor(rgb[0], rgb[1], rgb[2])
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


# ---------------------------------------------------------------------------
# Fundo em gradiente
# ---------------------------------------------------------------------------
def background_pixmap(width: int, height: int, dpr: float = 1.0) -> QPixmap:
    key = ("bg", width, height, round(dpr, 2))
    hit = _cache_get(key)
    if hit is not None:
        return hit

    pix = _new_pixmap(width, height, dpr)
    p = QPainter(pix)
    grad = QLinearGradient(0, 0, 0, height)
    for pos, rgb in T.BACKGROUND_STOPS:
        grad.setColorAt(pos, _color(rgb))
    p.fillRect(0, 0, width, height, QBrush(grad))

    # Suave clareamento lateral para dar profundidade (nao existe nas bordas do centro)
    side = QRadialGradient(QPointF(width * 0.5, height * 0.55), max(width, height) * 0.75)
    side.setColorAt(0.0, _color((255, 255, 255), 0.0))
    side.setColorAt(0.65, _color((255, 255, 255), 0.0))
    side.setColorAt(1.0, _color((255, 255, 255), 0.10))
    p.fillRect(0, 0, width, height, QBrush(side))
    p.end()
    return _cache_put(key, pix)


# ---------------------------------------------------------------------------
# Card de vidro
# ---------------------------------------------------------------------------
def glow_margin(scale: float) -> int:
    """Espaco reservado ao redor do card para o halo luminoso."""
    return max(10, int(round(46 * scale)))


def _rounded(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def glass_card_pixmap(width: int, height: int, scale: float, dpr: float = 1.0,
                      dark: bool = False) -> QPixmap:
    """
    Card de vidro com halo externo branco, corpo translucido com mancha teal
    e brilho interno nas bordas. O pixmap tem o tamanho total do widget; o corpo
    ocupa a area interna menos `glow_margin`.
    """
    key = ("card", width, height, int(scale * 100), round(dpr, 2), dark)
    hit = _cache_get(key)
    if hit is not None:
        return hit

    pix = _new_pixmap(width, height, dpr)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    m = glow_margin(scale)
    body = QRectF(m, m, width - 2 * m, height - 2 * m)
    radius = max(8.0, 24.0 * scale)

    # 1) Halo externo
    steps = 22
    for i in range(steps, 0, -1):
        t = i / steps
        grow = m * t
        alpha = 0.46 * (1.0 - t) ** 2.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_color(T.WHITE, alpha))
        p.drawPath(_rounded(body.adjusted(-grow, -grow, grow, grow), radius + grow))

    clip = _rounded(body, radius)
    p.save()
    p.setClipPath(clip)

    # 2) Base translucida
    base_alpha = 0.10 if dark else 0.18
    p.fillRect(body, _color(T.WHITE, base_alpha))
    if dark:
        p.fillRect(body, _color((6, 38, 52), 0.62))

    # 3) Corpo teal continuo, mais profundo a direita do centro (como na referencia)
    blob = QRadialGradient(QPointF(body.left() + body.width() * 0.66, body.top() + body.height() * 0.48),
                           body.width() * 0.82)
    blob.setColorAt(0.0, _color((44, 118, 138), 0.78))
    blob.setColorAt(0.50, _color((66, 138, 156), 0.56))
    blob.setColorAt(1.0, _color((110, 172, 182), 0.26))
    p.fillRect(body, QBrush(blob))

    # 4) Reflexos claros: canto superior-esquerdo e base-esquerda
    hi = QRadialGradient(QPointF(body.left() + body.width() * 0.10, body.top() + body.height() * 0.06),
                         body.width() * 0.36)
    hi.setColorAt(0.0, _color(T.WHITE, 0.34))
    hi.setColorAt(1.0, _color(T.WHITE, 0.0))
    p.fillRect(body, QBrush(hi))
    light = QRadialGradient(QPointF(body.left() + body.width() * 0.22, body.bottom() - body.height() * 0.08),
                            body.width() * 0.42)
    light.setColorAt(0.0, _color(T.WHITE, 0.24))
    light.setColorAt(1.0, _color(T.WHITE, 0.0))
    p.fillRect(body, QBrush(light))

    # 5) Brilho interno nas bordas (vinheta branca)
    inner = max(10, int(round(34 * scale)))
    for i in range(inner):
        t = i / inner
        alpha = 0.34 * (1.0 - t) ** 2.4
        p.setPen(QPen(_color(T.WHITE, alpha), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        inset = i + 0.7
        p.drawPath(_rounded(body.adjusted(inset, inset, -inset, -inset), max(2.0, radius - inset)))
    p.restore()

    # 6) Contorno externo nitido
    p.setPen(QPen(_color(T.WHITE, 0.82), max(1.2, 2.2 * scale)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(clip)
    p.end()
    return _cache_put(key, pix)


# ---------------------------------------------------------------------------
# Contorno neon (campos e botoes em pilula)
# ---------------------------------------------------------------------------
def paint_neon_pill(painter: QPainter, rect: QRectF, scale: float, *, hover: float = 0.0,
                    pressed: bool = False, fill_alpha: float = 0.13, enabled: bool = True) -> None:
    """Pilula com preenchimento translucido, halo suave e borda branca brilhante."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    radius = rect.height() / 2.0
    width = max(1.6, 3.0 * scale)

    alpha_mul = 1.0 if enabled else 0.45
    # halo
    for i in range(6, 0, -1):
        t = i / 6.0
        grow = 9.0 * scale * t
        a = (0.10 + 0.10 * hover) * (1.0 - t) * alpha_mul
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color(T.WHITE, a))
        painter.drawRoundedRect(rect.adjusted(-grow, -grow, grow, grow), radius + grow, radius + grow)

    inset = width / 2.0
    inner = rect.adjusted(inset, inset, -inset, -inset)
    # preenchimento teal (nao branco): o campo fica ligeiramente mais saturado que o card
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_color((52, 148, 166), 0.30 * alpha_mul))
    painter.drawRoundedRect(inner, radius, radius)
    extra = fill_alpha * 0.5 + 0.12 * hover + (0.08 if pressed else 0.0)
    painter.setBrush(_color(T.WHITE, extra * alpha_mul))
    painter.drawRoundedRect(inner, radius, radius)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_color(T.WHITE, (0.88 + 0.12 * hover) * alpha_mul), width))
    painter.drawRoundedRect(inner, radius, radius)
    painter.restore()


def paint_pill_surface(painter: QPainter, rect: QRectF, scale: float, *, glow: float = 1.0,
                       dark_underlay: float = 0.0) -> None:
    """Superficie da pilula de navegacao flutuante (translucida, teal, brilho branco)."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    radius = rect.height() / 2.0

    for i in range(10, 0, -1):
        t = i / 10.0
        grow = 16.0 * scale * t
        a = 0.34 * glow * (1.0 - t) ** 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color(T.WHITE, a))
        painter.drawRoundedRect(rect.adjusted(-grow, -grow, grow, grow), radius + grow, radius + grow)

    if dark_underlay > 0:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color((8, 30, 48), dark_underlay))
        painter.drawRoundedRect(rect, radius, radius)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_color(T.PILL_TINT, 0.46))
    painter.drawRoundedRect(rect, radius, radius)

    width = max(1.6, 3.0 * scale)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_color(T.WHITE, 0.92), width))
    inset = width / 2.0
    painter.drawRoundedRect(rect.adjusted(inset, inset, -inset, -inset), radius, radius)
    painter.restore()


# ---------------------------------------------------------------------------
# Tipografia com sombreamento suave (contraste sobre vidro)
# ---------------------------------------------------------------------------
def paint_shadowed_text(
    painter: QPainter,
    rect: QRectF,
    flags: int,
    text: str,
    font: QFont,
    color: QColor,
    *,
    scale: float = 1.0,
    offset: Tuple[float, float] = T.TEXT_SHADOW_OFFSET,
    shadow_rgba: Tuple[int, int, int, int] = T.TEXT_SHADOW_RGBA,
) -> None:
    """Desenha texto com halo de sombra suave projetada para alta legibilidade."""
    if not text:
        return
    painter.save()
    painter.setFont(font)

    fg_alpha = max(0.0, min(1.0, color.alphaF()))
    s_scale = max(0.65, scale)
    dx = offset[0] * s_scale
    dy = max(1.0, offset[1] * s_scale)
    r, g, b, base_a = shadow_rgba
    base_alpha = (base_a / 255.0) * fg_alpha

    # Camada difusa para replicar o relevo suave das telas de referencia
    blur_alpha = base_alpha * 0.28
    if blur_alpha > 0.01:
        blur_color = QColor(r, g, b)
        blur_color.setAlphaF(blur_alpha)
        painter.setPen(blur_color)
        for bx, by in ((-1.0 * s_scale, dy * 0.85), (1.0 * s_scale, dy * 0.85), (dx, dy * 1.45)):
            painter.drawText(rect.translated(bx, by), flags, text)

    # Sombra direcional principal
    core_alpha = base_alpha * 0.72
    if core_alpha > 0.01:
        core_color = QColor(r, g, b)
        core_color.setAlphaF(core_alpha)
        painter.setPen(core_color)
        painter.drawText(rect.translated(dx, dy), flags, text)

    painter.setPen(color)
    painter.drawText(rect, flags, text)
    painter.restore()
