#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit test suite for DA-V Rendezvous & STUN Reflexive Server.
Runs the server in a background thread and exercises all endpoints via urllib and socket.
"""

import sys
import os
import time
import json
import socket
import threading
import asyncio
import urllib.request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.signaling.server.dav_rendezvous import DavRendezvousServer

TEST_HTTP_PORT = 18765
TEST_STUN_PORT = 18768


def run_server_in_thread(stop_evt):
    server = DavRendezvousServer(host="127.0.0.1", http_port=TEST_HTTP_PORT, stun_port=TEST_STUN_PORT)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def main():
        server_coro = server.start()
        server_task = asyncio.create_task(server_coro)
        while not stop_evt.is_set():
            await asyncio.sleep(0.1)
        server_task.cancel()

    try:
        loop.run_until_complete(main())
    except asyncio.CancelledError:
        pass
    finally:
        loop.close()


def test_rendezvous():
    stop_evt = threading.Event()
    th = threading.Thread(target=run_server_in_thread, args=(stop_evt,), daemon=True)
    th.start()
    time.sleep(0.6)  # Give server time to bind

    base_url = f"http://127.0.0.1:{TEST_HTTP_PORT}"

    try:
        # 1. Test /health
        print("[1/5] Testing GET /health ...")
        with urllib.request.urlopen(f"{base_url}/health", timeout=3) as resp:
            data = json.loads(resp.read().decode())
            assert data["status"] == "online"
            assert data["service"] == "DAV-Rendezvous"
            print("  [OK] Healthcheck PASSED")

        # 2. Test /p2p/register (Sender)
        print("[2/5] Testing POST /p2p/register ...")
        reg_payload = json.dumps({
            "pin": "777-888",
            "node_name": "Host-Sender",
            "local_ip": "192.168.10.104",
            "local_port": 9000
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/p2p/register",
            data=reg_payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            reg_res = json.loads(resp.read().decode())
            assert reg_res["status"] == "registered"
            assert reg_res["pin"] == "777-888"
            sender_token = reg_res["token"]
            print("  [OK] Register PASSED")

        # 3. Test /p2p/resolve (Receiver)
        print("[3/5] Testing POST /p2p/resolve ...")
        resolve_payload = json.dumps({
            "pin": "777-888",
            "node_name": "Host-Receiver",
            "local_ip": "192.168.10.102",
            "local_port": 9002
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/p2p/resolve",
            data=resolve_payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            resolve_res = json.loads(resp.read().decode())
            assert resolve_res["status"] == "paired"
            assert resolve_res["peer"]["node_name"] == "Host-Sender"
            assert resolve_res["peer"]["local_port"] == 9000
            print("  [OK] Resolve & Pairing PASSED")

        # 4. Test /p2p/poll (Sender receives Receiver data)
        print("[4/5] Testing POST /p2p/poll ...")
        poll_payload = json.dumps({
            "pin": "777-888",
            "token": sender_token
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/p2p/poll",
            data=poll_payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            poll_res = json.loads(resp.read().decode())
            assert poll_res["status"] == "paired"
            assert poll_res["peer"]["node_name"] == "Host-Receiver"
            assert poll_res["peer"]["local_port"] == 9002
            print("  [OK] Sender Polling PASSED")

        # 5. Test UDP STUN Probe
        print("[5/5] Testing UDP STUN Reflexive Socket ...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)
        sock.sendto(b"DAV_STUN_REQ", ("127.0.0.1", TEST_STUN_PORT))
        raw, _ = sock.recvfrom(1024)
        stun_res = json.loads(raw.decode("utf-8"))
        assert stun_res["status"] == "ok"
        assert "reflexive_ip" in stun_res
        assert "reflexive_port" in stun_res
        sock.close()
        print(f"  [OK] STUN Reflexive PASSED -> {stun_res['reflexive_ip']}:{stun_res['reflexive_port']}")

        print("\n=======================================================")
        print("  TODOS OS 5 TESTES DO RENDEZVOUS APROVADOS (100% OK!)")
        print("=======================================================")

    finally:
        stop_evt.set()


if __name__ == "__main__":
    test_rendezvous()
