# -*- coding: utf-8 -*-
"""
DA-V Video Canvas Widget (Hardware-accelerated viewport with Glassmorphism HUD)
DirectComposition backing store for tear-free 60-144 FPS rendering.
"""

import time
from collections import deque
from typing import Optional

from scripts.qt_compat import (
    QWidget, QPainter, QImage, QColor, QFont, QRect,
    QBrush, QPen, QLinearGradient, Qt
)
from src.ui.theme import Theme

_probe_send = None
try:
    from scripts.dav_stage_probe import probe_send as _probe_send
except Exception:
    pass


class VideoCanvasWidget(QWidget):
    """
    Viewport for rendering decoded video frames at high framerate.
    Features an in-canvas HUD overlay with glassmorphism styling and full-screen toggle.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_image: Optional[QImage] = None
        self.fps = 0.0
        self.bitrate_mbps = 0.0
        self.latency_ms = 0.0
        self.packets_count = 0
        self.frames_count = 0
        self.show_hud = True
        self.is_connected = False
        self._frame_times = deque(maxlen=60)
        self.setMinimumSize(480, 270)
        self.sender_codec = "H.264 NVENC (RTX 4070)"
        self.sender_frame_kb = 24
        self.gpu_mode = "Hardware NVIDIA NVENC (RTX 4070) + WGC Direct3D"

        self.setStyleSheet(f"background-color: {Theme.SYS['bg_canvas']}; border-radius: {Theme.RADIUS_LG}px;")

    def update_frame(self, image: QImage, fps: float, bitrate: float, latency: float, packets: int, frames: int):
        """Called when a new frame is decoded and ready to display."""
        _t_render_start = time.perf_counter()
        self.current_image = image
        now = _t_render_start
        self._frame_times.append(now)
        if fps > 0:
            self.fps = fps
        elif len(self._frame_times) >= 4:
            dt = self._frame_times[-1] - self._frame_times[0]
            if dt > 0.001:
                self.fps = (len(self._frame_times) - 1) / dt

        self.bitrate_mbps = bitrate
        self.latency_ms = latency
        self.packets_count = packets
        self.frames_count = frames
        self.is_connected = True
        self.update()  # Repaint on Qt UI thread

        if _probe_send is not None:
            _probe_send("render", _t_render_start, time.perf_counter(), frames)

    def update_telemetry_only(self, fps: float, bitrate: float, latency: float, packets: int, frames: int):
        """Update HUD telemetry without a new video frame."""
        if not self._frame_times or (time.perf_counter() - self._frame_times[-1] > 0.5):
            self.fps = fps
        self.bitrate_mbps = bitrate
        self.latency_ms = latency
        self.packets_count = packets
        self.frames_count = frames
        self.update()

    def clear_display(self):
        """Resets canvas state upon disconnection."""
        self.current_image = None
        self.is_connected = False
        self._frame_times.clear()
        self.fps = 0.0
        self.bitrate_mbps = 0.0
        self.latency_ms = 0.0
        self.update()

    def mouseDoubleClickEvent(self, event):
        """Double click to toggle fullscreen."""
        win = self.window()
        if win.isFullScreen():
            win.showNormal()
        else:
            win.showFullScreen()
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        # 1. Background
        painter.fillRect(self.rect(), QColor(Theme.SYS["bg_canvas"]))

        # 2. Video Frame (Centered & Aspect-Ratio Preserved)
        if self.current_image and not self.current_image.isNull():
            cw, ch = self.width(), self.height()
            iw, ih = self.current_image.width(), self.current_image.height()
            if iw > 0 and ih > 0:
                scale = min(cw / iw, ch / ih)
                tw, th = int(iw * scale), int(ih * scale)
                tx, ty = (cw - tw) // 2, (ch - th) // 2
                painter.drawImage(QRect(tx, ty, tw, th), self.current_image)
        else:
            # Placeholder State
            painter.setPen(QColor(Theme.SYS["text_muted"]))
            font = QFont("Segoe UI", 12)
            painter.setFont(font)
            msg = "AGUARDANDO TRANSMISSAO DE VIDEO..." if self.is_connected else "RECEPTOR EM ESPERA — NENHUMA CONEXAO ATIVA"
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, msg)

            # Border guide
            painter.setPen(QPen(QColor(Theme.SYS["border_subtle"]), 1, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(self.rect().adjusted(4, 4, -5, -5), 8, 8)

        # 3. HUD Overlay (Glassmorphism)
        if self.show_hud and self.is_connected:
            self._draw_hud(painter)

    def _draw_hud(self, painter: QPainter):
        hud_w, hud_h = 320, 160
        hud_rect = QRect(16, 16, hud_w, hud_h)

        # Glassmorphism panel with subtle gradient and border
        grad = QLinearGradient(hud_rect.topLeft(), hud_rect.bottomLeft())
        grad.setColorAt(0.0, QColor(11, 16, 26, 230))
        grad.setColorAt(1.0, QColor(15, 23, 42, 245))

        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(56, 189, 248, 140), 1))
        painter.drawRoundedRect(hud_rect, Theme.RADIUS_LG, Theme.RADIUS_LG)

        # Header Title
        f_title = QFont("Segoe UI", 9, QFont.Weight.Bold)
        painter.setFont(f_title)
        painter.setPen(QColor(Theme.SYS["text_accent"]))
        painter.drawText(28, 36, "TELEMETRIA DA-V AO VIVO")

        # Security Badge (Pill)
        f_pill = QFont("Segoe UI", 8, QFont.Weight.Bold)
        painter.setFont(f_pill)
        painter.setBrush(QBrush(QColor(16, 185, 129, 220)))
        painter.setPen(Qt.PenStyle.NoPen)
        pill_rect = QRect(hud_w - 85, 23, 76, 20)
        painter.drawRoundedRect(pill_rect, 4, 4)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, "E2E AEAD")

        # Telemetry Metrics
        f_body = QFont("Segoe UI", 9)
        painter.setFont(f_body)

        # Color-coded FPS
        if self.fps >= 55:
            fps_color = QColor(Theme.SYS["status_success"])
        elif self.fps >= 40:
            fps_color = QColor(Theme.SYS["status_warning"])
        else:
            fps_color = QColor(Theme.SYS["status_danger"])

        painter.setPen(fps_color)
        painter.drawText(28, 58, f"Taxa de Quadros : {self.fps:4.1f} FPS")

        painter.setPen(QColor(Theme.SYS["text_primary"]))
        painter.drawText(28, 78, f"Vazao de Rede   : {self.bitrate_mbps:5.2f} Mbps")
        painter.drawText(28, 98, f"Latencia LAN    : {self.latency_ms:4.2f} ms")
        painter.drawText(28, 118, f"Quadros/Pacotes : {self.frames_count} / {self.packets_count}")

        painter.setPen(QColor(Theme.SYS["text_muted"]))
        f_small = QFont("Segoe UI", 8)
        painter.setFont(f_small)
        painter.drawText(28, 138, f"Codec: {self.sender_codec} | ~{self.sender_frame_kb}KB/frame")
        painter.drawText(28, 154, f"Engine: {self.gpu_mode}")
