# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
DA-V Video Canvas Widget (Hardware-accelerated viewport with Glassmorphism HUD)
DirectComposition backing store for tear-free 60-144 FPS rendering.
"""

import time
from collections import deque
from typing import Optional, Tuple

from src.ui.qt_compat import (
    QWidget, QPainter, QImage, QColor, QFont, QRect,
    QBrush, QPen, QLinearGradient, Qt, QTimer, Signal
)
from src.ui.theme import Theme
from src.dav.modules.remote_desktop.keymap import qt_key_to_hid
from src.dav.modules.remote_desktop.protocol import (
    EvType,
    InputEventPacket,
    KeyMod,
    MouseBtn,
    pack_wheel_deltas,
)
from src.dav.modules.telemetry.stage_probe import probe_send as _probe_send
from src.dav.modules.universal_input.keyboard_translator import ClientKeyboardTranslator


class VideoCanvasWidget(QWidget):
    """
    Viewport for rendering decoded video frames at high framerate.
    Features an in-canvas HUD overlay, sub-ms remote desktop input capture (250 Hz coalescing),
    exact inverse Fit/Stretch/Native coordinate mapping, and P2P file drag-and-drop.
    """

    first_frame_received = Signal()
    remote_input_event = Signal(object)
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_image: Optional[QImage] = None
        self.fps = 0.0
        self.bitrate_mbps = 0.0
        self.latency_ms = 0.0
        self.input_to_photon_ms = 0.0
        self.packets_count = 0
        self.frames_count = 0
        self.show_hud = True
        self.hud_mode = "pill"  # "full" | "pill" | "hidden" (compacto por padrao: nao cobre o video)
        self.scale_mode = "fit"  # "fit" | "stretch" | "native"
        self.is_connected = False
        self.remote_control_enabled = False
        self.host_allows_input = False
        self.host_allows_gamepad = False
        self.host_allows_files = False
        self.relative_mouse_mode = False
        self._kb_translator = ClientKeyboardTranslator()
        self._last_input_ts_us = 0

        self._frame_times = deque(maxlen=60)
        self._last_move_sent_mono = 0.0
        self._pending_move: Optional[Tuple[int, int, int, int]] = None
        self._last_cursor_pos: Optional[Tuple[float, float]] = None
        self._move_timer = QTimer(self)
        self._move_timer.setSingleShot(True)
        self._move_timer.setInterval(4)
        self._move_timer.timeout.connect(self._flush_coalesced_move)

        self.setMinimumSize(480, 270)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
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
        self._move_timer.stop()
        self._pending_move = None
        self._last_cursor_pos = None
        self._kb_translator.reset()
        self.current_image = None
        self.is_connected = False
        self.input_to_photon_ms = 0.0
        self._frame_times.clear()
        self.fps = 0.0
        self.bitrate_mbps = 0.0
        self.latency_ms = 0.0
        self.update()

    @property
    def is_interactive_active(self) -> bool:
        return bool(self.is_connected and self.remote_control_enabled and self.host_allows_input)

    def video_target_rect(self) -> QRect:
        """Retorna o retangulo exato onde o video esta desenhado dentro do widget."""
        cw, ch = max(1, self.width()), max(1, self.height())
        if self.current_image is None or self.current_image.isNull():
            return QRect(0, 0, cw, ch)
        iw, ih = self.current_image.width(), self.current_image.height()
        if iw <= 0 or ih <= 0:
            return QRect(0, 0, cw, ch)
        if self.scale_mode == "stretch":
            return QRect(0, 0, cw, ch)
        if self.scale_mode == "native":
            return QRect((cw - iw) // 2, (ch - ih) // 2, iw, ih)
        scale = min(cw / iw, ch / ih)
        tw, th = max(1, int(iw * scale)), max(1, int(ih * scale))
        return QRect((cw - tw) // 2, (ch - th) // 2, tw, th)

    def map_widget_pos_to_norm(self, wx: float, wy: float) -> Optional[Tuple[int, int]]:
        """Mapeia `(wx, wy)` em pixels locais do widget para `[0..65535]` na tela remota."""
        vr = self.video_target_rect()
        if vr.width() <= 0 or vr.height() <= 0:
            return None
        if wx < vr.left() or wx > (vr.left() + vr.width()) or wy < vr.top() or wy > (vr.top() + vr.height()):
            return None
        rx = (wx - vr.left()) / max(1.0, float(vr.width() - 1))
        ry = (wy - vr.top()) / max(1.0, float(vr.height() - 1))
        nx = max(0, min(65535, int(round(rx * 65535.0))))
        ny = max(0, min(65535, int(round(ry * 65535.0))))
        return (nx, ny)

    @staticmethod
    def _extract_buttons_mask(buttons) -> int:
        mask = 0
        if buttons & Qt.MouseButton.LeftButton:
            mask |= MouseBtn.LEFT
        if buttons & Qt.MouseButton.RightButton:
            mask |= MouseBtn.RIGHT
        if buttons & Qt.MouseButton.MiddleButton:
            mask |= MouseBtn.MIDDLE
        if buttons & Qt.MouseButton.BackButton:
            mask |= MouseBtn.BACK
        if buttons & Qt.MouseButton.ForwardButton:
            mask |= MouseBtn.FORWARD
        return mask

    @staticmethod
    def _extract_single_button(btn) -> int:
        if btn == Qt.MouseButton.LeftButton:
            return int(MouseBtn.LEFT)
        if btn == Qt.MouseButton.RightButton:
            return int(MouseBtn.RIGHT)
        if btn == Qt.MouseButton.MiddleButton:
            return int(MouseBtn.MIDDLE)
        if btn == Qt.MouseButton.BackButton:
            return int(MouseBtn.BACK)
        if btn == Qt.MouseButton.ForwardButton:
            return int(MouseBtn.FORWARD)
        return 0

    @staticmethod
    def _extract_modifiers_mask(mods) -> int:
        mask = 0
        if mods & Qt.KeyboardModifier.ShiftModifier:
            mask |= KeyMod.SHIFT
        if mods & Qt.KeyboardModifier.ControlModifier:
            mask |= KeyMod.CTRL
        if mods & Qt.KeyboardModifier.AltModifier:
            mask |= KeyMod.ALT
        if mods & Qt.KeyboardModifier.MetaModifier:
            mask |= KeyMod.META
        return mask

    def _emit_input(self, pkt: InputEventPacket) -> None:
        now_us = int(time.perf_counter_ns() // 1000)
        if now_us <= self._last_input_ts_us:
            now_us = self._last_input_ts_us + 1
        self._last_input_ts_us = now_us
        pkt.client_ts_us = now_us
        self.remote_input_event.emit(pkt)

    def _dispatch_key_actions(self, actions) -> None:
        for act in actions:
            if act.mode == "unicode" and act.codepoint > 0:
                self._emit_input(
                    InputEventPacket(
                        ev_type=EvType.KEY_UNICODE,
                        modifiers_mask=act.modifiers_mask,
                        key_or_wheel=act.codepoint,
                    )
                )
            elif act.mode == "hid" and act.hid_code > 0:
                self._emit_input(
                    InputEventPacket(
                        ev_type=EvType.KEY_UP if act.is_up else EvType.KEY_DOWN,
                        modifiers_mask=act.modifiers_mask,
                        key_or_wheel=act.hid_code,
                    )
                )

    def _flush_coalesced_move(self) -> None:
        if self._pending_move is None or not self.is_interactive_active:
            self._pending_move = None
            return
        xv, yv, b_mask, m_mask = self._pending_move
        self._pending_move = None
        self._last_move_sent_mono = time.perf_counter()
        self._emit_input(
            InputEventPacket(
                ev_type=EvType.MOVE_REL if self.relative_mouse_mode else EvType.MOVE_ABS,
                buttons_mask=b_mask,
                modifiers_mask=m_mask,
                x_val=xv,
                y_val=yv,
            )
        )

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

    def mouseMoveEvent(self, event):
        if not self.is_interactive_active:
            super().mouseMoveEvent(event)
            return
        pos = event.position() if hasattr(event, "position") else event.pos()
        wx, wy = float(pos.x()), float(pos.y())
        b_mask = self._extract_buttons_mask(event.buttons())
        m_mask = self._extract_modifiers_mask(event.modifiers())

        if self.relative_mouse_mode:
            if self._last_cursor_pos is None:
                self._last_cursor_pos = (wx, wy)
                return
            dx = int(round(wx - self._last_cursor_pos[0]))
            dy = int(round(wy - self._last_cursor_pos[1]))
            self._last_cursor_pos = (wx, wy)
            if dx == 0 and dy == 0:
                return
            if self._pending_move is not None:
                dx += self._pending_move[0]
                dy += self._pending_move[1]
            self._pending_move = (dx, dy, b_mask, m_mask)
        else:
            mapped = self.map_widget_pos_to_norm(wx, wy)
            if mapped is None:
                return
            self._pending_move = (mapped[0], mapped[1], b_mask, m_mask)

        now = time.perf_counter()
        if (now - self._last_move_sent_mono) >= 0.004:
            self._move_timer.stop()
            self._flush_coalesced_move()
        elif not self._move_timer.isActive():
            self._move_timer.start()
        event.accept()

    def mousePressEvent(self, event):
        self.setFocus()
        if not self.is_interactive_active:
            super().mousePressEvent(event)
            return
        single_btn = self._extract_single_button(event.button())
        if single_btn == 0:
            return
        pos = event.position() if hasattr(event, "position") else event.pos()
        mapped = self.map_widget_pos_to_norm(float(pos.x()), float(pos.y()))
        if mapped is None and not self.relative_mouse_mode:
            return
        if self._pending_move is not None:
            self._move_timer.stop()
            self._flush_coalesced_move()
        xv, yv = (0, 0) if (self.relative_mouse_mode or mapped is None) else mapped
        self._emit_input(
            InputEventPacket(
                ev_type=EvType.BTN_DOWN,
                buttons_mask=single_btn,
                modifiers_mask=self._extract_modifiers_mask(event.modifiers()),
                x_val=xv,
                y_val=yv,
            )
        )
        event.accept()

    def mouseReleaseEvent(self, event):
        if not self.is_interactive_active:
            super().mouseReleaseEvent(event)
            return
        single_btn = self._extract_single_button(event.button())
        if single_btn == 0:
            return
        pos = event.position() if hasattr(event, "position") else event.pos()
        mapped = self.map_widget_pos_to_norm(float(pos.x()), float(pos.y()))
        xv, yv = (0, 0) if (self.relative_mouse_mode or mapped is None) else mapped
        self._emit_input(
            InputEventPacket(
                ev_type=EvType.BTN_UP,
                buttons_mask=single_btn,
                modifiers_mask=self._extract_modifiers_mask(event.modifiers()),
                x_val=xv,
                y_val=yv,
            )
        )
        event.accept()

    def mouseDoubleClickEvent(self, event):
        """Quando o controle remoto esta ativo, repassa o segundo clique ao SO remoto."""
        if self.is_interactive_active:
            self.mousePressEvent(event)
            return
        self.toggle_fullscreen()
        event.accept()

    def wheelEvent(self, event):
        if not self.is_interactive_active:
            super().wheelEvent(event)
            return
        delta = event.angleDelta()
        dx, dy = int(delta.x()), int(delta.y())
        if dx == 0 and dy == 0:
            return
        self._emit_input(
            InputEventPacket(
                ev_type=EvType.WHEEL,
                buttons_mask=self._extract_buttons_mask(event.buttons()),
                modifiers_mask=self._extract_modifiers_mask(event.modifiers()),
                key_or_wheel=pack_wheel_deltas(dx, dy),
            )
        )
        event.accept()

    def keyPressEvent(self, event):
        """Captura teclado remoto (quando ativo) ou atalhos locais do player."""
        key = event.key()
        mods = event.modifiers()
        ctrl_alt = bool(
            (mods & Qt.KeyboardModifier.ControlModifier)
            and (mods & Qt.KeyboardModifier.AltModifier)
        )

        # Atalhos locais que funcionam mesmo durante controle remoto
        if ctrl_alt and key == Qt.Key.Key_M:
            self.relative_mouse_mode = not self.relative_mouse_mode
            self._last_cursor_pos = None
            self.update()
            event.accept()
            return
        if ctrl_alt and key == Qt.Key.Key_F:
            self.toggle_fullscreen()
            event.accept()
            return

        if self.is_interactive_active:
            m_mask = self._extract_modifiers_mask(mods)
            txt = event.text() if hasattr(event, "text") else ""
            actions = self._kb_translator.translate_key_press(
                qt_key=int(key),
                modifiers_mask=m_mask,
                text=txt,
                native_scancode=int(event.nativeScanCode()),
                native_vk=int(event.nativeVirtualKey()),
                is_auto_repeat=bool(event.isAutoRepeat()),
            )
            self._dispatch_key_actions(actions)
            event.accept()
            return

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

    def keyReleaseEvent(self, event):
        if self.is_interactive_active:
            m_mask = self._extract_modifiers_mask(event.modifiers())
            actions = self._kb_translator.translate_key_release(
                qt_key=int(event.key()),
                modifiers_mask=m_mask,
                native_scancode=int(event.nativeScanCode()),
                native_vk=int(event.nativeVirtualKey()),
                is_auto_repeat=bool(event.isAutoRepeat()),
            )
            self._dispatch_key_actions(actions)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def inputMethodEvent(self, event):
        """Processa caracteres compostos pelo teclado do cliente (ex: '~' + Espaco -> '~', '~' + 'a' -> 'ã')."""
        if self.is_interactive_active:
            committed = event.commitString() if hasattr(event, "commitString") else ""
            if committed:
                actions = self._kb_translator.translate_ime_commit(committed)
                self._dispatch_key_actions(actions)
            event.accept()
            return
        super().inputMethodEvent(event)

    def focusOutEvent(self, event):
        self._kb_translator.reset()
        if self.is_connected and self.host_allows_input:
            self._emit_input(InputEventPacket(ev_type=EvType.RELEASE_ALL))
        super().focusOutEvent(event)

    def dragEnterEvent(self, event):
        if self.is_connected and self.host_allows_files and event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        if self.is_connected and self.host_allows_files and event.mimeData().hasUrls():
            local_files = [
                u.toLocalFile()
                for u in event.mimeData().urls()
                if u.isLocalFile() and u.toLocalFile()
            ]
            if local_files:
                self.files_dropped.emit(local_files)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

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
        pill_w = 278 if self.is_interactive_active else 240
        pill_h = 28
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

        shown_lat = self.input_to_photon_ms if (self.is_interactive_active and self.input_to_photon_ms > 0) else self.latency_ms
        painter.setPen(QColor(Theme.SYS["text_primary"]))
        painter.drawText(pill_rect.adjusted(75, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, f"· {shown_lat:3.1f} ms")

        badge_txt = (
            "RELATIVO" if (self.is_interactive_active and self.relative_mouse_mode)
            else ("INTERATIVO" if self.is_interactive_active else "PAKE AEAD")
        )
        painter.setPen(QColor("#86efac") if self.is_interactive_active else QColor(Theme.SYS["text_accent"]))
        painter.drawText(pill_rect.adjusted(145, 0, -10, 0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, badge_txt)

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
        pill_rect = QRect(hud_w - 88, 23, 80, 20)
        painter.drawRoundedRect(pill_rect, 4, 4)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, "PAKE AEAD")

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
