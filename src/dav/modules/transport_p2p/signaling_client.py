#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Cliente de Sinalizacao Rendezvous, STUN Dual-Stack (IPv4+IPv6), NAT64 e Travessia de NAT — DA-V v5.2
Autor: Dante Ferraz (MonoTech)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import struct
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.dav.modules.transport_p2p.blind_relay import MAGIC_RLY1 as MAGIC_RELAY_HDR
from src.dav.modules.transport_p2p.blind_relay import normalize_pin, wrap_relay_packet
from src.dav.modules.transport_p2p.dualstack import (
    canonicalize_ip,
    create_dualstack_udp_socket,
    format_sendto_addr,
    format_url_host,
    get_local_ipv6,
    is_global_ipv6,
    is_ipv6_address,
    is_lan_or_local_address,
    is_overlay_address,
    normalize_recv_addr,
    sendto_dualstack,
    synthesize_nat64_ipv6,
)
from src.dav.modules.transport_p2p.packetizer import MAGIC_ACK, MAGIC_PLI, MAGIC_SYN
from src.dav.modules.transport_p2p.stun import parse_stun_response

logger = logging.getLogger("DAV.Transport.Signaling")

DEFAULT_RENDEZVOUS_HOST = os.environ.get("DAV_RENDEZVOUS_HOST", "129.148.26.150")
DEFAULT_RENDEZVOUS_HOST_V6 = os.environ.get("DAV_RENDEZVOUS_HOST_V6", "").strip()
DEFAULT_HTTP_PORT = int(os.environ.get("DAV_RENDEZVOUS_PORT", 80))
DEFAULT_STUN_PORT = int(os.environ.get("DAV_STUN_PORT", 8768))

STUN_MAGIC_COOKIE = 0x2112A442
PUBLIC_STUN_SERVERS: List[Tuple[str, int]] = [
    ("stun.l.google.com", 19302),
    ("stun.cloudflare.com", 3478),
    ("stun1.l.google.com", 19302),
]

# Supressao de re-pareamento para servidores Rendezvous legados que ignoram `since_index`
_LEGACY_DEDUP_WINDOW_SEC = 60.0


def get_local_ip() -> str:
    """Obtem o endereco IP local preferencial (IPv4 ou IPv6 Global se host for IPv6-only)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = canonicalize_ip(s.getsockname()[0])
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    try:
        ip = canonicalize_ip(socket.gethostbyname(socket.gethostname()))
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    v6 = get_local_ipv6()
    if v6:
        return v6
    return "::1" if getattr(socket, "has_ipv6", False) else "127.0.0.1"


def find_available_port(start_port: int = 9000, max_tries: int = 20) -> int:
    """Encontra uma porta UDP livre (Dual-Stack IPv6+IPv4) a partir de `start_port`."""
    for offset in range(max_tries):
        cand = start_port + offset
        try:
            s = create_dualstack_udp_socket(bind_port=cand, rcvbuf_mb=1, sndbuf_mb=1)
            bound = int(s.getsockname()[1])
            s.close()
            if bound == cand:
                return cand
        except OSError:
            continue
    return start_port


def _classify_private_ip(ip: str) -> Optional[str]:
    """Classifica um endereco IPv4 ou IPv6 local como 'lan', 'overlay' ou 'ipv6'."""
    clean = canonicalize_ip(ip)
    if not clean or clean in ("0.0.0.0", "::", "127.0.0.1", "::1") or clean.startswith("127.") or clean.startswith("169.254."):
        return None
    if is_overlay_address(clean):
        return "overlay"
    if is_global_ipv6(clean):
        return "ipv6"
    if is_lan_or_local_address(clean):
        # Ignora link-local IPv6 fe80:: em candidatos inter-redes
        if is_ipv6_address(clean) and clean.lower().startswith("fe80:"):
            return None
        return "lan"
    return None


def get_local_candidates(local_port: int = 9000) -> List[Dict[str, object]]:
    """Coleta candidatos IPv4 e IPv6 ativos da maquina (Ethernet, Wi-Fi, VPNs overlay e IPv6 Global)."""
    candidates: List[Dict[str, object]] = []
    seen = set()

    def _push(ip_s: str, kind_override: Optional[str] = None) -> None:
        clean = canonicalize_ip(ip_s)
        if not clean or clean in seen or clean in ("127.0.0.1", "::1", "0.0.0.0", "::"):
            return
        if is_ipv6_address(clean) and clean.lower().startswith("fe80:"):
            return
        kind = kind_override or _classify_private_ip(clean)
        if not kind:
            return
        seen.add(clean)
        candidates.append({"ip": clean, "port": int(local_port), "type": kind})

    primary_ip = get_local_ip()
    if primary_ip and primary_ip not in ("127.0.0.1", "::1"):
        _push(primary_ip, kind_override=_classify_private_ip(primary_ip) or "lan")

    primary_v6 = get_local_ipv6()
    if primary_v6:
        _push(primary_v6, kind_override="ipv6")

    try:
        import psutil
        for if_name, addrs in psutil.net_if_addrs().items():
            if_lower = if_name.lower()
            if any(
                skip in if_lower
                for skip in ("docker", "br-", "veth", "virbr", "loopback", "virtualbox", "vbox", "vmware", "vmnet", "wsl")
            ):
                continue
            for snic in addrs:
                if snic.family in (socket.AF_INET, socket.AF_INET6):
                    _push(snic.address)
    except Exception:
        pass

    if not candidates:
        fallback_ip = primary_v6 or primary_ip or "127.0.0.1"
        candidates.append({"ip": fallback_ip, "port": int(local_port), "type": "ipv6" if is_global_ipv6(fallback_ip) else "lan"})

    return candidates


def query_rfc5389_stun(
    local_sock: Optional[socket.socket] = None,
    stun_hosts: Optional[List[Tuple[str, int]]] = None,
    timeout: float = 0.85,
    family: Optional[int] = None,
) -> Optional[Tuple[str, int]]:
    """
    Executa Binding Request STUN (RFC 5389) Dual-Stack preservando `local_sock`.
    Suporta `XOR-MAPPED-ADDRESS` / `MAPPED-ADDRESS` IPv4 (`0x01`) e IPv6 (`0x02`, 128 bits).
    """
    if stun_hosts is None:
        stun_hosts = PUBLIC_STUN_SERVERS

    created_socket = False
    sock = local_sock
    if sock is None:
        if family == socket.AF_INET:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        else:
            sock = create_dualstack_udp_socket(bind_port=0, rcvbuf_mb=1, sndbuf_mb=1)
        created_socket = True

    old_timeout = sock.gettimeout()
    sock.settimeout(timeout)

    if family is None:
        resolve_fam = socket.AF_INET if sock.family == socket.AF_INET else socket.AF_UNSPEC
    else:
        resolve_fam = family
        if resolve_fam == socket.AF_INET6 and sock.family == socket.AF_INET:
            if created_socket:
                sock.close()
            return None

    try:
        for host, port in stun_hosts:
            try:
                infos = socket.getaddrinfo(host, port, resolve_fam, socket.SOCK_DGRAM)
            except OSError:
                continue
            if not infos:
                continue

            target_ip = canonicalize_ip(str(infos[0][4][0]))
            dst = format_sendto_addr(sock, target_ip, port)
            if dst is None:
                continue

            trans_id = os.urandom(12)
            req = struct.pack("!HHI12s", 0x0001, 0, STUN_MAGIC_COOKIE, trans_id)
            try:
                sock.sendto(req, dst)
                t_deadline = time.monotonic() + timeout
                while time.monotonic() < t_deadline:
                    data, _ = sock.recvfrom(2048)
                    if len(data) < 20 or data[8:20] != trans_id:
                        continue
                    parsed = parse_stun_response(data, trans_id=trans_id)
                    if parsed is not None:
                        return parsed
                    break
            except Exception:
                continue
    finally:
        try:
            sock.settimeout(old_timeout)
        except Exception:
            pass
        if created_socket:
            sock.close()

    return None


def send_stun_keepalive(sock: socket.socket, stun_host: Tuple[str, int] = ("stun.l.google.com", 19302)) -> None:
    """Envia pacote STUN Binding Request nao-bloqueante de 20 bytes no socket Dual-Stack."""
    try:
        req = struct.pack("!HHI12s", 0x0001, 0, STUN_MAGIC_COOKIE, os.urandom(12))
        sendto_dualstack(sock, req, stun_host[0], int(stun_host[1]))
    except Exception:
        pass


def discover_socket_endpoint(
    bound_sock: socket.socket,
    rendezvous_host: str = DEFAULT_RENDEZVOUS_HOST,
    stun_port: int = DEFAULT_STUN_PORT,
) -> Dict[str, object]:
    """Inspeciona um socket UDP ja vinculado para descobrir candidatos locais e endpoints publicos IPv4+IPv6."""
    try:
        actual_local_port = int(bound_sock.getsockname()[1])
    except Exception:
        actual_local_port = 9000

    local_ip = get_local_ip()
    local_ipv6 = get_local_ipv6()
    local_candidates = get_local_candidates(actual_local_port)

    pub_ip: Optional[str] = None
    pub_port: Optional[int] = None
    pub_ipv6: Optional[str] = local_ipv6
    pub_ipv6_port: int = actual_local_port
    nat_type = "local"

    is_loopback_env = rendezvous_host in ("127.0.0.1", "localhost", "::1")
    if not is_loopback_env:
        # 1. STUN IPv4 (detecta NAT Cone vs Simetrico)
        ep1 = query_rfc5389_stun(bound_sock, [("stun.l.google.com", 19302)], timeout=0.75, family=socket.AF_INET)
        if ep1:
            pub_ip, pub_port = ep1
            nat_type = "cone"
            ep2 = query_rfc5389_stun(bound_sock, [("stun.cloudflare.com", 3478)], timeout=0.65, family=socket.AF_INET)
            if ep2 and ep2[1] != ep1[1]:
                nat_type = "symmetric"
                pub_port = ep2[1]
        else:
            ep_fb = query_rfc5389_stun(bound_sock, [("stun1.l.google.com", 19302)], timeout=0.75, family=socket.AF_INET)
            if ep_fb:
                pub_ip, pub_port = ep_fb
                nat_type = "cone"

        # 2. STUN IPv6 (descobre IPv6 Global + porta reflexiva UDPv6 no mesmo socket Dual-Stack)
        if bound_sock.family == socket.AF_INET6:
            ep6 = query_rfc5389_stun(
                bound_sock,
                [("stun.l.google.com", 19302), ("stun.cloudflare.com", 3478)],
                timeout=0.65,
                family=socket.AF_INET6,
            )
            if ep6 and is_global_ipv6(ep6[0]):
                pub_ipv6, pub_ipv6_port = ep6[0], int(ep6[1])
                if not any(c.get("ip") == pub_ipv6 and int(c.get("port") or 0) == pub_ipv6_port for c in local_candidates):
                    local_candidates.append({"ip": pub_ipv6, "port": pub_ipv6_port, "type": "ipv6"})

    # 3. Fallback leve DAV_STUN_REQ no Rendezvous (em ambiente local ou se STUN publico falhar)
    if pub_ip is None:
        old_timeout = bound_sock.gettimeout()
        try:
            bound_sock.settimeout(0.65)
            sent = sendto_dualstack(bound_sock, b"DAV_STUN_REQ", rendezvous_host, int(stun_port))
            if sent:
                data, _ = bound_sock.recvfrom(1024)
                resp = json.loads(data.decode("utf-8"))
                if resp.get("status") == "ok":
                    ref_ip = canonicalize_ip(str(resp["reflexive_ip"]))
                    ref_port = int(resp["reflexive_port"])
                    if is_ipv6_address(ref_ip):
                        pub_ipv6 = ref_ip
                        pub_ipv6_port = ref_port
                    else:
                        pub_ip = ref_ip
                        pub_port = ref_port
                        nat_type = "local" if ref_ip.startswith("127.") else "cone"
        except Exception:
            pass
        finally:
            try:
                bound_sock.settimeout(old_timeout)
            except Exception:
                pass

    # 4. Host IPv6-Only: promove IPv6 Global como endpoint publico primario
    ipv6_only = False
    if pub_ip is None and pub_ipv6:
        pub_ip = pub_ipv6
        pub_port = pub_ipv6_port
        nat_type = "ipv6-direct"
        ipv6_only = True
        if not local_ip or local_ip.startswith("127."):
            local_ip = pub_ipv6

    return {
        "local_ip": local_ip,
        "local_ipv6": local_ipv6,
        "local_port": actual_local_port,
        "public_ip": pub_ip,
        "public_port": pub_port or actual_local_port,
        "public_ipv6": pub_ipv6,
        "public_ipv6_port": pub_ipv6_port,
        "nat_type": nat_type,
        "ipv6_only": ipv6_only,
        "candidates": local_candidates,
    }


def build_peer_candidates(peer_info: dict, my_public_ip: Optional[str] = None) -> List[Tuple[str, int, str]]:
    """
    Constroi lista ordenada e sem duplicatas de endpoints `(ip, porta, modo)` Dual-Stack:
    Overlay (v4/v6) -> LAN (v4/v6) -> IPv6 Global (direto sem CGNAT) -> WAN IPv4 -> Port Prediction.
    """
    if not peer_info:
        return []

    ordered: List[Tuple[str, int, str]] = []
    seen = set()

    def _add(ip_val: Optional[str], port_val: object, mode_tag: str) -> None:
        if not ip_val or not port_val:
            return
        ip_s = canonicalize_ip(str(ip_val))
        try:
            p_i = int(port_val)
        except (TypeError, ValueError):
            return
        if not ip_s or ip_s in ("0.0.0.0", "::") or p_i <= 0 or p_i > 65535:
            return
        if is_ipv6_address(ip_s) and ip_s.lower().startswith("fe80:"):
            return
        key = (ip_s, p_i)
        if key not in seen:
            seen.add(key)
            ordered.append((ip_s, p_i, mode_tag))

    peer_pub_ip = peer_info.get("public_ip")
    peer_pub_port = peer_info.get("public_port")
    peer_pub_v6 = peer_info.get("public_ipv6")
    peer_pub_v6_port = peer_info.get("public_ipv6_port") or peer_pub_port or peer_info.get("local_port")
    peer_loc_ip = peer_info.get("local_ip")
    peer_loc_port = peer_info.get("local_port") or peer_info.get("stream_port")
    same_wan = bool(my_public_ip and peer_pub_ip and canonicalize_ip(str(my_public_ip)) == canonicalize_ip(str(peer_pub_ip)))

    raw_cands = peer_info.get("candidates")
    if isinstance(raw_cands, list):
        for c in raw_cands:
            if isinstance(c, dict) and c.get("type") == "overlay":
                _add(c.get("ip"), c.get("port"), "overlay")
        for c in raw_cands:
            if isinstance(c, dict) and c.get("type") == "lan":
                _add(c.get("ip"), c.get("port"), "lan")
        for c in raw_cands:
            if isinstance(c, dict) and c.get("type") in ("ipv6", "wan-v6"):
                _add(c.get("ip"), c.get("port"), "ipv6")

    peer_lan_ips = peer_info.get("lan_ips")
    if isinstance(peer_lan_ips, list):
        eff_p = peer_loc_port or peer_pub_port or 9000
        for lip in peer_lan_ips:
            if is_overlay_address(str(lip)):
                _add(str(lip), eff_p, "overlay")
        for lip in peer_lan_ips:
            lip_s = str(lip)
            if not is_overlay_address(lip_s) and not lip_s.startswith("127.") and lip_s != "::1":
                _add(lip_s, eff_p, "ipv6" if is_global_ipv6(lip_s) else "lan")

    if peer_loc_ip:
        _add(peer_loc_ip, peer_loc_port, "ipv6" if is_global_ipv6(str(peer_loc_ip)) else "lan")

    # IPv6 Global direto tem prioridade sobre WAN IPv4 (dispensa CGNAT/NAT)
    if peer_pub_v6 and is_global_ipv6(str(peer_pub_v6)):
        _add(peer_pub_v6, peer_pub_v6_port or peer_loc_port or 9000, "ipv6")

    if peer_pub_ip:
        pub_tag = "ipv6" if is_ipv6_address(str(peer_pub_ip)) else "wan"
        _add(peer_pub_ip, peer_pub_port or peer_loc_port, pub_tag)
        if not same_wan and pub_tag == "wan":
            try:
                base_p = int(peer_pub_port)
                if peer_info.get("nat_type") == "symmetric" or (peer_loc_port and base_p != int(peer_loc_port)):
                    if base_p < 65535:
                        _add(peer_pub_ip, base_p + 1, "wan")
                    if base_p > 1024:
                        _add(peer_pub_ip, base_p - 1, "wan")
            except (TypeError, ValueError):
                pass

    return ordered


class P2PChannelClient:
    """Cliente de sinalizacao Rendezvous Dual-Stack (IPv4 + IPv6 + NAT64 RFC 7050) e travessia P2P."""

    def __init__(
        self,
        rendezvous_host: str = DEFAULT_RENDEZVOUS_HOST,
        http_port: int = DEFAULT_HTTP_PORT,
        stun_port: int = DEFAULT_STUN_PORT,
        rendezvous_host_v6: str = DEFAULT_RENDEZVOUS_HOST_V6,
    ):
        self.rendezvous_host = rendezvous_host
        self.rendezvous_host_v6 = rendezvous_host_v6
        self.http_port = http_port
        self.stun_port = stun_port
        self.base_url = self._make_base_url(rendezvous_host, http_port)
        self._effective_base_url: str = self.base_url
        self._effective_host_header: Optional[str] = None
        self.is_running = False

    @staticmethod
    def _make_base_url(host: str, port: int) -> str:
        url_h = format_url_host(host)
        if port == 443:
            return f"https://{url_h}"
        if port == 80:
            return f"http://{url_h}"
        return f"http://{url_h}:{port}"

    def _candidate_base_urls(self) -> List[Tuple[str, Optional[str]]]:
        """Retorna lista ordenada de `(base_url, host_header_override)` incluindo IPv6 e NAT64 RFC 7050."""
        urls: List[Tuple[str, Optional[str]]] = [(self._effective_base_url, self._effective_host_header)]
        if self.base_url != self._effective_base_url:
            urls.append((self.base_url, None))
        if self.rendezvous_host_v6:
            v6_url = self._make_base_url(self.rendezvous_host_v6, self.http_port)
            if not any(u == v6_url for u, _ in urls):
                urls.append((v6_url, None))
        # Se o host primario for literal IPv4, oferece sintese automatica NAT64 (RFC 7050) para hosts IPv6-only
        if not is_ipv6_address(self.rendezvous_host) and self.rendezvous_host not in ("127.0.0.1", "localhost"):
            nat64_ip = synthesize_nat64_ipv6(self.rendezvous_host)
            if nat64_ip:
                n64_url = self._make_base_url(nat64_ip, self.http_port)
                if not any(u == n64_url for u, _ in urls):
                    urls.append((n64_url, self.rendezvous_host))
        return urls

    def _urlopen_resilient(
        self,
        path: str,
        data: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 4.0,
    ):
        last_exc: Optional[Exception] = None
        for b_url, host_hdr in self._candidate_base_urls():
            req_headers = dict(headers or {})
            if host_hdr and "Host" not in req_headers:
                req_headers["Host"] = host_hdr
            req = urllib.request.Request(f"{b_url}{path}", data=data, headers=req_headers)
            try:
                resp = urllib.request.urlopen(req, timeout=timeout)
                self._effective_base_url = b_url
                self._effective_host_header = host_hdr
                return resp
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc is not None:
            raise last_exc
        raise OSError("Nenhum endpoint Rendezvous acessivel.")

    @property
    def active_base_url(self) -> str:
        return self._effective_base_url

    def _ensure_local_rendezvous(self):
        """Inicia automaticamente o microservico Rendezvous local apenas em modo localhost."""
        if self.rendezvous_host not in ("127.0.0.1", "localhost", "::1"):
            return
        try:
            fam = socket.AF_INET6 if self.rendezvous_host == "::1" else socket.AF_INET
            with socket.socket(fam, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                connect_host = "::1" if fam == socket.AF_INET6 else "127.0.0.1"
                if s.connect_ex((connect_host, self.http_port)) == 0:
                    return
        except Exception:
            pass

        if getattr(sys, "frozen", False):
            try:
                from src.signaling.server.dav_rendezvous import DavRendezvousServer

                def _run_embedded_rdv():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    srv = DavRendezvousServer("127.0.0.1", self.http_port, self.stun_port)
                    loop.run_until_complete(srv.start())

                threading.Thread(target=_run_embedded_rdv, daemon=True, name="Embedded-Rendezvous").start()
                time.sleep(0.45)
            except Exception as err:
                logger.debug(f"Auto-inicio embutido do Rendezvous local falhou: {err}")
            return

        proj_root = Path(__file__).resolve().parents[4]
        srv_script = proj_root / "src" / "signaling" / "server" / "dav_rendezvous.py"
        if srv_script.is_file():
            import subprocess
            try:
                env = os.environ.copy()
                env["DAV_HTTP_PORT"] = str(self.http_port)
                env["DAV_STUN_PORT"] = str(self.stun_port)
                creationflags = 0x08000000 if sys.platform == "win32" else 0
                subprocess.Popen(
                    [sys.executable, str(srv_script)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    creationflags=creationflags,
                )
                time.sleep(0.5)
            except Exception as err:
                logger.debug(f"Auto-inicio do Rendezvous local falhou: {err}")

    def get_public_endpoint_via_stun(self, local_sock: Optional[socket.socket] = None) -> Optional[Tuple[str, int]]:
        if local_sock is not None:
            info = discover_socket_endpoint(local_sock, self.rendezvous_host, self.stun_port)
            if info.get("public_ip"):
                return (str(info["public_ip"]), int(info["public_port"]))
            return None

        stun_res = query_rfc5389_stun(None)
        if stun_res:
            return stun_res
        return None

    def register_as_sender(
        self,
        pin: str,
        local_port: int,
        node_name: str = "Host-Sender",
        on_paired_callback: Optional[Callable[[dict], None]] = None,
        bound_sock: Optional[socket.socket] = None,
        endpoint_info: Optional[Dict[str, object]] = None,
    ) -> Optional[dict]:
        self._ensure_local_rendezvous()
        try:
            if endpoint_info is None and bound_sock is not None:
                endpoint_info = discover_socket_endpoint(bound_sock, self.rendezvous_host, self.stun_port)

            if endpoint_info is not None:
                loc_ip = str(endpoint_info.get("local_ip") or get_local_ip())
                eff_local_port = int(endpoint_info.get("local_port") or local_port)
                pub_ip = endpoint_info.get("public_ip")
                pub_port = int(endpoint_info.get("public_port") or eff_local_port)
                pub_ipv6 = endpoint_info.get("public_ipv6")
                pub_ipv6_port = int(endpoint_info.get("public_ipv6_port") or eff_local_port)
                nat_type = str(endpoint_info.get("nat_type") or "unknown")
                candidates = endpoint_info.get("candidates") or get_local_candidates(eff_local_port)
            else:
                loc_ip = get_local_ip()
                eff_local_port = int(local_port)
                stun_ep = self.get_public_endpoint_via_stun()
                pub_ip = stun_ep[0] if stun_ep else None
                pub_port = int(stun_ep[1]) if stun_ep else eff_local_port
                pub_ipv6 = get_local_ipv6()
                pub_ipv6_port = eff_local_port
                nat_type = "cone" if stun_ep else ("ipv6-direct" if pub_ipv6 else "unknown")
                candidates = get_local_candidates(eff_local_port)

            clean_pin = normalize_pin(pin)
            payload_dict: Dict[str, object] = {
                "pin": clean_pin,
                "node_name": node_name,
                "local_ip": loc_ip,
                "local_port": eff_local_port,
                "public_port": pub_port,
                "candidates": candidates,
                "nat_type": nat_type,
            }
            if pub_ip:
                payload_dict["public_ip"] = pub_ip
            if pub_ipv6:
                payload_dict["public_ipv6"] = pub_ipv6
                payload_dict["public_ipv6_port"] = pub_ipv6_port

            with self._urlopen_resilient(
                "/p2p/register",
                data=json.dumps(payload_dict).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                timeout=4.0,
            ) as resp:
                reg_data = json.loads(resp.read().decode("utf-8"))

            token = reg_data.get("token")
            if not token:
                return None

            default_relay = reg_data.get("relay") or {"host": self.rendezvous_host, "port": self.stun_port}
            if isinstance(default_relay, dict):
                default_relay = dict(default_relay)
                default_relay.setdefault("http_base_url", self._effective_base_url)
            self.is_running = True

            if on_paired_callback:
                def _sse_or_poll_worker():
                    # Deduplicacao longa (60s) evita loop de 1.2s contra servidores Rendezvous legados
                    dispatched_peers: Dict[Tuple[object, ...], float] = {}
                    poll_since_idx = 0
                    server_supports_index = False
                    paired_once = False

                    def _maybe_dispatch(raw_peer: dict, relay_obj: object, explicit_idx: Optional[int]) -> None:
                        nonlocal paired_once
                        peer = dict(raw_peer)
                        r_copy = dict(relay_obj) if isinstance(relay_obj, dict) else dict(default_relay)
                        r_copy.setdefault("http_base_url", self._effective_base_url)
                        peer["_relay"] = r_copy
                        peer_sig = (
                            canonicalize_ip(str(peer.get("public_ip") or "")),
                            peer.get("public_port"),
                            canonicalize_ip(str(peer.get("public_ipv6") or "")),
                            peer.get("public_ipv6_port"),
                            canonicalize_ip(str(peer.get("local_ip") or "")),
                            peer.get("local_port"),
                        )
                        now_m = time.monotonic()
                        # Com `peer_index` explicito, cada novo indice e um evento real; sem indice, suprime 60s
                        dedup_ttl = 1.5 if explicit_idx is not None else _LEGACY_DEDUP_WINDOW_SEC
                        last_ts = dispatched_peers.get(peer_sig)
                        if last_ts is None or (now_m - last_ts) >= dedup_ttl:
                            dispatched_peers[peer_sig] = now_m
                            paired_once = True
                            on_paired_callback(peer)

                    while self.is_running:
                        try:
                            sse_path = f"/p2p/events?pin={clean_pin}&token={token}"
                            with self._urlopen_resilient(
                                sse_path,
                                headers={"Accept": "text/event-stream"},
                                timeout=90,
                            ) as sse_resp:
                                for raw_line in sse_resp:
                                    if not self.is_running:
                                        return
                                    line = raw_line.decode("utf-8", errors="ignore").strip()
                                    if line.startswith("data:"):
                                        try:
                                            evt_data = json.loads(line[5:].strip())
                                            if evt_data.get("status") == "paired" and isinstance(evt_data.get("peer"), dict):
                                                exp_idx = evt_data.get("peer_index")
                                                if exp_idx is not None:
                                                    server_supports_index = True
                                                    idx_i = int(exp_idx)
                                                    if idx_i <= poll_since_idx:
                                                        continue
                                                    poll_since_idx = idx_i
                                                    _maybe_dispatch(evt_data["peer"], evt_data.get("relay"), idx_i)
                                                else:
                                                    poll_since_idx = max(poll_since_idx, 1)
                                                    _maybe_dispatch(evt_data["peer"], evt_data.get("relay"), None)
                                        except Exception:
                                            pass
                        except Exception as sse_err:
                            logger.debug(f"Fluxo SSE encerrado ({sse_err}); alternando para polling.")

                        if not self.is_running:
                            return

                        for _ in range(80):
                            if not self.is_running:
                                return
                            # Polling rapido enquanto aguarda 1o par; cadencia suave apos pareado em VPS legado
                            time.sleep(2.5 if (paired_once and not server_supports_index) else 1.2)
                            try:
                                with self._urlopen_resilient(
                                    "/p2p/poll",
                                    data=json.dumps(
                                        {"pin": clean_pin, "token": token, "since_index": poll_since_idx}
                                    ).encode("utf-8"),
                                    headers={"Content-Type": "application/json"},
                                    timeout=3.0,
                                ) as p_resp:
                                    p_data = json.loads(p_resp.read().decode("utf-8"))
                                    if p_data.get("status") == "paired":
                                        has_next = "next_index" in p_data or "peers" in p_data
                                        if has_next:
                                            server_supports_index = True
                                        peers_list = p_data.get("peers") or ([p_data["peer"]] if p_data.get("peer") else [])
                                        if has_next:
                                            next_i = int(p_data.get("next_index", poll_since_idx + len(peers_list)))
                                            if next_i <= poll_since_idx:
                                                continue
                                            poll_since_idx = next_i
                                            for raw_p in peers_list:
                                                _maybe_dispatch(raw_p, p_data.get("relay"), next_i)
                                        else:
                                            for raw_p in peers_list:
                                                _maybe_dispatch(raw_p, p_data.get("relay"), None)
                            except Exception:
                                continue

                t = threading.Thread(target=_sse_or_poll_worker, daemon=True, name=f"P2P-SSE-{clean_pin}")
                t.start()

            return reg_data

        except Exception as exc:
            logger.warning(f"Falha ao registrar PIN no Rendezvous ({self.base_url}): {exc}")
            return None

    def stop(self):
        self.is_running = False

    def resolve_receiver_target(
        self,
        pin: str,
        local_port: int,
        node_name: str = "Host-Receiver",
        bound_sock: Optional[socket.socket] = None,
        endpoint_info: Optional[Dict[str, object]] = None,
    ) -> Optional[dict]:
        self._ensure_local_rendezvous()
        try:
            if endpoint_info is None and bound_sock is not None:
                endpoint_info = discover_socket_endpoint(bound_sock, self.rendezvous_host, self.stun_port)

            if endpoint_info is not None:
                loc_ip = str(endpoint_info.get("local_ip") or get_local_ip())
                eff_local_port = int(endpoint_info.get("local_port") or local_port)
                pub_ip = endpoint_info.get("public_ip")
                pub_port = int(endpoint_info.get("public_port") or eff_local_port)
                pub_ipv6 = endpoint_info.get("public_ipv6")
                pub_ipv6_port = int(endpoint_info.get("public_ipv6_port") or eff_local_port)
                nat_type = str(endpoint_info.get("nat_type") or "unknown")
                candidates = endpoint_info.get("candidates") or get_local_candidates(eff_local_port)
            else:
                loc_ip = get_local_ip()
                eff_local_port = int(local_port)
                stun_ep = self.get_public_endpoint_via_stun()
                pub_ip = stun_ep[0] if stun_ep else None
                pub_port = int(stun_ep[1]) if stun_ep else eff_local_port
                pub_ipv6 = get_local_ipv6()
                pub_ipv6_port = eff_local_port
                nat_type = "cone" if stun_ep else ("ipv6-direct" if pub_ipv6 else "unknown")
                candidates = get_local_candidates(eff_local_port)

            clean_pin = normalize_pin(pin)
            payload_dict: Dict[str, object] = {
                "pin": clean_pin,
                "node_name": node_name,
                "local_ip": loc_ip,
                "local_port": eff_local_port,
                "public_port": pub_port,
                "candidates": candidates,
                "nat_type": nat_type,
            }
            if pub_ip:
                payload_dict["public_ip"] = pub_ip
            if pub_ipv6:
                payload_dict["public_ipv6"] = pub_ipv6
                payload_dict["public_ipv6_port"] = pub_ipv6_port

            with self._urlopen_resilient(
                "/p2p/resolve",
                data=json.dumps(payload_dict).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                timeout=4.0,
            ) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))

            if res_data.get("status") == "paired":
                r_info = dict(res_data.get("relay") or {"host": self.rendezvous_host, "port": self.stun_port})
                r_info.setdefault("http_base_url", self._effective_base_url)
                res_data["relay"] = r_info
                return res_data

        except Exception as exc:
            logger.warning(f"Falha ao resolver PIN no Rendezvous ({self.base_url}): {exc}")
        return None

    def punch_hole(
        self,
        local_sock: socket.socket,
        peer_info: dict,
        pin: str = "",
        timeout_sec: float = 2.5,
        my_public_ip: Optional[str] = None,
    ) -> Tuple[str, int, str]:
        candidates = build_peer_candidates(peer_info, my_public_ip=my_public_ip)
        if not candidates:
            return ("127.0.0.1", 9000, "lan")

        clean_pin = normalize_pin(pin)
        syn_pkt = f"DAV_P2P_SYN:{clean_pin}".encode("ascii") if clean_pin else MAGIC_SYN
        ack_pkt = f"DAV_P2P_ACK:{clean_pin}".encode("ascii") if clean_pin else MAGIC_ACK

        old_timeout = local_sock.gettimeout()
        local_sock.settimeout(0.12)

        working_target: Optional[Tuple[str, int]] = None
        start_t = time.monotonic()

        try:
            for _ in range(4):
                for ip, port, _ in candidates:
                    sendto_dualstack(local_sock, syn_pkt, ip, port)
                time.sleep(0.025)

            while time.monotonic() - start_t < timeout_sec:
                try:
                    data, raw_addr = local_sock.recvfrom(2048)
                    addr = normalize_recv_addr(raw_addr)
                    if data.startswith(MAGIC_SYN) or data.startswith(MAGIC_ACK):
                        working_target = addr
                        for _ in range(3):
                            sendto_dualstack(local_sock, ack_pkt, addr[0], addr[1])
                        break
                    if len(data) >= 48 and data[0] == 1:
                        working_target = addr
                        break
                except (socket.timeout, BlockingIOError, ConnectionResetError):
                    for ip, port, _ in candidates:
                        sendto_dualstack(local_sock, syn_pkt, ip, port)
                    continue
                except Exception:
                    break
        finally:
            try:
                local_sock.settimeout(old_timeout)
            except Exception:
                pass

        if working_target:
            kind = _classify_private_ip(working_target[0])
            if working_target[0].startswith("127.") or working_target[0] == "::1":
                mode = "lan"
            elif kind:
                mode = kind
            else:
                mode = "ipv6" if is_ipv6_address(working_target[0]) else "wan"
            return (working_target[0], working_target[1], mode)

        return candidates[0]
