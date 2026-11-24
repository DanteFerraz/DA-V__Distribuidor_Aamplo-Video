# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Trigger Nativo e Broker Isolado de Privilegio Administrativo (Windows UAC & Linux Polkit) — DA-V v5.0
Autor: Dante Ferraz (MonoTech)

Arquitetura:
- Permite elevar APENAS o micro-broker de injecao (`--elevated-input-broker`), mantendo a GUI
  principal, captura PipeWire/WGC e audio PulseAudio/WASAPI intactos na sessao do usuario comum
  e sem derrubar chamadas P2P em andamento.
- Windows: Dispara UAC via `ShellExecuteW(None, "runas", ...)` subindo `Win32InputInjector` com
  *High Mandatory Integrity Level* (capaz de interagir com janelas de Administrador / UIPI).
- Linux: Dispara Polkit via `pkexec` abrindo `/dev/uinput` no kernel (`LinuxUInputInjector`).
- Seguranca IPC: Conexao loopback `127.0.0.1` (`TCP_NODELAY`), arquivo de segredo `0600` apagado
  apos handshake `HMAC-SHA256` mutuo e watchdog do PID pai a cada 250 ms.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, List, Optional, Tuple

from src.dav.kernel.result import ServiceResult
from src.dav.modules.remote_desktop.injector_base import (
    BaseInputInjector,
    MonitorBounds,
    NullSyntheticInjector,
)
from src.dav.modules.remote_desktop.protocol import INPUT_PACKET_SIZE, InputEventPacket

_BROKER_MAGIC = b"DAV_BRK1"
_CMD_INJECT = 1      # 1B cmd + 24B InputEventPacket
_CMD_BOUNDS = 2      # 1B cmd + 16B (!iiii: left, top, width, height)
_CMD_RELEASE = 3     # 1B cmd
_CMD_SHUTDOWN = 4    # 1B cmd
_BOUNDS_STRUCT = struct.Struct("!iiii")


def is_process_elevated() -> bool:
    """Retorna True se o processo atual ja possui privilegio de injecao administrativa."""
    if sys.platform == "win32":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        if os.geteuid() == 0:
            return True
    except AttributeError:
        pass
    for dev in ("/dev/uinput", "/dev/input/uinput"):
        if os.path.exists(dev) and os.access(dev, os.W_OK):
            return True
    return False


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            SYNCHRONIZE = 0x00100000
            WAIT_OBJECT_0 = 0x00000000
            k32 = ctypes.windll.kernel32
            h_proc = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
            if not h_proc:
                return False
            res = k32.WaitForSingleObject(h_proc, 0)
            k32.CloseHandle(h_proc)
            return res != WAIT_OBJECT_0
        except Exception:
            return True
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True


def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except (socket.timeout, BlockingIOError):
            return None
        except OSError:
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _create_native_broker_injector(force_synthetic: bool = False) -> BaseInputInjector:
    if force_synthetic or os.environ.get("DAV_HEADLESS_SYNTHETIC") == "1":
        return NullSyntheticInjector(elevated=True)
    if sys.platform == "win32":
        from src.dav.modules.remote_desktop.injector_win32 import Win32InputInjector

        return Win32InputInjector()
    from src.dav.modules.remote_desktop.injector_linux import (
        LinuxUInputInjector,
        X11XTestInjector,
    )

    try:
        return LinuxUInputInjector()
    except Exception:
        try:
            return X11XTestInjector()
        except Exception:
            return NullSyntheticInjector(elevated=True)


def run_elevated_broker_loop(
    port: int,
    parent_pid: int,
    token_file: str,
    force_synthetic: bool = False,
) -> int:
    """Loop principal do micro-processo privilegiado (`--elevated-input-broker`)."""
    token_path = Path(token_file)
    try:
        secret = token_path.read_bytes().strip()
    except Exception:
        return 2
    finally:
        try:
            token_path.unlink(missing_ok=True)
        except Exception:
            pass

    if len(secret) < 32:
        return 3

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.settimeout(5.0)
    try:
        sock.connect(("127.0.0.1", int(port)))
        challenge = _recv_exact(sock, 32)
        if not challenge:
            return 4
        proof = hmac.new(secret, _BROKER_MAGIC + challenge, hashlib.sha256).digest()
        sock.sendall(_BROKER_MAGIC + proof)
        ack = _recv_exact(sock, 2)
        if ack != b"OK":
            return 5
    except Exception:
        sock.close()
        return 6

    injector = _create_native_broker_injector(force_synthetic=force_synthetic)
    sock.settimeout(0.20)
    last_parent_check = time.monotonic()

    try:
        while True:
            now = time.monotonic()
            if (now - last_parent_check) >= 0.25:
                last_parent_check = now
                injector.tick_watchdog(now_mono=now)
                if not _is_pid_alive(parent_pid):
                    break

            try:
                cmd_b = sock.recv(1)
            except socket.timeout:
                continue
            except OSError:
                break

            if not cmd_b:
                break

            cmd = cmd_b[0]
            if cmd == _CMD_INJECT:
                raw_pkt = _recv_exact(sock, INPUT_PACKET_SIZE)
                if raw_pkt is None:
                    break
                pkt = InputEventPacket.unpack(raw_pkt)
                if pkt is not None:
                    injector.inject(pkt)
            elif cmd == _CMD_BOUNDS:
                raw_b = _recv_exact(sock, _BOUNDS_STRUCT.size)
                if raw_b is None:
                    break
                l_px, t_px, w_px, h_px = _BOUNDS_STRUCT.unpack(raw_b)
                injector.update_monitor_bounds(l_px, t_px, w_px, h_px)
            elif cmd == _CMD_RELEASE:
                injector.release_all()
            elif cmd == _CMD_SHUTDOWN:
                break
    finally:
        injector.close()
        try:
            sock.close()
        except Exception:
            pass
    return 0


def run_elevated_broker_cli(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--elevated-input-broker", action="store_true")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--token-file", type=str, required=True)
    parser.add_argument("--synthetic", action="store_true")
    ns, _ = parser.parse_known_args(argv)
    return run_elevated_broker_loop(
        port=ns.port,
        parent_pid=ns.parent_pid,
        token_file=ns.token_file,
        force_synthetic=ns.synthetic,
    )


def _resolve_broker_command(port: int, parent_pid: int, token_file: str) -> Tuple[str, List[str], str]:
    """Retorna `(executavel, lista_argumentos, cwd)` para invocar o broker em fonte ou PyInstaller."""
    if getattr(sys, "frozen", False):
        exe = os.path.abspath(sys.executable)
        cwd = os.path.dirname(exe)
        args = [
            "--elevated-input-broker",
            "--port", str(port),
            "--parent-pid", str(parent_pid),
            "--token-file", token_file,
        ]
        return exe, args, cwd

    proj_root = str(Path(__file__).resolve().parents[4])
    gui_script = str(Path(proj_root) / "scripts" / "gui_app.py")
    exe = sys.executable
    if sys.platform == "win32":
        pyw = Path(exe).with_name("pythonw.exe")
        if pyw.is_file():
            exe = str(pyw)
    args = [
        gui_script,
        "--elevated-input-broker",
        "--port", str(port),
        "--parent-pid", str(parent_pid),
        "--token-file", token_file,
    ]
    return exe, args, proj_root


def _default_elevated_launcher(exe: str, args: List[str], cwd: str) -> Tuple[bool, str]:
    """Dispara UAC (`runas`) no Windows ou Polkit (`pkexec`) no Linux."""
    if sys.platform == "win32":
        try:
            params = subprocess.list2cmdline(args)
            ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, cwd, 0)
            if int(ret) <= 32:
                return False, f"Elevacao UAC recusada ou cancelada pelo usuario (codigo={ret})."
            return True, "UAC autorizado"
        except Exception as exc:
            return False, f"Falha ao solicitar UAC no Windows: {exc}"

    pkexec_bin = shutil.which("pkexec")
    if not pkexec_bin:
        return False, "Utilitario Polkit (pkexec) nao encontrado na distribuicao Linux."
    try:
        subprocess.Popen(
            [pkexec_bin, exe, *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return True, "Polkit iniciado"
    except Exception as exc:
        return False, f"Falha ao iniciar Polkit (pkexec): {exc}"


class ElevatedProxyInjector(BaseInputInjector):
    """Cliente local que encaminha `InputEventPacket`s em `< 0,08 ms` ao `ElevatedInputBroker`."""

    def __init__(self, conn: socket.socket, bounds: Optional[MonitorBounds] = None):
        super().__init__(bounds=bounds)
        self._conn = conn
        self._send_lock = threading.Lock()
        self._alive = True
        self.update_monitor_bounds(
            self.bounds.left, self.bounds.top, self.bounds.width, self.bounds.height
        )

    @property
    def backend_name(self) -> str:
        return "elevated_broker_uac" if sys.platform == "win32" else "elevated_broker_polkit_uinput"

    @property
    def is_elevated(self) -> bool:
        return self._alive

    def update_monitor_bounds(self, left: int, top: int, width: int, height: int) -> None:
        super().update_monitor_bounds(left, top, width, height)
        frame = bytes([_CMD_BOUNDS]) + _BOUNDS_STRUCT.pack(
            self.bounds.left, self.bounds.top, self.bounds.width, self.bounds.height
        )
        self._send_frame(frame)

    def _send_frame(self, data: bytes) -> bool:
        if not self._alive:
            return False
        with self._send_lock:
            try:
                self._conn.sendall(data)
                return True
            except OSError:
                self._alive = False
                return False

    def _inject_native(self, pkt: InputEventPacket) -> bool:
        return self._send_frame(bytes([_CMD_INJECT]) + pkt.pack())

    def release_all(self) -> int:
        count = super().release_all()
        self._send_frame(bytes([_CMD_RELEASE]))
        return count

    def close(self) -> None:
        if self._alive:
            self._send_frame(bytes([_CMD_RELEASE, _CMD_SHUTDOWN]))
            self._alive = False
        try:
            self._conn.close()
        except Exception:
            pass


def request_elevated_injector(
    bounds: Optional[MonitorBounds] = None,
    timeout_sec: float = 25.0,
    launcher_fn: Optional[Callable[[str, List[str], str], Tuple[bool, str]]] = None,
) -> ServiceResult[ElevatedProxyInjector]:
    """
    Solicita autorizacao de Administrador (Windows UAC / Linux Polkit) e retorna um
    `ElevatedProxyInjector` autenticado conectado ao broker isolado.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(max(1.0, float(timeout_sec)))
    port = int(listener.getsockname()[1])

    secret_hex = secrets.token_hex(32).encode("ascii")
    fd_tmp, token_file = tempfile.mkstemp(prefix="dav_brk_", suffix=".tok")
    try:
        try:
            os.chmod(token_file, 0o600)
        except Exception:
            pass
        os.write(fd_tmp, secret_hex)
    finally:
        os.close(fd_tmp)

    exe, args, cwd = _resolve_broker_command(port=port, parent_pid=os.getpid(), token_file=token_file)
    launch = launcher_fn or _default_elevated_launcher
    launched_ok, msg = launch(exe, args, cwd)
    if not launched_ok:
        listener.close()
        Path(token_file).unlink(missing_ok=True)
        return ServiceResult.fail(msg)

    try:
        conn, _ = listener.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.settimeout(3.0)
        challenge = secrets.token_bytes(32)
        conn.sendall(challenge)
        reply = _recv_exact(conn, len(_BROKER_MAGIC) + 32)
        expected = _BROKER_MAGIC + hmac.new(secret_hex, _BROKER_MAGIC + challenge, hashlib.sha256).digest()
        if reply is None or not hmac.compare_digest(reply, expected):
            conn.close()
            return ServiceResult.fail("Falha na autenticacao HMAC do broker administrativo.")
        conn.sendall(b"OK")
        conn.settimeout(0.5)
        proxy = ElevatedProxyInjector(conn=conn, bounds=bounds)
        return ServiceResult.ok(proxy)
    except socket.timeout:
        return ServiceResult.fail("Tempo esgotado aguardando autorizacao UAC / Polkit.")
    except Exception as exc:
        return ServiceResult.fail(f"Erro ao conectar ao broker administrativo: {exc}")
    finally:
        listener.close()
        Path(token_file).unlink(missing_ok=True)
