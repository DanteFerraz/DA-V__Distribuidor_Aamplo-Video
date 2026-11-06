# -*- coding: utf-8 -*-
"""
Validação unitária do motor de captura Wayland/PipeWire, ambiente desempacotado
e pipeline de compressão multi-core SIMD com escala de passe único.
"""

import os
import sys
from pathlib import Path
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.capture.linux_wayland_portal import _build_clean_host_env, is_wayland_session
from src.codec.hybrid_codec import HybridEncoder


def test_build_clean_host_env_cleans_pyinstaller_pollution(monkeypatch):
    """Garante que variáveis de ambiente injetadas por PyInstaller sejam expurgadas."""
    monkeypatch.setenv("PYTHONHOME", "/fake/_MEIPASS2/python")
    monkeypatch.setenv("PYTHONPATH", "/fake/_MEIPASS2/site-packages")
    monkeypatch.setenv(
        "LD_LIBRARY_PATH",
        f"/tmp/_MEI12345/lib{os.pathsep}/usr/lib/x86_64-linux-gnu{os.pathsep}/app/_internal/libs",
    )

    clean_env = _build_clean_host_env()
    assert "PYTHONHOME" not in clean_env
    assert "PYTHONPATH" not in clean_env
    assert "_MEI" not in clean_env.get("LD_LIBRARY_PATH", "")
    assert "_internal" not in clean_env.get("LD_LIBRARY_PATH", "")
    assert "/usr/lib/x86_64-linux-gnu" in clean_env.get("LD_LIBRARY_PATH", "")


def test_is_wayland_session_detection(monkeypatch):
    """Verifica detecção de compositor Wayland ativo via variáveis de ambiente."""
    if sys.platform == "win32":
        # No Windows, is_wayland_session() deve retornar sempre False
        assert not is_wayland_session()
    else:
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert is_wayland_session()

        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        assert is_wayland_session()

        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert not is_wayland_session()


def test_hybrid_encoder_single_pass_rescale():
    """Valida encode libx264 com redimensionamento de quadro nativo 1366x768 -> 1280x720."""
    try:
        import av
    except ImportError:
        pytest.skip("PyAV não instalado no ambiente de teste")

    enc = HybridEncoder(
        codec_type="libx264",
        width=1280,
        height=720,
        fps=60,
        bitrate_kbps=6000,
    )
    # Quadro 1366x768 simulando monitor do notebook cliente
    dummy_frame = np.full((768, 1366, 4), 120, dtype=np.uint8)
    dummy_frame[:, :, 0] = 200  # canal Azul
    dummy_frame[:, :, 1] = 50   # canal Verde
    dummy_frame[:, :, 2] = 20   # canal Vermelho
    dummy_frame[:, :, 3] = 255  # canal Alpha

    payload = enc.encode(dummy_frame)
    assert payload is not None
    assert len(payload) > 100
    assert payload.startswith(b"DAV_H264:")
    enc.close()
