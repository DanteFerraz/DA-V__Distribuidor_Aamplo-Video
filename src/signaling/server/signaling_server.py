#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Public WAN Signaling Server for DA-V (Distribuidor Aamplo - Video)
Lightweight asyncio WebSocket / TCP signaling relay for NAT traversal,
ICE candidate exchange, and peer rendezvous.
"""

import asyncio
import json
import logging
import time

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("DAV-Signaling")

class DavSignalingServer:
    def __init__(self, host="0.0.0.0", port=8765):
        self.host = host
        self.port = port
        self.peers = {}        # peer_id -> writer
        self.rooms = {}        # room_id -> set of peer_ids
        self.peer_rooms = {}   # peer_id -> room_id

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer_id = None
        addr = writer.get_extra_info("peername")
        logger.info(f"New connection from {addr}")

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break

                try:
                    msg = json.loads(line.decode("utf-8").strip())
                except Exception:
                    continue

                msg_type = msg.get("type")
                
                # 1. Register Peer
                if msg_type == "register":
                    peer_id = msg.get("peer_id")
                    self.peers[peer_id] = writer
                    logger.info(f"Peer registered: {peer_id} from {addr}")
                    await self._send(writer, {"type": "registered", "peer_id": peer_id, "status": "ok"})

                # 2. Join Room / Rendezvous
                elif msg_type == "join_room":
                    room_id = msg.get("room_id")
                    if not peer_id:
                        peer_id = msg.get("peer_id")
                        self.peers[peer_id] = writer

                    if room_id not in self.rooms:
                        self.rooms[room_id] = set()
                    
                    self.rooms[room_id].add(peer_id)
                    self.peer_rooms[peer_id] = room_id
                    logger.info(f"Peer {peer_id} joined room '{room_id}' (Total peers: {len(self.rooms[room_id])})")

                    # Notify other peers in room
                    for other_id in self.rooms[room_id]:
                        if other_id != peer_id and other_id in self.peers:
                            await self._send(self.peers[other_id], {
                                "type": "peer_joined",
                                "room_id": room_id,
                                "peer_id": peer_id
                            })

                    await self._send(writer, {
                        "type": "room_joined",
                        "room_id": room_id,
                        "peers": list(self.rooms[room_id])
                    })

                # 3. Relay ICE Candidates / SDP Offer / Answer
                elif msg_type in ("candidate", "offer", "answer"):
                    target_peer = msg.get("target_peer")
                    if target_peer and target_peer in self.peers:
                        msg["from_peer"] = peer_id
                        await self._send(self.peers[target_peer], msg)
                    elif peer_id in self.peer_rooms:
                        # Broadcast to room
                        room_id = self.peer_rooms[peer_id]
                        msg["from_peer"] = peer_id
                        for other_id in self.rooms.get(room_id, set()):
                            if other_id != peer_id and other_id in self.peers:
                                await self._send(self.peers[other_id], msg)

        except Exception as e:
            logger.warning(f"Error handling client {peer_id}: {e}")
        finally:
            # Cleanup peer on disconnect
            if peer_id:
                logger.info(f"Peer disconnected: {peer_id}")
                self.peers.pop(peer_id, None)
                room_id = self.peer_rooms.pop(peer_id, None)
                if room_id and room_id in self.rooms:
                    self.rooms[room_id].discard(peer_id)
                    for other_id in self.rooms[room_id]:
                        if other_id in self.peers:
                            await self._send(self.peers[other_id], {
                                "type": "peer_left",
                                "room_id": room_id,
                                "peer_id": peer_id
                            })
            writer.close()
            await writer.wait_closed()

    async def _send(self, writer: asyncio.StreamWriter, msg: dict):
        try:
            data = (json.dumps(msg) + "\n").encode("utf-8")
            writer.write(data)
            await writer.drain()
        except Exception:
            pass

    async def run(self):
        server = await asyncio.start_server(self.handle_client, self.host, self.port)
        logger.info(f"DA-V Signaling Server listening on {self.host}:{self.port}")
        async with server:
            await server.serve_forever()

if __name__ == "__main__":
    server = DavSignalingServer(port=8765)
    asyncio.run(server.run())
