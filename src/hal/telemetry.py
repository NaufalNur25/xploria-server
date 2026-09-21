import json
import asyncio

class TelemetryHAL:
    def __init__(self):
        self._running = False
        self._queue = None

    def _ensure_queue(self):
        if self._queue is None:
            try:
                self._queue = asyncio.Queue()
            except RuntimeError:
                pass
                
    def send(self, **kwargs):
        """Kirim data telemetri generik ke aplikasi Flutter via JSON stream."""
        self._ensure_queue()
        payload = {
            "type": "telemetry",
            "telemetry": kwargs
        }
        
        # If queue exists, push to queue, else print to stdout
        if self._queue:
            try:
                self._queue.put_nowait(json.dumps(payload))
            except Exception:
                pass
        else:
            print(f"TELEMETRY:{json.dumps(payload)}", flush=True)

    def start_stream(self, interval=1.0):
        # We delegate the actual stream logic to the WebSocket server handler 
        # so it doesn't print to stdout, but this acts as an interface marker if needed.
        self._running = True

    def stop_stream(self):
        self._running = False
