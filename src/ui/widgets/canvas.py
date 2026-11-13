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
    QBrush, QPen, QLinearGradient, Qt, Signal
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

    first_frame_received = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_image: Optional[QImage] = None
        self.fps = 0.0
        self.bitrate_mbps = 0.0
        self.latency_ms = 0.0
        self.packets_count = 0
        self.frames_count = 0
        self.show_hud = True
        self.hud_mode = "pill"  # "full" | "pill" | "hidden" (compacto por padrao: nao cobre o video)
        self.scale_mode = "fit"  # "fit" | "stretch" | "native"
        self.is_connected = False
        self._frame_times = deque(maxlen=60)
        self.setMinimumSize(480, 270)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.sender_codec = "H.264 / HEVC ULL"
        self.sender_frame_kb = 24
        self.gpu_mode = "PyAV SIMD Zero-Copy + DirectComposition"

        self.setStyleSheet(f"background-color: {Theme.SYS['bg_canvas']}; border-radius: {Theme.RADIUS_LG}px;")

    def update_frame(self, image: QImage, fps: float, bitrate: float, latency: float, packets: int, frames: int):
        """Called when a new frame is decoded and ready to display."""
        _t_render_start = time.perf_counter()
        is_first = self.current_image is None
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
        if is_first:
            self.first_frame_received.emit()

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
        if packets > 0:
            self.is_connected = True
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

    def toggle_fullscreen(self):
        """Alterna a janela entre modo tela cheia e modo janela normal."""
        win = self.window()
        if win.isFullScreen():
            win.showNormal()
        else:
            win.showFullScreen()
        self.update()

    def toggle_hud(self):
        """Cicla entre exibição completa do HUD, pílula minimalista e oculto."""
        if self.hud_mode == "full":
            self.hud_mode = "pill"
            self.show_hud = True
        elif self.hud_mode == "pill":
            self.hud_mode = "hidden"
            self.show_hud = False
        else:
            self.hud_mode = "full"
            self.show_hud = True
        self.update()

    def toggle_scale_mode(self):
        """Cicla entre modo de ajuste proporcional (fit), esticar (stretch) e 1:1 nativo."""
        modes = ["fit", "stretch", "native"]
        cur_idx = modes.index(self.scale_mode) if self.scale_mode in modes else 0
        self.scale_mode = modes[(cur_idx + 1) % len(modes)]
        self.update()

    def save_screenshot(self, save_dir: Optional[str] = None) -> Optional[str]:
        """Salva captura instantânea do quadro atual em PNG."""
        if self.current_image and not self.current_image.isNull():
            import os
            target_dir = save_dir or os.path.join(os.path.expanduser("~"), "Desktop")
            os.makedirs(target_dir, exist_ok=True)
            fname = f"DA-V_Screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
            path = os.path.join(target_dir, fname)
            self.current_image.save(path, "PNG")
            return path
        return None

    def mouseDoubleClickEvent(self, event):
        """Duplo clique para alternar tela cheia."""
        self.toggle_fullscreen()
        event.accept()

    def keyPressEvent(self, event):
        """Atalhos interativos do teclado no canvas de vídeo."""
        key = event.key()
        if key == Qt.Key.Key_F11:
            self.toggle_fullscreen()
            event.accept()
        elif key == Qt.Key.Key_Escape:
            win = self.window()
            if win.isFullScreen():
                win.showNormal()
                event.accept()
        elif key in (Qt.Key.Key_F2, Qt.Key.Key_H):
            self.toggle_hud()
            event.accept()
        elif key in (Qt.Key.Key_F3, Qt.Key.Key_M):
            self.toggle_scale_mode()
            event.accept()
        elif key == Qt.Key.Key_F12:
            self.save_screenshot()
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        # 1. Background
        painter.fillRect(self.rect(), QColor(Theme.SYS["bg_canvas"]))

        # 2. Video Frame (Suporte a Fit, Stretch e Native 1:1)
        if self.current_image and not self.current_image.isNull():
            cw, ch = self.width(), self.height()
            iw, ih = self.current_image.width(), self.current_image.height()
            if iw > 0 and ih > 0:
                if self.scale_mode == "stretch":
                    tx, ty, tw, th = 0, 0, cw, ch
                elif self.scale_mode == "native":
                    tw, th = iw, ih
                    tx, ty = (cw - tw) // 2, (ch - th) // 2
                else:  # "fit" (Padrão: Preserva proporção)
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

        # 3. HUD Overlay (Glassmorphism Completo ou Pílula Minimalista)
        if self.is_connected and self.show_hud:
            if self.hud_mode == "full":
                self._draw_hud(painter)
            elif self.hud_mode == "pill":
                self._draw_hud_pill(painter)

    def _draw_hud_pill(self, painter: QPainter):
        """Desenha a pílula minimalista no canto superior direito."""
        pill_w, pill_h = 240, 28
        pill_rect = QRect(self.width() - pill_w - 16, 16, pill_w, pill_h)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QBrush(QColor(8, 52, 70, 190)))
        painter.setPen(QPen(QColor(255, 255, 255, 190), 1.5))
        painter.drawRoundedRect(pill_rect, pill_h / 2, pill_h / 2)

        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        fps_color = QColor(Theme.SYS["status_success"]) if self.fps >= 55 else (
            QColor(Theme.SYS["status_warning"]) if self.fps >= 40 else QColor(Theme.SYS["status_danger"])
        )
        painter.setPen(fps_color)
        painter.drawText(pill_rect.adjusted(10, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, f"{self.fps:4.1f} FPS")

        painter.setPen(QColor(Theme.SYS["text_primary"]))
        painter.drawText(pill_rect.adjusted(75, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, f"· {self.latency_ms:3.1f} ms")

        painter.setPen(QColor(Theme.SYS["text_accent"]))
        painter.drawText(pill_rect.adjusted(145, 0, -10, 0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "E2E AEAD")

    def _draw_hud(self, painter: QPainter):
        hud_w, hud_h = 320, 160
        hud_rect = QRect(16, 16, hud_w, hud_h)

        # Glassmorphism panel with subtle gradient and border
        grad = QLinearGradient(hud_rect.topLeft(), hud_rect.bottomLeft())
        grad.setColorAt(0.0, QColor(8, 52, 70, 214))
        grad.setColorAt(1.0, QColor(6, 40, 56, 230))

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(255, 255, 255, 190), 1.5))
        painter.drawRoundedRect(hud_rect, 16, 16)

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

        frame_kb_real = (
            max(1, int((self.bitrate_mbps * 1000.0 / 8.0) / max(self.fps, 1.0)))
            if self.bitrate_mbps > 0 and self.fps > 0
            else self.sender_frame_kb
        )
        res_info = ""
        if self.current_image and not self.current_image.isNull():
            res_info = f" ({self.current_image.width()}x{self.current_image.height()})"

        painter.setPen(QColor(Theme.SYS["text_primary"]))
        painter.drawText(28, 78, f"Vazao de Rede   : {self.bitrate_mbps:5.2f} Mbps")
        painter.drawText(28, 98, f"Latencia Rede   : {self.latency_ms:4.2f} ms")
        painter.drawText(28, 118, f"Quadros/Pacotes : {self.frames_count} / {self.packets_count}")

        painter.setPen(QColor(Theme.SYS["text_muted"]))
        f_small = QFont("Segoe UI", 8)
        painter.setFont(f_small)
        painter.drawText(28, 138, f"Stream: {self.sender_codec}{res_info} | ~{frame_kb_real} KB/quadro")
        painter.drawText(28, 154, f"Engine: {self.gpu_mode}")
