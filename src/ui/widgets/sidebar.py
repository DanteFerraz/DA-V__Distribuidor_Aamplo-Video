# -*- coding: utf-8 -*-
"""
DA-V Sidebar Navigation Rail
Modern collapsible lateral navigation bar inspired by AnyDesk, Parsec and Discord.
"""

from scripts.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, Signal, Qt, QFont
)
from src.ui.theme import Theme


class SidebarButton(QPushButton):
    """Navigation button with custom active indicator, icon, label, and badge."""

    def __init__(self, page_index: int, icon_str: str, label_text: str, parent=None):
        super().__init__(parent)
        self.page_index = page_index
        self.icon_str = icon_str
        self.label_text = label_text
        self.is_active = False
        self.is_collapsed = False
        self.badge_text = ""

        self.setCheckable(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)
        self._update_appearance()

    def set_active(self, active: bool):
        self.is_active = active
        self._update_appearance()

    def set_collapsed(self, collapsed: bool):
        self.is_collapsed = collapsed
        self._update_appearance()

    def set_badge(self, text: str):
        self.badge_text = text
        self._update_appearance()

    def _update_appearance(self):
        s = Theme.SYS
        bg_col = s["bg_surface_elevated"] if self.is_active else "transparent"
        txt_col = s["text_primary"] if self.is_active else s["text_secondary"]
        border_left = f"3px solid {s['accent_primary']}" if self.is_active else "3px solid transparent"

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_col};
                color: {txt_col};
                text-align: left;
                padding-left: {14 if not self.is_collapsed else 0}px;
                border: none;
                border-left: {border_left};
                border-radius: 6px;
                font-weight: {'700' if self.is_active else '500'};
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {s["bg_surface_hover"]};
                color: {s["text_primary"]};
            }}
        """)

        if self.is_collapsed:
            self.setText(self.icon_str)
            self.setToolTip(f"{self.label_text} {f'({self.badge_text})' if self.badge_text else ''}")
        else:
            badge_suffix = f"  [{self.badge_text}]" if self.badge_text else ""
            self.setText(f"{self.icon_str}   {self.label_text}{badge_suffix}")
            self.setToolTip("")


class SidebarNavigation(QFrame):
    """Collapsible lateral navigation bar for the main application."""
    page_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_collapsed = False
        self.current_page = 0
        self.buttons: list[SidebarButton] = []

        self.setObjectName("sidebarFrame")
        self.setStyleSheet(f"""
            QFrame#sidebarFrame {{
                background-color: {Theme.SYS["bg_surface"]};
                border-right: 1px solid {Theme.SYS["border_subtle"]};
            }}
        """)
        self.setFixedWidth(230)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Theme.SPACE_MD, Theme.SPACE_LG, Theme.SPACE_MD, Theme.SPACE_LG)
        layout.setSpacing(Theme.SPACE_SM)

        # ── Logo & Brand Area ──
        self.brand_container = QWidget()
        brand_layout = QHBoxLayout(self.brand_container)
        brand_layout.setContentsMargins(4, 4, 4, 12)
        brand_layout.setSpacing(10)

        self.lbl_logo = QLabel("DA-V")
        self.lbl_logo.setStyleSheet(f"""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {Theme.SYS["accent_primary"]}, stop:1 {Theme.SYS["status_success"]});
            color: #070a0f;
            font-weight: 900;
            font-size: 11px;
            padding: 4px 8px;
            border-radius: 4px;
        """)
        brand_layout.addWidget(self.lbl_logo)

        self.lbl_brand_text = QLabel("Distribuidor Amplo")
        self.lbl_brand_text.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {Theme.SYS['text_primary']};")
        brand_layout.addWidget(self.lbl_brand_text)
        brand_layout.addStretch()

        layout.addWidget(self.brand_container)

        # ── Navigation Buttons ──
        nav_items = [
            (0, "▶", "Assistir / Receptor"),
            (1, "●", "Compartilhar Tela"),
            (2, "⚡", "Diagnóstico TUPÃ"),
            (3, "☊", "Dispositivos LAN"),
            (4, "🛠", "Troubleshooting"),
        ]

        for idx, icon, label in nav_items:
            btn = SidebarButton(idx, icon, label, self)
            btn.clicked.connect(lambda _, i=idx: self._on_btn_clicked(i))
            layout.addWidget(btn)
            self.buttons.append(btn)

        layout.addStretch()

        # ── Bottom Section: Collapse Button ──
        self.btn_collapse = QPushButton("«  Recolher Menu", self)
        self.btn_collapse.setObjectName("ghostBtn")
        self.btn_collapse.setFixedHeight(34)
        self.btn_collapse.clicked.connect(self.toggle_collapse)
        layout.addWidget(self.btn_collapse)

        # Select first page by default
        self.set_active_page(0)

    def _on_btn_clicked(self, page_index: int):
        self.set_active_page(page_index)
        self.page_changed.emit(page_index)

    def set_active_page(self, page_index: int):
        self.current_page = page_index
        for btn in self.buttons:
            btn.set_active(btn.page_index == page_index)

    def set_badge(self, page_index: int, text: str):
        if 0 <= page_index < len(self.buttons):
            self.buttons[page_index].set_badge(text)

    def toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        new_width = 64 if self.is_collapsed else 230
        self.setFixedWidth(new_width)

        self.lbl_brand_text.setVisible(not self.is_collapsed)
        self.btn_collapse.setText("»" if self.is_collapsed else "«  Recolher Menu")
        self.btn_collapse.setToolTip("Expandir Menu" if self.is_collapsed else "Recolher Menu")

        for btn in self.buttons:
            btn.set_collapsed(self.is_collapsed)
