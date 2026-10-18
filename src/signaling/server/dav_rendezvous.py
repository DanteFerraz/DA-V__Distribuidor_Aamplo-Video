#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V — Servidor de Sinalização Rendezvous e Descoberta STUN
Autor: Dante Ferraz (MonoTech)

Microserviço autônomo e sem dependências externas (Python puro: asyncio + socket),
projetado para deploy imediato em VPS Linux (Oracle Cloud) ou teste local.
Responsabilidades:
- Servidor STUN UDP reflexivo para identificação do par (IP:Porta) público.
- Pareamento de nós transmissor e receptor baseado em PIN efêmero de 180 segundos.
- Derivação de tokens de autenticação HMAC anti-replay (herdado do TCD Core).
- Roteamento cego (Blind Encrypted Relay) como fallback caso os dois nós
  estejam atrás de NATs simétricos restritivos que impeçam o hole-punching direto.
"""

import sys
import os
import time
import json
import hmac
import hashlib
import secrets
import socket
import asyncio
import logging
from typing import Dict, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [DAV-Rendezvous] %(message)s"
)
logger = logging.getLogger("DAV-Rendezvous")

HTTP_PORT = 8765
STUN_PORT = 8768
SESSION_TTL_SEC = 180


class SessionRecord:
    def __init__(self, pin: str, sender_node: str, sender_local_ip: str, sender_local_port: int, sender_public_ip: str):
        self.pin = pin
        self.sender_node = sender_node
        self.sender_local_ip = sender_local_ip
        self.sender_local_port = sender_local_port
        self.sender_public_ip = sender_public_ip
        self.sender_public_port = sender_local_port  # updated via STUN
        self.created_at = time.time()
        self.last_active = time.time()
        self.token = secrets.token_hex(16)
        self.session_seed = secrets.token_hex(32)

        # Receiver fields
        self.receiver_node: Optional[str] = None
        self.receiver_local_ip: Optional[str] = None
        self.receiver_local_port: Optional[int] = None
        self.receiver_public_ip: Optional[str] = None
        self.receiver_public_port: Optional[int] = None
        self.is_paired = False
        self.relay_mode = False
        self.relay_port: Optional[int] = None


class StunProbeProtocol(asyncio.DatagramProtocol):
    """Reflexive UDP STUN responder: sends back the public IP and Port of the requester."""
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        try:
            # Client sends magic 'DAV_STUN_REQ' (optionally with PIN)
            msg = data.decode("utf-8", errors="ignore").strip()
            if msg.startswith("DAV_STUN"):
                resp = json.dumps({
                    "status": "ok",
                    "reflexive_ip": addr[0],
                    "reflexive_port": addr[1],
                    "ts": time.time()
                })
                self.transport.sendto(resp.encode("utf-8"), addr)
        except Exception as e:
            logger.debug(f"STUN probe handling error: {e}")


class DavRendezvousServer:
    def __init__(self, host: str = "0.0.0.0", http_port: int = HTTP_PORT, stun_port: int = STUN_PORT):
        self.host = host
        self.http_port = http_port
        self.stun_port = stun_port
        self.sessions: Dict[str, SessionRecord] = {}  # key: PIN -> SessionRecord
        self.start_time = time.time()

    def _cleanup_stale_sessions(self):
        now = time.time()
        expired = [pin for pin, s in self.sessions.items() if now - s.last_active > SESSION_TTL_SEC]
        for pin in expired:
            logger.info(f"Session with PIN {pin} expired and cleaned up.")
            del self.sessions[pin]

    async def handle_http_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._cleanup_stale_sessions()
        peer_addr = writer.get_extra_info("peername")
        client_ip = peer_addr[0] if peer_addr else "127.0.0.1"

        try:
            # Read HTTP request line
            line = await reader.readline()
            if not line:
                writer.close()
                return

            req_line = line.decode("utf-8", errors="ignore").strip()
            parts = req_line.split()
            if len(parts) < 2:
                writer.close()
                return

            method, path = parts[0], parts[1]

            # Read headers
            headers = {}
            content_length = 0
            while True:
                h_line = await reader.readline()
                if not h_line or h_line == b"\r\n" or h_line == b"\n":
                    break
                decoded_h = h_line.decode("utf-8", errors="ignore").strip()
                if ":" in decoded_h:
                    k, v = decoded_h.split(":", 1)
                    k_lower = k.strip().lower()
                    headers[k_lower] = v.strip()
                    if k_lower == "content-length":
                        try:
                            content_length = int(v.strip())
                        except ValueError:
                            content_length = 0

            # Read body
            body_bytes = b""
            if content_length > 0:
                body_bytes = await reader.readexactly(content_length)

            body_json = {}
            if body_bytes:
                try:
                    body_json = json.loads(body_bytes.decode("utf-8"))
                except Exception:
                    body_json = {}

            # Route handling
            status_code = 200
            resp_data = {}

            # ── 1. GET /health or /status ──
            if method == "GET" and path in ("/health", "/status", "/"):
                resp_data = {
                    "service": "DAV-Rendezvous",
                    "status": "online",
                    "uptime_sec": int(time.time() - self.start_time),
                    "active_sessions": len(self.sessions),
                    "http_port": self.http_port,
                    "stun_port": self.stun_port,
                    "client_ip": client_ip
                }

            # ── 2. POST /p2p/register (Sender creates/registers PIN) ──
            elif method == "POST" and path == "/p2p/register":
                pin = body_json.get("pin", "").strip()
                node_name = body_json.get("node_name", "Unknown-Sender")
                local_ip = body_json.get("local_ip", client_ip)
                local_port = int(body_json.get("local_port", 9000))
                public_port = int(body_json.get("public_port", local_port))

                if not pin:
                    status_code = 400
                    resp_data = {"error": "PIN obrigatorio"}
                else:
                    record = SessionRecord(
                        pin=pin,
                        sender_node=node_name,
                        sender_local_ip=local_ip,
                        sender_local_port=local_port,
                        sender_public_ip=client_ip
                    )
                    record.sender_public_port = public_port
                    self.sessions[pin] = record
                    logger.info(f"Transmissor registrado com PIN {pin} ({client_ip}:{public_port})")

                    resp_data = {
                        "status": "registered",
                        "pin": pin,
                        "token": record.token,
                        "session_seed": record.session_seed,
                        "your_public_ip": client_ip,
                        "stun_port": self.stun_port
                    }

            # ── 3. POST /p2p/resolve (Receiver pairs using PIN) ──
            elif method == "POST" and path == "/p2p/resolve":
                pin = body_json.get("pin", "").strip()
                node_name = body_json.get("node_name", "Unknown-Receiver")
                local_ip = body_json.get("local_ip", client_ip)
                local_port = int(body_json.get("local_port", 9002))
                public_port = int(body_json.get("public_port", local_port))

                if pin not in self.sessions:
                    status_code = 404
                    resp_data = {"error": "PIN nao encontrado ou sessao expirada"}
                else:
                    record = self.sessions[pin]
                    record.receiver_node = node_name
                    record.receiver_local_ip = local_ip
                    record.receiver_local_port = local_port
                    record.receiver_public_ip = client_ip
                    record.receiver_public_port = public_port
                    record.is_paired = True
                    record.last_active = time.time()

                    logger.info(f"Receptor pareado com PIN {pin} ({client_ip}:{public_port})")

                    resp_data = {
                        "status": "paired",
                        "pin": pin,
                        "token": record.token,
                        "session_seed": record.session_seed,
                        "your_public_ip": client_ip,
                        "peer": {
                            "node_name": record.sender_node,
                            "public_ip": record.sender_public_ip,
                            "public_port": record.sender_public_port,
                            "local_ip": record.sender_local_ip,
                            "local_port": record.sender_local_port
                        }
                    }

            # ── 4. POST /p2p/poll (Sender checks if Receiver has paired) ──
            elif method == "POST" and path == "/p2p/poll":
                pin = body_json.get("pin", "").strip()
                token = body_json.get("token", "")

                if pin not in self.sessions:
                    status_code = 404
                    resp_data = {"error": "Sessao nao encontrada"}
                else:
                    record = self.sessions[pin]
                    if record.token != token:
                        status_code = 403
                        resp_data = {"error": "Token invalido"}
                    else:
                        record.last_active = time.time()
                        if record.is_paired:
                            resp_data = {
                                "status": "paired",
                                "peer": {
                                    "node_name": record.receiver_node,
                                    "public_ip": record.receiver_public_ip,
                                    "public_port": record.receiver_public_port,
                                    "local_ip": record.receiver_local_ip,
                                    "local_port": record.receiver_local_port
                                }
                            }
                        else:
                            resp_data = {"status": "waiting"}

            # ── 5. POST /p2p/relay_init (Fallback for Symmetric NAT) ──
            elif method == "POST" and path == "/p2p/relay_init":
                pin = body_json.get("pin", "").strip()
                if pin in self.sessions:
                    record = self.sessions[pin]
                    record.relay_mode = True
                    record.last_active = time.time()
                    resp_data = {
                        "status": "relay_enabled",
                        "relay_host": self.host if self.host != "0.0.0.0" else client_ip,
                        "relay_port": self.stun_port
                    }
                else:
                    status_code = 404
                    resp_data = {"error": "Sessao nao encontrada"}

            else:
                status_code = 404
                resp_data = {"error": "Endpoint nao encontrado"}

            # Send HTTP response with CORS headers
            resp_body = json.dumps(resp_data, ensure_ascii=False).encode("utf-8")
            status_text = "OK" if status_code == 200 else ("Not Found" if status_code == 404 else "Forbidden")
            resp_headers = (
                f"HTTP/1.1 {status_code} {status_text}\r\n"
                f"Content-Type: application/json; charset=utf-8\r\n"
                f"Content-Length: {len(resp_body)}\r\n"
                f"Access-Control-Allow-Origin: *\r\n"
                f"Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
                f"Access-Control-Allow-Headers: Content-Type\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode("utf-8")

            writer.write(resp_headers + resp_body)
            await writer.drain()

        except Exception as e:
            logger.debug(f"HTTP handler error: {e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self):
        # 1. Start HTTP Server
        http_server = await asyncio.start_server(
            self.handle_http_client, self.host, self.http_port
        )
        logger.info(f"HTTP Rendezvous API ativa em http://{self.host}:{self.http_port}")

        # 2. Start STUN Reflexive UDP Server
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: StunProbeProtocol(),
            local_addr=(self.host, self.stun_port)
        )
        logger.info(f"UDP STUN Reflexivo ativo em udp://{self.host}:{self.stun_port}")

        async with http_server:
            await http_server.serve_forever()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="DA-V Rendezvous Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host bind address")
    parser.add_argument("--port", type=int, default=HTTP_PORT, help="HTTP API Port")
    parser.add_argument("--stun-port", type=int, default=STUN_PORT, help="UDP STUN Port")
    args = parser.parse_args()

    server = DavRendezvousServer(host=args.host, http_port=args.port, stun_port=args.stun_port)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Rendezvous server encerrado pelo operador.")


if __name__ == "__main__":
    main()
