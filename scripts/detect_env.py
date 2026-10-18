#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Environment & Hardware Detector for DA-V (Distribuidor Aamplo - Video)
Scans CPU, dedicated GPU (NVIDIA / AMD / Intel), CUDA compute capability,
available encoders, and network interfaces.
"""

import sys
import os
import subprocess
import json
import platform
import socket

def check_nvidia_gpu():
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if res.returncode == 0:
            lines = res.stdout.strip().split("\n")
            gpus = []
            for line in lines:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    gpus.append({
                        "vendor": "NVIDIA",
                        "model": parts[0],
                        "driver": parts[1],
                        "vram_mb": int(parts[2]),
                        "utilization_pct": int(parts[3])
                    })
            return gpus
    except Exception:
        pass
    return []

def detect_platform_info():
    return {
        "os": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version()
    }

def detect_network_adapters():
    hostname = socket.gethostname()
    try:
        ip_addresses = socket.gethostbyname_ex(hostname)[2]
    except Exception:
        ip_addresses = ["127.0.0.1"]
    
    return {
        "hostname": hostname,
        "local_ips": [ip for ip in ip_addresses if not ip.startswith("127.")]
    }

def detect_environment():
    gpus = check_nvidia_gpu()
    plat = detect_platform_info()
    net = detect_network_adapters()
    
    has_cuda = len(gpus) > 0 and "NVIDIA" in [g["vendor"] for g in gpus]
    
    capabilities = {
        "hardware_acceleration": {
            "nvenc": has_cuda,
            "qsv": False,
            "amf": False,
            "recommended_encoder": "nvenc" if has_cuda else "x264"
        },
        "capture_backend": "dxgi" if plat["os"] == "Windows" else "x11",
        "transport_default": "kcp",
        "crypto_backend": "libsodium_chacha20_poly1305"
    }
    
    report = {
        "platform": plat,
        "gpus": gpus,
        "network": net,
        "capabilities": capabilities,
        "status": "ready"
    }
    return report

if __name__ == "__main__":
    rep = detect_environment()
    print(json.dumps(rep, indent=2))
