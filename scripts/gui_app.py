#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V — Distribuidor Aamplo · Video Distribution Service GUI
Modern Desktop Application powered by PySide6 (LGPL v3 - Safe for Commercial & Closed-Source Use).
Acts strictly as a lightweight presentation launcher consuming the modular DA-V UI package.
"""

import sys
import os
import argparse

# Enable 1ms high-precision multimedia timer, elevate priority and attach to WinSta0\Default
if sys.platform == "win32":
    try:
        import ctypes
        from ctypes import wintypes
        ctypes.windll.winmm.timeBeginPeriod(1)
        _k32 = ctypes.windll.kernel32
        _k32.GetCurrentProcessId.restype = wintypes.DWORD
        _k32.OpenProcess.restype = wintypes.HANDLE
        _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        _k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        _k32.SetPriorityClass.restype = wintypes.BOOL
        _k32.CloseHandle.argtypes = [wintypes.HANDLE]
        _k32.CloseHandle.restype = wintypes.BOOL
        _pid = _k32.GetCurrentProcessId()
        _h = _k32.OpenProcess(0x1F0FFF, False, _pid)
        if _h:
            _k32.SetPriorityClass(_h, 0x8000)  # ABOVE_NORMAL_PRIORITY_CLASS
            _k32.CloseHandle(_h)

        # Attach main thread to interactive user desktop WinSta0\Default
        _u32 = ctypes.windll.user32
        _h_desk = _u32.OpenDesktopW("Default", 0, False, 0x01FF)
        if _h_desk:
            _u32.SetThreadDesktop(_h_desk)
    except Exception:
        pass
else:
    try:
        os.nice(-10)
    except Exception:
        pass

try:
    sys.setswitchinterval(0.001)
except Exception:
    pass

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.qt_compat import QApplication
from src.ui.main_window import DavMainWindow


def main():
    parser = argparse.ArgumentParser(description="DA-V Video Hub")
    parser.add_argument("--port", type=int, default=None, help="Porta UDP padrao para escuta do receptor")
    parser.add_argument("--target-port", type=int, default=None, help="Porta UDP alvo padrao para o transmissor")
    parser.add_argument("--auto-recv", action="store_true", help="Inicia automaticamente o receptor ao abrir")
    parser.add_argument("--auto-send", action="store_true", help="Inicia automaticamente a transmissao ao abrir")
    parser.add_argument("--monitor", type=int, default=1, help="Indice do monitor de origem (0=Mon1, 1=Mon2)")
    parser.add_argument("--pin", type=str, default=None, help="PIN de autenticacao compartilhado")
    args, _ = parser.parse_known_args()

    try:
        from PySide6.QtGui import QSurfaceFormat
        fmt = QSurfaceFormat()
        fmt.setSwapInterval(0)  # Immediate unbuffered presentation without VSync coalescence
        QSurfaceFormat.setDefaultFormat(fmt)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("DA-V Video Hub")
    window = DavMainWindow(
        custom_port=args.port,
        custom_target_port=args.target_port,
        auto_recv=args.auto_recv,
        auto_send=args.auto_send,
        monitor_idx=args.monitor,
        custom_pin=args.pin
    )
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
