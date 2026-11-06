#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Capturador Nativo Wayland via XDG Desktop Portal + PipeWire + GStreamer — DA-V v3.2
Autor: Dante Ferraz (MonoTech)

Resolve o isolamento de tela preta do XWayland em sessões modernas Linux (Ubuntu GNOME,
KDE Plasma, Fedora, Hyprland/Sway). Utiliza o Python de sistema (/usr/bin/python3) com
ambiente desacoplado do PyInstaller (_MEIPASS) para negociar a sessão ScreenCast via DBus,
extrair o descritor de arquivo Unix do PipeWire e alimentar um pipeline GStreamer de
baixa latência com leitura assíncrona em double-buffer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Optional

import numpy as np


# Script auxiliar auto-contido executado pelo /usr/bin/python3 do sistema operacional
# (onde python3-gi / gir1.2-glib-2.0 já vêm pré-instalados nas distribuições Desktop).
_PORTAL_HELPER_CODE = r'''
import os
import subprocess
import sys
import uuid

import gi
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

width = int(sys.argv[1])
height = int(sys.argv[2])
fps = int(sys.argv[3])

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
unique_sender = bus.get_unique_name().lstrip(":").replace(".", "_")

def portal_request(method_name: str, params: GLib.Variant, token: str, timeout_s: int = 90):
    req_path = f"/org/freedesktop/portal/desktop/request/{unique_sender}/{token}"
    loop = GLib.MainLoop()
    outcome = {"code": 2, "results": {}}

    def _on_response(_conn, _sender, _path, _iface, _sig, sig_params, _user_data):
        code, results = sig_params.unpack()
        outcome["code"] = int(code)
        outcome["results"] = results
        if loop.is_running():
            loop.quit()

    sub_id = bus.signal_subscribe(
        "org.freedesktop.portal.Desktop",
        "org.freedesktop.portal.Request",
        "Response",
        req_path,
        None,
        Gio.DBusSignalFlags.NONE,
        _on_response,
        None,
    )

    def _on_timeout():
        if loop.is_running():
            loop.quit()
        return False

    timer_id = GLib.timeout_add_seconds(timeout_s, _on_timeout)
    try:
        bus.call_sync(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.ScreenCast",
            method_name,
            params,
            GLib.VariantType.new("(o)"),
            Gio.DBusCallFlags.NONE,
            15000,
            None,
        )
        loop.run()
    finally:
        GLib.source_remove(timer_id)
        bus.signal_unsubscribe(sub_id)

    if outcome["code"] != 0:
        raise RuntimeError(f"Portal {method_name} recusado ou expirado (code={outcome['code']})")
    return outcome["results"]

tok1 = f"dav_{uuid.uuid4().hex[:10]}"
sess_tok = f"dav_sess_{uuid.uuid4().hex[:10]}"
res_create = portal_request(
    "CreateSession",
    GLib.Variant(
        "(a{sv})",
        ({
            "handle_token": GLib.Variant("s", tok1),
            "session_handle_token": GLib.Variant("s", sess_tok),
        },),
    ),
    tok1,
    timeout_s=15,
)
session_handle = res_create["session_handle"]

tok2 = f"dav_{uuid.uuid4().hex[:10]}"
select_opts = {
    "handle_token": GLib.Variant("s", tok2),
    "types": GLib.Variant("u", 3),        # 1=Monitor | 2=Janela
    "multiple": GLib.Variant("b", False),
    "cursor_mode": GLib.Variant("u", 2),  # 2=Cursor embutido na imagem
}
try:
    portal_request(
        "SelectSources",
        GLib.Variant("(oa{sv})", (session_handle, select_opts)),
        tok2,
        timeout_s=30,
    )
except Exception:
    select_opts.pop("cursor_mode", None)
    tok2b = f"dav_{uuid.uuid4().hex[:10]}"
    select_opts["handle_token"] = GLib.Variant("s", tok2b)
    portal_request(
        "SelectSources",
        GLib.Variant("(oa{sv})", (session_handle, select_opts)),
        tok2b,
        timeout_s=30,
    )

tok3 = f"dav_{uuid.uuid4().hex[:10]}"
res_start = portal_request(
    "Start",
    GLib.Variant(
        "(osa{sv})",
        (session_handle, "", {"handle_token": GLib.Variant("s", tok3)}),
    ),
    tok3,
    timeout_s=120,
)
streams = res_start.get("streams", [])
if not streams:
    raise RuntimeError("Nenhum stream retornado pelo XDG Desktop Portal.")
node_id = int(streams[0][0])

fd_reply, fd_list = bus.call_with_unix_fd_list_sync(
    "org.freedesktop.portal.Desktop",
    "/org/freedesktop/portal/desktop",
    "org.freedesktop.portal.ScreenCast",
    "OpenPipeWireRemote",
    GLib.Variant("(oa{sv})", (session_handle, {})),
    GLib.VariantType.new("(h)"),
    Gio.DBusCallFlags.NONE,
    15000,
    None,
    None,
)
fd_idx = int(fd_reply.unpack()[0])
pw_fd = fd_list.get(fd_idx)
os.set_inheritable(pw_fd, True)

sys.stderr.write(f"[Portal-Wayland] Stream PipeWire autorizado (node={node_id}, fd={pw_fd}, {width}x{height}@{fps}).\n")
sys.stderr.flush()

gst_cmd = [
    "gst-launch-1.0",
    "-q",
    "pipewiresrc",
    f"fd={pw_fd}",
    f"path={node_id}",
    "do-timestamp=true",
    "keepalive-time=1000",
    "resend-last=true",
    "!",
    "videoconvert",
    "!",
    "videoscale",
    "method=0",
    "!",
    "videorate",
    "drop-only=true",
    f"max-rate={fps}",
    "!",
    f"video/x-raw,format=BGRx,width={width},height={height}",
    "!",
    "fdsink",
    "fd=1",
    "sync=false",
]
proc = subprocess.Popen(
    gst_cmd,
    stdin=subprocess.DEVNULL,
    stdout=sys.stdout.buffer,
    stderr=sys.stderr.buffer,
    pass_fds=(pw_fd,),
    close_fds=True,
)
os.close(pw_fd)
sys.exit(proc.wait())
'''


def is_wayland_session() -> bool:
    """Detecta se o processo está rodando sob um compositor Wayland ativo."""
    if sys.platform == "win32":
        return False
    xdg_type = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    wayland_disp = os.environ.get("WAYLAND_DISPLAY", "").strip()
    return xdg_type == "wayland" or bool(wayland_disp)


def _build_clean_host_env() -> dict:
    """
    Remove variáveis injetadas pelo PyInstaller (_MEIPASS) ou virtualenv para que
    binários nativos do sistema (/usr/bin/python3 e gst-launch-1.0) usem as bibliotecas
    GObject/PipeWire/GStreamer originais da distribuição Linux.
    """
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "PYINSTALLER_RESET_ENVIRONMENT"):
        env.pop(k, None)

    if "LD_LIBRARY_PATH_ORIG" in env:
        orig = env["LD_LIBRARY_PATH_ORIG"]
        if orig:
            env["LD_LIBRARY_PATH"] = orig
        else:
            env.pop("LD_LIBRARY_PATH", None)
    elif "LD_LIBRARY_PATH" in env:
        clean_parts = [
            p for p in env["LD_LIBRARY_PATH"].split(os.pathsep)
            if p and "_MEI" not in p and "_internal" not in p
        ]
        if clean_parts:
            env["LD_LIBRARY_PATH"] = os.pathsep.join(clean_parts)
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env


class WaylandPortalCapturer:
    """
    Leitor assíncrono de quadros BGRx via XDG Desktop Portal + PipeWire + GStreamer.
    Mantém o último quadro válido em double-buffer para alimentar o loop de 60 FPS
    sem bloqueio mesmo quando o compositor Wayland não emite danos em tela parada.
    """

    def __init__(self, width: int, height: int, fps: int = 60):
        self.width = int(width)
        self.height = int(height)
        self.fps = max(1, int(fps))
        self.frame_bytes = self.width * self.height * 4

        self._proc: Optional[subprocess.Popen] = None
        self._stop_evt = threading.Event()
        self._first_frame_evt = threading.Event()
        self._lock = threading.Lock()
        self._latest_frame = np.zeros((self.height, self.width, 4), dtype=np.uint8)
        self._has_valid_frame = False
        self._frames_received = 0
        self._last_error: str = ""
        self._reader_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None

    @property
    def has_valid_frame(self) -> bool:
        return self._has_valid_frame

    @property
    def last_error(self) -> str:
        return self._last_error

    def start(self, wait_first_frame_timeout: float = 45.0) -> bool:
        """Inicia o Portal ScreenCast e aguarda a autorização do usuário na janela nativa."""
        host_py = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else shutil.which("python3")
        gst_bin = shutil.which("gst-launch-1.0")
        if not host_py or not gst_bin:
            self._last_error = (
                "Dependências Wayland ausentes (/usr/bin/python3 ou gst-launch-1.0). "
                "Instale: sudo apt install python3-gi gstreamer1.0-pipewire gstreamer1.0-tools gstreamer1.0-plugins-base"
            )
            return False

        env = _build_clean_host_env()
        try:
            self._proc = subprocess.Popen(
                [host_py, "-u", "-c", _PORTAL_HELPER_CODE, str(self.width), str(self.height), str(self.fps)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=max(self.frame_bytes * 2, 1048576),
                env=env,
            )
        except Exception as exc:
            self._last_error = f"Falha ao iniciar helper Wayland Portal: {exc}"
            return False

        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="DAV-Wayland-PipeWire-Reader"
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop, daemon=True, name="DAV-Wayland-Portal-Log"
        )
        self._reader_thread.start()
        self._stderr_thread.start()

        got_first = self._first_frame_evt.wait(timeout=wait_first_frame_timeout)
        if not got_first or not self._has_valid_frame:
            if not self._last_error:
                self._last_error = "Permissão de tela Wayland recusada, expirada ou plugin pipewiresrc ausente."
            self.close()
            return False
        return True

    def _stderr_loop(self):
        proc = self._proc
        if not proc or not proc.stderr:
            return
        try:
            for raw_line in iter(proc.stderr.readline, b""):
                if self._stop_evt.is_set():
                    break
                msg = raw_line.decode("utf-8", errors="replace").strip()
                if msg:
                    self._last_error = msg
                    print(msg)
        except Exception:
            pass

    def _reader_loop(self):
        proc = self._proc
        if not proc or not proc.stdout:
            return
        scratch = bytearray(self.frame_bytes)
        mv = memoryview(scratch)
        stream = proc.stdout

        while not self._stop_evt.is_set():
            offset = 0
            while offset < self.frame_bytes and not self._stop_evt.is_set():
                try:
                    n = stream.readinto(mv[offset:])
                except Exception:
                    n = 0
                if not n:
                    self._first_frame_evt.set()
                    return
                offset += n

            if offset < self.frame_bytes:
                break

            arr = np.frombuffer(scratch, dtype=np.uint8).reshape((self.height, self.width, 4))
            with self._lock:
                np.copyto(self._latest_frame, arr)
                self._frames_received += 1
                if not self._has_valid_frame:
                    self._has_valid_frame = True
                    self._first_frame_evt.set()

        self._first_frame_evt.set()

    def grab_into(self, dst_bgra: np.ndarray) -> bool:
        """Copia o quadro mais recente em < 0.3 ms para o buffer do worker de transmissão."""
        if not self._has_valid_frame:
            return False
        if self._proc is not None and self._proc.poll() is not None and self._frames_received == 0:
            return False
        with self._lock:
            np.copyto(dst_bgra, self._latest_frame)
        return True

    def close(self):
        self._stop_evt.set()
        self._first_frame_evt.set()
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
