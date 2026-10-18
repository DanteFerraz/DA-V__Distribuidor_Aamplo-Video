# -*- coding: utf-8 -*-
"""
DA-V Reusable Metric Cards and Status Badges
Consistent presentation components adhering to the 4pt/8pt spatial grid.
"""

from scripts.qt_compat import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    Qt, QFont
)
from src.ui.theme import Theme


class StatCard(QFrame):
    """Card displaying a single key metric with title, large numeric value, and optional subtext."""

    def __init__(self, title: str, initial_value: str = "—", subtext: str = "", accent_color: str = "#38bdf8", parent=None):
        super().__init__(parent)
        self.accent_color = accent_color
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {Theme.SYS["bg_surface_card"]};
                border: 1px solid {Theme.SYS["border_subtle"]};
                border-radius: {Theme.RADIUS_MD}px;
                padding: 10px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        self.lbl_title = QLabel(title.upper())
        self.lbl_title.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 700;
            color: {Theme.SYS["text_muted"]};
            letter-spacing: 0.5px;
        """)
        layout.addWidget(self.lbl_title)

        self.lbl_value = QLabel(initial_value)
        self.lbl_value.setStyleSheet(f"""
            font-size: 20px;
            font-weight: 800;
            color: {accent_color};
        """)
        layout.addWidget(self.lbl_value)

        if subtext:
            self.lbl_subtext = QLabel(subtext)
            self.lbl_subtext.setStyleSheet(f"font-size: 11px; color: {Theme.SYS['text_muted']};")
            layout.addWidget(self.lbl_subtext)
        else:
            self.lbl_subtext = None

    def set_value(self, value: str, subtext: str = ""):
        self.lbl_value.setText(value)
        if self.lbl_subtext and subtext:
            self.lbl_subtext.setText(subtext)


class StatusPill(QLabel):
    """Pill badge communicating state with a high-contrast label."""

    def __init__(self, text: str, status_type: str = "success", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status(text, status_type)

    def set_status(self, text: str, status_type: str):
        self.setText(text)
        if status_type == "success":
            bg, fg, border = Theme.SYS["status_success_bg"], Theme.SYS["status_success"], Theme.SYS["status_success"]
        elif status_type == "warning":
            bg, fg, border = Theme.SYS["status_warning_bg"], Theme.SYS["status_warning"], Theme.SYS["status_warning"]
        elif status_type == "danger":
            bg, fg, border = Theme.SYS["status_danger_bg"], Theme.SYS["status_danger"], Theme.SYS["status_danger"]
        else:
            bg, fg, border = Theme.SYS["bg_surface_elevated"], Theme.SYS["text_secondary"], Theme.SYS["border_subtle"]

        self.setStyleSheet(f"""
            background-color: {bg};
            color: {fg};
            border: 1px solid {border};
            border-radius: 4px;
            padding: 3px 8px;
            font-size: 11px;
            font-weight: 700;
        """)
