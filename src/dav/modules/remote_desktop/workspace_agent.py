# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Agente de Area de Trabalho (Clipboard Deduplicado, Arquivos P2P e Shell Persistente LTSP) — DA-V v5.0
Autor: Dante Ferraz (MonoTech)

Responsabilidades:
1. Sincronizacao bidirecional de Clipboard com deduplicacao SHA-256 (ate 2 MB UTF-8).
2. Transferencia P2P de arquivos em blocos de 1150 bytes com sanitizacao anti-path-traversal
   (`~/Downloads/DA-V/`) e verificacao criptografica SHA-256 antes do commit em disco.
3. `PtyShellManager` (inspiracao LTSP fat-client / shell persistente): mantem sessao interativa
   persistente (`/bin/bash` via `pty` no Linux ou `powershell.exe` no Windows) exclusivamente
   quando `allow_shell=True`, eliminando overhead de spawn por comando.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.dav.modules.remote_desktop.protocol import (
    WorkspaceChannel,
    WorkspaceMessage,
    WsMsgType,
)
from src.dav.modules.remote_desktop.security_gate import SecurityGate

MAX_CLIPBOARD_BYTES = 2 * 1024 * 1024        # 2 MB
MAX_FILE_BYTES = 512 * 1024 * 1024           # 512 MB
FILE_CHUNK_PAYLOAD_SIZE = 1150               # Seguro dentro do MTU UDP 1300 c/ AEAD + ARQ
_FILE_CHUNK_HDR = struct.Struct("!16sI")     # 16B uuid + uint32 chunk_idx


def sanitize_filename(raw_name: str) -> str:
    """Remove qualquer tentativa de Path Traversal (`../`, barras, bytes nulos, nomes reservados)."""
    cleaned = str(raw_name or "").replace("\x00", "").replace("\\", "/").strip()
    base = Path(cleaned).name.strip().lstrip(".")
    safe_chars = [c for c in base if ord(c) >= 32 and c not in '<>:"/\\|?*']
    name = "".join(safe_chars).strip()
    if not name or name.upper() in {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4",
        "LPT1", "LPT2", "LPT3",
    }:
        name = "arquivo_dav.bin"
    return name[:180]


class PtyShellManager:
    """Sessao interativa persistente de terminal remoto (Linux PTY / Windows PowerShell)."""

    def __init__(self, on_stdout: Callable[[bytes], None]):
        self._on_stdout = on_stdout
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._master_fd: Optional[int] = None
        self._stop_evt = threading.Event()
        self._threads: List[threading.Thread] = []

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def ensure_started(self) -> bool:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return True
            self._stop_locked()
            self._stop_evt.clear()
            home_cwd = str(Path.home())

            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                self._proc = subprocess.Popen(
                    [
                        "powershell.exe",
                        "-NoLogo",
                        "-NoProfile",
                        "-NoExit",
                        "-Command",
                        "[Console]::InputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)",
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=home_cwd,
                    bufsize=0,
                    creationflags=creationflags,
                )
                t = threading.Thread(
                    target=self._win_stdout_loop,
                    args=(self._proc,),
                    daemon=True,
                    name="DAV-RemoteShell-Win",
                )
                t.start()
                self._threads = [t]
                return True

            import pty

            master_fd, slave_fd = pty.openpty()
            shell_bin = os.environ.get("SHELL") or "/bin/bash"
            if not os.path.exists(shell_bin):
                shell_bin = "/bin/sh"
            env = dict(os.environ)
            env.setdefault("TERM", "xterm-256color")
            self._proc = subprocess.Popen(
                [shell_bin, "-i"],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=home_cwd,
                env=env,
                close_fds=True,
                start_new_session=True,
            )
            os.close(slave_fd)
            self._master_fd = master_fd
            t = threading.Thread(
                target=self._posix_pty_loop,
                args=(master_fd,),
                daemon=True,
                name="DAV-RemoteShell-PTY",
            )
            t.start()
            self._threads = [t]
            return True

    def write_stdin(self, data: bytes) -> bool:
        if not data:
            return False
        if not self.ensure_started():
            return False
        with self._lock:
            if sys.platform == "win32":
                if self._proc and self._proc.stdin:
                    try:
                        self._proc.stdin.write(data)
                        self._proc.stdin.flush()
                        return True
                    except Exception:
                        return False
                return False
            if self._master_fd is not None:
                try:
                    os.write(self._master_fd, data)
                    return True
                except OSError:
                    return False
        return False

    def resize(self, cols: int, rows: int) -> None:
        if sys.platform == "win32":
            return
        with self._lock:
            if self._master_fd is None:
                return
            try:
                import fcntl
                import termios

                winsz = struct.pack("HHHH", max(10, int(rows)), max(20, int(cols)), 0, 0)
                fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsz)
            except Exception:
                pass

    def _win_stdout_loop(self, proc: subprocess.Popen) -> None:
        stream = proc.stdout
        if stream is None:
            return
        while not self._stop_evt.is_set() and proc.poll() is None:
            try:
                chunk = os.read(stream.fileno(), 1024)
            except Exception:
                break
            if not chunk:
                break
            self._on_stdout(chunk)

    def _posix_pty_loop(self, master_fd: int) -> None:
        while not self._stop_evt.is_set():
            try:
                chunk = os.read(master_fd, 1024)
            except OSError:
                break
            if not chunk:
                break
            self._on_stdout(chunk)

    def _stop_locked(self) -> None:
        self._stop_evt.set()
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except Exception:
                pass
            self._master_fd = None
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=0.3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def close(self) -> None:
        with self._lock:
            self._stop_locked()


class WorkspaceAgent:
    """Orquestra Clipboard, Recebimento/Envio de Arquivos P2P e Shell Persistente sobre `WorkspaceChannel`."""

    def __init__(
        self,
        gate: SecurityGate,
        channel: Optional[WorkspaceChannel] = None,
        download_dir: Optional[str] = None,
        on_clipboard_rx: Optional[Callable[[str], None]] = None,
        on_file_status: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_shell_output: Optional[Callable[[str], None]] = None,
        send_wire_fn: Optional[Callable[[bytes], None]] = None,
    ):
        self.gate = gate
        self.channel = channel or WorkspaceChannel()
        base_dl = Path(download_dir) if download_dir else (Path.home() / "Downloads" / "DA-V")
        self.download_dir = base_dl
        self.on_clipboard_rx = on_clipboard_rx
        self.on_file_status = on_file_status
        self.on_shell_output = on_shell_output
        self._send_wire = send_wire_fn

        self._clip_lock = threading.Lock()
        self._last_clip_hash: str = ""
        self._rx_transfers: Dict[bytes, Dict[str, Any]] = {}
        self.shell = PtyShellManager(on_stdout=self._handle_local_shell_stdout)

    def set_send_wire_fn(self, fn: Callable[[bytes], None]) -> None:
        self._send_wire = fn

    def _emit_wire(self, wire_frame: bytes) -> None:
        if self._send_wire is not None and wire_frame:
            self._send_wire(wire_frame)

    def broadcast_permissions(self) -> bytes:
        frame = self.channel.send_json(WsMsgType.PERM_UPDATE, self.gate.permissions.to_dict())
        self._emit_wire(frame)
        if not self.gate.permissions.allow_shell:
            self.shell.close()
        return frame

    def build_clipboard_frames(self, text: str) -> List[bytes]:
        if text is None:
            return []
        encoded = text.encode("utf-8", errors="replace")
        if not encoded or len(encoded) > MAX_CLIPBOARD_BYTES:
            return []
        digest = hashlib.sha256(encoded).hexdigest()
        with self._clip_lock:
            if digest == self._last_clip_hash:
                return []
            self._last_clip_hash = digest
        frame = self.channel.send_reliable(WsMsgType.CLIPBOARD_TEXT, encoded)
        self._emit_wire(frame)
        return [frame]

    def build_file_transfer_frames(self, file_path: str) -> Tuple[str, List[bytes]]:
        """Le um arquivo local e gera os frames ordenados (`FILE_META` + N x `FILE_CHUNK`)."""
        p = Path(file_path)
        if not p.is_file():
            raise FileNotFoundError(f"Arquivo inexistente: {file_path}")
        size = p.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError(f"Arquivo excede o limite de {MAX_FILE_BYTES // (1024 * 1024)} MB.")

        raw_bytes = p.read_bytes()
        sha256_hex = hashlib.sha256(raw_bytes).hexdigest()
        tid_uuid = uuid.uuid4()
        tid_bytes = tid_uuid.bytes
        tid_hex = tid_uuid.hex
        safe_name = sanitize_filename(p.name)

        chunks = [
            raw_bytes[i : i + FILE_CHUNK_PAYLOAD_SIZE]
            for i in range(0, len(raw_bytes), FILE_CHUNK_PAYLOAD_SIZE)
        ] or [b""]

        frames: List[bytes] = []
        meta_frame = self.channel.send_json(
            WsMsgType.FILE_META,
            {
                "transfer_id": tid_hex,
                "filename": safe_name,
                "size": len(raw_bytes),
                "sha256": sha256_hex,
                "total_chunks": len(chunks),
            },
        )
        frames.append(meta_frame)
        self._emit_wire(meta_frame)

        for idx, chunk in enumerate(chunks):
            c_payload = _FILE_CHUNK_HDR.pack(tid_bytes, idx) + chunk
            cf = self.channel.send_reliable(WsMsgType.FILE_CHUNK, c_payload)
            frames.append(cf)
            self._emit_wire(cf)

        return tid_hex, frames

    def send_shell_input(self, command_or_chars: str) -> Optional[bytes]:
        if not command_or_chars:
            return None
        frame = self.channel.send_reliable(WsMsgType.SHELL_STDIN, command_or_chars.encode("utf-8"))
        self._emit_wire(frame)
        return frame

    def _handle_local_shell_stdout(self, raw_out: bytes) -> None:
        if not self.gate.permissions.allow_shell:
            return
        for i in range(0, len(raw_out), 1024):
            frame = self.channel.send_reliable(WsMsgType.SHELL_STDOUT, raw_out[i : i + 1024])
            self._emit_wire(frame)

    def handle_incoming_wire(self, raw_frame: bytes, is_host: bool = True) -> List[WorkspaceMessage]:
        """Processa frame bruto `PT_WORKSPACE`, envia ACK e executa acoes autorizadas."""
        messages, ack_frame = self.channel.receive(raw_frame)
        if ack_frame is not None:
            self._emit_wire(ack_frame)

        accepted: List[WorkspaceMessage] = []
        for msg in messages:
            if is_host and not self.gate.allow_workspace_msg(msg.msg_type):
                continue
            accepted.append(msg)
            self._dispatch_message(msg, is_host=is_host)
        return accepted

    def _dispatch_message(self, msg: WorkspaceMessage, is_host: bool) -> None:
        mt = msg.msg_type
        if mt == WsMsgType.CLIPBOARD_TEXT:
            if len(msg.payload) <= MAX_CLIPBOARD_BYTES:
                digest = hashlib.sha256(msg.payload).hexdigest()
                with self._clip_lock:
                    if digest == self._last_clip_hash:
                        return
                    self._last_clip_hash = digest
                text = msg.payload.decode("utf-8", errors="replace")
                if self.on_clipboard_rx is not None:
                    self.on_clipboard_rx(text)

        elif mt == WsMsgType.FILE_META:
            info = msg.decode_json()
            if not info:
                return
            try:
                tid_bytes = bytes.fromhex(str(info.get("transfer_id", "")))
                size = int(info.get("size", 0))
                total_chunks = max(1, int(info.get("total_chunks", 1)))
                if len(tid_bytes) != 16 or size < 0 or size > MAX_FILE_BYTES:
                    return
                safe_name = sanitize_filename(str(info.get("filename", "arquivo.bin")))
                self._rx_transfers[tid_bytes] = {
                    "transfer_id": tid_bytes.hex(),
                    "filename": safe_name,
                    "size": size,
                    "sha256": str(info.get("sha256", "")).lower(),
                    "total_chunks": total_chunks,
                    "chunks": {},
                }
                if self.on_file_status:
                    self.on_file_status({"stage": "receiving", "filename": safe_name, "progress": 0.0})
            except Exception:
                pass

        elif mt == WsMsgType.FILE_CHUNK:
            if len(msg.payload) < _FILE_CHUNK_HDR.size:
                return
            tid_bytes, chunk_idx = _FILE_CHUNK_HDR.unpack(msg.payload[: _FILE_CHUNK_HDR.size])
            state = self._rx_transfers.get(tid_bytes)
            if state is None:
                return
            state["chunks"][chunk_idx] = msg.payload[_FILE_CHUNK_HDR.size :]
            got = len(state["chunks"])
            tot = state["total_chunks"]
            if got >= tot:
                self._finalize_file_rx(tid_bytes, state)
            elif self.on_file_status and (got % 16 == 0):
                self.on_file_status({
                    "stage": "receiving",
                    "filename": state["filename"],
                    "progress": round((got / max(1, tot)) * 100.0, 1),
                })

        elif mt == WsMsgType.FILE_DONE:
            info = msg.decode_json()
            if info and self.on_file_status:
                self.on_file_status(info)

        elif mt == WsMsgType.SHELL_STDIN and is_host:
            self.shell.write_stdin(msg.payload)

        elif mt == WsMsgType.SHELL_RESIZE and is_host and len(msg.payload) >= 4:
            cols, rows = struct.unpack("!HH", msg.payload[:4])
            self.shell.resize(cols, rows)

        elif mt == WsMsgType.SHELL_STDOUT and not is_host:
            if self.on_shell_output:
                self.on_shell_output(msg.payload.decode("utf-8", errors="replace"))

    def _finalize_file_rx(self, tid_bytes: bytes, state: Dict[str, Any]) -> None:
        self._rx_transfers.pop(tid_bytes, None)
        ordered = [state["chunks"].get(i, b"") for i in range(state["total_chunks"])]
        full_bytes = b"".join(ordered)
        actual_sha = hashlib.sha256(full_bytes).hexdigest().lower()

        if state["sha256"] and actual_sha != state["sha256"]:
            done_info = {
                "stage": "error",
                "transfer_id": state["transfer_id"],
                "ok": False,
                "filename": state["filename"],
                "error": "Falha de integridade SHA-256.",
            }
            self._emit_wire(self.channel.send_json(WsMsgType.FILE_DONE, done_info))
            if self.on_file_status:
                self.on_file_status(done_info)
            return

        self.download_dir.mkdir(parents=True, exist_ok=True)
        base_name = sanitize_filename(state["filename"])
        dest = self.download_dir / base_name
        stem, suffix = dest.stem, dest.suffix
        counter = 1
        while dest.exists():
            dest = self.download_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        tmp_dest = self.download_dir / f".{dest.name}.part"
        tmp_dest.write_bytes(full_bytes)
        tmp_dest.replace(dest)

        done_info = {
            "stage": "completed",
            "transfer_id": state["transfer_id"],
            "ok": True,
            "filename": dest.name,
            "size": len(full_bytes),
            "progress": 100.0,
        }
        self._emit_wire(self.channel.send_json(WsMsgType.FILE_DONE, done_info))
        if self.on_file_status:
            self.on_file_status(done_info)

    def close(self) -> None:
        self.shell.close()
        self._rx_transfers.clear()
