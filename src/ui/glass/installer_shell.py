# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
DA-V Glass Design System - Shell Grafico Multiplataforma do Instalador (v5.0)
Autor: Dante Ferraz (MonoTech)

Unifica os instaladores oficiais de Windows e Linux no mesmo sistema visual Glassmorphism
da aplicacao principal:
- Fundo em gradiente menta-ciano-petroleo (`paint.background_pixmap`)
- Superficie unificada `GlassCard(dark=True)` com halo luminoso e reflexo especular
- Stepper lateral em pilula neon com icones vetoriais sombreados (`QPainterPath`)
- Botoes `GlassButton`, controles translúcidos (`qss.sheet_qss`) e escala responsiva (`ui_scale`)
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import List, Optional

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.ui.glass import icons, paint, qss
from src.ui.glass import tokens as T
from src.ui.glass.widgets import GlassButton, GlassCard, GlassLabel


def read_bundled_version(default: str = "5.0.0") -> str:
    """Resolve a versao atual a partir do arquivo VERSION em fonte ou bundle PyInstaller."""
    candidates: List[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "VERSION")
    candidates.append(Path(sys.executable).resolve().parent / "VERSION")
    candidates.append(Path(__file__).resolve().parents[3] / "VERSION")
    for cand in candidates:
        try:
            if cand.is_file():
                val = cand.read_text(encoding="utf-8").strip()
                if val:
                    return val
        except Exception:
            pass
    return default


class GlassVectorEmblem(QWidget):
    """Emblema vetorial circular/arredondado desenhado em QPainter (sem imagens nem Unicode extra)."""

    def __init__(
        self,
        kind: str = "step",
        step_num: int = 1,
        tone: str = "muted",
        size_px: int = 30,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._kind = kind      # "step" | "check" | "chip" | "display" | "shield" | "alert" | "dot"
        self._step_num = int(step_num)
        self._tone = tone      # "muted" | "active" | "ok" | "warn"
        self._base_size = int(size_px)
        self._scale = 1.0
        self.setAutoFillBackground(False)
        self.apply_scale(1.0)

    def set_visual(self, kind: str, tone: str) -> None:
        self._kind = kind
        self._tone = tone
        self.update()

    def apply_scale(self, scale: float) -> None:
        self._scale = scale
        s = max(18, int(round(self._base_size * max(0.82, min(1.25, scale * 1.32)))))
        self.setFixedSize(s, s)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        rad = r.height() / 2.0

        if self._tone == "active":
            p.setPen(QPen(QColor(255, 255, 255, 240), 1.8))
            p.setBrush(QColor(56, 189, 248, 92))
        elif self._tone == "ok":
            p.setPen(QPen(QColor(134, 239, 172, 235), 1.6))
            p.setBrush(QColor(16, 185, 129, 78))
        elif self._tone == "warn":
            p.setPen(QPen(QColor(253, 224, 71, 230), 1.6))
            p.setBrush(QColor(245, 158, 11, 78))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 125), 1.2))
            p.setBrush(QColor(255, 255, 255, 24))

        p.drawRoundedRect(r, rad, rad)

        ic_pad = r.width() * 0.20
        box = r.adjusted(ic_pad, ic_pad, -ic_pad, -ic_pad)
        if self._kind == "check":
            icons.draw_check(p, box, alpha=1.0)
        elif self._kind == "chip":
            icons.draw_chip(p, box, alpha=0.96)
        elif self._kind == "display":
            icons.draw_display(p, box, alpha=0.96)
        elif self._kind == "shield":
            icons.draw_shield(p, box, alpha=0.96, checked=(self._tone == "ok"))
        elif self._kind == "alert":
            icons.draw_alert(p, box, alpha=1.0)
        elif self._kind == "dot":
            c_rad = r.width() * (0.22 if self._tone == "active" else 0.16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 235 if self._tone == "active" else 135))
            p.drawEllipse(QPointF(r.center().x(), r.center().y()), c_rad, c_rad)
        else:
            f = QFont()
            f.setFamilies(T.FONT_FAMILIES)
            f.setPixelSize(max(10, int(r.height() * 0.44)))
            f.setWeight(QFont.Weight.Bold)
            fg = QColor(255, 255, 255, 255 if self._tone == "active" else 190)
            paint.paint_shadowed_text(
                p,
                r,
                int(Qt.AlignmentFlag.AlignCenter),
                str(self._step_num),
                f,
                fg,
                scale=self._scale,
            )
        p.end()


class GlassStepperItem(QWidget):
    """Item da barra lateral de etapas do instalador com realce em vidro."""

    def __init__(self, step_num: int, title: str, subtitle: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.step_num = int(step_num)
        self._state = "pending"
        self.setAutoFillBackground(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)

        self.emblem = GlassVectorEmblem(kind="step", step_num=step_num, tone="muted", size_px=28, parent=self)
        lay.addWidget(self.emblem)

        txt_col = QVBoxLayout()
        txt_col.setSpacing(1)
        self.lbl_title = QLabel(title)
        self.lbl_sub = QLabel(subtitle)
        txt_col.addWidget(self.lbl_title)
        txt_col.addWidget(self.lbl_sub)
        lay.addLayout(txt_col, stretch=1)

        self.set_state("pending")

    def set_state(self, state: str) -> None:
        self._state = state
        if state == "active":
            self.emblem.set_visual("step", "active")
            self.lbl_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #ffffff;")
            self.lbl_sub.setStyleSheet("font-size: 11px; color: #d8f3f3;")
        elif state == "completed":
            self.emblem.set_visual("check", "ok")
            self.lbl_title.setStyleSheet("font-size: 13px; font-weight: 600; color: #d8f8e8;")
            self.lbl_sub.setStyleSheet("font-size: 11px; color: #b7e4dc;")
        else:
            self.emblem.set_visual("step", "muted")
            self.lbl_title.setStyleSheet("font-size: 13px; font-weight: 600; color: rgba(255,255,255,0.68);")
            self.lbl_sub.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.48);")
        self.update()

    def paintEvent(self, event):
        if self._state == "active":
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            r = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
            p.setPen(QPen(QColor(255, 255, 255, 165), 1.2))
            p.setBrush(QColor(255, 255, 255, 34))
            p.drawRoundedRect(r, 11.0, 11.0)
            p.end()
        super().paintEvent(event)


class GlassDiagnosticStrip(QWidget):
    """Faixa translúcida de diagnostico de GPU / Servidor Grafico com icone vetorial e pilula de status."""

    def __init__(
        self,
        icon_kind: str,
        title: str,
        subtitle: str,
        badge_text: str,
        ok: bool = True,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)

        self.emblem = GlassVectorEmblem(
            kind=icon_kind,
            tone="ok" if ok else "active",
            size_px=34,
            parent=self,
        )
        lay.addWidget(self.emblem)

        col = QVBoxLayout()
        col.setSpacing(2)
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {'#a7f3d0' if ok else '#ffffff'};"
        )
        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setWordWrap(True)
        self.lbl_sub.setStyleSheet("font-size: 11px; color: #cfe8e8;")
        col.addWidget(self.lbl_title)
        col.addWidget(self.lbl_sub)
        lay.addLayout(col, stretch=1)

        self.lbl_badge = QLabel(badge_text)
        bd_col = "rgba(134,239,172,0.85)" if ok else "rgba(255,255,255,0.72)"
        bg_col = "rgba(16,185,129,0.24)" if ok else "rgba(255,255,255,0.14)"
        fg_col = "#d1fae5" if ok else "#ffffff"
        self.lbl_badge.setStyleSheet(
            f"background: {bg_col}; color: {fg_col}; border: 1px solid {bd_col}; "
            f"border-radius: 9px; padding: 3px 10px; font-size: 10px; font-weight: 800;"
        )
        lay.addWidget(self.lbl_badge, alignment=Qt.AlignmentFlag.AlignVCenter)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        p.setPen(QPen(QColor(255, 255, 255, 115), 1.1))
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(r, 12.0, 12.0)
        p.end()
        super().paintEvent(event)


class GlassInstallStepRow(QWidget):
    """Linha deterministica da etapa de instalacao com icone vetorial de estado (WCAG 2.2 POUR)."""

    def __init__(self, initial_text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(10)

        self.emblem = GlassVectorEmblem(kind="dot", tone="muted", size_px=22, parent=self)
        lay.addWidget(self.emblem, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.lbl = QLabel(initial_text)
        self.lbl.setWordWrap(True)
        self.lbl.setStyleSheet("font-size: 12px; color: rgba(255,255,255,0.72);")
        lay.addWidget(self.lbl, stretch=1)

    def set_status(self, state: str, text: str) -> None:
        """Atualiza estado: 'pending' | 'running' | 'ok' | 'warn' | 'skipped'."""
        self.lbl.setText(text)
        if state == "ok":
            self.emblem.set_visual("check", "ok")
            self.lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #a7f3d0;")
        elif state == "warn":
            self.emblem.set_visual("alert", "warn")
            self.lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #fde68a;")
        elif state == "running":
            self.emblem.set_visual("dot", "active")
            self.lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #ffffff;")
        else:
            self.emblem.set_visual("dot", "muted")
            self.lbl.setStyleSheet("font-size: 12px; color: rgba(255,255,255,0.68);")


class DavGlassInstallerDialog(QDialog):
    """Dialogo base do instalador DA-V v5.0 com estetica Glassmorphism identica ao aplicativo."""

    def __init__(
        self,
        window_title: str,
        platform_edition: str,
        step_definitions: List[tuple[str, str]],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.version_str = read_bundled_version()
        self._platform_edition = platform_edition
        self._step_defs = step_definitions
        self.current_step = 0
        self._ui_scale = 0.68

        self.setWindowTitle(window_title)
        self.setMinimumSize(820, 520)
        self.resize(900, 560)

        self._build_glass_shell()
        self._sync_scale()
        self._update_step_view()

    def _build_glass_shell(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)

        self.glass_card = GlassCard(self, dark=True)
        outer.addWidget(self.glass_card, stretch=1)

        # Substitui margens internas padrao do GlassCard para acomodar rail lateral + palco
        self._card_inner = QHBoxLayout()
        self._card_inner.setContentsMargins(0, 0, 0, 0)
        self._card_inner.setSpacing(18)
        self.glass_card.content_layout.addLayout(self._card_inner, stretch=1)

        # ── 1. Rail Lateral de Vidro (Marca + Stepper + Licenca) ─────────────
        self.sidebar = QWidget(self.glass_card)
        self.sidebar.setAutoFillBackground(False)
        self.sidebar.setStyleSheet("background: transparent;")
        self.sidebar.setFixedWidth(238)
        side_lay = QVBoxLayout(self.sidebar)
        side_lay.setContentsMargins(4, 6, 8, 6)
        side_lay.setSpacing(12)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        self.brand_icon = QLabel()
        self.brand_icon.setFixedSize(38, 38)
        icon_png = self._resolve_bundled_icon("png")
        if icon_png and icon_png.is_file():
            pm = QPixmap(str(icon_png)).scaled(
                38, 38, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self.brand_icon.setPixmap(pm)
        brand_row.addWidget(self.brand_icon)

        brand_col = QVBoxLayout()
        brand_col.setSpacing(0)
        self.lbl_brand_name = GlassLabel("DA-V", design_px=34, weight=700)
        self.lbl_brand_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_brand_sub = QLabel("Distribuidor Amplo de Vídeo")
        self.lbl_brand_sub.setStyleSheet("font-size: 11px; color: #cfe8e8; font-weight: 500;")
        brand_col.addWidget(self.lbl_brand_name)
        brand_col.addWidget(self.lbl_brand_sub)
        brand_row.addLayout(brand_col, stretch=1)
        side_lay.addLayout(brand_row)

        h_div = QFrame()
        h_div.setFrameShape(QFrame.Shape.HLine)
        h_div.setStyleSheet("border: none; border-top: 1px solid rgba(255,255,255,0.25); margin: 4px 0;")
        side_lay.addWidget(h_div)

        self.stepper_items: List[GlassStepperItem] = []
        for idx, (st_title, st_sub) in enumerate(self._step_defs, start=1):
            item = GlassStepperItem(idx, st_title, st_sub, parent=self.sidebar)
            self.stepper_items.append(item)
            side_lay.addWidget(item)

        side_lay.addStretch(1)

        self.lbl_footer = QLabel(
            f"DA-V v{self.version_str} · {self._platform_edition}\n"
            "Dante Ferraz · MonoTech\n"
            "GNU AGPLv3 + Seção 7 NOTICE"
        )
        self.lbl_footer.setStyleSheet("font-size: 10px; color: rgba(255,255,255,0.64);")
        side_lay.addWidget(self.lbl_footer)

        self._card_inner.addWidget(self.sidebar)

        # Divisor vertical translucido
        v_div = QFrame(self.glass_card)
        v_div.setFrameShape(QFrame.Shape.VLine)
        v_div.setStyleSheet("border: none; border-left: 1px solid rgba(255,255,255,0.24);")
        self._card_inner.addWidget(v_div)

        # ── 2. Palco Principal + Navegacao em Pilulas GlassButton ────────────
        self.stage_host = QWidget(self.glass_card)
        self.stage_host.setAutoFillBackground(False)
        self.stage_host.setStyleSheet("background: transparent;")
        self.stage_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        stage_lay = QVBoxLayout(self.stage_host)
        stage_lay.setContentsMargins(8, 6, 4, 4)
        stage_lay.setSpacing(14)

        self.stack = QStackedWidget(self.stage_host)
        self.stack.setAutoFillBackground(False)
        self.page_welcome = self._create_page_welcome()
        self.page_options = self._create_page_options()
        self.page_progress = self._create_page_progress()
        self.page_finish = self._create_page_finish()

        for p in (self.page_welcome, self.page_options, self.page_progress, self.page_finish):
            p.setAutoFillBackground(False)
            self.stack.addWidget(p)
        stage_lay.addWidget(self.stack, stretch=1)

        nav_div = QFrame(self.stage_host)
        nav_div.setFrameShape(QFrame.Shape.HLine)
        nav_div.setStyleSheet("border: none; border-top: 1px solid rgba(255,255,255,0.20);")
        stage_lay.addWidget(nav_div)

        nav_row = QHBoxLayout()
        nav_row.setContentsMargins(0, 2, 0, 0)
        nav_row.setSpacing(10)

        self.btn_cancel = GlassButton("Cancelar", design_w=200, design_h=56, design_font=22, parent=self.stage_host)
        self.btn_cancel.clicked.connect(self.reject)
        nav_row.addWidget(self.btn_cancel)

        nav_row.addStretch(1)

        self.btn_back = GlassButton("Voltar", design_w=185, design_h=56, design_font=22, parent=self.stage_host)
        self.btn_back.clicked.connect(self._go_back)
        nav_row.addWidget(self.btn_back)

        self.btn_next = GlassButton("Continuar", design_w=295, design_h=56, design_font=22, parent=self.stage_host)
        self.btn_next.clicked.connect(self._go_next)
        nav_row.addWidget(self.btn_next)

        stage_lay.addLayout(nav_row)
        self._card_inner.addWidget(self.stage_host, stretch=1)

    @staticmethod
    def _make_option_block(chk: QCheckBox, subtitle: str) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(3)
        lay.addWidget(chk)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setWordWrap(True)
            sub.setStyleSheet("font-size: 11px; color: #cfe8e8; padding-left: 26px;")
            lay.addWidget(sub)
        return box

    def _make_page_header(self, title: str, subtitle: str) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(4)
        lbl_t = GlassLabel(title, design_px=30, weight=700, wrap=True)
        lbl_t.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lbl_s = QLabel(subtitle)
        lbl_s.setWordWrap(True)
        lbl_s.setStyleSheet("font-size: 13px; color: #d8f3f3;")
        col.addWidget(lbl_t)
        col.addWidget(lbl_s)
        return col

    # ── Hooks implementados pelas subclasses Windows / Linux ─────────────────
    @classmethod
    def _resolve_bundled_icon(cls, ext: str = "png") -> Optional[Path]:
        return None

    def _create_page_welcome(self) -> QWidget:
        raise NotImplementedError

    def _create_page_options(self) -> QWidget:
        raise NotImplementedError

    def _create_page_progress(self) -> QWidget:
        raise NotImplementedError

    def _create_page_finish(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(16)

        emblem = GlassVectorEmblem(kind="check", tone="ok", size_px=56, parent=w)
        lay.addWidget(emblem, alignment=Qt.AlignmentFlag.AlignLeft)

        lay.addLayout(
            self._make_page_header(
                "Instalação Concluída com Sucesso",
                self._finish_description_text(),
            )
        )

        self.chk_launch = QCheckBox("Iniciar o DA-V agora")
        self.chk_launch.setChecked(True)
        lay.addWidget(
            self._make_option_block(
                self.chk_launch,
                "Abre imediatamente o hub principal Glassmorphism pronto para transmitir ou controlar remotamente.",
            )
        )
        lay.addStretch(1)
        return w

    def _finish_description_text(self) -> str:
        return "O DA-V foi integrado ao sistema com suporte a streaming 60/120 FPS e área de trabalho remota."

    def _execute_installation(self) -> None:
        raise NotImplementedError

    def _launch_app(self) -> None:
        raise NotImplementedError

    # ── Escala, Pintura de Fundo e Navegacao ─────────────────────────────────
    def _sync_scale(self) -> None:
        w, h = max(600, self.width()), max(420, self.height())
        scale = max(0.56, min(0.88, T.ui_scale(w * 1.25, h * 1.35)))
        self._ui_scale = scale
        self.glass_card.set_scale(scale)
        m = paint.glow_margin(scale)
        pad_x = T.px(24, scale, 10)
        pad_y = T.px(18, scale, 8)
        self.glass_card.content_layout.setContentsMargins(m + pad_x, m + pad_y, m + pad_x, m + pad_y)
        self.stack.setStyleSheet(
            "QDialog, QStackedWidget { background: transparent; border: none; }\n"
            + qss.sheet_qss(max(0.66, scale))
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_scale()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w > 0 and h > 0:
            pix = paint.background_pixmap(w, h, self.devicePixelRatioF())
            p = QPainter(self)
            p.drawPixmap(0, 0, pix)
            p.end()

    def _update_step_view(self) -> None:
        self.stack.setCurrentIndex(self.current_step)
        for idx, item in enumerate(self.stepper_items):
            if idx < self.current_step:
                item.set_state("completed")
            elif idx == self.current_step:
                item.set_state("active")
            else:
                item.set_state("pending")

        if self.current_step == 0:
            self.btn_back.setVisible(False)
            self.btn_cancel.setVisible(True)
            self.btn_next.setVisible(True)
            self.btn_next.setText("Continuar")
            self.btn_next.setEnabled(True)
        elif self.current_step == 1:
            self.btn_back.setVisible(True)
            self.btn_cancel.setVisible(True)
            self.btn_next.setVisible(True)
            self.btn_next.setText("Instalar Agora")
            self.btn_next.setEnabled(True)
        elif self.current_step == 2:
            self.btn_back.setVisible(False)
            self.btn_cancel.setVisible(False)
            self.btn_next.setVisible(False)
            if os.environ.get("DAV_INSTALLER_DRY_RUN") != "1":
                QTimer.singleShot(180, self._execute_installation)
        elif self.current_step == 3:
            self.btn_back.setVisible(False)
            self.btn_cancel.setVisible(False)
            self.btn_next.setVisible(True)
            self.btn_next.setText("Concluir e Abrir")
            self.btn_next.setEnabled(True)

    def _go_next(self) -> None:
        if self.current_step == 3:
            if self.chk_launch.isChecked():
                self._launch_app()
            self.accept()
            return
        self.current_step = min(self.current_step + 1, 3)
        self._update_step_view()

    def _go_back(self) -> None:
        self.current_step = max(self.current_step - 1, 0)
        self._update_step_view()

    def _advance_to_finish(self) -> None:
        self.current_step = 3
        self._update_step_view()
