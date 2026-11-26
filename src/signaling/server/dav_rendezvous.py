#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
DA-V — Servidor Rendezvous Dual-Stack, STUN Reflexivo e Blind Encrypted Relay Hibrido (v3.2.0)
Autor: Dante Ferraz (MonoTech)

Microservico assincrono leve em Python stdlib puro (asyncio + socket), sem dependencias externas:
1. Bind Dual-Stack (`AF_INET6` + `IPV6_V6ONLY=0` em `[::]`) aceitando clientes IPv4 e IPv6-Only
   simultaneamente, incluindo **Blind Relay Cross-Family (`IPv4 <-> IPv6`)** em O(1).
2. Registro/resolucao de sessoes por PIN (TTL 300s) com SSE multi-peer e `since_index`.
3. Gateway UDP (STUN reflexivo + Blind Relay `DAV_RLY1` na porta 8768).
4. Blind Relay sobre HTTP/TCP (`GET /p2p/relay_stream` SSE com `X-Accel-Buffering: no`,
   `POST /p2p/relay_push` keep-alive e `GET /p2p/ws_relay` RFC 6455 stdlib) para redes
   institucionais que bloqueiam UDP externo.
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import socket
import struct
import time
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
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _clean_ip(ip_str: str) -> str:
    """Remove prefixo IPv4-mapped (`::ffff:`) e colchetes para retrocompatibilidade JSON."""
    s = str(ip_str or "").strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    if s.lower().startswith("::ffff:") and "." in s:
        return s[7:]
    return s


def _parse_http_host_header(host_hdr: str) -> str:
    """Extrai o host de um cabecalho HTTP `Host:` preservando literais IPv6 `[2603:...]:8765`."""
    h = str(host_hdr or "").strip()
    if not h:
        return ""
    if h.startswith("["):
        end_b = h.find("]")
        if end_b > 1:
            return h[1:end_b].strip()
    if h.count(":") == 1:
        return h.split(":", 1)[0].strip()
    return h


class SessionRecord:
    """Estado em memoria de uma sessao de pareamento ativa identificada por PIN."""

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
        sender_public_ipv6: Optional[str] = None,
        sender_public_ipv6_port: Optional[int] = None,
    ):
        self.pin = pin
        self.sender_node = sender_node
        self.sender_local_ip = sender_local_ip
        self.sender_local_port = sender_local_port
        self.sender_public_ip = sender_public_ip
        self.sender_public_port = sender_public_port
        self.sender_public_ipv6 = sender_public_ipv6
        self.sender_public_ipv6_port = sender_public_ipv6_port
        self.sender_candidates = sender_candidates or []
        self.sender_nat_type = sender_nat_type

        self.created_at = time.time()
        self.last_active = time.time()
        self.token = secrets.token_hex(16)
        self.session_seed = secrets.token_hex(32)

        self.receiver_node: Optional[str] = None
        self.receiver_local_ip: Optional[str] = None
        self.receiver_local_port: Optional[int] = None
        self.receiver_public_ip: Optional[str] = None
        self.receiver_public_port: Optional[int] = None
        self.receiver_public_ipv6: Optional[str] = None
        self.receiver_public_ipv6_port: Optional[int] = None
        self.receiver_candidates: List[dict] = []
        self.receiver_nat_type: str = "unknown"

        self.is_paired = False
        self.pair_event = asyncio.Event()
        self.paired_receivers: List[dict] = []

        # Endpoints ativos no Blind Encrypted UDP Relay (suporta Cross-Family IPv4 <-> IPv6)
        self.relay_mode = False
        self.relay_sender_addr: Optional[tuple] = None
        self.relay_receiver_addr: Optional[tuple] = None
        self.relay_receiver_addrs: List[tuple] = []
        self.relayed_packets = 0

        # Filas do Blind Encrypted HTTP-Stream / WebSocket Relay (porta 80/443)
        self.http_sender_queues: List[asyncio.Queue] = []
        self.http_receiver_queues: List[asyncio.Queue] = []

    def push_to_http_role(self, target_role: str, raw_pkt: bytes) -> None:
        queues = self.http_sender_queues if target_role == "S" else self.http_receiver_queues
        for q in list(queues):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(raw_pkt)
            except asyncio.QueueFull:
                pass


class RendezvousUdpGateway(asyncio.DatagramProtocol):
    """
    Gateway UDP Dual-Stack (porta 8768):
    - Responde sondas STUN reflexivas (`DAV_STUN_REQ`) com IP limpo (IPv4 ou IPv6).
    - Encaminha `DAV_RLY1` em O(1), incluindo ponte Cross-Family IPv4 <-> IPv6 e ponte UDP <-> HTTP-Stream.
    """

    def __init__(self, server: "DavRendezvousServer"):
        self.server = server
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.BaseTransport):
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple):
        if not self.transport or not data:
            return

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
                    if record.relay_receiver_addr or record.relay_receiver_addrs or record.http_receiver_queues:
                        self.transport.sendto(b"DAV_RLY_PEER_READY", addr)
                elif inner:
                    targets = record.relay_receiver_addrs or (
                        [record.relay_receiver_addr] if record.relay_receiver_addr else []
                    )
                    for r_addr in targets:
                        try:
                            self.transport.sendto(inner, r_addr)
                            record.relayed_packets += 1
                        except OSError:
                            pass
                    if record.http_receiver_queues:
                        record.push_to_http_role("R", inner)
                        record.relayed_packets += 1
            elif role == b"R":
                record.relay_receiver_addr = addr
                if addr not in record.relay_receiver_addrs:
                    if len(record.relay_receiver_addrs) >= 8:
                        record.relay_receiver_addrs.pop(0)
                    record.relay_receiver_addrs.append(addr)
                if inner == b"BIND":
                    self.transport.sendto(b"DAV_RLY_ACK", addr)
                    if record.relay_sender_addr:
                        self.transport.sendto(b"DAV_RLY_PEER_READY", record.relay_sender_addr)
                elif inner:
                    if record.relay_sender_addr:
                        try:
                            self.transport.sendto(inner, record.relay_sender_addr)
                        except OSError:
                            pass
                    if record.http_sender_queues:
                        record.push_to_http_role("S", inner)
            return

        if data[:8] == b"DAV_STUN":
            try:
                resp = json.dumps({
                    "status": "ok",
                    "reflexive_ip": _clean_ip(addr[0]),
                    "reflexive_port": int(addr[1]),
                    "ts": time.time(),
                }).encode("utf-8")
                self.transport.sendto(resp, addr)
            except Exception as exc:
                logger.debug(f"Falha ao responder sonda STUN de {addr}: {exc}")


class DavRendezvousServer:
    """Servidor HTTP/SSE/HTTP-Relay/WS Dual-Stack acoplado ao RendezvousUdpGateway."""

    def __init__(self, host: str = "0.0.0.0", http_port: int = HTTP_PORT, stun_port: int = STUN_PORT):
        self.host = host
        self.http_port = http_port
        self.stun_port = stun_port
        self.public_relay_host = os.environ.get("DAV_PUBLIC_HOST", "")
        self.sessions: Dict[str, SessionRecord] = {}
        self.start_time = time.time()
        self._udp_gateway: Optional[RendezvousUdpGateway] = None

    def _cleanup_stale_sessions(self):
        now = time.time()
        expired = [pin for pin, rec in self.sessions.items() if now - rec.last_active > SESSION_TTL_SEC]
        for pin in expired:
            logger.info(f"Sessao PIN {pin} expirada apos inatividade ({SESSION_TTL_SEC}s).")
            del self.sessions[pin]

    def _resolve_relay_host(self, req_headers: Dict[str, str]) -> str:
        if self.public_relay_host:
            return self.public_relay_host
        parsed = _parse_http_host_header(req_headers.get("host", ""))
        if parsed:
            return parsed
        return "127.0.0.1" if self.host in ("0.0.0.0", "127.0.0.1", "localhost", "::") else self.host

    @staticmethod
    def _build_receiver_peer_dict(record: SessionRecord) -> dict:
        out = {
            "node_name": record.receiver_node,
            "public_ip": record.receiver_public_ip,
            "public_port": record.receiver_public_port,
            "local_ip": record.receiver_local_ip,
            "local_port": record.receiver_local_port,
            "candidates": record.receiver_candidates,
            "nat_type": record.receiver_nat_type,
        }
        if record.receiver_public_ipv6:
            out["public_ipv6"] = record.receiver_public_ipv6
            out["public_ipv6_port"] = record.receiver_public_ipv6_port or record.receiver_local_port
        return out

    @staticmethod
    def _build_sender_peer_dict(record: SessionRecord) -> dict:
        out = {
            "node_name": record.sender_node,
            "public_ip": record.sender_public_ip,
            "public_port": record.sender_public_port,
            "local_ip": record.sender_local_ip,
            "local_port": record.sender_local_port,
            "candidates": record.sender_candidates,
            "nat_type": record.sender_nat_type,
        }
        if record.sender_public_ipv6:
            out["public_ipv6"] = record.sender_public_ipv6
            out["public_ipv6_port"] = record.sender_public_ipv6_port or record.sender_local_port
        return out

    def _forward_from_http_relay(self, record: SessionRecord, role: str, raw_pkt: bytes) -> None:
        record.last_active = time.time()
        record.relay_mode = True
        if role == "S":
            record.push_to_http_role("R", raw_pkt)
            if self._udp_gateway and self._udp_gateway.transport:
                targets = record.relay_receiver_addrs or (
                    [record.relay_receiver_addr] if record.relay_receiver_addr else []
                )
                for r_addr in targets:
                    try:
                        self._udp_gateway.transport.sendto(raw_pkt, r_addr)
                    except OSError:
                        pass
            record.relayed_packets += 1
        else:
            record.push_to_http_role("S", raw_pkt)
            if self._udp_gateway and self._udp_gateway.transport and record.relay_sender_addr:
                try:
                    self._udp_gateway.transport.sendto(raw_pkt, record.relay_sender_addr)
                except OSError:
                    pass
            record.relayed_packets += 1

    async def _handle_ws_relay(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        record: SessionRecord,
        role: str,
        ws_key: str,
    ) -> None:
        """WebSocket RFC 6455 stdlib puro para Blind Relay binario na porta HTTP/HTTPS."""
        accept = base64.b64encode(hashlib.sha1((ws_key + WS_GUID).encode("ascii")).digest()).decode("ascii")
        handshake = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode("ascii")
        writer.write(handshake)
        await writer.drain()

        my_q: asyncio.Queue = asyncio.Queue(maxsize=256)
        q_list = record.http_sender_queues if role == "S" else record.http_receiver_queues
        q_list.append(my_q)

        async def _ws_writer() -> None:
            while not writer.is_closing():
                pkt = await my_q.get()
                n = len(pkt)
                if n < 126:
                    hdr = bytes([0x82, n])
                elif n < 65536:
                    hdr = struct.pack("!BBH", 0x82, 126, n)
                else:
                    hdr = struct.pack("!BBQ", 0x82, 127, n)
                writer.write(hdr + pkt)
                await writer.drain()

        w_task = asyncio.create_task(_ws_writer())
        try:
            while not writer.is_closing():
                h2 = await asyncio.wait_for(reader.readexactly(2), timeout=30.0)
                opcode = h2[0] & 0x0F
                masked = bool(h2[1] & 0x80)
                plen = h2[1] & 0x7F
                if plen == 126:
                    plen = struct.unpack("!H", await reader.readexactly(2))[0]
                elif plen == 127:
                    plen = struct.unpack("!Q", await reader.readexactly(8))[0]
                if plen > 131072:
                    break
                mask_key = await reader.readexactly(4) if masked else b""
                payload = bytearray(await reader.readexactly(plen)) if plen else bytearray()
                if masked and mask_key:
                    for i in range(len(payload)):
                        payload[i] ^= mask_key[i & 3]
                if opcode == 0x8:  # Close
                    break
                if opcode == 0x9:  # Ping -> Pong
                    writer.write(bytes([0x8A, 0]))
                    await writer.drain()
                elif opcode in (0x1, 0x2) and payload:
                    self._forward_from_http_relay(record, role, bytes(payload))
        except Exception:
            pass
        finally:
            w_task.cancel()
            try:
                q_list.remove(my_q)
            except ValueError:
                pass

    async def handle_http_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._cleanup_stale_sessions()
        peer_addr = writer.get_extra_info("peername")
        client_ip = _clean_ip(peer_addr[0]) if peer_addr else "127.0.0.1"

        try:
            # Permite keep-alive para POST /p2p/relay_push de baixa latencia
            while not writer.is_closing():
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=15.0)
                except asyncio.TimeoutError:
                    break
                if not line:
                    break

                parts = line.decode("utf-8", errors="ignore").strip().split()
                if len(parts) < 2:
                    break

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
                                content_length = max(0, min(262144, int(v.strip())))
                            except ValueError:
                                content_length = 0

                eff_client_ip = client_ip
                if "x-real-ip" in headers:
                    eff_client_ip = _clean_ip(headers["x-real-ip"])
                elif "x-forwarded-for" in headers:
                    eff_client_ip = _clean_ip(headers["x-forwarded-for"].split(",")[0].strip())

                body_bytes = b""
                if content_length > 0:
                    body_bytes = await asyncio.wait_for(reader.readexactly(content_length), timeout=10.0)

                relay_host = self._resolve_relay_host(headers)

                # ── A. Blind Relay HTTP-Stream Downlink (SSE binario com X-Accel-Buffering: no) ──
                if method == "GET" and (raw_path in ("/p2p/relay_stream", "/relay_stream") or raw_path.endswith("/relay_stream")):
                    clean_pin = query_params.get("pin", "").replace("-", "").replace(" ", "").strip()
                    role = "S" if query_params.get("role", "R").upper().startswith("S") else "R"
                    if clean_pin not in self.sessions:
                        body = json.dumps({"error": "Sessao nao encontrada"}).encode("utf-8")
                        writer.write(
                            f"HTTP/1.1 404 Not Found\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("ascii")
                            + body
                        )
                        await writer.drain()
                        return
                    record = self.sessions[clean_pin]
                    sse_headers = (
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: text/event-stream; charset=utf-8\r\n"
                        "Cache-Control: no-cache, no-transform\r\n"
                        "Connection: keep-alive\r\n"
                        "Access-Control-Allow-Origin: *\r\n"
                        "X-Accel-Buffering: no\r\n\r\n"
                    ).encode("ascii")
                    writer.write(sse_headers)
                    writer.write(b": relay_connected\n\n")
                    await writer.drain()

                    my_q: asyncio.Queue = asyncio.Queue(maxsize=256)
                    q_list = record.http_sender_queues if role == "S" else record.http_receiver_queues
                    q_list.append(my_q)
                    try:
                        while not writer.is_closing() and clean_pin in self.sessions:
                            try:
                                pkt = await asyncio.wait_for(my_q.get(), timeout=10.0)
                                b64 = base64.b64encode(pkt)
                                writer.write(b"data: " + b64 + b"\n\n")
                                await writer.drain()
                            except asyncio.TimeoutError:
                                writer.write(b": ka\n\n")
                                await writer.drain()
                    except Exception:
                        pass
                    finally:
                        try:
                            q_list.remove(my_q)
                        except ValueError:
                            pass
                    return

                # ── B. Blind Relay HTTP-Stream Uplink (Keep-Alive em lotes binarios !H + pkt) ──
                if method == "POST" and (raw_path in ("/p2p/relay_push", "/relay_push") or raw_path.endswith("/relay_push")):
                    clean_pin = query_params.get("pin", "").replace("-", "").replace(" ", "").strip()
                    role = "S" if query_params.get("role", "R").upper().startswith("S") else "R"
                    if clean_pin not in self.sessions:
                        writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
                        await writer.drain()
                        return
                    record = self.sessions[clean_pin]
                    off = 0
                    total_len = len(body_bytes)
                    while off + 2 <= total_len:
                        plen = struct.unpack("!H", body_bytes[off : off + 2])[0]
                        off += 2
                        if plen == 0 or off + plen > total_len:
                            break
                        self._forward_from_http_relay(record, role, body_bytes[off : off + plen])
                        off += plen
                    keep_alive = headers.get("connection", "").lower() != "close"
                    conn_hdr = "keep-alive" if keep_alive else "close"
                    writer.write(
                        f"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: {conn_hdr}\r\n\r\nok".encode("ascii")
                    )
                    await writer.drain()
                    if keep_alive:
                        continue
                    return

                # ── C. Blind Relay WebSocket RFC 6455 (stdlib puro) ──
                if method == "GET" and (raw_path in ("/p2p/ws_relay", "/ws_relay") or raw_path.endswith("/ws_relay")):
                    clean_pin = query_params.get("pin", "").replace("-", "").replace(" ", "").strip()
                    role = "S" if query_params.get("role", "R").upper().startswith("S") else "R"
                    ws_key = headers.get("sec-websocket-key", "")
                    if clean_pin in self.sessions and ws_key:
                        await self._handle_ws_relay(reader, writer, self.sessions[clean_pin], role, ws_key)
                        return
                    writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    await writer.drain()
                    return

                body_json: dict = {}
                if body_bytes:
                    try:
                        body_json = json.loads(body_bytes.decode("utf-8"))
                    except Exception:
                        body_json = {}

                status_code = 200
                resp_data: dict = {}

                # ── 1. Health & Diagnostico Operacional ──
                if method == "GET" and (
                    raw_path in ("/health", "/status", "/", "/p2p/health", "/p2p/status", "/p2p/", "/p2p")
                    or raw_path.endswith("/health")
                    or raw_path.endswith("/status")
                ):
                    resp_data = {
                        "service": "DAV-Rendezvous",
                        "version": "3.2.0",
                        "status": "online",
                        "dualstack": True,
                        "http_relay": True,
                        "ws_relay": True,
                        "uptime_sec": int(time.time() - self.start_time),
                        "active_sessions": len(self.sessions),
                        "http_port": self.http_port,
                        "stun_port": self.stun_port,
                        "relay_port": self.stun_port,
                        "client_ip": eff_client_ip,
                    }

                # ── 2. Canal SSE de Pareamento Instantaneo ──
                elif method == "GET" and (raw_path in ("/p2p/events", "/events") or raw_path.endswith("/events")):
                    raw_pin = query_params.get("pin", "").strip()
                    clean_pin = raw_pin.replace("-", "").replace(" ", "")
                    token = query_params.get("token", "").strip()

                    if not clean_pin or clean_pin not in self.sessions:
                        status_code = 404
                        resp_data = {"error": "Sessao nao encontrada"}
                    else:
                        record = self.sessions[clean_pin]
                        if record.token != token:
                            status_code = 403
                            resp_data = {"error": "Token de sessao invalido"}
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

                            sent_idx = 0
                            t_deadline = time.time() + SESSION_TTL_SEC
                            while time.time() < t_deadline and not writer.is_closing():
                                record.last_active = time.time()
                                while sent_idx < len(record.paired_receivers):
                                    peer_dict = record.paired_receivers[sent_idx]
                                    sent_idx += 1
                                    peer_payload = {
                                        "status": "paired",
                                        "peer": peer_dict,
                                        "peer_index": sent_idx,
                                        "relay": {"host": relay_host, "port": self.stun_port},
                                    }
                                    evt_bytes = f"event: paired\ndata: {json.dumps(peer_payload)}\n\n".encode("utf-8")
                                    writer.write(evt_bytes)
                                    await writer.drain()

                                record.pair_event.clear()
                                if sent_idx < len(record.paired_receivers):
                                    continue

                                try:
                                    await asyncio.wait_for(record.pair_event.wait(), timeout=10.0)
                                except asyncio.TimeoutError:
                                    writer.write(b": keepalive\n\n")
                                    await writer.drain()
                            return

                # ── 3. Registro do No Transmissor (POST /p2p/register) ──
                elif method == "POST" and (raw_path == "/p2p/register" or raw_path.endswith("/register")):
                    raw_pin = str(body_json.get("pin", "")).strip()
                    clean_pin = raw_pin.replace("-", "").replace(" ", "")
                    node_name = str(body_json.get("node_name", "Host-Sender"))
                    local_ip = _clean_ip(str(body_json.get("local_ip") or eff_client_ip))
                    local_port = int(body_json.get("local_port", 9000))
                    public_ip = _clean_ip(str(body_json.get("public_ip") or eff_client_ip))
                    effective_pub_ip = eff_client_ip if eff_client_ip not in ("127.0.0.1", "::1") else (public_ip or eff_client_ip)
                    if public_ip and public_ip not in ("127.0.0.1", "0.0.0.0", "::1", "::") and eff_client_ip not in ("127.0.0.1", "::1"):
                        effective_pub_ip = public_ip
                    public_port = int(body_json.get("public_port") or local_port)
                    public_ipv6 = _clean_ip(str(body_json.get("public_ipv6") or "")) or None
                    public_ipv6_port = int(body_json.get("public_ipv6_port") or local_port)
                    candidates = body_json.get("candidates") if isinstance(body_json.get("candidates"), list) else []
                    nat_type = str(body_json.get("nat_type", "unknown"))

                    if not clean_pin:
                        status_code = 400
                        resp_data = {"error": "PIN obrigatorio"}
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
                            sender_public_ipv6=public_ipv6,
                            sender_public_ipv6_port=public_ipv6_port,
                        )
                        self.sessions[clean_pin] = record
                        logger.info(
                            f"Transmissor registrado [PIN {raw_pin}] -> WAN {effective_pub_ip}:{public_port} "
                            f"| LAN {local_ip}:{local_port} ({nat_type})"
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

                # ── 4. Resolucao e Pareamento do Receptor (POST /p2p/resolve) ──
                elif method == "POST" and (raw_path == "/p2p/resolve" or raw_path.endswith("/resolve")):
                    raw_pin = str(body_json.get("pin", "")).strip()
                    clean_pin = raw_pin.replace("-", "").replace(" ", "")
                    node_name = str(body_json.get("node_name", "Host-Receiver"))
                    local_ip = _clean_ip(str(body_json.get("local_ip") or eff_client_ip))
                    local_port = int(body_json.get("local_port", 9002))
                    public_ip = _clean_ip(str(body_json.get("public_ip") or eff_client_ip))
                    effective_pub_ip = eff_client_ip if eff_client_ip not in ("127.0.0.1", "::1") else (public_ip or eff_client_ip)
                    if public_ip and public_ip not in ("127.0.0.1", "0.0.0.0", "::1", "::") and eff_client_ip not in ("127.0.0.1", "::1"):
                        effective_pub_ip = public_ip
                    public_port = int(body_json.get("public_port") or local_port)
                    public_ipv6 = _clean_ip(str(body_json.get("public_ipv6") or "")) or None
                    public_ipv6_port = int(body_json.get("public_ipv6_port") or local_port)
                    candidates = body_json.get("candidates") if isinstance(body_json.get("candidates"), list) else []
                    nat_type = str(body_json.get("nat_type", "unknown"))

                    if clean_pin not in self.sessions:
                        status_code = 404
                        resp_data = {"error": "PIN nao encontrado ou sessao expirada"}
                    else:
                        record = self.sessions[clean_pin]
                        record.receiver_node = node_name
                        record.receiver_local_ip = local_ip
                        record.receiver_local_port = local_port
                        record.receiver_public_ip = effective_pub_ip
                        record.receiver_public_port = public_port
                        record.receiver_public_ipv6 = public_ipv6
                        record.receiver_public_ipv6_port = public_ipv6_port
                        record.receiver_candidates = candidates
                        record.receiver_nat_type = nat_type
                        peer_entry = self._build_receiver_peer_dict(record)
                        if len(record.paired_receivers) >= 32:
                            record.paired_receivers.pop(0)
                        record.paired_receivers.append(peer_entry)
                        record.is_paired = True
                        record.last_active = time.time()
                        record.pair_event.set()

                        logger.info(
                            f"Receptor pareado [PIN {raw_pin}] -> WAN {effective_pub_ip}:{public_port} "
                            f"| LAN {local_ip}:{local_port} ({nat_type})"
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
                        resp_data = {"error": "Sessao nao encontrada"}
                    else:
                        record = self.sessions[clean_pin]
                        if record.token != token:
                            status_code = 403
                            resp_data = {"error": "Token invalido"}
                        else:
                            record.last_active = time.time()
                            since_index = int(body_json.get("since_index", 0) or 0)
                            if record.is_paired and len(record.paired_receivers) > since_index:
                                new_peers = record.paired_receivers[since_index:]
                                resp_data = {
                                    "status": "paired",
                                    "peer": new_peers[-1],
                                    "peers": new_peers,
                                    "next_index": len(record.paired_receivers),
                                    "relay": {"host": relay_host, "port": self.stun_port},
                                }
                            elif record.is_paired and since_index == 0:
                                resp_data = {
                                    "status": "paired",
                                    "peer": self._build_receiver_peer_dict(record),
                                    "peers": [self._build_receiver_peer_dict(record)],
                                    "next_index": 1,
                                    "relay": {"host": relay_host, "port": self.stun_port},
                                }
                            else:
                                resp_data = {"status": "waiting", "next_index": len(record.paired_receivers)}

                # ── 6. Ativacao explicita de Blind Relay (POST /p2p/relay_init) ──
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
                        resp_data = {"error": "Sessao nao encontrada"}
                else:
                    status_code = 404
                    resp_data = {"error": "Endpoint nao encontrado"}

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
                return

        except Exception as exc:
            logger.debug(f"Erro ao atender cliente HTTP ({client_ip}): {exc}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def _make_dualstack_socket(self, sock_type: int, port: int) -> Optional[socket.socket]:
        if self.host not in ("0.0.0.0", "::", "") or not getattr(socket, "has_ipv6", False):
            return None
        try:
            s = socket.socket(socket.AF_INET6, sock_type)
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("::", int(port)))
            if sock_type == socket.SOCK_DGRAM:
                s.setblocking(False)
            return s
        except OSError:
            return None

    async def start(self):
        loop = asyncio.get_running_loop()

        udp_sock = self._make_dualstack_socket(socket.SOCK_DGRAM, self.stun_port)
        if udp_sock is not None:
            transport, proto = await loop.create_datagram_endpoint(
                lambda: RendezvousUdpGateway(self),
                sock=udp_sock,
            )
            logger.info(f"Gateway UDP Dual-Stack [::]:{self.stun_port}/udp ativo (STUN + Blind Relay Cross-Family)")
        else:
            transport, proto = await loop.create_datagram_endpoint(
                lambda: RendezvousUdpGateway(self),
                local_addr=(self.host, self.stun_port),
            )
            logger.info(f"Gateway UDP ativo em {self.host}:{self.stun_port}/udp")
        self._udp_gateway = proto  # type: ignore[assignment]

        tcp_sock = self._make_dualstack_socket(socket.SOCK_STREAM, self.http_port)
        if tcp_sock is not None:
            http_server = await asyncio.start_server(self.handle_http_client, sock=tcp_sock)
            logger.info(f"Servidor HTTP/SSE/Relay Dual-Stack ativo em [::]:{self.http_port}")
        else:
            http_server = await asyncio.start_server(self.handle_http_client, self.host, self.http_port)
            logger.info(f"Servidor HTTP/SSE/Relay ativo em http://{self.host}:{self.http_port}")

        try:
            async with http_server:
                await http_server.serve_forever()
        finally:
            transport.close()


def main():
    http_p = int(os.environ.get("DAV_HTTP_PORT", HTTP_PORT))
    stun_p = int(os.environ.get("DAV_STUN_PORT", STUN_PORT))
    host_bind = os.environ.get("DAV_BIND_HOST", "0.0.0.0")
    server = DavRendezvousServer(host=host_bind, http_port=http_p, stun_port=stun_p)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Servidor Rendezvous encerrado manualmente.")


if __name__ == "__main__":
    main()
