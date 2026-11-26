# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# -*- coding: utf-8 -*-
"""
Primitivos Canonicos Dual-Stack IPv4/IPv6 e Sintese NAT64 (RFC 7050) — DA-V v5.2
Autor: Dante Ferraz (MonoTech)

Centraliza a compatibilidade transparente entre redes IPv4, Dual-Stack e IPv6-Only:
1. Socket UDP unico `AF_INET6` com `IPV6_V6ONLY = 0` vinculado em `("::", porta)` (com
   fallback automatico para `AF_INET` em kernels sem IPv6);
2. Mapeamento automatico `IPv4 -> ::ffff:x.x.x.x` em `sendto()` no Winsock/Linux e
   normalizacao `normalize_recv_addr()` removendo `::ffff:` para comparacoes estaveis;
3. Parser/Formatador RFC 3986 (`[2804:...]:9000` vs `192.168.1.1:9000`), resolucao DNS
   `AF_UNSPEC` (`A` + `AAAA`) e ajuste seguro de MTU (`1180 B` em IPv6 <= `1280 B` RFC 8200);
4. Descoberta automatica de prefixo NAT64 (RFC 7050 via `ipv4only.arpa`) para hosts
   IPv6-Only alcancarem endpoints literais IPv4 quando a operadora fornece NAT64.
"""

from __future__ import annotations

import ipaddress
import socket
import struct
import sys
import threading
import time
from typing import List, Optional, Tuple

IPV4_DEFAULT_MTU = 1300
IPV6_SAFE_MTU = 1180

_NAT64_CACHE_LOCK = threading.Lock()
_NAT64_PREFIX_CACHE: Optional[Tuple[Optional[bytes], float]] = None
_NAT64_CACHE_TTL = 120.0


def disable_win_udp_connreset(sock: socket.socket) -> None:
    """Desativa WSAECONNRESET (WinError 10054) no Windows para evitar quebrar o loop UDP."""
    if sys.platform == "win32" and hasattr(sock, "ioctl"):
        try:
            sock.ioctl(0x9800000C, False)
        except Exception:
            pass


def strip_ip_brackets(ip_str: str) -> str:
    """Remove colchetes RFC 3986 `[...]` e espacos ao redor de um endereco IP."""
    s = str(ip_str or "").strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1].strip()
    return s


def strip_ipv6_zone(ip_str: str) -> Tuple[str, Optional[str]]:
    """Separa eventual sufixo de zona `%eth0` / `%12` de um literal IPv6."""
    clean = strip_ip_brackets(ip_str)
    if "%" in clean:
        base, zone = clean.split("%", 1)
        return base.strip(), zone.strip() or None
    return clean, None


def canonicalize_ip(ip_str: str) -> str:
    """Normaliza IPv4, IPv4-mapped (`::ffff:x.x.x.x`) ou IPv6 para forma canonica comprimida."""
    base, zone = strip_ipv6_zone(ip_str)
    if not base:
        return ""
    try:
        addr = ipaddress.ip_address(base)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        res = str(addr)
        if zone and isinstance(addr, ipaddress.IPv6Address) and addr.is_link_local:
            return f"{res}%{zone}"
        return res
    except ValueError:
        return base


def is_valid_ip(ip_str: str) -> bool:
    """Retorna True se `ip_str` for um literal IPv4 ou IPv6 valido (aceita `[ipv6]` e `%zone`)."""
    base, _ = strip_ipv6_zone(ip_str)
    if not base:
        return False
    try:
        ipaddress.ip_address(base)
        return True
    except ValueError:
        return False


def is_ipv6_address(ip_str: str) -> bool:
    """Retorna True se o literal for IPv6 nativo (nao IPv4-mapped `::ffff:`)."""
    base, _ = strip_ipv6_zone(ip_str)
    if not base or ":" not in base:
        return False
    try:
        addr = ipaddress.ip_address(base)
        return isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is None
    except ValueError:
        return False


def is_global_ipv6(ip_str: str) -> bool:
    """Retorna True para IPv6 Global Unicast roteavel na internet (`2000::/3`, excluindo Teredo/6to4)."""
    base, _ = strip_ipv6_zone(ip_str)
    if not base or ":" not in base:
        return False
    try:
        addr = ipaddress.ip_address(base)
        if not isinstance(addr, ipaddress.IPv6Address) or addr.ipv4_mapped is not None:
            return False
        if not addr.is_global or addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast:
            return False
        # Exclui Teredo (2001::/32) e 6to4 legado (2002::/16) que degradam latencia
        if addr in ipaddress.IPv6Network("2001:0000::/32") or addr in ipaddress.IPv6Network("2002::/16"):
            return False
        return True
    except ValueError:
        return False


def is_lan_or_local_address(ip_str: str) -> bool:
    """Verifica se um IPv4 ou IPv6 pertence a LAN privada (RFC1918 / ULA fc00::/7), Link-Local ou Loopback."""
    base, _ = strip_ipv6_zone(ip_str)
    if not base:
        return False
    try:
        addr = ipaddress.ip_address(base)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        if isinstance(addr, ipaddress.IPv4Address):
            # Exclui CGNAT/Tailscale 100.64.0.0/10 da categoria LAN fisica
            if addr in ipaddress.IPv4Network("100.64.0.0/10"):
                return False
            return bool(addr.is_private or addr.is_loopback or addr.is_link_local)
        # IPv6: exclui Tailscale fd7a:115c:a1e0::/48 da categoria LAN fisica
        if addr in ipaddress.IPv6Network("fd7a:115c:a1e0::/48"):
            return False
        return bool(addr.is_private or addr.is_loopback or addr.is_link_local)
    except ValueError:
        return False


def is_overlay_address(ip_str: str) -> bool:
    """Identifica enderecos de VPN overlay (Tailscale IPv4 100.64/10 ou IPv6 fd7a:115c:a1e0::/48)."""
    base, _ = strip_ipv6_zone(ip_str)
    if not base:
        return False
    try:
        addr = ipaddress.ip_address(base)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        if isinstance(addr, ipaddress.IPv4Address):
            return addr in ipaddress.IPv4Network("100.64.0.0/10")
        return addr in ipaddress.IPv6Network("fd7a:115c:a1e0::/48")
    except ValueError:
        return False


def format_endpoint_display(ip_str: str, port: int) -> str:
    """Formata endpoint para exibicao/URI seguindo RFC 3986 (`[ipv6]:porta` ou `ipv4:porta`)."""
    clean = canonicalize_ip(ip_str)
    if is_ipv6_address(clean):
        return f"[{clean}]:{int(port)}"
    return f"{clean}:{int(port)}"


def format_url_host(host: str) -> str:
    """Envolve literais IPv6 em colchetes para uso seguro em URLs `http://[...]:porta`."""
    clean = strip_ip_brackets(host)
    if is_ipv6_address(clean):
        return f"[{clean}]"
    return clean


def parse_host_port(text: str) -> Tuple[str, Optional[int]]:
    """
    Faz parsing de `[ipv6]:porta`, `[ipv6]`, `ipv6`, `ipv4:porta`, `ipv4`, `host:porta` ou `host`.
    Retorna `(host_ou_ip_limpo, porta_ou_None)`.
    """
    s = str(text or "").strip()
    if not s:
        return "", None

    # 1. Formato RFC 3986 com colchetes: [2804:...]:9000 ou [2804:...]
    if s.startswith("["):
        end_br = s.find("]")
        if end_br > 1:
            inner = s[1:end_br].strip()
            rest = s[end_br + 1 :].strip()
            port: Optional[int] = None
            if rest.startswith(":"):
                p_str = rest[1:].strip()
                if p_str.isdigit():
                    p_val = int(p_str)
                    if 1 <= p_val <= 65535:
                        port = p_val
            return canonicalize_ip(inner) if is_valid_ip(inner) else inner, port

    # 2. Literal IPv6 puro sem colchetes (sempre tem >= 2 dois-pontos)
    if s.count(":") >= 2 and is_valid_ip(s):
        return canonicalize_ip(s), None

    # 3. IPv4:porta ou hostname:porta (exatamente 1 dois-pontos)
    if s.count(":") == 1:
        host_part, port_part = s.rsplit(":", 1)
        host_part = host_part.strip()
        port_part = port_part.strip()
        if port_part.isdigit():
            p_val = int(port_part)
            if 1 <= p_val <= 65535:
                return (canonicalize_ip(host_part) if is_valid_ip(host_part) else host_part), p_val
        return host_part, None

    return (canonicalize_ip(s) if is_valid_ip(s) else s), None


def effective_mtu_for_ip(ip_str: str) -> int:
    """Retorna payload MTU seguro (`1180 B` para IPv6 <= `1280 B` RFC 8200; `1300 B` para IPv4)."""
    return IPV6_SAFE_MTU if is_ipv6_address(ip_str) else IPV4_DEFAULT_MTU


def create_dualstack_udp_socket(
    bind_port: int = 0,
    rcvbuf_mb: int = 32,
    sndbuf_mb: int = 8,
    prefer_dualstack: bool = True,
) -> socket.socket:
    """
    Cria e vincula um socket UDP Dual-Stack (`AF_INET6` + `IPV6_V6ONLY=0` em `::`),
    aceitando trafego IPv6 nativo e IPv4 mapeado no mesmo descritor.
    Faz fallback transparente para `AF_INET` (`0.0.0.0`) se o kernel nao suportar IPv6.
    """
    sock: Optional[socket.socket] = None
    if prefer_dualstack and getattr(socket, "has_ipv6", False):
        try:
            s6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s6.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf_mb * 1024 * 1024)
                s6.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, sndbuf_mb * 1024 * 1024)
            except OSError:
                pass
            try:
                s6.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0xB8)
            except OSError:
                pass
            if hasattr(socket, "IPV6_TCLASS"):
                try:
                    s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_TCLASS, 0xB8)
                except OSError:
                    pass
            if hasattr(socket, "SO_PRIORITY"):
                try:
                    s6.setsockopt(socket.SOL_SOCKET, socket.SO_PRIORITY, 6)
                except OSError:
                    pass
            disable_win_udp_connreset(s6)
            try:
                s6.bind(("::", int(bind_port)))
            except OSError:
                s6.bind(("::", 0))
            sock = s6
        except OSError:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
            sock = None

    if sock is None:
        s4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s4.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf_mb * 1024 * 1024)
            s4.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, sndbuf_mb * 1024 * 1024)
        except OSError:
            pass
        try:
            s4.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0xB8)
        except OSError:
            pass
        if hasattr(socket, "SO_PRIORITY"):
            try:
                s4.setsockopt(socket.SOL_SOCKET, socket.SO_PRIORITY, 6)
            except OSError:
                pass
        disable_win_udp_connreset(s4)
        try:
            s4.bind(("0.0.0.0", int(bind_port)))
        except OSError:
            s4.bind(("0.0.0.0", 0))
        sock = s4

    return sock


def format_sendto_addr(sock: socket.socket, host_or_ip: str, port: int) -> Optional[Tuple]:
    """
    Converte `(host_or_ip, port)` na tupla aceita por `sock.sendto()` de acordo com `sock.family`.
    Em sockets `AF_INET6` (`IPV6_V6ONLY=0`), mapeia IPv4 para `::ffff:x.x.x.x` evitando
    `gaierror(11001)` no Windows Winsock.
    """
    if not host_or_ip:
        return None
    p_int = int(port)
    if p_int <= 0 or p_int > 65535:
        return None

    base, zone = strip_ipv6_zone(host_or_ip)
    if not base:
        return None

    is_v6_sock = sock.family == socket.AF_INET6

    try:
        ip_obj = ipaddress.ip_address(base)
        if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped is not None:
            ip_obj = ip_obj.ipv4_mapped

        if isinstance(ip_obj, ipaddress.IPv4Address):
            if is_v6_sock:
                return (f"::ffff:{ip_obj}", p_int, 0, 0)
            return (str(ip_obj), p_int)

        # IPv6 nativo
        if not is_v6_sock:
            return None
        scope_id = 0
        if zone:
            if zone.isdigit():
                scope_id = int(zone)
            elif hasattr(socket, "if_nametoindex"):
                try:
                    scope_id = int(socket.if_nametoindex(zone))
                except OSError:
                    scope_id = 0
        return (str(ip_obj), p_int, 0, scope_id)
    except ValueError:
        # Hostname DNS: resolve usando getaddrinfo respeitando familia do socket
        try:
            infos = socket.getaddrinfo(base, p_int, socket.AF_UNSPEC, socket.SOCK_DGRAM)
            if is_v6_sock:
                for fam, _, _, _, sockaddr in infos:
                    if fam == socket.AF_INET6:
                        return sockaddr
                for fam, _, _, _, sockaddr in infos:
                    if fam == socket.AF_INET:
                        return (f"::ffff:{sockaddr[0]}", int(sockaddr[1]), 0, 0)
            else:
                for fam, _, _, _, sockaddr in infos:
                    if fam == socket.AF_INET:
                        return (str(sockaddr[0]), int(sockaddr[1]))
        except OSError:
            return None
    return None


def sendto_dualstack(sock: socket.socket, data: bytes, host_or_ip: str, port: int) -> bool:
    """Envia datagrama UDP abstraindo automaticamente mapeamento Dual-Stack IPv4/IPv6."""
    dst = format_sendto_addr(sock, host_or_ip, port)
    if dst is None:
        return False
    try:
        sock.sendto(data, dst)
        return True
    except OSError:
        return False


def normalize_recv_addr(raw_addr: Tuple) -> Tuple[str, int]:
    """Normaliza qualquer tupla retornada por `recvfrom()` (2-tupla ou 4-tupla) para `(ip_canonico, port)`."""
    if not raw_addr or len(raw_addr) < 2:
        return ("", 0)
    ip_s = canonicalize_ip(str(raw_addr[0]))
    return (ip_s, int(raw_addr[1]))


def resolve_host_dualstack(host: str, prefer_ipv6: bool = False) -> Optional[str]:
    """Resolve hostname DNS aceitando tanto registros `A` (IPv4) quanto `AAAA` (IPv6)."""
    clean = strip_ip_brackets(host)
    if not clean:
        return None
    if is_valid_ip(clean):
        return canonicalize_ip(clean)
    try:
        infos = socket.getaddrinfo(clean, None, socket.AF_UNSPEC, socket.SOCK_DGRAM)
    except OSError:
        return None
    v4_list: List[str] = []
    v6_list: List[str] = []
    for fam, _, _, _, sockaddr in infos:
        ip_c = canonicalize_ip(str(sockaddr[0]))
        if fam == socket.AF_INET6 and ip_c not in v6_list:
            v6_list.append(ip_c)
        elif fam == socket.AF_INET and ip_c not in v4_list:
            v4_list.append(ip_c)
    order = (v6_list + v4_list) if prefer_ipv6 else (v4_list + v6_list)
    return order[0] if order else None


def get_local_ipv6() -> Optional[str]:
    """Descobre o endereco IPv6 Global Unicast preferencial da maquina sem enviar trafego."""
    if not getattr(socket, "has_ipv6", False):
        return None
    for probe_ip in ("2606:4700:4700::1111", "2001:4860:4860::8888"):
        try:
            with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as s6:
                s6.connect((probe_ip, 80))
                cand = canonicalize_ip(s6.getsockname()[0])
                if is_global_ipv6(cand):
                    return cand
        except OSError:
            continue
    return None


def discover_nat64_prefix(force_refresh: bool = False) -> Optional[bytes]:
    """
    Descobre o prefixo NAT64 de 12 bytes da rede via RFC 7050 (`ipv4only.arpa`).
    Retorna `bytes(12)` (ex.: `64:ff9b::/96`) ou `None` se a rede nao possuir DNS64/NAT64.
    """
    global _NAT64_PREFIX_CACHE
    now = time.monotonic()
    with _NAT64_CACHE_LOCK:
        if not force_refresh and _NAT64_PREFIX_CACHE is not None:
            cached_prefix, ts = _NAT64_PREFIX_CACHE
            if (now - ts) < _NAT64_CACHE_TTL:
                return cached_prefix

    prefix: Optional[bytes] = None
    try:
        infos = socket.getaddrinfo("ipv4only.arpa", 80, socket.AF_INET6, socket.SOCK_STREAM)
        for _, _, _, _, sockaddr in infos:
            addr6 = ipaddress.IPv6Address(strip_ipv6_zone(sockaddr[0])[0])
            packed = addr6.packed
            # RFC 7050 well-known IPv4 suffixes: 192.0.0.170 (c00000aa) ou 192.0.0.171 (c00000ab)
            tail = packed[12:16]
            if tail in (b"\xc0\x00\x00\xaa", b"\xc0\x00\x00\xab"):
                prefix = packed[:12]
                break
    except OSError:
        prefix = None

    with _NAT64_CACHE_LOCK:
        _NAT64_PREFIX_CACHE = (prefix, now)
    return prefix


def synthesize_nat64_ipv6(ipv4_str: str, prefix_12b: Optional[bytes] = None) -> Optional[str]:
    """Sintetiza um endereco IPv6 NAT64 (`[prefix96][ipv4_32]`) a partir de um literal IPv4."""
    try:
        v4 = ipaddress.IPv4Address(strip_ip_brackets(ipv4_str))
    except ValueError:
        return None
    pref = prefix_12b if (prefix_12b is not None and len(prefix_12b) == 12) else discover_nat64_prefix()
    if pref is None or len(pref) != 12:
        return None
    addr6 = ipaddress.IPv6Address(pref + v4.packed)
    return str(addr6)
