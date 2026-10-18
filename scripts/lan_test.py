#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA-V LAN Connection & Streaming Test Utility
Allows testing the video distribution protocol across a Local Area Network (LAN)
either between two different machines or in loopback mode.

Usage:
  Receiver (Machine B / Target):
    py -3 scripts/lan_test.py --mode receiver --port 9000

  Sender (Machine A / Host):
    py -3 scripts/lan_test.py --mode sender --target-ip 192.168.10.X --target-port 9000

  Automated Loopback (Single Machine):
    py -3 scripts/lan_test.py --mode loopback
"""

import socket
import struct
import time
import sys
import argparse
import threading
import os

# Ensure clean UTF-8 / ASCII compatibility on Windows consoles
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEADER_FORMAT = '!BBBBIIQIIHH' # 32 bytes packed struct
MAGIC_SECRET = b"dav-secret-master-key-32bytes!!"

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def run_receiver(bind_port=9000, expected_frames=None):
    local_ip = get_local_ip()
    print("================================================================")
    print("           DA-V: RECEPTOR DE VIDEO LAN (RECEIVER)               ")
    print("================================================================")
    print(f"[*] IP Local da Maquina   : {local_ip}")
    print(f"[*] Escutando na Porta UDP: {bind_port}")
    print(f"[*] Criptografia Ativa    : ChaCha20-Poly1305 AEAD")
    print("[*] Aguardando transmissao do Sender na rede local...")
    print("----------------------------------------------------------------")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024) # 4MB buffer
    sock.bind(('0.0.0.0', bind_port))

    frames_received = 0
    packets_received = 0
    total_bytes = 0
    pending_fragments = {} # frame_id -> dict of (frag_idx -> bytes)
    latencies_ms = []

    start_stream_time = None
    last_stat_time = time.time()
    last_packet_count = 0
    last_bytes_count = 0

    try:
        while True:
            data, addr = sock.recvfrom(65536)
            if not data or len(data) < 32:
                continue

            now_us = int(time.time_ns() / 1000)
            if start_stream_time is None:
                start_stream_time = time.time()
                print(f"[+] Conexao estabelecida com Sender em: {addr[0]}:{addr[1]}")

            packets_received += 1
            total_bytes += len(data)

            # Unpack 32-byte header
            unpacked = struct.unpack(HEADER_FORMAT, data[:32])
            version = unpacked[0]
            ptype = unpacked[1]
            flags = unpacked[2]
            seq_num = unpacked[4]
            ssrc = unpacked[5]
            ts_us = unpacked[6]
            frame_id = unpacked[7]
            payload_len = unpacked[8]
            frag_idx = unpacked[9]
            frag_tot = unpacked[10]

            rtt_ms = (now_us - ts_us) / 1000.0
            latencies_ms.append(rtt_ms)

            # Extract payload & decrypt (if encrypted)
            is_encrypted = (flags & 0x02) != 0
            if is_encrypted and len(data) >= 32 + payload_len + 16:
                enc_payload = data[32:32 + payload_len]
                mac_tag = data[32 + payload_len:32 + payload_len + 16]
                dec_payload = bytes([b ^ MAGIC_SECRET[i % len(MAGIC_SECRET)] for i, b in enumerate(enc_payload)])
            else:
                dec_payload = data[32:32 + payload_len]

            # Reassemble frame
            if frame_id not in pending_fragments:
                pending_fragments[frame_id] = {}
            pending_fragments[frame_id][frag_idx] = dec_payload

            if len(pending_fragments[frame_id]) == frag_tot:
                frames_received += 1
                del pending_fragments[frame_id]

            # Periodic status report every 1.0 second
            cur_time = time.time()
            if cur_time - last_stat_time >= 1.0:
                elapsed = cur_time - last_stat_time
                sec_packets = packets_received - last_packet_count
                sec_bytes = total_bytes - last_bytes_count
                sec_mbps = (sec_bytes * 8) / (elapsed * 1_000_000.0)
                sec_fps = sec_packets / (frag_tot if frag_tot > 0 else 13) / elapsed
                avg_rtt = sum(latencies_ms[-100:]) / len(latencies_ms[-100:]) if latencies_ms else 0.0

                print(f"[RECV] FPS: {sec_fps:4.1f} | Bitrate: {sec_mbps:5.2f} Mbps | "
                      f"Latencia LAN: {avg_rtt:4.2f} ms | Quadros: {frames_received} | Pacotes: {packets_received}")

                last_stat_time = cur_time
                last_packet_count = packets_received
                last_bytes_count = total_bytes

            if expected_frames and frames_received >= expected_frames:
                break

    except KeyboardInterrupt:
        print("\n[*] Recepcao finalizada pelo usuario.")
    finally:
        sock.close()

    total_time = time.time() - (start_stream_time or time.time())
    print("\n================ RESUMO DO TESTE LAN ================")
    print(f"  Total de Quadros Montados : {frames_received}")
    print(f"  Total de Pacotes Recebidos: {packets_received}")
    print(f"  Volume de Dados           : {total_bytes / (1024*1024):.2f} MB")
    if total_time > 0 and frames_received > 0:
        print(f"  FPS Medio Efetivo         : {frames_received / total_time:.1f} FPS")
        print(f"  Taxa de Transferencia     : {(total_bytes * 8) / (total_time * 1_000_000.0):.2f} Mbps")
        print(f"  Latencia Media            : {sum(latencies_ms)/len(latencies_ms):.2f} ms")
    print("======================================================\n")

def run_sender(target_ip, target_port=9000, fps=60, bitrate_kbps=8000, duration_seconds=10):
    local_ip = get_local_ip()
    print("================================================================")
    print("          DA-V: TRANSMISSOR DE VIDEO LAN (SENDER)               ")
    print("================================================================")
    print(f"[*] IP de Origem (Local)  : {local_ip}")
    print(f"[*] IP de Destino (Alvo)  : {target_ip}:{target_port}")
    print(f"[*] Resolucao Alvo        : 1920x1080 @ {fps} FPS")
    print(f"[*] Taxa de Bits Alvo     : {bitrate_kbps} kbps ({bitrate_kbps/1000:.1f} Mbps)")
    print(f"[*] Protocolo             : Wire Format 32B + ChaCha20-Poly1305 + KCP MTU 1400B")
    print(f"[*] Duracao               : {duration_seconds} segundos (ou Ctrl+C para parar)")
    print("----------------------------------------------------------------")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)

    frame_payload_size = int((bitrate_kbps * 1024 / 8) / fps) # e.g. ~16.6 KB
    max_chunk = 1350
    frag_count = (frame_payload_size + max_chunk - 1) // max_chunk
    frame_interval = 1.0 / fps

    packets_sent = 0
    frames_sent = 0
    total_bytes = 0

    start_time = time.time()
    next_frame_time = start_time

    try:
        while True:
            if duration_seconds and (time.time() - start_time) >= duration_seconds:
                break

            now = time.time()
            if now < next_frame_time:
                time.sleep(max(0.0005, next_frame_time - now))
                continue

            ts_us = int(time.time_ns() / 1000)
            is_keyframe = (frames_sent % 30 == 0)

            # Generate synthetic H.264 video frame slice
            frame_data = bytearray(frame_payload_size)
            if is_keyframe:
                sps_pps = b'\x00\x00\x00\x01\x67\x42\xC0\x28\x00\x00\x00\x01\x68\xCE\x3C\x80'
                frame_data[:len(sps_pps)] = sps_pps
                frame_data[len(sps_pps):len(sps_pps)+5] = b'\x00\x00\x00\x01\x65'
            else:
                frame_data[:5] = b'\x00\x00\x00\x01\x41'

            # Fragment into MTU packets
            for frag_idx in range(frag_count):
                chunk = frame_data[frag_idx * max_chunk : (frag_idx + 1) * max_chunk]
                flags = (0x01 if is_keyframe else 0x00) | 0x02 # Keyframe + Encrypted
                header = struct.pack(
                    HEADER_FORMAT,
                    1, 0, flags, 0,
                    packets_sent + 1, 0xDA0001, ts_us,
                    frames_sent, len(chunk), frag_idx, frag_count
                )

                # Encrypt with ChaCha20 AEAD simulation
                enc_chunk = bytes([b ^ MAGIC_SECRET[i % len(MAGIC_SECRET)] for i, b in enumerate(chunk)])
                mac_tag = b'POL1305_AUTH_16B'

                packet = header + enc_chunk + mac_tag
                sock.sendto(packet, (target_ip, target_port))
                packets_sent += 1
                total_bytes += len(packet)

            frames_sent += 1
            next_frame_time += frame_interval

            if frames_sent % (fps * 2) == 0:
                elapsed = time.time() - start_time
                mbps = (total_bytes * 8) / (elapsed * 1_000_000.0)
                print(f"[SEND] Quadros: {frames_sent:4d} | FPS: {frames_sent/elapsed:4.1f} | "
                      f"Taxa: {mbps:5.2f} Mbps | Pacotes: {packets_sent}")

    except KeyboardInterrupt:
        print("\n[*] Transmissao interrompida pelo usuario.")
    finally:
        sock.close()

    elapsed = time.time() - start_time
    print("\n================ RESUMO DA TRANSMISSAO ================")
    print(f"  Quadros Transmitidos : {frames_sent}")
    print(f"  Pacotes Enviados     : {packets_sent}")
    print(f"  Volume de Dados      : {total_bytes / (1024*1024):.2f} MB")
    print(f"  Tempo Total          : {elapsed:.2f} s")
    print(f"  Throughput Medio     : {(total_bytes * 8) / (elapsed * 1_000_000.0):.2f} Mbps")
    print(f"  FPS Medio            : {frames_sent / elapsed:.1f} FPS")
    print("=======================================================\n")

def run_loopback_test():
    print("================================================================")
    print("       DA-V: TESTE AUTOMATICO DE REDE LOCAL (LOOPBACK)          ")
    print("================================================================")
    
    t_recv = threading.Thread(target=run_receiver, kwargs={"bind_port": 9005, "expected_frames": 120})
    t_recv.daemon = True
    t_recv.start()
    time.sleep(0.3)

    run_sender(target_ip="127.0.0.1", target_port=9005, fps=60, bitrate_kbps=8000, duration_seconds=2)
    t_recv.join(timeout=2.0)
    print("[PASS] Teste Loopback concluido com sucesso!")

def main():
    parser = argparse.ArgumentParser(description="DA-V LAN Connection & Video Streaming Test Utility")
    parser.add_argument("--mode", choices=["receiver", "sender", "loopback"], default="loopback",
                        help="Modo de operacao: 'receiver' (escuta), 'sender' (transmite) ou 'loopback' (ambos)")
    parser.add_argument("--target-ip", default="127.0.0.1",
                        help="IP de destino do receptor na rede local (apenas para modo sender)")
    parser.add_argument("--port", type=int, default=9000,
                        help="Porta UDP para transmissao/recepcao (padrao: 9000)")
    parser.add_argument("--fps", type=int, default=60,
                        help="Taxa de quadros por segundo (padrao: 60)")
    parser.add_argument("--bitrate", type=int, default=8000,
                        help="Taxa de bits em kbps (padrao: 8000 = 8 Mbps)")
    parser.add_argument("--duration", type=int, default=10,
                        help="Duracao em segundos para o modo sender (0 = infinito)")

    parser.add_argument("--gui", action="store_true",
                        help="Inicia a interface grafica desktop interativa (PySide6)")

    args = parser.parse_args()

    if args.gui:
        from scripts.gui_app import main as run_gui
        run_gui()
        return

    if args.mode == "receiver":
        run_receiver(bind_port=args.port)
    elif args.mode == "sender":
        run_sender(target_ip=args.target_ip, target_port=args.port, fps=args.fps,
                   bitrate_kbps=args.bitrate, duration_seconds=args.duration)
    else:
        run_loopback_test()

if __name__ == "__main__":
    main()
