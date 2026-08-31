import asyncio
import logging

logger = logging.getLogger(__name__)


class WSManager:
    def __init__(self):
        self._clients: set = set()

    async def register(self, ws):
        self._clients.add(ws)

    async def unregister(self, ws):
        self._clients.discard(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for d in dead:
            self._clients.discard(d)


ws_manager = WSManager()
