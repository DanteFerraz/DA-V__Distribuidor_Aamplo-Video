#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V — Orquestrador de Canal P2P, STUN Single-Socket e Travessia de NAT (v2.0)
Autor: Dante Ferraz (MonoTech)

Estabelece túneis UDP diretos entre máquinas Windows e Linux através da internet
ou em redes locais/híbridas usando apenas um código PIN de 6 dígitos:

1. STUN RFC 5389 Single-Socket: descobre o par (IP:Porta) público diretamente no mesmo
   descritor de socket UDP que transportará o vídeo, preservando o mapeamento da tabela NAT
   do roteador e classificando automaticamente o tipo de NAT (Cone vs Simétrico).
2. Coleta Multi-Candidato (ICE-Lite): agrega interfaces LAN físicas, malhas overlay
   (Tailscale/WireGuard) e endpoint WAN reflexivo para corrida paralela de conectividade.
3. Hole-Punching Bidirecional: dispara sondas concorrentes SYN/ACK autenticadas pelo PIN
   e promove automaticamente a rota de menor latência.
4. Blind Encrypted UDP Relay: envelopa datagramas criptografados via cabeçalho leve de
   17 bytes ('DAV_RLY1') quando ambos os lados operam sob CGNAT Simétrico restritivo.
"""

import os
import sys
import time
import json
import struct
import socket
import logging
import threading
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("DAV-P2PChannel")

DEFAULT_RENDEZVOUS_HOST = os.environ.get("DAV_RENDEZVOUS_HOST", "129.148.26.150")
DEFAULT_HTTP_PORT = int(os.environ.get("DAV_RENDEZVOUS_PORT", 80))
DEFAULT_STUN_PORT = int(os.environ.get("DAV_STUN_PORT", 8768))

MAGIC_SYN = b"DAV_P2P_SYN"
MAGIC_ACK = b"DAV_P2P_ACK"
MAGIC_PLI = b"DAV_P2P_PLI"
MAGIC_RELAY_HDR = b"DAV_RLY1"

STUN_MAGIC_COOKIE = 0x2112A442
PUBLIC_STUN_SERVERS: List[Tuple[str, int]] = [
    ("stun.l.google.com", 19302),
    ("stun.cloudflare.com", 3478),
    ("stun1.l.google.com", 19302),
]


def normalize_pin(pin: str) -> str:
    """Remove hifens e espaços do PIN para comparação canônica."""
    return str(pin or "").replace("-", "").replace(" ", "").strip()


def wrap_relay_packet(pin: str, role: bytes, inner_payload: bytes) -> bytes:
    """
    Envelopa um pacote (já criptografado ponta a ponta) com o cabeçalho de 17 bytes
    do Blind Encrypted UDP Relay ('DAV_RLY1' + 8B PIN + 1B papel 'S'/'R').
    """
    pin_field = normalize_pin(pin).encode("ascii", errors="ignore")[:8].ljust(8, b"\x00")
    role_byte = role[:1] if role else b"S"
    return MAGIC_RELAY_HDR + pin_field + role_byte + inner_payload


def get_local_ip() -> str:
    """Obtém o endereço IPv4 da interface de saída padrão sem transmitir pacotes na rede."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"


def _classify_private_ip(ip: str) -> Optional[str]:
    """Classifica um endereço IPv4 local como 'lan' ou 'overlay' (ex: Tailscale 100.64/10)."""
    if not ip or ip.startswith("127.") or ip.startswith("169.254.") or ip == "0.0.0.0":
        return None
    parts = ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return None
    a, b = int(parts[0]), int(parts[1])
    if a == 100 and 64 <= b <= 127:
        return "overlay"
    if a == 10 or (a == 192 and b == 168) or (a == 172 and 16 <= b <= 31):
        return "lan"
    return None


def get_local_candidates(local_port: int) -> List[Dict[str, object]]:
    """
    Coleta todos os endereços IPv4 candidatos ativos da máquina (Ethernet, Wi-Fi e VPNs
    overlay como Tailscale/WireGuard), priorizando a rota padrão de saída.
    """
    candidates: List[Dict[str, object]] = []
    seen = set()

    primary_ip = get_local_ip()
    if primary_ip and primary_ip != "127.0.0.1":
        kind = _classify_private_ip(primary_ip) or "lan"
        candidates.append({"ip": primary_ip, "port": int(local_port), "type": kind})
        seen.add(primary_ip)

    try:
        import psutil
        for if_name, addrs in psutil.net_if_addrs().items():
            if_lower = if_name.lower()
            # Ignora pontes virtuais isoladas de containers/VMs sem rota externa real
            if any(
                skip in if_lower
                for skip in ("docker", "br-", "veth", "virbr", "loopback", "virtualbox", "vbox", "vmware", "vmnet")
            ):
                continue
            for snic in addrs:
                if snic.family == socket.AF_INET and snic.address not in seen:
                    kind = _classify_private_ip(snic.address)
                    if kind:
                        candidates.append({"ip": snic.address, "port": int(local_port), "type": kind})
                        seen.add(snic.address)
    except Exception:
        pass

    if not candidates:
        candidates.append({"ip": primary_ip or "127.0.0.1", "port": int(local_port), "type": "lan"})

    return candidates


def query_rfc5389_stun(
    local_sock: Optional[socket.socket] = None,
    stun_hosts: Optional[List[Tuple[str, int]]] = None,
    timeout: float = 0.85,
) -> Optional[Tuple[str, int]]:
    """
    Executa Binding Request STUN (RFC 5389) diretamente no socket fornecido,
    validando o Transaction ID de 96 bits e preservando intacto o modo bloqueante
    original do descritor (sem jamais fechar um socket externo).
    """
    if stun_hosts is None:
        stun_hosts = PUBLIC_STUN_SERVERS

    created_socket = False
    sock = local_sock
    if sock is None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        created_socket = True

    old_timeout = sock.gettimeout()
    sock.settimeout(timeout)

    try:
        for host, port in stun_hosts:
            trans_id = os.urandom(12)
            req = struct.pack("!HHI12s", 0x0001, 0, STUN_MAGIC_COOKIE, trans_id)
            try:
                sock.sendto(req, (host, port))
                t_deadline = time.monotonic() + timeout
                while time.monotonic() < t_deadline:
                    data, _ = sock.recvfrom(2048)
                    # Ignora datagramas que não sejam Binding Success Response desta transação
                    if len(data) < 20 or data[8:20] != trans_id:
                        continue
                    msg_type = struct.unpack("!H", data[0:2])[0]
                    if msg_type != 0x0101:
                        continue

                    offset = 20
                    while offset + 4 <= len(data):
                        attr_type, attr_len = struct.unpack("!HH", data[offset : offset + 4])
                        val_start = offset + 4
                        val_end = val_start + attr_len
                        if val_end > len(data):
                            break

                        # 0x0020: XOR-MAPPED-ADDRESS (IPv4)
                        if attr_type == 0x0020 and attr_len >= 8 and data[val_start + 1] == 0x01:
                            xport = struct.unpack("!H", data[val_start + 2 : val_start + 4])[0]
                            mapped_port = xport ^ (STUN_MAGIC_COOKIE >> 16)
                            xip = struct.unpack("!I", data[val_start + 4 : val_start + 8])[0]
                            real_ip = xip ^ STUN_MAGIC_COOKIE
                            return (socket.inet_ntoa(struct.pack("!I", real_ip)), int(mapped_port))

                        # 0x0001: MAPPED-ADDRESS legado (fallback)
                        if attr_type == 0x0001 and attr_len >= 8 and data[val_start + 1] == 0x01:
                            mport = struct.unpack("!H", data[val_start + 2 : val_start + 4])[0]
                            mip = socket.inet_ntoa(data[val_start + 4 : val_start + 8])
                            return (mip, int(mport))

                        # Atributos STUN são alinhados em fronteiras de 4 bytes
                        padded_len = (attr_len + 3) & ~3
                        offset += 4 + padded_len
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


def send_stun_keepalive(sock: socket.socket, stun_host: Tuple[str, int] = ("stun.l.google.com", 19302)):
    """
    Envia um pacote STUN Binding Request não-bloqueante de 20 bytes no próprio socket
    de mídia para renovar o estado da porta mapeada na tabela NAT do roteador durante Standby.
    """
    try:
        req = struct.pack("!HHI12s", 0x0001, 0, STUN_MAGIC_COOKIE, os.urandom(12))
        sock.sendto(req, stun_host)
    except Exception:
        pass


def discover_socket_endpoint(
    bound_sock: socket.socket,
    rendezvous_host: str = DEFAULT_RENDEZVOUS_HOST,
    stun_port: int = DEFAULT_STUN_PORT,
) -> Dict[str, object]:
    """
    Inspeciona um socket UDP já vinculado (bound) para descobrir:
    - Porta local efetiva atribuída pelo SO.
    - Lista completa de candidatos locais (LAN + Overlay).
    - Endpoint público reflexivo (IP:Porta) mapeado para ESTE exato descritor de socket.
    - Classificação empírica do NAT ('cone', 'symmetric' ou 'local').
    """
    try:
        actual_local_port = int(bound_sock.getsockname()[1])
    except Exception:
        actual_local_port = 9000

    local_ip = get_local_ip()
    local_candidates = get_local_candidates(actual_local_port)

    pub_ip: Optional[str] = None
    pub_port: Optional[int] = None
    nat_type = "local"

    # Em testes locais isolados (127.0.0.1), prioriza o STUN interno do próprio Rendezvous primeiro
    is_loopback_env = rendezvous_host in ("127.0.0.1", "localhost")
    if not is_loopback_env:
        ep1 = query_rfc5389_stun(bound_sock, [("stun.l.google.com", 19302)], timeout=0.75)
        if ep1:
            pub_ip, pub_port = ep1
            nat_type = "cone"
            ep2 = query_rfc5389_stun(bound_sock, [("stun.cloudflare.com", 3478)], timeout=0.65)
            if ep2:
                if ep2[1] != ep1[1]:
                    nat_type = "symmetric"
                    pub_port = ep2[1]
        else:
            ep_fb = query_rfc5389_stun(bound_sock, [("stun1.l.google.com", 19302)], timeout=0.75)
            if ep_fb:
                pub_ip, pub_port = ep_fb
                nat_type = "cone"

    # Fallback para sonda reflexiva nativa do servidor Rendezvous
    if pub_ip is None:
        old_timeout = bound_sock.gettimeout()
        try:
            bound_sock.settimeout(0.8)
            bound_sock.sendto(b"DAV_STUN_REQ", (rendezvous_host, stun_port))
            data, _ = bound_sock.recvfrom(1024)
            resp = json.loads(data.decode("utf-8"))
            if resp.get("status") == "ok":
                pub_ip = str(resp["reflexive_ip"])
                pub_port = int(resp["reflexive_port"])
                nat_type = "local" if pub_ip.startswith("127.") else "cone"
        except Exception:
            pass
        finally:
            try:
                bound_sock.settimeout(old_timeout)
            except Exception:
                pass

    return {
        "local_ip": local_ip,
        "local_port": actual_local_port,
        "public_ip": pub_ip,
        "public_port": pub_port or actual_local_port,
        "nat_type": nat_type,
        "candidates": local_candidates,
    }


def build_peer_candidates(peer_info: dict, my_public_ip: Optional[str] = None) -> List[Tuple[str, int, str]]:
    """
    Constrói a lista ordenada e sem duplicatas de endpoints (ip, porta, modo) de um peer
    para sondagem simultânea:
    1. Interfaces Overlay (Tailscale/WireGuard) e LAN locais.
    2. Endpoint WAN reflexivo descoberto via STUN no próprio socket.
    3. Predição de portas sequenciais adjacentes (+1 / -1) para roteadores CGNAT lineares.
    """
    if not peer_info:
        return []

    ordered: List[Tuple[str, int, str]] = []
    seen = set()

    def _add(ip_val: Optional[str], port_val: object, mode_tag: str):
        if not ip_val or not port_val:
            return
        ip_s = str(ip_val).strip()
        try:
            p_i = int(port_val)
        except (TypeError, ValueError):
            return
        if not ip_s or ip_s == "0.0.0.0" or p_i <= 0 or p_i > 65535:
            return
        key = (ip_s, p_i)
        if key not in seen:
            seen.add(key)
            ordered.append((ip_s, p_i, mode_tag))

    peer_pub_ip = peer_info.get("public_ip")
    peer_pub_port = peer_info.get("public_port")
    peer_loc_ip = peer_info.get("local_ip")
    peer_loc_port = peer_info.get("local_port")
    same_wan = bool(my_public_ip and peer_pub_ip and str(my_public_ip) == str(peer_pub_ip))

    # 1. Candidatos explícitos reportados pelo peer (overlay e lan primeiro)
    raw_cands = peer_info.get("candidates")
    if isinstance(raw_cands, list):
        for c in raw_cands:
            if isinstance(c, dict) and c.get("type") == "overlay":
                _add(c.get("ip"), c.get("port"), "overlay")
        for c in raw_cands:
            if isinstance(c, dict) and c.get("type") == "lan":
                _add(c.get("ip"), c.get("port"), "lan")

    # 2. IP local primário (sempre testado em paralelo para evitar bloqueio de Hairpin NAT)
    _add(peer_loc_ip, peer_loc_port, "lan")

    # 3. Endpoint público WAN STUN (exceto se idêntico ao IP local)
    if peer_pub_ip and not same_wan:
        _add(peer_pub_ip, peer_pub_port or peer_loc_port, "wan")
        # Predição leve de portas contíguas útil em roteadores residenciais/CGNAT sequenciais
        try:
            base_p = int(peer_pub_port)
            if peer_info.get("nat_type") == "symmetric" or (peer_loc_port and base_p != int(peer_loc_port)):
                if base_p < 65535:
                    _add(peer_pub_ip, base_p + 1, "wan")
                if base_p > 1024:
                    _add(peer_pub_ip, base_p - 1, "wan")
        except (TypeError, ValueError):
            pass
    elif peer_pub_ip and same_wan:
        # Mesmo IP público, mas sub-redes corporativas isoladas ainda podem responder via Hairpin
        _add(peer_pub_ip, peer_pub_port or peer_loc_port, "wan")

    return ordered


class P2PChannelClient:
    """Cliente de sinalização Rendezvous e negociação direta P2P."""

    def __init__(
        self,
        rendezvous_host: str = DEFAULT_RENDEZVOUS_HOST,
        http_port: int = DEFAULT_HTTP_PORT,
        stun_port: int = DEFAULT_STUN_PORT,
    ):
        self.rendezvous_host = rendezvous_host
        self.http_port = http_port
        self.stun_port = stun_port
        self.base_url = (
            f"http://{rendezvous_host}:{http_port}"
            if http_port not in (80, 443)
            else f"http://{rendezvous_host}"
        )
        self.is_running = False

    def _ensure_local_rendezvous(self):
        """Inicia automaticamente o microserviço Rendezvous local apenas em modo localhost."""
        if self.rendezvous_host not in ("127.0.0.1", "localhost"):
            return
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                if s.connect_ex(("127.0.0.1", self.http_port)) == 0:
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
                logger.debug(f"Auto-início embutido do Rendezvous local falhou: {err}")
            return

        srv_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "src",
            "signaling",
            "server",
            "dav_rendezvous.py",
        )
        if os.path.isfile(srv_script):
            import subprocess
            try:
                env = os.environ.copy()
                env["DAV_HTTP_PORT"] = str(self.http_port)
                env["DAV_STUN_PORT"] = str(self.stun_port)
                creationflags = 0x08000000 if sys.platform == "win32" else 0
                subprocess.Popen(
                    [sys.executable, srv_script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    creationflags=creationflags,
                )
                time.sleep(0.5)
            except Exception as err:
                logger.debug(f"Auto-início do Rendezvous local falhou: {err}")

    def get_public_endpoint_via_stun(self, local_sock: Optional[socket.socket] = None) -> Optional[Tuple[str, int]]:
        """Obtém o endpoint público reflexivo preservando o descritor `local_sock`."""
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
        """
        Registra o nó Transmissor no servidor Rendezvous usando as coordenadas reais do
        próprio socket de mídia (`endpoint_info` ou `bound_sock`) e abre escuta SSE/Polling.
        """
        self._ensure_local_rendezvous()
        try:
            if endpoint_info is None and bound_sock is not None:
                endpoint_info = discover_socket_endpoint(bound_sock, self.rendezvous_host, self.stun_port)

            if endpoint_info is not None:
                loc_ip = str(endpoint_info.get("local_ip") or get_local_ip())
                eff_local_port = int(endpoint_info.get("local_port") or local_port)
                pub_ip = endpoint_info.get("public_ip")
                pub_port = int(endpoint_info.get("public_port") or eff_local_port)
                nat_type = str(endpoint_info.get("nat_type") or "unknown")
                candidates = endpoint_info.get("candidates") or get_local_candidates(eff_local_port)
            else:
                loc_ip = get_local_ip()
                eff_local_port = int(local_port)
                stun_ep = self.get_public_endpoint_via_stun()
                pub_ip = stun_ep[0] if stun_ep else None
                pub_port = int(stun_ep[1]) if stun_ep else eff_local_port
                nat_type = "cone" if stun_ep else "unknown"
                candidates = get_local_candidates(eff_local_port)

            clean_pin = normalize_pin(pin)
            payload_dict = {
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

            req = urllib.request.Request(
                f"{self.base_url}/p2p/register",
                data=json.dumps(payload_dict).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                reg_data = json.loads(resp.read().decode("utf-8"))

            token = reg_data.get("token")
            if not token:
                return None

            default_relay = reg_data.get("relay") or {"host": self.rendezvous_host, "port": self.stun_port}
            self.is_running = True

            if on_paired_callback:
                def _sse_or_poll_worker():
                    last_peer_sig = None
                    while self.is_running:
                        paired_in_cycle = False
                        # 1. Push instantâneo via Server-Sent Events (< 50 ms)
                        try:
                            sse_url = f"{self.base_url}/p2p/events?pin={clean_pin}&token={token}"
                            sse_req = urllib.request.Request(sse_url, headers={"Accept": "text/event-stream"})
                            with urllib.request.urlopen(sse_req, timeout=90) as sse_resp:
                                for raw_line in sse_resp:
                                    if not self.is_running:
                                        return
                                    line = raw_line.decode("utf-8", errors="ignore").strip()
                                    if line.startswith("data:"):
                                        try:
                                            evt_data = json.loads(line[5:].strip())
                                            if evt_data.get("status") == "paired":
                                                peer = dict(evt_data["peer"])
                                                peer["_relay"] = evt_data.get("relay") or default_relay
                                                peer_sig = (
                                                    peer.get("public_ip"),
                                                    peer.get("public_port"),
                                                    peer.get("local_ip"),
                                                    peer.get("local_port"),
                                                )
                                                if peer_sig != last_peer_sig:
                                                    last_peer_sig = peer_sig
                                                    on_paired_callback(peer)
                                                paired_in_cycle = True
                                                return
                                        except Exception:
                                            pass
                        except Exception as sse_err:
                            logger.debug(f"Fluxo SSE encerrado ({sse_err}); alternando para polling.")

                        if paired_in_cycle or not self.is_running:
                            return

                        # 2. Fallback resiliente por HTTP Polling
                        for _ in range(80):
                            if not self.is_running:
                                return
                            time.sleep(1.2)
                            try:
                                p_req = urllib.request.Request(
                                    f"{self.base_url}/p2p/poll",
                                    data=json.dumps({"pin": clean_pin, "token": token}).encode("utf-8"),
                                    headers={"Content-Type": "application/json"},
                                )
                                with urllib.request.urlopen(p_req, timeout=3.0) as p_resp:
                                    p_data = json.loads(p_resp.read().decode("utf-8"))
                                    if p_data.get("status") == "paired":
                                        peer = dict(p_data["peer"])
                                        peer["_relay"] = p_data.get("relay") or default_relay
                                        on_paired_callback(peer)
                                        return
                            except Exception:
                                continue
                        break

                t = threading.Thread(target=_sse_or_poll_worker, daemon=True, name=f"P2P-SSE-{clean_pin}")
                t.start()

            return reg_data

        except Exception as exc:
            logger.warning(f"Falha ao registrar PIN no Rendezvous ({self.base_url}): {exc}")
            return None

    def stop(self):
        """Interrompe threads auxiliares de sinalização SSE/Polling."""
        self.is_running = False

    def resolve_receiver_target(
        self,
        pin: str,
        local_port: int,
        node_name: str = "Host-Receiver",
        bound_sock: Optional[socket.socket] = None,
        endpoint_info: Optional[Dict[str, object]] = None,
    ) -> Optional[dict]:
        """
        Resolve um código PIN no Rendezvous enviando o endpoint real STUN/LAN do socket
        de recepção já aberto, garantindo simetria de porta externa para o Hole-Punching.
        """
        self._ensure_local_rendezvous()
        try:
            if endpoint_info is None and bound_sock is not None:
                endpoint_info = discover_socket_endpoint(bound_sock, self.rendezvous_host, self.stun_port)

            if endpoint_info is not None:
                loc_ip = str(endpoint_info.get("local_ip") or get_local_ip())
                eff_local_port = int(endpoint_info.get("local_port") or local_port)
                pub_ip = endpoint_info.get("public_ip")
                pub_port = int(endpoint_info.get("public_port") or eff_local_port)
                nat_type = str(endpoint_info.get("nat_type") or "unknown")
                candidates = endpoint_info.get("candidates") or get_local_candidates(eff_local_port)
            else:
                loc_ip = get_local_ip()
                eff_local_port = int(local_port)
                stun_ep = self.get_public_endpoint_via_stun()
                pub_ip = stun_ep[0] if stun_ep else None
                pub_port = int(stun_ep[1]) if stun_ep else eff_local_port
                nat_type = "cone" if stun_ep else "unknown"
                candidates = get_local_candidates(eff_local_port)

            clean_pin = normalize_pin(pin)
            payload_dict = {
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

            req = urllib.request.Request(
                f"{self.base_url}/p2p/resolve",
                data=json.dumps(payload_dict).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))

            if res_data.get("status") == "paired":
                if "relay" not in res_data:
                    res_data["relay"] = {"host": self.rendezvous_host, "port": self.stun_port}
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
        """
        Executa UDP Hole-Punching bidirecional concorrente no próprio `local_sock`
        testando simultaneamente candidatos Overlay, LAN e WAN e confirmando via SYN/ACK.
        """
        candidates = build_peer_candidates(peer_info, my_public_ip=my_public_ip)
        if not candidates:
            return ("127.0.0.1", 9000, "lan")

        clean_pin = normalize_pin(pin)
        syn_pkt = f"DAV_P2P_SYN:{clean_pin}".encode("ascii") if clean_pin else MAGIC_SYN
        ack_pkt = f"DAV_P2P_ACK:{clean_pin}".encode("ascii") if clean_pin else MAGIC_ACK

        old_timeout = local_sock.gettimeout()
        local_sock.settimeout(0.12)

        working_target: Optional[Tuple[str, int]] = None
        working_mode = candidates[0][2]
        start_t = time.monotonic()

        try:
            # Rajada inicial de abertura da tabela de estado NAT em todos os candidatos
            for _ in range(4):
                for ip, port, _ in candidates:
                    try:
                        local_sock.sendto(syn_pkt, (ip, port))
                    except Exception:
                        pass
                time.sleep(0.025)

            while time.monotonic() - start_t < timeout_sec:
                try:
                    data, addr = local_sock.recvfrom(2048)
                    if data.startswith(MAGIC_SYN) or data.startswith(MAGIC_ACK):
                        working_target = (addr[0], int(addr[1]))
                        for _ in range(3):
                            try:
                                local_sock.sendto(ack_pkt, working_target)
                            except Exception:
                                pass
                        break
                    # Caso já seja um pacote de mídia válido do DA-V (32B header + payload)
                    if len(data) >= 48 and data[0] == 1:
                        working_target = (addr[0], int(addr[1]))
                        break
                except (socket.timeout, BlockingIOError, ConnectionResetError):
                    for ip, port, _ in candidates:
                        try:
                            local_sock.sendto(syn_pkt, (ip, port))
                        except Exception:
                            pass
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
            if working_target[0].startswith("127."):
                mode = "lan"
            elif kind:
                mode = kind
            else:
                mode = "wan"
            return (working_target[0], working_target[1], mode)

        # Se nenhum ACK retornou dentro do timeout, retorna o melhor candidato primário
        return candidates[0]
