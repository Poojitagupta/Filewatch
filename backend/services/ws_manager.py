import json
from fastapi import WebSocket
from typing import Set


class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)
        await self.send(ws, {"type": "connected", "message": "FileWatch WS connected"})

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def send(self, ws: WebSocket, data: dict):
        try:
            await ws.send_text(json.dumps(data, default=str))
        except Exception:
            self.disconnect(ws)

    async def broadcast(self, data: dict):
        dead = set()
        for ws in self.active:
            try:
                await ws.send_text(json.dumps(data, default=str))
            except Exception:
                dead.add(ws)
        self.active -= dead


ws_manager = ConnectionManager()