#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V — Servidor Rendezvous, STUN Reflexivo e Blind Encrypted UDP Relay (v2.0)
Autor: Dante Ferraz (MonoTech)

Microserviço assíncrono leve em Python puro (asyncio + socket), sem dependências externas,
desenhado para execução contínua em VPS Linux (Oracle Cloud) ou em rede local/testes.

Responsabilidades:
1. Registro e resolução de sessões efêmeras por PIN de 6 dígitos (TTL de 180s renovável).
2. Notificação instantânea (< 50 ms) ao Transmissor via Server-Sent Events (SSE) quando
   um Receptor solicita pareamento, mantendo fallback resiliente por HTTP Polling.
3. Descoberta STUN reflexiva e troca completa de candidatos de rede (LAN, Overlay e WAN).
4. Blind Encrypted UDP Relay em memória O(1): quando ambos os nós estão atrás de CGNAT
   Simétrico estrito (comum em redes móveis 4G/5G e provedores fibra residencial), encaminha
   os datagramas já criptografados ponta a ponta sem possuir as chaves da sessão.
"""

import os
import time
import json
import secrets
import asyncio
import logging
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [DAV-Rendezvous] %(message)s",
)
logger = logging.getLogger("DAV-Rendezvous")

HTTP_PORT = int(os.environ.get("DAV_HTTP_PORT", 8765))
STUN_PORT = int(os.environ.get("DAV_STUN_PORT", 8768))
SESSION_TTL_SEC = int(os.environ.get("DAV_SESSION_TTL", 300))

MAGIC_RELAY_HDR = b"DAV_RLY1"  # 8B magic + 8B pin + 1B role ('S'|'R') = 17 bytes


class SessionRecord:
    """Estado em memória de uma sessão de pareamento ativa identificada por PIN."""

    def __init__(
        self,
        pin: str,
        sender_node: str,
        sender_local_ip: str,
        sender_local_port: int,
        sender_public_ip: str,
        sender_public_port: int,
        sender_candidates: Optional[List[dict]] = None,
        sender_nat_type: str = "unknown",
    ):
        self.pin = pin
        self.sender_node = sender_node
        self.sender_local_ip = sender_local_ip
        self.sender_local_port = sender_local_port
        self.sender_public_ip = sender_public_ip
        self.sender_public_port = sender_public_port
        self.sender_candidates = sender_candidates or []
        self.sender_nat_type = sender_nat_type

        self.created_at = time.time()
        self.last_active = time.time()
        self.token = secrets.token_hex(16)
        self.session_seed = secrets.token_hex(32)

        # Metadados do Receptor preenchidos no pareamento
        self.receiver_node: Optional[str] = None
        self.receiver_local_ip: Optional[str] = None
        self.receiver_local_port: Optional[int] = None
        self.receiver_public_ip: Optional[str] = None
        self.receiver_public_port: Optional[int] = None
        self.receiver_candidates: List[dict] = []
        self.receiver_nat_type: str = "unknown"

        self.is_paired = False
        self.pair_event = asyncio.Event()

        # Endpoints ativos no Blind Encrypted UDP Relay (fallback CGNAT Simétrico)
        self.relay_mode = False
        self.relay_sender_addr: Optional[Tuple[str, int]] = None
        self.relay_receiver_addr: Optional[Tuple[str, int]] = None
        self.relayed_packets = 0


class RendezvousUdpGateway(asyncio.DatagramProtocol):
    """
    Gateway UDP de dupla função na porta STUN_PORT (padrão 8768):
    - Responde sondas STUN reflexivas ('DAV_STUN_REQ') informando IP e porta externos reais.
    - Executa encaminhamento cego O(1) ('DAV_RLY1') de pacotes de vídeo criptografados
      quando o UDP Hole-Punching direto é bloqueado por CGNAT Simétrico.
    """

    def __init__(self, server: "DavRendezvousServer"):
        self.server = server
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.BaseTransport):
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        if not self.transport or not data:
            return

        # 1. Rota rápida: Blind Encrypted UDP Relay (custo O(1) sem decodificar UTF-8)
        if len(data) >= 17 and data[:8] == MAGIC_RELAY_HDR:
            pin_key = data[8:16].rstrip(b"\x00").decode("ascii", errors="ignore")
            role = data[16:17]
            inner = data[17:]

            record = self.server.sessions.get(pin_key)
            if record is None:
                return

            record.last_active = time.time()
            record.relay_mode = True

            if role == b"S":
                record.relay_sender_addr = addr
                if inner == b"BIND":
                    self.transport.sendto(b"DAV_RLY_ACK", addr)
                    if record.relay_receiver_addr:
                        self.transport.sendto(b"DAV_RLY_PEER_READY", addr)
                elif inner and record.relay_receiver_addr:
                    self.transport.sendto(inner, record.relay_receiver_addr)
                    record.relayed_packets += 1
            elif role == b"R":
                record.relay_receiver_addr = addr
                if inner == b"BIND":
                    self.transport.sendto(b"DAV_RLY_ACK", addr)
                    if record.relay_sender_addr:
                        self.transport.sendto(b"DAV_RLY_PEER_READY", record.relay_sender_addr)
                elif inner and record.relay_sender_addr:
                    self.transport.sendto(inner, record.relay_sender_addr)
            return

        # 2. Sonda STUN reflexiva leve
        if data[:8] == b"DAV_STUN":
            try:
                resp = json.dumps({
                    "status": "ok",
                    "reflexive_ip": addr[0],
                    "reflexive_port": addr[1],
                    "ts": time.time(),
                }).encode("utf-8")
                self.transport.sendto(resp, addr)
            except Exception as exc:
                logger.debug(f"Falha ao responder sonda STUN de {addr}: {exc}")


class DavRendezvousServer:
    """Servidor HTTP/SSE de sinalização P2P acoplado ao RendezvousUdpGateway."""

    def __init__(self, host: str = "0.0.0.0", http_port: int = HTTP_PORT, stun_port: int = STUN_PORT):
        self.host = host
        self.http_port = http_port
        self.stun_port = stun_port
        self.public_relay_host = os.environ.get("DAV_PUBLIC_HOST", "")
        self.sessions: Dict[str, SessionRecord] = {}
        self.start_time = time.time()

    def _cleanup_stale_sessions(self):
        now = time.time()
        expired = [pin for pin, rec in self.sessions.items() if now - rec.last_active > SESSION_TTL_SEC]
        for pin in expired:
            logger.info(f"Sessão PIN {pin} expirada após inatividade ({SESSION_TTL_SEC}s).")
            del self.sessions[pin]

    def _resolve_relay_host(self, req_headers: Dict[str, str]) -> str:
        if self.public_relay_host:
            return self.public_relay_host
        host_hdr = req_headers.get("host", "")
        if host_hdr:
            return host_hdr.split(":")[0].strip()
        return "127.0.0.1" if self.host in ("0.0.0.0", "127.0.0.1", "localhost") else self.host

    @staticmethod
    def _build_receiver_peer_dict(record: SessionRecord) -> dict:
        return {
            "node_name": record.receiver_node,
            "public_ip": record.receiver_public_ip,
            "public_port": record.receiver_public_port,
            "local_ip": record.receiver_local_ip,
            "local_port": record.receiver_local_port,
            "candidates": record.receiver_candidates,
            "nat_type": record.receiver_nat_type,
        }

    @staticmethod
    def _build_sender_peer_dict(record: SessionRecord) -> dict:
        return {
            "node_name": record.sender_node,
            "public_ip": record.sender_public_ip,
            "public_port": record.sender_public_port,
            "local_ip": record.sender_local_ip,
            "local_port": record.sender_local_port,
            "candidates": record.sender_candidates,
            "nat_type": record.sender_nat_type,
        }

    async def handle_http_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._cleanup_stale_sessions()
        peer_addr = writer.get_extra_info("peername")
        client_ip = peer_addr[0] if peer_addr else "127.0.0.1"

        try:
            line = await asyncio.wait_for(reader.readline(), timeout=10.0)
            if not line:
                writer.close()
                return

            parts = line.decode("utf-8", errors="ignore").strip().split()
            if len(parts) < 2:
                writer.close()
                return

            method, path = parts[0].upper(), parts[1]
            query_params: Dict[str, str] = {}
            if "?" in path:
                raw_path, query_str = path.split("?", 1)
                for pair in query_str.split("&"):
                    if "=" in pair:
                        qk, qv = pair.split("=", 1)
                        query_params[qk.strip()] = qv.strip()
            else:
                raw_path = path

            headers: Dict[str, str] = {}
            content_length = 0
            while True:
                h_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
                if not h_line or h_line in (b"\r\n", b"\n"):
                    break
                decoded_h = h_line.decode("utf-8", errors="ignore").strip()
                if ":" in decoded_h:
                    k, v = decoded_h.split(":", 1)
                    k_lower = k.strip().lower()
                    headers[k_lower] = v.strip()
                    if k_lower == "content-length":
                        try:
                            content_length = max(0, min(65536, int(v.strip())))
                        except ValueError:
                            content_length = 0

            if "x-real-ip" in headers:
                client_ip = headers["x-real-ip"]
            elif "x-forwarded-for" in headers:
                client_ip = headers["x-forwarded-for"].split(",")[0].strip()

            body_json: dict = {}
            if content_length > 0:
                body_bytes = await asyncio.wait_for(reader.readexactly(content_length), timeout=10.0)
                try:
                    body_json = json.loads(body_bytes.decode("utf-8"))
                except Exception:
                    body_json = {}

            relay_host = self._resolve_relay_host(headers)
            status_code = 200
            resp_data: dict = {}

            # ── 1. Health & Diagnóstico Operacional ──
            if method == "GET" and (
                raw_path in ("/health", "/status", "/", "/p2p/health", "/p2p/status", "/p2p/", "/p2p")
                or raw_path.endswith("/health")
                or raw_path.endswith("/status")
            ):
                resp_data = {
                    "service": "DAV-Rendezvous",
                    "version": "3.1.0",
                    "status": "online",
                    "uptime_sec": int(time.time() - self.start_time),
                    "active_sessions": len(self.sessions),
                    "http_port": self.http_port,
                    "stun_port": self.stun_port,
                    "relay_port": self.stun_port,
                    "client_ip": client_ip,
                }

            # ── 2. Canal SSE de Pareamento Instantâneo (< 50 ms) ──
            elif method == "GET" and (raw_path in ("/p2p/events", "/events") or raw_path.endswith("/events")):
                raw_pin = query_params.get("pin", "").strip()
                clean_pin = raw_pin.replace("-", "").replace(" ", "")
                token = query_params.get("token", "").strip()

                if not clean_pin or clean_pin not in self.sessions:
                    status_code = 404
                    resp_data = {"error": "Sessão não encontrada"}
                else:
                    record = self.sessions[clean_pin]
                    if record.token != token:
                        status_code = 403
                        resp_data = {"error": "Token de sessão inválido"}
                    else:
                        sse_headers = (
                            "HTTP/1.1 200 OK\r\n"
                            "Content-Type: text/event-stream; charset=utf-8\r\n"
                            "Cache-Control: no-cache, no-transform\r\n"
                            "Connection: keep-alive\r\n"
                            "Access-Control-Allow-Origin: *\r\n"
                            "X-Accel-Buffering: no\r\n\r\n"
                        ).encode("utf-8")
                        writer.write(sse_headers)
                        writer.write(b": connected\n\n")
                        await writer.drain()

                        t_deadline = time.time() + SESSION_TTL_SEC
                        while time.time() < t_deadline and not writer.is_closing():
                            record.last_active = time.time()
                            if record.is_paired:
                                peer_payload = {
                                    "status": "paired",
                                    "peer": self._build_receiver_peer_dict(record),
                                    "relay": {"host": relay_host, "port": self.stun_port},
                                }
                                evt_bytes = f"event: paired\ndata: {json.dumps(peer_payload)}\n\n".encode("utf-8")
                                writer.write(evt_bytes)
                                await writer.drain()
                                break

                            try:
                                await asyncio.wait_for(record.pair_event.wait(), timeout=10.0)
                            except asyncio.TimeoutError:
                                writer.write(b": keepalive\n\n")
                                await writer.drain()
                        return

            # ── 3. Registro do Nó Transmissor (POST /p2p/register) ──
            elif method == "POST" and (raw_path == "/p2p/register" or raw_path.endswith("/register")):
                raw_pin = str(body_json.get("pin", "")).strip()
                clean_pin = raw_pin.replace("-", "").replace(" ", "")
                node_name = str(body_json.get("node_name", "Host-Sender"))
                local_ip = str(body_json.get("local_ip") or client_ip)
                local_port = int(body_json.get("local_port", 9000))
                public_ip = str(body_json.get("public_ip") or client_ip)
                # Em loopback local, preserva o IP reflexivo observado pelo socket se STUN externo veio público
                effective_pub_ip = client_ip if client_ip not in ("127.0.0.1", "::1") else (public_ip or client_ip)
                if public_ip and public_ip not in ("127.0.0.1", "0.0.0.0") and client_ip not in ("127.0.0.1", "::1"):
                    effective_pub_ip = public_ip
                public_port = int(body_json.get("public_port") or local_port)
                candidates = body_json.get("candidates") if isinstance(body_json.get("candidates"), list) else []
                nat_type = str(body_json.get("nat_type", "unknown"))

                if not clean_pin:
                    status_code = 400
                    resp_data = {"error": "PIN obrigatório"}
                else:
                    record = SessionRecord(
                        pin=raw_pin,
                        sender_node=node_name,
                        sender_local_ip=local_ip,
                        sender_local_port=local_port,
                        sender_public_ip=effective_pub_ip,
                        sender_public_port=public_port,
                        sender_candidates=candidates,
                        sender_nat_type=nat_type,
                    )
                    self.sessions[clean_pin] = record
                    logger.info(
                        f"Transmissor registrado [PIN {raw_pin}] -> WAN {effective_pub_ip}:{public_port} | LAN {local_ip}:{local_port} ({nat_type})"
                    )
                    resp_data = {
                        "status": "registered",
                        "pin": raw_pin,
                        "token": record.token,
                        "session_seed": record.session_seed,
                        "your_public_ip": effective_pub_ip,
                        "stun_port": self.stun_port,
                        "relay": {"host": relay_host, "port": self.stun_port},
                    }

            # ── 4. Resolução e Pareamento do Receptor (POST /p2p/resolve) ──
            elif method == "POST" and (raw_path == "/p2p/resolve" or raw_path.endswith("/resolve")):
                raw_pin = str(body_json.get("pin", "")).strip()
                clean_pin = raw_pin.replace("-", "").replace(" ", "")
                node_name = str(body_json.get("node_name", "Host-Receiver"))
                local_ip = str(body_json.get("local_ip") or client_ip)
                local_port = int(body_json.get("local_port", 9002))
                public_ip = str(body_json.get("public_ip") or client_ip)
                effective_pub_ip = client_ip if client_ip not in ("127.0.0.1", "::1") else (public_ip or client_ip)
                if public_ip and public_ip not in ("127.0.0.1", "0.0.0.0") and client_ip not in ("127.0.0.1", "::1"):
                    effective_pub_ip = public_ip
                public_port = int(body_json.get("public_port") or local_port)
                candidates = body_json.get("candidates") if isinstance(body_json.get("candidates"), list) else []
                nat_type = str(body_json.get("nat_type", "unknown"))

                if clean_pin not in self.sessions:
                    status_code = 404
                    resp_data = {"error": "PIN não encontrado ou sessão expirada"}
                else:
                    record = self.sessions[clean_pin]
                    # Suporta reconexão limpa de um novo Receptor ao mesmo PIN ativo
                    record.receiver_node = node_name
                    record.receiver_local_ip = local_ip
                    record.receiver_local_port = local_port
                    record.receiver_public_ip = effective_pub_ip
                    record.receiver_public_port = public_port
                    record.receiver_candidates = candidates
                    record.receiver_nat_type = nat_type
                    record.is_paired = True
                    record.last_active = time.time()
                    record.pair_event.set()

                    logger.info(
                        f"Receptor pareado [PIN {raw_pin}] -> WAN {effective_pub_ip}:{public_port} | LAN {local_ip}:{local_port} ({nat_type})"
                    )
                    resp_data = {
                        "status": "paired",
                        "pin": raw_pin,
                        "token": record.token,
                        "session_seed": record.session_seed,
                        "your_public_ip": effective_pub_ip,
                        "peer": self._build_sender_peer_dict(record),
                        "relay": {"host": relay_host, "port": self.stun_port},
                    }

            # ── 5. Polling Fallback do Transmissor (POST /p2p/poll) ──
            elif method == "POST" and (raw_path == "/p2p/poll" or raw_path.endswith("/poll")):
                raw_pin = str(body_json.get("pin", "")).strip()
                clean_pin = raw_pin.replace("-", "").replace(" ", "")
                token = str(body_json.get("token", ""))

                if clean_pin not in self.sessions:
                    status_code = 404
                    resp_data = {"error": "Sessão não encontrada"}
                else:
                    record = self.sessions[clean_pin]
                    if record.token != token:
                        status_code = 403
                        resp_data = {"error": "Token inválido"}
                    else:
                        record.last_active = time.time()
                        if record.is_paired:
                            resp_data = {
                                "status": "paired",
                                "peer": self._build_receiver_peer_dict(record),
                                "relay": {"host": relay_host, "port": self.stun_port},
                            }
                        else:
                            resp_data = {"status": "waiting"}

            # ── 6. Ativação explícita de Blind Relay (POST /p2p/relay_init) ──
            elif method == "POST" and (raw_path == "/p2p/relay_init" or raw_path.endswith("/relay_init")):
                raw_pin = str(body_json.get("pin", "")).strip()
                clean_pin = raw_pin.replace("-", "").replace(" ", "")
                if clean_pin in self.sessions:
                    record = self.sessions[clean_pin]
                    record.relay_mode = True
                    record.last_active = time.time()
                    resp_data = {
                        "status": "relay_enabled",
                        "relay_host": relay_host,
                        "relay_port": self.stun_port,
                    }
                else:
                    status_code = 404
                    resp_data = {"error": "Sessão não encontrada"}

            else:
                status_code = 404
                resp_data = {"error": "Endpoint não encontrado"}

            resp_body = json.dumps(resp_data, ensure_ascii=False).encode("utf-8")
            status_map = {200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found"}
            status_text = status_map.get(status_code, "Error")
            resp_headers = (
                f"HTTP/1.1 {status_code} {status_text}\r\n"
                f"Content-Type: application/json; charset=utf-8\r\n"
                f"Content-Length: {len(resp_body)}\r\n"
                f"Access-Control-Allow-Origin: *\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("utf-8")

            writer.write(resp_headers + resp_body)
            await writer.drain()

        except Exception as exc:
            logger.debug(f"Erro ao atender cliente HTTP ({client_ip}): {exc}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self):
        loop = asyncio.get_running_loop()

        transport, _ = await loop.create_datagram_endpoint(
            lambda: RendezvousUdpGateway(self),
            local_addr=(self.host, self.stun_port),
        )
        logger.info(f"Gateway UDP (STUN + Blind Encrypted Relay) ativo em {self.host}:{self.stun_port}/udp")

        http_server = await asyncio.start_server(
            self.handle_http_client,
            self.host,
            self.http_port,
        )
        logger.info(f"Servidor HTTP/SSE Rendezvous ativo em http://{self.host}:{self.http_port}")

        try:
            async with http_server:
                await http_server.serve_forever()
        finally:
            transport.close()


def main():
    http_p = int(os.environ.get("DAV_HTTP_PORT", HTTP_PORT))
    stun_p = int(os.environ.get("DAV_STUN_PORT", STUN_PORT))
    server = DavRendezvousServer(http_port=http_p, stun_port=stun_p)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Servidor Rendezvous encerrado manualmente.")


if __name__ == "__main__":
    main()
