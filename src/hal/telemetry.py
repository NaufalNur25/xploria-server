import json
import asyncio
import logging

logger = logging.getLogger(__name__)

class TelemetryHAL:
    def __init__(self):
        self._queue = None
        self._loop = None  # Referensi ke main asyncio loop, diset oleh ws_server
        self._last_sent = {} # Menyimpan state terakhir yang dikirim

    def _ensure_queue(self):
        if self._queue is None:
            try:
                self._queue = asyncio.Queue()
            except RuntimeError as e:
                logger.warning(f"Cannot create telemetry queue: {e}")

    def send(self, **kwargs):
        """Kirim data telemetri delta ke aplikasi Flutter via JSON stream.
        Menggunakan epsilon (0.5) untuk float agar tidak spam.
        """
        changed = False
        updates = {}

        for key, new_val in kwargs.items():
            old_val = self._last_sent.get(key)
            
            # Cek apakah nilai berubah. Jika float, beri toleransi epsilon 0.5
            if isinstance(new_val, float) and isinstance(old_val, float):
                if abs(new_val - old_val) >= 0.5:
                    changed = True
                    updates[key] = new_val
                    self._last_sent[key] = new_val
            else:
                if new_val != old_val:
                    changed = True
                    updates[key] = new_val
                    self._last_sent[key] = new_val

        # Hanya kirim jika ada perubahan
        if not changed:
            return

        payload = {
            "type": "telemetry_delta",
            "telemetry": updates
        }
        msg = json.dumps(payload)

        self._put_queue(msg)

    def send_snapshot(self):
        """Mengirimkan seluruh state terakhir dari _last_sent ke klien."""
        payload = {
            "type": "telemetry_snapshot",
            "telemetry": self._last_sent
        }
        self._put_queue(json.dumps(payload))

    def _put_queue(self, msg):
        """Internal helper to push into the queue thread-safely."""
        if self._loop and self._queue:
            try:
                asyncio.run_coroutine_threadsafe(self._queue.put(msg), self._loop)
            except Exception as e:
                logger.warning(f"Telemetry put failed: {e}")
        elif self._queue:
            try:
                self._queue.put_nowait(msg)
            except asyncio.QueueFull:
                pass
        else:
            print(f"TELEMETRY:{msg}", flush=True)
