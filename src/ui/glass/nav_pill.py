# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
DA-V Glass Design System - Pilula de navegacao flutuante
Autor: Dante Ferraz (MonoTech)

Recolhida: um unico botao de menu. Expandida: tres acoes (configuracoes, alternar modo,
telemetria). Expande/recolhe com animacao suave, recolhe sozinha apos alguns segundos sem
uso e nao rouba o foco do teclado (a janela de video continua recebendo F11/F2/F3/F12).
"""

from __future__ import annotations

from typing import Optional

from src.ui.qt_compat import (
    Property, QColor, QEasingCurve, QPainter, QPointF, QPropertyAnimation, QRectF,
    QTimer, QToolTip, QWidget, Qt, Signal,
)
from src.ui.glass import icons, paint
from src.ui.glass import tokens as T

ZONE_SETTINGS, ZONE_SWAP, ZONE_STATS = 0, 1, 2
_ZONE_CENTERS = (0.142, 0.500, 0.858)       # centros dos icones na pilula expandida (referencia)
_IDLE_COLLAPSE_MS = 4500


class FloatingNavPill(QWidget):
    settings_clicked = Signal()
    swap_clicked = Signal()
    stats_clicked = Signal()
    expanded_changed = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._scale = 1.0
        self._progress = 0.0           # 0 = recolhida, 1 = expandida
        self._target_expanded = False
        self._hover_zone = -1
        self._active: Optional[str] = None    # "settings" | "stats" | None
        self._live = False
        self._underlay = 0.0
        self._swap_tip = "Alternar modo"

        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(_IDLE_COLLAPSE_MS)
        self._idle.timeout.connect(self.collapse)

        self._relayout()

    # ------------------------------------------------------------------ propriedades
    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        self._progress = float(value)
        self._relayout()
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    @property
    def expanded(self) -> bool:
        return self._target_expanded

    # ------------------------------------------------------------------ API publica
    def set_ui_scale(self, scale: float) -> None:
        self._scale = scale
        self._relayout()
        self.update()

    def set_active(self, which: Optional[str]) -> None:
        if which != self._active:
            self._active = which
            self.update()

    def set_live(self, live: bool) -> None:
        if live != self._live:
            self._live = live
            self.update()

    def set_over_video(self, over_video: bool) -> None:
        """Escurece levemente o fundo da pilula quando ela flutua sobre o video."""
        value = 0.34 if over_video else 0.0
        if value != self._underlay:
            self._underlay = value
            self.update()

    def set_swap_tooltip(self, text: str) -> None:
        self._swap_tip = text

    def expand(self) -> None:
        self._animate_to(True)

    def collapse(self) -> None:
        self._animate_to(False)

    def toggle(self) -> None:
        self._animate_to(not self._target_expanded)

    def _animate_to(self, expanded: bool) -> None:
        if expanded == self._target_expanded and self._anim.state() != QPropertyAnimation.State.Running:
            if (expanded and self._progress >= 1.0) or (not expanded and self._progress <= 0.0):
                return
        changed = expanded != self._target_expanded
        self._target_expanded = expanded
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(1.0 if expanded else 0.0)
        self._anim.start()
        if expanded:
            self._idle.start()
        else:
            self._idle.stop()
        if changed:
            self.expanded_changed.emit(expanded)

    # ------------------------------------------------------------------ geometria
    def _glow(self) -> int:
        return T.px(22, self._scale, 8)

    def _pill_size(self):
        cw, ch, ctop = T.PILL_COLLAPSED
        ew, eh, etop = T.PILL_EXPANDED
        t = self._progress
        w = (cw + (ew - cw) * t) * self._scale
        h = (ch + (eh - ch) * t) * self._scale
        top = (ctop + (etop - ctop) * t) * self._scale
        return max(60.0, w), max(24.0, h), top

    def _relayout(self) -> None:
        w, h, top = self._pill_size()
        g = self._glow()
        self.resize(int(w + 2 * g), int(h + 2 * g))
        self.reposition()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        w, h, top = self._pill_size()
        g = self._glow()
        self.move(int((parent.width() - w) / 2.0 - g), int(top - g))

    def _pill_rect(self) -> QRectF:
        g = self._glow()
        return QRectF(g, g, self.width() - 2 * g, self.height() - 2 * g)

    def _icon_box(self, zone: int) -> QRectF:
        r = self._pill_rect()
        size = 58.0 * self._scale
        cx = r.left() + r.width() * _ZONE_CENTERS[zone]
        return QRectF(cx - size / 2, r.center().y() - size / 2, size, size)

    def _zone_at(self, pos: QPointF) -> int:
        """Zona do icone sob o cursor (-1 se fora dos icones). So vale com a pilula expandida."""
        if self._progress < 0.6:
            return -1
        reach = 52.0 * self._scale
        for zone in (ZONE_SETTINGS, ZONE_SWAP, ZONE_STATS):
            c = self._icon_box(zone).center()
            if abs(pos.x() - c.x()) <= reach and abs(pos.y() - c.y()) <= reach:
                return zone
        return -1

    # ------------------------------------------------------------------ eventos
    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._progress < 0.5 and not self._target_expanded:
            self.expand()
            return
        zone = self._zone_at(event.position())
        if zone == ZONE_SETTINGS:
            self.settings_clicked.emit()
        elif zone == ZONE_SWAP:
            self.swap_clicked.emit()
        elif zone == ZONE_STATS:
            self.stats_clicked.emit()
        else:
            self.collapse()
            return
        self._idle.start()

    def mouseMoveEvent(self, event):
        zone = self._zone_at(event.position())
        if zone != self._hover_zone:
            self._hover_zone = zone
            self.update()

    def enterEvent(self, event):
        self._idle.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_zone = -1
        if self._target_expanded:
            self._idle.start()
        self.update()
        super().leaveEvent(event)

    def event(self, ev):
        if ev.type() == ev.Type.ToolTip:
            zone = self._zone_at(ev.pos().toPointF()) if hasattr(ev.pos(), "toPointF") else -1
            if self._progress < 0.5:
                text = "Menu"
            else:
                text = {ZONE_SETTINGS: "Configuracoes", ZONE_SWAP: self._swap_tip,
                        ZONE_STATS: "Telemetria, dispositivos e registros"}.get(zone, "")
            if text:
                QToolTip.showText(ev.globalPos(), text, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(ev)

    # ------------------------------------------------------------------ pintura
    def paintEvent(self, event):
        p = QPainter(self)
        rect = self._pill_rect()
        paint.paint_pill_surface(p, rect, self._scale, glow=0.7 + 0.3 * self._progress,
                                 dark_underlay=self._underlay)
        t = self._progress

        # icone de menu (recolhida)
        if t < 0.98:
            size = 36.0 * self._scale
            box = QRectF(rect.center().x() - size / 2, rect.center().y() - size / 2, size, size)
            icons.draw_menu(p, box, alpha=1.0 - t)

        # tres acoes (expandida)
        if t > 0.02:
            draw = (icons.draw_gear, icons.draw_refresh, icons.draw_chart)
            actives = ("settings", None, "stats")
            for zone in (ZONE_SETTINGS, ZONE_SWAP, ZONE_STATS):
                box = self._icon_box(zone)
                if zone == self._hover_zone or (actives[zone] and actives[zone] == self._active):
                    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                    p.setPen(Qt.PenStyle.NoPen)
                    glow_a = 0.30 if zone == self._hover_zone else 0.20
                    p.setBrush(QColor(255, 255, 255, int(255 * glow_a * t)))
                    c = box.center()
                    rad = 46.0 * self._scale
                    p.drawEllipse(c, rad, rad)
                scale_up = 1.0 + (0.08 if zone == self._hover_zone else 0.0)
                bsize = box.width() * scale_up
                bb = QRectF(box.center().x() - bsize / 2, box.center().y() - bsize / 2, bsize, bsize)
                draw[zone](p, bb, alpha=t)

        # indicador de transmissao ativa
        if self._live:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            d = 11.0 * self._scale
            cx = rect.right() - 18.0 * self._scale - d / 2
            cy = rect.top() + rect.height() * 0.5
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 70))
            p.drawEllipse(QPointF(cx, cy), d * 1.0, d * 1.0)
            p.setBrush(QColor(255, 120, 120, 255))
            p.drawEllipse(QPointF(cx, cy), d * 0.5, d * 0.5)
        p.end()

