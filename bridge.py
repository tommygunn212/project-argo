import asyncio
import json
import logging
from typing import Set

import websockets

ARGO_WS_URL = "ws://localhost:8001/ws"
BRIDGE_HOST = "localhost"
BRIDGE_PORT = 8766

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ARGO.Bridge")

clients: Set[websockets.WebSocketServerProtocol] = set()


async def _broadcast(message: str) -> None:
    if not clients:
        return
    dead = []
    for client in clients:
        try:
            await client.send(message)
        except Exception:
            dead.append(client)
    for client in dead:
        clients.discard(client)


async def _send_status(status: str) -> None:
    payload = json.dumps({"type": "bridge_status", "payload": status})
    await _broadcast(payload)


async def _handle_client(ws: websockets.WebSocketServerProtocol) -> None:
    clients.add(ws)
    await _send_status("online")
    try:
        async for _ in ws:
            # Bridge is read-only; ignore incoming messages.
            pass
    finally:
        clients.discard(ws)


async def _run_bridge() -> None:
    while True:
        try:
            async with websockets.connect(ARGO_WS_URL) as argo_ws:
                logger.info("Connected to ARGO websocket")
                await _send_status("online")
                async for message in argo_ws:
                    try:
                        data = json.loads(message)
                        if isinstance(data, dict) and data.get("type") == "log":
                            payload = json.dumps({"type": "log", "payload": data.get("payload", "")})
                            await _broadcast(payload)
                        else:
                            await _broadcast(message)
                    except Exception:
                        await _broadcast(json.dumps({"type": "log", "payload": str(message)}))
        except Exception as e:
            logger.warning("ARGO websocket disconnected: %s", e)
            await _send_status("offline")
            await asyncio.sleep(2)


async def main() -> None:
    server = await websockets.serve(_handle_client, BRIDGE_HOST, BRIDGE_PORT)
    logger.info("Bridge websocket server listening on ws://%s:%s", BRIDGE_HOST, BRIDGE_PORT)
    await _run_bridge()
    server.close()
    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
