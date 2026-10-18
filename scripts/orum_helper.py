# -*- coding: utf-8 -*-
"""
ORUM Integration Helper for DA-V (Distribuidor Aamplo - Video)
Handles project registration, task DAG management, audit logging,
test execution records and knowledge base sync with ORUM Hub.
"""

import urllib.request
import urllib.error
import json
import os
import sys
import datetime

ORUM_BASE_URL = os.environ.get("ORUM_BASE_URL", "http://localhost:5000")

def _request(endpoint, method="GET", data=None):
    url = f"{ORUM_BASE_URL}{endpoint}"
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json", "User-Agent": "DA-V-ORUM-Client/1.0"}
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
            return resp.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8")
        try:
            err_json = json.loads(content)
        except Exception:
            err_json = {"error": content}
        return e.code, err_json
    except Exception as e:
        return 500, {"error": str(e)}

def get_project(project_id_or_slug):
    status, data = _request(f"/api/projects/{project_id_or_slug}")
    return data if status == 200 else None

def get_all_projects():
    status, data = _request("/api/projects")
    return data if status == 200 else []

def ensure_project(name, slug, category, description, tech_stack, target_dir, spec_data=None):
    projects = get_all_projects()
    for p in projects:
        if p.get("slug") == slug or p.get("name") == name:
            return p
    
    payload = {
        "name": name,
        "slug": slug,
        "category": category,
        "description": description,
        "tech_stack": tech_stack,
        "target_directory": target_dir,
        "status": "in_progress",
        "spec_data": spec_data or {}
    }
    status, data = _request("/api/projects", method="POST", data=payload)
    if status in (200, 201):
        return data
    return None

def create_task(project_id, title, description, priority="high", agent_role="developer", acceptance_criteria=None, dependencies=None):
    payload = {
        "title": title,
        "description": description,
        "priority": priority,
        "agent_role": agent_role,
        "acceptance_criteria": acceptance_criteria or [],
        "dependencies": dependencies or []
    }
    status, data = _request(f"/api/projects/{project_id}/tasks", method="POST", data=payload)
    return data if status in (200, 201) else None

def update_task_status(project_id, task_id, status, output_summary=None, error_message=None):
    payload = {"status": status}
    if output_summary:
        payload["output_summary"] = output_summary
    if error_message:
        payload["error_message"] = error_message
    
    res_status, data = _request(f"/api/projects/{project_id}/tasks/{task_id}", method="PATCH", data=payload)
    return data if res_status == 200 else None

def log_note(title, slug, category, tags, content, project_id=None):
    payload = {
        "title": title,
        "slug": slug,
        "category": category,
        "tags": tags,
        "content": content,
        "project_id": project_id
    }
    status, data = _request("/api/notes", method="POST", data=payload)
    return data if status in (200, 201) else None

def sync_project_files(project_id):
    status, data = _request(f"/api/projects/{project_id}/sync", method="POST")
    return data if status == 200 else None

def setup_dav_dag(project_id):
    """Configures the complete 8-task DAG for DA-V in ORUM."""
    current = get_project(project_id)
    existing_tasks = {t.get("title"): t for t in current.get("tasks", [])}
    
    tasks_spec = [
        {
            "title": "Task 1: Scaffold, Build System & Hardware Detection",
            "description": "Estrutura CMake 3.28+, detecção automática de GPU RTX 4070 / CUDA / NVENC, abstrações de plataforma Windows/Linux, setup de dependências (KCP, toml++, spdlog, libsodium, FFmpeg headers).",
            "acceptance_criteria": ["CMakeLists.txt funcional", "Detecção automática de hardware", "Headers e módulos base integrados"]
        },
        {
            "title": "Task 2: UDP Sockets & KCP ARQ Transport Layer",
            "description": "Camada de transporte assíncrona UDP com KCP ARQ de baixíssima latência (30-40% mais rápido que TCP), janelas de congestionamento agressivas, sem Nagle, e buffer de retransmissão.",
            "acceptance_criteria": ["UdpSocket multiplataforma", "KcpTransport com ARQ próprio", "Loopback teste de pacotes com throughput e RTT"]
        },
        {
            "title": "Task 3: ICapturer & Zero-Copy Screen Capture",
            "description": "Interface abstrata ICapturer, Windows DXGI Desktop Duplication API (GPU-side zero-copy ring buffer SPSC lock-free), abstração Linux X11/PipeWire, e conversão de formato.",
            "acceptance_criteria": ["ICapturer interface", "DxgiCapturer Windows zero-copy", "RingBuffer SPSC lock-free", "X11Capturer Linux"]
        },
        {
            "title": "Task 4: IEncoder & Hardware-Accelerated Video Codec",
            "description": "Interface abstrata IEncoder, codificador H.264 via software (libx264) e aceleração por hardware NVIDIA NVENC, mais FrameScaler (libyuv NV12 conversion).",
            "acceptance_criteria": ["IEncoder interface", "SwEncoder H.264 baseline", "NvencEncoder com zero-copy GPU", "FrameScaler BGRA->NV12"]
        },
        {
            "title": "Task 5: RTP-like Packetizer, Wire Protocol & Crypto",
            "description": "Fragmentador MTU-aware (≤ 1400 bytes) para NAL units H.264, FrameAssembler no receptor, wire format binário com timestamp µs, criptografia ChaCha20-Poly1305 e troca de chaves X25519.",
            "acceptance_criteria": ["Wire format de 32 bytes header", "RtpPacketizer e FrameAssembler", "CryptoChannel ChaCha20-Poly1305 autenticado"]
        },
        {
            "title": "Task 6: QoS Engine, Congestion Control & Adaptive Bitrate",
            "description": "Motor de Qualidade de Serviço: GCC (Google Congestion Control delay-based), Adaptive Bitrate (ABR) dinâmico, Reed-Solomon & XOR Forward Error Correction (FEC), jitter buffer adaptativo e retransmissão NACK seletiva.",
            "acceptance_criteria": ["BandwidthEstimator GCC", "AdaptiveBitrate controller", "FecHandler Reed-Solomon/XOR", "JitterBuffer adaptativo", "NackHandler"]
        },
        {
            "title": "Task 7: Session Management, LAN Discovery & WAN Signaling",
            "description": "Gerenciador de sessões multi-peer com isolamento de QoS, reconexão resiliente com backoff exponencial, descoberta mDNS em LAN, e servidor de sinalização público em Python asyncio para travessia NAT/ICE.",
            "acceptance_criteria": ["SessionManager com state machine", "ReconnectHandler", "mDNS LAN discovery", "Servidor de sinalização WebSocket Python"]
        },
        {
            "title": "Task 8: Observability, Prometheus Metrics & Full Loopback Test Suite",
            "description": "Registro de métricas de QoS em tempo real (FPS, bitrate, RTT, perda, jitter, FEC overhead), endpoint Prometheus HTTP /metrics, suíte completa de testes unitários e de integração de ponta a ponta.",
            "acceptance_criteria": ["Prometheus metrics registry", "Endpoint /metrics", "Test suite completa passando", "Comprovação de sucesso registrada no ORUM"]
        }
    ]
    
    created = []
    for spec in tasks_spec:
        if spec["title"] not in existing_tasks:
            t = create_task(
                project_id=project_id,
                title=spec["title"],
                description=spec["description"],
                acceptance_criteria=spec["acceptance_criteria"]
            )
            if t:
                created.append(t)
                print(f"Task created: [{t.get('id')}] {spec['title']}")
        else:
            created.append(existing_tasks[spec["title"]])
    
    return created

if __name__ == "__main__":
    p = ensure_project(
        name="DA-V — Distribuidor Aamplo Video",
        slug="da-v-distribuidor-aamplo-video",
        category="Backend / QoS Video Streaming Service",
        description="Serviço de distribuição de vídeo de alta performance e baixa latência sobre redes LAN e WAN com QoS adaptativo, KCP ARQ e aceleração por hardware NVENC/x264.",
        tech_stack="C++23 + Python + KCP + libsodium + FFmpeg/NVENC + DXGI/X11 + Prometheus",
        target_dir=r"c:\Users\Dante\Desktop\Distribuidor_Aamplo-Video"
    )
    print("Project ID:", p.get("id"))
    tasks = setup_dav_dag(p.get("id"))
    print(f"Total DAG tasks registered: {len(tasks)}")
    sync_project_files(p.get("id"))
