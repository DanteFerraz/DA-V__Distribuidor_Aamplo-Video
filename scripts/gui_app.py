#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V — Distribuidor Amplo de Vídeo (Desktop Launcher)
Autor: Dante Ferraz (MonoTech)

Ponto de entrada da interface gráfica desktop construída sobre PySide6 (Qt).
Configura afinidade de SO, timer de alta precisão (1ms), prioridade de processo
e formatação de superfície gráfica sem bloqueio de VSync antes de inicializar a janela.
"""

import sys
import os
import argparse
import multiprocessing


def _configure_os_realtime_priority():
    """Eleva prioridade de escalonamento e reduz granularidade do timer do SO para 1ms."""
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


if getattr(sys, "frozen", False):
    PROJECT_ROOT = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
else:
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def main():
    _configure_os_realtime_priority()

    from scripts.qt_compat import QApplication
    from src.ui.main_window import DavMainWindow

    parser = argparse.ArgumentParser(description="DA-V Video Hub")
    parser.add_argument("--port", type=int, default=None, help="Porta UDP padrao para escuta do receptor")
    parser.add_argument("--target-port", type=int, default=None, help="Porta UDP alvo padrao para o transmissor")
    parser.add_argument("--auto-recv", action="store_true", help="Inicia automaticamente o receptor ao abrir")
    parser.add_argument("--auto-send", action="store_true", help="Inicia automaticamente a transmissao ao abrir")
    parser.add_argument("--monitor", type=int, default=1, help="Indice do monitor de origem (0=Mon1, 1=Mon2)")
    parser.add_argument("--pin", type=str, default=None, help="PIN de autenticacao compartilhado")
    parser.add_argument("--self-check", action="store_true", help="Valida inicializacao do binario empacotado e encerra")
    parser.add_argument("uri", nargs="?", default=None, help="URI de convite direto (ex: dav://connect/415-759)")
    args, _ = parser.parse_known_args()

    pin_arg = args.pin
    auto_recv_arg = args.auto_recv
    p2p_uri_mode = False
    if args.uri and ("dav" in args.uri or "/" in args.uri):
        extracted_pin = args.uri.split("/")[-1].strip().replace("dav:", "").strip(":/ ")
        if extracted_pin:
            pin_arg = extracted_pin
            auto_recv_arg = True
            p2p_uri_mode = True

    try:
        from PySide6.QtGui import QSurfaceFormat
        fmt = QSurfaceFormat()
        fmt.setSwapInterval(0)  # Immediate unbuffered presentation without VSync coalescence
        QSurfaceFormat.setDefaultFormat(fmt)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("DA-V Video Hub")

    try:
        from PySide6.QtGui import QIcon
        for icon_rel in ("installer/dav_icon.ico", "installer/dav_icon.png", "dav_icon.ico", "dav_icon.png"):
            icon_candidate = os.path.join(PROJECT_ROOT, icon_rel)
            if os.path.isfile(icon_candidate):
                app.setWindowIcon(QIcon(icon_candidate))
                break
    except Exception:
        pass

    window = DavMainWindow(
        custom_port=args.port,
        custom_target_port=args.target_port,
        auto_recv=auto_recv_arg,
        auto_send=args.auto_send,
        monitor_idx=args.monitor,
        custom_pin=pin_arg,
        p2p_uri_mode=p2p_uri_mode,
    )

    if args.self_check:
        from PySide6.QtCore import QTimer
        print("DAV_SELF_CHECK_OK")
        QTimer.singleShot(150, window.close)
        QTimer.singleShot(250, app.quit)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
