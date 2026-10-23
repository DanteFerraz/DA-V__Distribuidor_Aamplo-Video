#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V — Orquestrador de Canal P2P e Perfuração de NAT (UDP Hole-Punching)
Autor: Dante Ferraz (MonoTech)

Viabiliza conexão ponto a ponto direta entre dois computadores remotos atrás
de roteadores domésticos/corporativos (NAT assimétrico/cone de portas).
Fluxo Operacional:
1. Consulta STUN reflexivo para mapeamento da porta pública externa do nó.
2. Troca de endpoints através do servidor Rendezvous via código PIN de 6 dígitos.
3. Rajada concorrente de pacotes UDP SYN/ACK para abrir as tabelas de estado do NAT.
4. Confirmação bidirecional e comutação para transmissão direta sem intermediários.
"""

import sys
import os
import time
import json
import socket
import threading
import urllib.request
import logging
from typing import Optional, Tuple, Callable

logger = logging.getLogger("DAV-P2PChannel")

DEFAULT_RENDEZVOUS_HOST = os.environ.get("DAV_RENDEZVOUS_HOST", "129.148.26.150")
DEFAULT_HTTP_PORT = int(os.environ.get("DAV_RENDEZVOUS_PORT", 80))
DEFAULT_STUN_PORT = int(os.environ.get("DAV_STUN_PORT", 8768))

MAGIC_SYN = b"DAV_P2P_SYN"
MAGIC_ACK = b"DAV_P2P_ACK"


import struct

def query_rfc5389_stun(local_sock: Optional[socket.socket] = None, stun_hosts=None) -> Optional[Tuple[str, int]]:
    """
    Executes a standard RFC 5389 STUN Binding Request against public STUN servers
    (Google / Cloudflare) to discover the NAT reflexive public IP and external UDP port.
    """
    if stun_hosts is None:
        stun_hosts = [
            ("stun.l.google.com", 19302),
            ("stun1.l.google.com", 19302),
            ("stun.cloudflare.com", 3478),
        ]

    created_socket = False
    sock = local_sock
    if sock is None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        created_socket = True

    magic_cookie = 0x2112A442
    trans_id = os.urandom(12)
    req = struct.pack('!HHI12s', 0x0001, 0, magic_cookie, trans_id)

    old_timeout = sock.gettimeout()
    sock.settimeout(1.5)

    try:
        for host, port in stun_hosts:
            try:
                sock.sendto(req, (host, port))
                data, _ = sock.recvfrom(2048)
                if len(data) >= 20:
                    offset = 20
                    while offset + 4 <= len(data):
                        attr_type, attr_len = struct.unpack('!HH', data[offset:offset+4])
                        if attr_type == 0x0020 and offset + 4 + attr_len <= len(data):  # XOR-MAPPED-ADDRESS
                            xport = struct.unpack('!H', data[offset+6:offset+8])[0]
                            mapped_port = xport ^ (magic_cookie >> 16)
                            xip = struct.unpack('!I', data[offset+8:offset+12])[0]
                            real_ip = xip ^ magic_cookie
                            return (socket.inet_ntoa(struct.pack('!I', real_ip)), mapped_port)
                        offset += 4 + attr_len
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


class P2PChannelClient:
    """
    Cliente de conexão direta P2P para tráfego de vídeo e sinalização em tempo real.
    """
    def __init__(self, rendezvous_host: str = DEFAULT_RENDEZVOUS_HOST,
                 http_port: int = DEFAULT_HTTP_PORT,
                 stun_port: int = DEFAULT_STUN_PORT):
        self.rendezvous_host = rendezvous_host
        self.http_port = http_port
        self.stun_port = stun_port
        self.base_url = f"http://{rendezvous_host}:{http_port}" if http_port not in (80, 443) else f"http://{rendezvous_host}"
        self.is_running = False

    def _ensure_local_rendezvous(self):
        """Inicia automaticamente o microserviço Rendezvous local se estiver em localhost e a porta estiver fechada."""
        if self.rendezvous_host not in ("127.0.0.1", "localhost"):
            return
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                if s.connect_ex(("127.0.0.1", self.http_port)) == 0:
                    return
        except Exception:
            pass

        srv_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "src", "signaling", "server", "dav_rendezvous.py"
        )
        if os.path.isfile(srv_script):
            import subprocess
            try:
                creationflags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
                subprocess.Popen(
                    [sys.executable, srv_script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags
                )
                time.sleep(0.6)
            except Exception as err:
                logger.debug(f"Auto-início do Rendezvous local: {err}")

    def get_public_endpoint_via_stun(self, local_sock: Optional[socket.socket] = None) -> Optional[Tuple[str, int]]:
        """Queries STUN servers to get the reflexive public IP and Port."""
        stun_res = query_rfc5389_stun(local_sock)
        if stun_res:
            return stun_res

        self._ensure_local_rendezvous()
        if local_sock is not None:
            try:
                local_sock.sendto(b"DAV_STUN_REQ", (self.rendezvous_host, self.stun_port))
                old_timeout = local_sock.gettimeout()
                local_sock.settimeout(2.0)
                data, _ = local_sock.recvfrom(1024)
                local_sock.settimeout(old_timeout)

                resp = json.loads(data.decode("utf-8"))
                if resp.get("status") == "ok":
                    return (resp["reflexive_ip"], int(resp["reflexive_port"]))
            except Exception as e:
                logger.debug(f"STUN query failed: {e}")
        return None

    def register_as_sender(
        self,
        pin: str,
        local_port: int,
        node_name: str = "Host-Sender",
        on_paired_callback: Optional[Callable[[dict], None]] = None
    ) -> Optional[dict]:
        """
        Registers sender on the Rendezvous server with PIN and starts background polling
        for receiver connection.
        """
        self._ensure_local_rendezvous()
        try:
            pub_ip, pub_port = None, None
            try:
                stun_ep = self.get_public_endpoint_via_stun()
                if stun_ep:
                    pub_ip, pub_port = stun_ep
            except Exception:
                pass

            payload = json.dumps({
                "pin": pin,
                "node_name": node_name,
                "local_port": local_port,
                "public_port": pub_port or local_port,
                "local_ip": pub_ip or "127.0.0.1"
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{self.base_url}/p2p/register",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                reg_data = json.loads(resp.read().decode("utf-8"))

            token = reg_data.get("token")
            if not token:
                return None

            # Start background poller to wait for receiver match
            if on_paired_callback:
                def _poller():
                    for _ in range(90):  # poll every 2s for 180s
                        time.sleep(2.0)
                        try:
                            p_req = urllib.request.Request(
                                f"{self.base_url}/p2p/poll",
                                data=json.dumps({"pin": pin, "token": token}).encode("utf-8"),
                                headers={"Content-Type": "application/json"}
                            )
                            with urllib.request.urlopen(p_req, timeout=3) as p_resp:
                                p_data = json.loads(p_resp.read().decode("utf-8"))
                                if p_data.get("status") == "paired":
                                    peer = p_data["peer"]
                                    on_paired_callback(peer)
                                    break
                        except Exception:
                            continue

                t = threading.Thread(target=_poller, daemon=True, name=f"P2P-Poller-{pin}")
                t.start()

            return reg_data

        except Exception as e:
            logger.warning(f"Failed to register PIN on Rendezvous: {e}")
            return None

    def resolve_receiver_target(
        self,
        pin: str,
        local_port: int,
        node_name: str = "Host-Receiver"
    ) -> Optional[dict]:
        """
        Queries the Rendezvous server to match a Sender using only the PIN.
        Returns the peer's endpoints and session tokens.
        """
        self._ensure_local_rendezvous()
        try:
            pub_ip, pub_port = None, None
            try:
                stun_ep = self.get_public_endpoint_via_stun()
                if stun_ep:
                    pub_ip, pub_port = stun_ep
            except Exception:
                pass

            payload = json.dumps({
                "pin": pin,
                "node_name": node_name,
                "local_port": local_port,
                "public_port": pub_port or local_port,
                "local_ip": pub_ip or "127.0.0.1"
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{self.base_url}/p2p/resolve",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))

            if res_data.get("status") == "paired":
                return res_data

        except Exception as e:
            logger.warning(f"Failed to resolve PIN on Rendezvous: {e}")
        return None

    def punch_hole(
        self,
        local_sock: socket.socket,
        peer_info: dict,
        timeout_sec: float = 3.0
    ) -> Tuple[str, int, str]:
        """
        Performs simultaneous UDP hole punching probes against the peer's public and local endpoints.
        Returns (target_ip, target_port, mode) where mode is 'lan' or 'wan'.
        """
        candidates = []
        loc_ip = peer_info.get("local_ip")
        loc_port = peer_info.get("local_port")
        pub_ip = peer_info.get("public_ip")
        pub_port = peer_info.get("public_port")

        if loc_ip and loc_port:
            candidates.append((loc_ip, int(loc_port), "lan"))
        if pub_ip and pub_port and pub_ip != loc_ip:
            candidates.append((pub_ip, int(pub_port), "wan"))

        # Send punch probes concurrently
        start_t = time.time()
        for _ in range(6):
            for ip, port, _ in candidates:
                try:
                    local_sock.sendto(MAGIC_SYN, (ip, port))
                except Exception:
                    pass
            time.sleep(0.05)

        # Listen for peer SYN or ACK
        old_timeout = local_sock.gettimeout()
        local_sock.settimeout(0.3)
        working_target = None
        working_mode = "wan"

        while time.time() - start_t < timeout_sec:
            try:
                data, addr = local_sock.recvfrom(256)
                if data in (MAGIC_SYN, MAGIC_ACK):
                    working_target = addr
                    # Send ACK back
                    local_sock.sendto(MAGIC_ACK, addr)
                    local_sock.sendto(MAGIC_ACK, addr)
                    break
            except socket.timeout:
                # Re-probe candidates
                for ip, port, _ in candidates:
                    try:
                        local_sock.sendto(MAGIC_SYN, (ip, port))
                    except Exception:
                        pass
                continue
            except Exception:
                break

        local_sock.settimeout(old_timeout)

        if working_target:
            mode = "lan" if working_target[0].startswith("192.168.") or working_target[0].startswith("127.") or working_target[0].startswith("10.") else "wan"
            return (working_target[0], working_target[1], mode)

        # Fallback to public endpoint if punch did not receive explicit ACK
        if pub_ip and pub_port:
            return (pub_ip, int(pub_port), "wan")
        elif loc_ip and loc_port:
            return (loc_ip, int(loc_port), "lan")
        return ("127.0.0.1", 9000, "lan")
