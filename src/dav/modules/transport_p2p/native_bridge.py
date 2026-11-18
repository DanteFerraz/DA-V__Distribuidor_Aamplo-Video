# -*- coding: utf-8 -*-
"""
Ponte Opcional para Data Plane Nativo C++23 (`libdav_core` C-ABI) — DA-V v4.5
Autor: Dante Ferraz (MonoTech)

Permite acelerar AEAD ChaCha20-Poly1305 e Reed-Solomon GF(2^8) via C-ABI quando
`dav_core.dll` / `libdav_core.so` estiver compilado e `DAV_USE_NATIVE_CORE=1`.
"""

from __future__ import annotations

import ctypes
import os
from typing import Optional


class NativeDataPlaneBridge:
    """Wrapper stateless C-ABI com fallback automatico para Python/OpenSSL/NumPy."""

    def __init__(self):
        self._lib = None
        self.available = False
        if os.environ.get("DAV_USE_NATIVE_CORE") == "1":
            self._load()

    def _load(self) -> None:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        candidates = [
            os.path.join(base_dir, "build", "Release", "dav_core.dll"),
            os.path.join(base_dir, "build", "dav_core.dll"),
            os.path.join(base_dir, "build", "libdav_core.so"),
            "dav_core.dll",
            "libdav_core.so",
        ]
        for path in candidates:
            if not os.path.exists(path):
                continue
            try:
                lib = ctypes.CDLL(os.path.abspath(path))
                if not hasattr(lib, "dav_aead_seal_raw") or not hasattr(lib, "dav_fec_encode_gf256"):
                    continue
                lib.dav_aead_seal_raw.argtypes = [
                    ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t,
                    ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p,
                ]
                lib.dav_aead_seal_raw.restype = ctypes.c_int

                lib.dav_aead_open_raw.argtypes = [
                    ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t,
                    ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p,
                ]
                lib.dav_aead_open_raw.restype = ctypes.c_int

                lib.dav_fec_encode_gf256.argtypes = [
                    ctypes.c_uint16, ctypes.c_uint8, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_char_p,
                ]
                lib.dav_fec_encode_gf256.restype = ctypes.c_int

                lib.dav_fec_recover_gf256.argtypes = [
                    ctypes.c_uint16, ctypes.c_uint8, ctypes.c_size_t,
                    ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                ]
                lib.dav_fec_recover_gf256.restype = ctypes.c_int

                self._lib = lib
                self.available = True
                return
            except Exception:
                continue

    def aead_seal(self, key32: bytes, nonce12: bytes, aad: bytes, plaintext: bytes) -> Optional[bytes]:
        if not self.available or self._lib is None:
            return None
        out = ctypes.create_string_buffer(len(plaintext) + 16)
        rc = self._lib.dav_aead_seal_raw(key32, nonce12, aad, len(aad), plaintext, len(plaintext), out)
        return out.raw if rc == 0 else None

    def aead_open(self, key32: bytes, nonce12: bytes, aad: bytes, ct_and_tag: bytes) -> Optional[bytes]:
        if not self.available or self._lib is None or len(ct_and_tag) < 16:
            return None
        pt_len = len(ct_and_tag) - 16
        out = ctypes.create_string_buffer(max(1, pt_len))
        rc = self._lib.dav_aead_open_raw(key32, nonce12, aad, len(aad), ct_and_tag, len(ct_and_tag), out)
        return out.raw[:pt_len] if rc == 0 else None
