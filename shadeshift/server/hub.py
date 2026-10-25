"""Live message fan-out for the WebSocket stream (docs/CONTRACT.md §5.7).

Endpoints run in a thread pool, so publish() hands messages to the event loop with call_soon_threadsafe.
Slow clients drop messages instead of blocking ingestion.
"""
import asyncio


class Hub:
    def __init__(self, max_queue=500):
        self.loop = None
        self.max_queue = max_queue
        self._clients = set()                  # (queue, device_filter)

    def attach(self, loop):
        self.loop = loop

    def subscribe(self, device_id=None):
        client = (asyncio.Queue(maxsize=self.max_queue), device_id)
        self._clients.add(client)
        return client

    def unsubscribe(self, client):
        self._clients.discard(client)

    def publish(self, msg_type, data, device_id=None):
        if self.loop is None or self.loop.is_closed():
            return
        msg = {"type": msg_type, "data": data}
        try:
            self.loop.call_soon_threadsafe(self._fan_out, msg, device_id)
        except RuntimeError:                    # loop shutting down
            pass

    def _fan_out(self, msg, device_id):
        for queue, wanted in list(self._clients):
            if wanted is None or device_id is None or wanted == device_id:
                try:
                    queue.put_nowait(msg)
                except asyncio.QueueFull:
                    pass
