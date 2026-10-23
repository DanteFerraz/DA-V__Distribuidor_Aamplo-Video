#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
End-to-end integration test for DA-V P2P connection.
Exercises:
1. DavRendezvousServer initialization.
2. P2PChannelClient for Sender registering PIN.
3. P2PChannelClient for Receiver resolving PIN.
4. Simultaneous UDP hole punching handshake (SYN/ACK).
5. Verification of active direct P2P data path.
"""

import sys
import os
import time
import json
import socket
import threading
import asyncio

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.signaling.server.dav_rendezvous import DavRendezvousServer
from src.discovery.p2p_channel import P2PChannelClient

TEST_HTTP = 19765
TEST_STUN = 19768


def run_test_server(stop_evt):
    server = DavRendezvousServer(host="127.0.0.1", http_port=TEST_HTTP, stun_port=TEST_STUN)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def main():
        server_coro = server.start()
        task = asyncio.create_task(server_coro)
        while not stop_evt.is_set():
            await asyncio.sleep(0.1)
        task.cancel()

    try:
        loop.run_until_complete(main())
    except asyncio.CancelledError:
        pass
    finally:
        loop.close()


def test_p2p_e2e():
    print("=======================================================")
    print("  TESTE E2E: CONEXAO P2P COM HOLE-PUNCHING E RENDEZVOUS")
    print("=======================================================")

    stop_evt = threading.Event()
    th = threading.Thread(target=run_test_server, args=(stop_evt,), daemon=True)
    th.start()
    time.sleep(0.5)

    sender_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender_sock.bind(("127.0.0.1", 19000))

    receiver_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver_sock.bind(("127.0.0.1", 19002))

    try:
        sender_client = P2PChannelClient(rendezvous_host="127.0.0.1", http_port=TEST_HTTP, stun_port=TEST_STUN)
        receiver_client = P2PChannelClient(rendezvous_host="127.0.0.1", http_port=TEST_HTTP, stun_port=TEST_STUN)

        paired_peer = {}

        def on_paired(peer_info):
            paired_peer.update(peer_info)

        # 1. Sender registers PIN
        print("[1/4] Sender registrando PIN '555-444' no Rendezvous ...")
        reg = sender_client.register_as_sender("555-444", 19000, "Node-Sender", on_paired_callback=on_paired)
        assert reg and reg["status"] == "registered"
        print("  [OK] PIN registrado com sucesso")

        # 2. Receiver resolves PIN
        print("[2/4] Receiver consultando PIN '555-444' ...")
        res = receiver_client.resolve_receiver_target("555-444", 19002, "Node-Receiver")
        assert res and res["status"] == "paired"
        sender_target = res["peer"]
        print(f"  [OK] Pareamento encontrado: {sender_target['node_name']} em {sender_target['local_ip']}:{sender_target['local_port']}")

        # 3. Simulate UDP Hole-Punching
        print("[3/4] Disparando Hole-Punching simultaneo entre sockets ...")
        results = {}

        def _punch_sender():
            # Wait a moment for sender to get peer info via poller or resolve
            time.sleep(0.2)
            # Receiver endpoint
            rec_peer = {"local_ip": "127.0.0.1", "local_port": 19002}
            tip, tport, mode = sender_client.punch_hole(sender_sock, rec_peer, timeout_sec=2.0)
            results["sender_target"] = (tip, tport, mode)

        def _punch_receiver():
            tip, tport, mode = receiver_client.punch_hole(receiver_sock, sender_target, timeout_sec=2.0)
            results["receiver_target"] = (tip, tport, mode)

        t_s = threading.Thread(target=_punch_sender)
        t_r = threading.Thread(target=_punch_receiver)
        t_s.start()
        t_r.start()
        t_s.join()
        t_r.join()

        assert "sender_target" in results
        assert "receiver_target" in results
        print(f"  [OK] Hole-Punching concluido com sucesso!")
        print(f"       Sender conectou em: {results['sender_target']}")
        print(f"       Receiver conectou em: {results['receiver_target']}")

        # 4. Transmit data packet over P2P tunnel
        print("[4/4] Testando envio de dados pelo tunel P2P aberto ...")
        sender_sock.sendto(b"DAV_FRAME_DATA_CHUNK_60FPS", ("127.0.0.1", 19002))
        
        receiver_sock.settimeout(0.5)
        received_frame = False
        t_end = time.time() + 3.0
        while time.time() < t_end:
            try:
                data, addr = receiver_sock.recvfrom(1024)
                print(f"       Pacote no receiver: {data} de {addr}")
                if data == b"DAV_FRAME_DATA_CHUNK_60FPS":
                    received_frame = True
                    break
            except (socket.timeout, ConnectionResetError):
                continue

        assert received_frame, "Quadro de video nao recebido pelo tunel P2P"
        print(f"  [OK] Pacote de video recebido via P2P de {addr}!")

        print("\n=======================================================")
        print("  CONEXAO P2P 100% FUNCIONAL E APROVADA!")
        print("=======================================================")

    finally:
        sender_sock.close()
        receiver_sock.close()
        stop_evt.set()


if __name__ == "__main__":
    test_p2p_e2e()
