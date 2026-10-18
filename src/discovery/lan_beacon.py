#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V Advanced LAN Beacon & Peer Discovery
Provides:
1. Multi-Interface Directed Subnet Broadcast (e.g. 192.168.10.255:9005)
2. Active Subnet Sweep / Direct Unicast UDP Ping-Pong (bypasses Wi-Fi broadcast filtering)
3. Multicast Group (239.255.255.250:9005)
"""

import socket
import json
import time
import ipaddress
import threading
from typing import Dict, Callable, Optional, List, Tuple

BEACON_PORT = 9005
BEACON_MAGIC = "DAV_BEACON_V1"
PING_MAGIC = "DAV_PING"
PONG_MAGIC = "DAV_PONG"

def get_all_active_ipv4_interfaces() -> List[Tuple[str, str, str]]:
    """Returns list of (interface_name, ip_address, broadcast_address)."""
    interfaces = []
    try:
        import psutil
        for iface_name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith("127."):
                    ip = a.address
                    netmask = a.netmask or "255.255.255.0"
                    try:
                        net = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
                        broadcast = str(net.broadcast_address)
                        interfaces.append((iface_name, ip, broadcast))
                    except Exception:
                        interfaces.append((iface_name, ip, "255.255.255.255"))
    except Exception:
        # Fallback if psutil fails
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            parts = ip.split(".")
            bcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
            interfaces.append(("default", ip, bcast))
        except Exception:
            interfaces.append(("loopback", "127.0.0.1", "127.255.255.255"))
    return interfaces

def get_local_ip() -> str:
    ifaces = get_all_active_ipv4_interfaces()
    # Prioritize physical ethernet/wifi over virtualbox/hyper-v (192.168.56.x)
    for name, ip, bcast in ifaces:
        if not ip.startswith("192.168.56.") and not ip.startswith("169.254."):
            return ip
    return ifaces[0][1] if ifaces else "127.0.0.1"


class LanBeaconService:
    def __init__(self, node_name: str, stream_port: int = 9000, pin: str = "123456"):
        self.node_name = node_name
        self.stream_port = stream_port
        self.pin = pin
        self.local_ip = get_local_ip()
        self.is_sharing = False
        self.running = False
        
        self.discovered_peers: Dict[str, dict] = {} # key: f"{ip}:{port}" -> peer_info
        self._lock = threading.Lock()
        self.on_peers_updated: Optional[Callable[[list], None]] = None

        self._listen_sock: Optional[socket.socket] = None
        self._threads = []

    def start(self):
        if self.running:
            return
        self.running = True

        # Setup listener on 0.0.0.0:9005
        try:
            self._listen_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._listen_sock.bind(('0.0.0.0', BEACON_PORT))
            self._listen_sock.settimeout(0.5)
        except Exception as e:
            print(f"[Beacon] Erro ao bindar porta de escuta {BEACON_PORT}: {e}")

        t_sender = threading.Thread(target=self._broadcast_loop, daemon=True, name="Beacon-Broadcaster")
        t_receiver = threading.Thread(target=self._listen_loop, daemon=True, name="Beacon-Listener")
        t_prune = threading.Thread(target=self._prune_loop, daemon=True, name="Beacon-Pruner")

        self._threads = [t_sender, t_receiver, t_prune]
        for t in self._threads:
            t.start()

        # Initial sweep
        self.trigger_subnet_sweep()

    def stop(self):
        self.running = False
        if self._listen_sock:
            try:
                self._listen_sock.close()
            except Exception:
                pass

    def update_status(self, is_sharing: bool, pin: Optional[str] = None):
        self.is_sharing = is_sharing
        if pin is not None:
            self.pin = pin

    def trigger_subnet_sweep(self):
        """Actively sends direct UDP probes across the subnet to find peers even if broadcast is blocked."""
        t = threading.Thread(target=self._run_subnet_sweep, daemon=True, name="Subnet-Sweep")
        t.start()

    def _run_subnet_sweep(self):
        ifaces = get_all_active_ipv4_interfaces()
        payload = json.dumps({
            "magic": PING_MAGIC,
            "node_name": self.node_name,
            "ip": self.local_ip,
            "port": self.stream_port,
            "is_sharing": self.is_sharing
        }).encode('utf-8')

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        try:
            for iface_name, ip, bcast in ifaces:
                if ip.startswith("169.254.") or ip.startswith("127."):
                    continue
                # Also send to directed subnet broadcast
                try:
                    sock.sendto(payload, (bcast, BEACON_PORT))
                    sock.sendto(payload, ("255.255.255.255", BEACON_PORT))
                except Exception:
                    pass

                # Probe /24 IP range
                parts = ip.split(".")
                prefix = f"{parts[0]}.{parts[1]}.{parts[2]}."
                my_last_octet = int(parts[3])

                for octet in range(1, 255):
                    if octet == my_last_octet:
                        continue
                    target_ip = prefix + str(octet)
                    try:
                        sock.sendto(payload, (target_ip, BEACON_PORT))
                    except Exception:
                        pass
        finally:
            sock.close()

    def _broadcast_loop(self):
        while self.running:
            try:
                ifaces = get_all_active_ipv4_interfaces()
                payload = json.dumps({
                    "magic": BEACON_MAGIC,
                    "node_name": self.node_name,
                    "ip": self.local_ip,
                    "port": self.stream_port,
                    "is_sharing": self.is_sharing,
                    "timestamp": time.time()
                }).encode('utf-8')

                for iface_name, iface_ip, bcast in ifaces:
                    if iface_ip.startswith("169.254.") or iface_ip.startswith("127."):
                        continue
                    try:
                        # Specific bound socket per interface to ensure packet leaves correct NIC
                        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                        sock.bind((iface_ip, 0))
                        sock.sendto(payload, (bcast, BEACON_PORT))
                        sock.sendto(payload, ("255.255.255.255", BEACON_PORT))
                        sock.close()
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(2.0)

    def _listen_loop(self):
        while self.running:
            if not self._listen_sock:
                time.sleep(0.5)
                continue
            try:
                data, addr = self._listen_sock.recvfrom(4096)
                if not data:
                    continue
                obj = json.loads(data.decode('utf-8'))
                magic = obj.get("magic")

                if magic not in (BEACON_MAGIC, PING_MAGIC, PONG_MAGIC):
                    continue
                
                peer_ip = obj.get("ip") or addr[0]
                peer_port = obj.get("port", 9000)

                # Skip self
                all_local_ips = [a[1] for a in get_all_active_ipv4_interfaces()]
                if peer_ip in all_local_ips and peer_port == self.stream_port:
                    continue

                peer_key = f"{peer_ip}:{peer_port}"
                now = time.time()
                is_sharing = obj.get("is_sharing", False)
                node_name = obj.get("node_name", "Desconhecido")
                changed = False

                with self._lock:
                    prev = self.discovered_peers.get(peer_key)
                    if prev is None:
                        changed = True
                    elif prev.get("is_sharing") != is_sharing or prev.get("node_name") != node_name:
                        changed = True

                    self.discovered_peers[peer_key] = {
                        "node_name": node_name,
                        "ip": peer_ip,
                        "port": peer_port,
                        "is_sharing": is_sharing,
                        "last_seen": now
                    }

                if changed:
                    self._notify_update()

                # If received PING, answer back with PONG immediately
                if magic == PING_MAGIC:
                    pong_payload = json.dumps({
                        "magic": PONG_MAGIC,
                        "node_name": self.node_name,
                        "ip": self.local_ip,
                        "port": self.stream_port,
                        "is_sharing": self.is_sharing,
                        "timestamp": now
                    }).encode('utf-8')
                    try:
                        self._listen_sock.sendto(pong_payload, (addr[0], BEACON_PORT))
                    except Exception:
                        pass

            except socket.timeout:
                continue
            except Exception:
                continue

    def _prune_loop(self):
        while self.running:
            time.sleep(3.0)
            now = time.time()
            changed = False
            with self._lock:
                expired = [k for k, v in self.discovered_peers.items() if now - v["last_seen"] > 8.0]
                for k in expired:
                    del self.discovered_peers[k]
                    changed = True
            if changed:
                self._notify_update()

    def get_peers(self) -> list:
        with self._lock:
            return list(self.discovered_peers.values())

    def _notify_update(self):
        if self.on_peers_updated:
            peers = self.get_peers()
            try:
                self.on_peers_updated(peers)
            except Exception as e:
                print(f"[Beacon] Callback error: {e}")
