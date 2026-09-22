import json
import asyncio
import logging

logger = logging.getLogger(__name__)

class TelemetryHAL:
    def __init__(self):
        self._running = False
        self._queue = None
        self._loop = None  # Referensi ke main asyncio loop, diset oleh ws_server

    def _ensure_queue(self):
        if self._queue is None:
            try:
                self._queue = asyncio.Queue()
            except RuntimeError as e:
                logger.warning(f"Cannot create telemetry queue: {e}")

    def send(self, **kwargs):
        """Kirim data telemetri generik ke aplikasi Flutter via JSON stream.
        Thread-safe: bisa dipanggil dari Blockly thread pool.
        """
        payload = {
            "type": "telemetry",
            "telemetry": kwargs
        }
        msg = json.dumps(payload)

        # Jika ada loop dan queue, kirim secara thread-safe
        if self._loop and self._queue:
            try:
                asyncio.run_coroutine_threadsafe(self._queue.put(msg), self._loop)
            except Exception as e:
                logger.warning(f"Telemetry send failed: {e}")
        elif self._queue:
            # Fallback: dipanggil dari event loop thread langsung
            try:
                self._queue.put_nowait(msg)
            except asyncio.QueueFull:
                logger.warning("Telemetry queue full, message dropped")
        else:
            # Queue belum siap, print ke stdout sebagai fallback
            print(f"TELEMETRY:{msg}", flush=True)

    def start_stream(self, interval=1.0):
        self._running = True

    def stop_stream(self):
        self._running = False
