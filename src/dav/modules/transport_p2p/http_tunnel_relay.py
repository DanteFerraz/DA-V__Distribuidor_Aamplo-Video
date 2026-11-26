# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Blind Encrypted HTTP-Stream Tunnel Relay (Porta 80/443, Stdlib Puro) — DA-V v5.2
Autor: Dante Ferraz (MonoTech)

Fallback automatico para redes institucionais (universidades/empresas) que bloqueiam UDP
externo (incluindo porta 8768) ou quando um peer esta em IPv4-only e o outro em IPv6-only:
- Downlink: stream HTTP SSE persistente (`GET /p2p/relay_stream?pin=...&role=S|R`) com
  `X-Accel-Buffering: no`, atravessando Nginx e proxies corporativos sem exigir Upgrade WS;
- Uplink: conexao HTTP keep-alive com `TCP_NODELAY` (`POST /p2p/relay_push?pin=...&role=S|R`)
  despachando lotes binarios (`!H` + datagrama) dos mesmos pacotes ChaCha20-Poly1305 E2E.
"""

from __future__ import annotations

import base64
import collections
import http.client
import logging
import socket
import struct
import threading
import time
import urllib.parse
import urllib.request
from typing import Callable, Deque, Optional

from src.dav.modules.transport_p2p.blind_relay import normalize_pin
from src.dav.modules.transport_p2p.dualstack import (
    format_url_host,
    is_ipv6_address,
    synthesize_nat64_ipv6,
)

logger = logging.getLogger("DAV.Transport.HttpRelay")


class HttpTunnelRelayClient:
    """Cliente leve bidirecional de Blind Relay cifrado ponta a ponta sobre HTTP/HTTPS."""

    def __init__(
        self,
        base_url: str,
        pin: str,
        role: str,
        on_packet_rx: Callable[[bytes], None],
        on_connected: Optional[Callable[[], None]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.clean_pin = normalize_pin(pin)
        self.role = "S" if str(role).upper().startswith("S") else "R"
        self._on_packet_rx = on_packet_rx
        self._on_connected = on_connected

        self._running = False
        self._connected = False
        self._tx_queue: Deque[bytes] = collections.deque(maxlen=256)
        self._tx_cond = threading.Condition()
        self._rx_thread: Optional[threading.Thread] = None
        self._tx_thread: Optional[threading.Thread] = None
        self._active_base_url = self.base_url
        self._host_header: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._rx_thread = threading.Thread(
            target=self._rx_loop, daemon=True, name=f"DAV-HttpRelay-RX-{self.role}"
        )
        self._tx_thread = threading.Thread(
            target=self._tx_loop, daemon=True, name=f"DAV-HttpRelay-TX-{self.role}"
        )
        self._rx_thread.start()
        self._tx_thread.start()

    def stop(self) -> None:
        self._running = False
        self._connected = False
        with self._tx_cond:
            self._tx_cond.notify_all()
        if self._tx_thread and self._tx_thread.is_alive():
            self._tx_thread.join(timeout=0.35)
        if self._rx_thread and self._rx_thread.is_alive():
            self._rx_thread.join(timeout=0.35)

    def send_datagram(self, pkt: bytes) -> bool:
        if not self._running or not pkt or len(pkt) > 65500:
            return False
        with self._tx_cond:
            self._tx_queue.append(pkt)
            self._tx_cond.notify()
        return True

    def _resolve_urls(self) -> list[tuple[str, Optional[str]]]:
        urls: list[tuple[str, Optional[str]]] = [(self._active_base_url, self._host_header)]
        if self.base_url != self._active_base_url:
            urls.append((self.base_url, None))
        parsed = urllib.parse.urlparse(self.base_url)
        host = (parsed.hostname or "").strip()
        if host and not is_ipv6_address(host) and host not in ("127.0.0.1", "localhost"):
            nat64 = synthesize_nat64_ipv6(host)
            if nat64:
                scheme = parsed.scheme or "http"
                port_part = f":{parsed.port}" if parsed.port else ""
                n64_url = f"{scheme}://{format_url_host(nat64)}{port_part}"
                if not any(u == n64_url for u, _ in urls):
                    urls.append((n64_url, host))
        return urls

    def _rx_loop(self) -> None:
        path = f"/p2p/relay_stream?pin={self.clean_pin}&role={self.role}"
        while self._running:
            opened = False
            for b_url, host_hdr in self._resolve_urls():
                if not self._running:
                    return
                headers = {"Accept": "text/event-stream", "Cache-Control": "no-cache"}
                if host_hdr:
                    headers["Host"] = host_hdr
                req = urllib.request.Request(f"{b_url}{path}", headers=headers)
                try:
                    with urllib.request.urlopen(req, timeout=15.0) as resp:
                        self._active_base_url = b_url
                        self._host_header = host_hdr
                        opened = True
                        was_conn = self._connected
                        self._connected = True
                        if not was_conn and self._on_connected is not None:
                            try:
                                self._on_connected()
                            except Exception:
                                pass
                        for raw_line in resp:
                            if not self._running:
                                return
                            line = raw_line.strip()
                            if line.startswith(b"data:"):
                                b64_part = line[5:].strip()
                                if not b64_part:
                                    continue
                                try:
                                    pkt = base64.b64decode(b64_part)
                                    if pkt:
                                        self._on_packet_rx(pkt)
                                except Exception:
                                    continue
                except Exception as exc:
                    logger.debug(f"[HttpRelay-RX] Reconectando stream ({exc})")
                    continue
                if opened:
                    break
            self._connected = False
            if self._running:
                time.sleep(0.35)

    def _open_tx_conn(self) -> Optional[http.client.HTTPConnection]:
        parsed = urllib.parse.urlparse(self._active_base_url)
        host = parsed.hostname or "127.0.0.1"
        is_https = parsed.scheme.lower() == "https"
        port = parsed.port or (443 if is_https else 80)
        try:
            conn: http.client.HTTPConnection = (
                http.client.HTTPSConnection(host, port, timeout=4.0)
                if is_https
                else http.client.HTTPConnection(host, port, timeout=4.0)
            )
            conn.connect()
            if conn.sock is not None:
                try:
                    conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError:
                    pass
            return conn
        except Exception:
            return None

    def _tx_loop(self) -> None:
        push_path = f"/p2p/relay_push?pin={self.clean_pin}&role={self.role}"
        conn: Optional[http.client.HTTPConnection] = None

        while self._running:
            batch: list[bytes] = []
            batch_bytes = 0
            with self._tx_cond:
                if not self._tx_queue:
                    self._tx_cond.wait(timeout=0.05)
                while self._tx_queue and batch_bytes < 48000 and len(batch) < 32:
                    item = self._tx_queue.popleft()
                    batch.append(item)
                    batch_bytes += len(item) + 2

            if not batch:
                continue

            # Empacota lote binario [!H len][pkt]
            wire = b"".join(struct.pack("!H", len(p)) + p for p in batch)
            headers = {
                "Content-Type": "application/octet-stream",
                "Connection": "keep-alive",
            }
            if self._host_header:
                headers["Host"] = self._host_header

            for attempt in range(2):
                if conn is None:
                    conn = self._open_tx_conn()
                if conn is None:
                    break
                try:
                    conn.request("POST", push_path, body=wire, headers=headers)
                    resp = conn.getresponse()
                    resp.read()
                    if resp.status == 200:
                        break
                    conn.close()
                    conn = None
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = None
                    if attempt == 0:
                        continue
            else:
                time.sleep(0.05)

        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
