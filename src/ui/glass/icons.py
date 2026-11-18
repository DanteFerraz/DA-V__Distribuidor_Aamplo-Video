# -*- coding: utf-8 -*-
"""
DA-V Glass Design System - Icones vetoriais
Autor: Dante Ferraz (MonoTech)

Icones desenhados com QPainterPath (sem arquivos de imagem e sem emoji), escalaveis e
nitidos em qualquer DPI. Cada funcao desenha dentro de um QRectF quadrado e aplica
sombreamento projetado suave para legibilidade sobre vidro ou video ao vivo.
"""

from __future__ import annotations

import math
from typing import Callable

from src.ui.glass import tokens as T
from src.ui.qt_compat import QColor, QPainter, QPainterPath, QPen, QPointF, QRectF, Qt


def _white(alpha: float = 1.0) -> QColor:
    c = QColor(255, 255, 255)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _shadow_color(alpha: float, weight: float) -> QColor:
    r, g, b, base_a = T.ICON_SHADOW_RGBA
    c = QColor(r, g, b)
    c.setAlphaF(max(0.0, min(1.0, (base_a / 255.0) * alpha * weight)))
    return c


def _render_shadowed(
    p: QPainter,
    box: QRectF,
    alpha: float,
    draw_geom: Callable[[QPainter, QRectF, QColor], None],
    *,
    shadow: bool = True,
) -> None:
    """Renderiza geometria vetorial com duas camadas suaves de sombra antes do traço principal."""
    if alpha <= 0.005:
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if shadow:
        dy = max(1.0, min(box.width(), box.height()) * 0.045)
        c = box.center()
        halo_box = QRectF(
            c.x() - box.width() * 0.52,
            c.y() - box.height() * 0.52,
            box.width() * 1.04,
            box.height() * 1.04,
        )
        p.save()
        p.translate(0.0, dy * 1.15)
        draw_geom(p, halo_box, _shadow_color(alpha, 0.42))
        p.restore()

        p.save()
        p.translate(0.0, dy * 0.85)
        draw_geom(p, box, _shadow_color(alpha, 0.72))
        p.restore()

    draw_geom(p, box, _white(alpha))
    p.restore()


def _draw_menu_geom(p: QPainter, box: QRectF, color: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    bar_h = box.height() * 0.15
    gap = box.height() * 0.17
    total = bar_h * 3 + gap * 2
    y = box.center().y() - total / 2.0
    w = box.width() * 0.86
    x = box.center().x() - w / 2.0
    for _ in range(3):
        p.drawRoundedRect(QRectF(x, y, w, bar_h), bar_h / 2, bar_h / 2)
        y += bar_h + gap


def draw_menu(p: QPainter, box: QRectF, alpha: float = 1.0, shadow: bool = True) -> None:
    """Tres barras horizontais (hamburger)."""
    _render_shadowed(p, box, alpha, _draw_menu_geom, shadow=shadow)


def _gear_path(c: QPointF, r: float, teeth: int = 8) -> QPainterPath:
    """Engrenagem: contorno com dentes trapezoidais e furo central."""
    outer, root = r, r * 0.74
    pts = []
    step = 2 * math.pi / teeth
    half_tooth = step * 0.22
    half_base = step * 0.31
    for k in range(teeth):
        a = k * step - math.pi / 2
        for ang, rad in (
            (a - half_base, root),
            (a - half_tooth, outer),
            (a + half_tooth, outer),
            (a + half_base, root),
        ):
            pts.append(QPointF(c.x() + rad * math.cos(ang), c.y() + rad * math.sin(ang)))
    path = QPainterPath()
    path.moveTo(pts[0])
    for pt in pts[1:]:
        path.lineTo(pt)
    path.closeSubpath()
    hole = QPainterPath()
    hole.addEllipse(c, r * 0.34, r * 0.34)
    return path.subtracted(hole)


def _draw_gear_geom(p: QPainter, box: QRectF, color: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(_gear_path(box.center(), min(box.width(), box.height()) / 2.0))


def draw_gear(p: QPainter, box: QRectF, alpha: float = 1.0, shadow: bool = True) -> None:
    """Engrenagem (configuracoes)."""
    _render_shadowed(p, box, alpha, _draw_gear_geom, shadow=shadow)


def _arrow_head(p: QPainter, center: QPointF, radius: float, angle_deg: float, size: float) -> None:
    """Ponta de seta no fim de um arco percorrido no sentido anti-horario."""
    a = math.radians(angle_deg)
    tip_base = QPointF(center.x() + radius * math.cos(a), center.y() - radius * math.sin(a))
    tangent = QPointF(-math.sin(a), -math.cos(a))
    radial = QPointF(math.cos(a), -math.sin(a))
    tip = QPointF(tip_base.x() + tangent.x() * size * 1.1, tip_base.y() + tangent.y() * size * 1.1)
    b1 = QPointF(tip_base.x() + radial.x() * size, tip_base.y() + radial.y() * size)
    b2 = QPointF(tip_base.x() - radial.x() * size, tip_base.y() - radial.y() * size)
    head = QPainterPath()
    head.moveTo(tip)
    head.lineTo(b1)
    head.lineTo(b2)
    head.closeSubpath()
    p.drawPath(head)


def _draw_refresh_geom(p: QPainter, box: QRectF, color: QColor) -> None:
    size = min(box.width(), box.height())
    c = box.center()
    r = size * 0.36
    stroke = size * 0.15
    arc_rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)

    pen = QPen(color, stroke)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    sweep = 128
    for start in (28, 208):
        p.drawArc(arc_rect, int(start * 16), int(sweep * 16))

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    for start in (28, 208):
        _arrow_head(p, c, r, start + sweep, stroke * 1.15)


def draw_refresh(p: QPainter, box: QRectF, alpha: float = 1.0, shadow: bool = True) -> None:
    """Duas setas circulares (alternar modo)."""
    _render_shadowed(p, box, alpha, _draw_refresh_geom, shadow=shadow)


def _draw_chart_geom(p: QPainter, box: QRectF, color: QColor) -> None:
    size = min(box.width(), box.height())
    side = size * 0.98
    sq = QRectF(box.center().x() - side / 2, box.center().y() - side / 2, side, side)
    body = QPainterPath()
    body.addRoundedRect(sq, side * 0.10, side * 0.10)

    bars = QPainterPath()
    bw = side * 0.14
    gap = side * 0.085
    base = sq.bottom() - side * 0.17
    heights = (0.26, 0.50, 0.36)
    total = bw * 3 + gap * 2
    x = sq.center().x() - total / 2
    for h in heights:
        bh = side * h
        bars.addRoundedRect(QRectF(x, base - bh, bw, bh), bw * 0.12, bw * 0.12)
        x += bw + gap
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(body.subtracted(bars))


def draw_chart(p: QPainter, box: QRectF, alpha: float = 1.0, shadow: bool = True) -> None:
    """Quadrado arredondado com tres barras vazadas (estatisticas)."""
    _render_shadowed(p, box, alpha, _draw_chart_geom, shadow=shadow)


def _draw_speaker_geom(p: QPainter, box: QRectF, color: QColor, *, muted: bool) -> None:
    size = min(box.width(), box.height())
    left = box.center().x() - size * 0.5
    top = box.center().y() - size * 0.5

    # Corpo do alto-falante (base retangular + cone trapezoidal)
    cone = QPainterPath()
    cone.moveTo(left + size * 0.12, top + size * 0.37)
    cone.lineTo(left + size * 0.31, top + size * 0.37)
    cone.lineTo(left + size * 0.51, top + size * 0.20)
    cone.lineTo(left + size * 0.51, top + size * 0.80)
    cone.lineTo(left + size * 0.31, top + size * 0.63)
    cone.lineTo(left + size * 0.12, top + size * 0.63)
    cone.closeSubpath()

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(cone)

    # Ondas sonoras (atenuadas quando silenciado)
    wave_color = QColor(color)
    if muted:
        wave_color.setAlphaF(max(0.0, color.alphaF() * 0.28))

    stroke = max(1.4, size * 0.085)
    pen = QPen(wave_color, stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    origin = QPointF(left + size * 0.52, box.center().y())
    for radius in (size * 0.20, size * 0.34):
        arc_rect = QRectF(origin.x() - radius, origin.y() - radius, 2 * radius, 2 * radius)
        p.drawArc(arc_rect, -42 * 16, 84 * 16)

    if muted:
        slash_pen = QPen(color, max(1.6, size * 0.10))
        slash_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(slash_pen)
        p.drawLine(
            QPointF(left + size * 0.14, top + size * 0.18),
            QPointF(left + size * 0.86, top + size * 0.84),
        )


def draw_speaker(
    p: QPainter,
    box: QRectF,
    alpha: float = 1.0,
    muted: bool = False,
    shadow: bool = True,
) -> None:
    """Alto-falante com ondas sonoras (e traco diagonal quando silenciado)."""
    _render_shadowed(
        p,
        box,
        alpha,
        lambda qp, rc, col: _draw_speaker_geom(qp, rc, col, muted=muted),
        shadow=shadow,
    )


def _draw_fullscreen_geom(p: QPainter, box: QRectF, color: QColor, *, is_fullscreen: bool) -> None:
    size = min(box.width(), box.height())
    stroke = max(1.6, size * 0.11)
    pad = size * 0.15
    cx, cy = box.center().x(), box.center().y()
    half = size * 0.5 - pad
    arm = size * 0.23

    pen = QPen(color, stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    corners = ((-1, -1), (1, -1), (-1, 1), (1, 1))
    for sx, sy in corners:
        path = QPainterPath()
        if not is_fullscreen:
            # Quatro cantos voltados para fora (entrar em tela cheia)
            vx = cx + sx * half
            vy = cy + sy * half
            path.moveTo(vx - sx * arm, vy)
            path.lineTo(vx, vy)
            path.lineTo(vx, vy - sy * arm)
        else:
            # Quatro cantos voltados para dentro (sair da tela cheia)
            vx = cx + sx * (half - arm)
            vy = cy + sy * (half - arm)
            path.moveTo(vx + sx * arm, vy)
            path.lineTo(vx, vy)
            path.lineTo(vx, vy + sy * arm)
        p.drawPath(path)


def draw_fullscreen_corners(
    p: QPainter,
    box: QRectF,
    alpha: float = 1.0,
    is_fullscreen: bool = False,
    shadow: bool = True,
) -> None:
    """Moldura de quatro cantos para alternar o modo Tela Cheia."""
    _render_shadowed(
        p,
        box,
        alpha,
        lambda qp, rc, col: _draw_fullscreen_geom(qp, rc, col, is_fullscreen=is_fullscreen),
        shadow=shadow,
    )
