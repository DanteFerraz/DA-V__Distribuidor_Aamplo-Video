# -*- coding: utf-8 -*-
"""
DA-V Glass Design System - Icones vetoriais
Autor: Dante Ferraz (MonoTech)

Icones desenhados com QPainterPath (sem arquivos de imagem e sem emoji), escalaveis e
nitidos em qualquer DPI. Cada funcao desenha dentro de um QRectF quadrado.
"""

from __future__ import annotations

import math

from scripts.qt_compat import QColor, QPainter, QPainterPath, QPen, QPointF, QRectF, Qt


def _white(alpha: float = 1.0) -> QColor:
    c = QColor(255, 255, 255)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def draw_menu(p: QPainter, box: QRectF, alpha: float = 1.0) -> None:
    """Tres barras horizontais (hamburger)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white(alpha))
    bar_h = box.height() * 0.15
    gap = box.height() * 0.17
    total = bar_h * 3 + gap * 2
    y = box.center().y() - total / 2.0
    w = box.width() * 0.86
    x = box.center().x() - w / 2.0
    for _ in range(3):
        p.drawRoundedRect(QRectF(x, y, w, bar_h), bar_h / 2, bar_h / 2)
        y += bar_h + gap
    p.restore()


def _gear_path(c: QPointF, r: float, teeth: int = 8) -> QPainterPath:
    """Engrenagem: contorno com dentes trapezoidais e furo central."""
    outer, root = r, r * 0.74
    pts = []
    step = 2 * math.pi / teeth
    half_tooth = step * 0.22     # meia largura do dente no topo
    half_base = step * 0.31      # meia largura do dente na base
    for k in range(teeth):
        a = k * step - math.pi / 2
        for ang, rad in ((a - half_base, root), (a - half_tooth, outer),
                         (a + half_tooth, outer), (a + half_base, root)):
            pts.append(QPointF(c.x() + rad * math.cos(ang), c.y() + rad * math.sin(ang)))
    path = QPainterPath()
    path.moveTo(pts[0])
    for pt in pts[1:]:
        path.lineTo(pt)
    path.closeSubpath()
    hole = QPainterPath()
    hole.addEllipse(c, r * 0.34, r * 0.34)
    return path.subtracted(hole)


def draw_gear(p: QPainter, box: QRectF, alpha: float = 1.0) -> None:
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white(alpha))
    p.drawPath(_gear_path(box.center(), min(box.width(), box.height()) / 2.0))
    p.restore()


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


def draw_refresh(p: QPainter, box: QRectF, alpha: float = 1.0) -> None:
    """Duas setas circulares (sincronizar / alternar)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    size = min(box.width(), box.height())
    c = box.center()
    r = size * 0.36
    stroke = size * 0.15
    arc_rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)

    pen = QPen(_white(alpha), stroke)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    sweep = 128
    for start in (28, 208):
        p.drawArc(arc_rect, int(start * 16), int(sweep * 16))

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_white(alpha))
    for start in (28, 208):
        _arrow_head(p, c, r, start + sweep, stroke * 1.15)
    p.restore()


def draw_chart(p: QPainter, box: QRectF, alpha: float = 1.0) -> None:
    """Quadrado arredondado com tres barras vazadas (estatisticas)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
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
    p.setBrush(_white(alpha))
    p.drawPath(body.subtracted(bars))
    p.restore()

