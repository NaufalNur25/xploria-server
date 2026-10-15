"""
Audio HAL implementation for Xploria Server.
Handles playback of preset sounds and custom recordings via Linux ALSA (aplay).
Optimized for Raspberry Pi 3B with RAM-disk /tmp storage, quota self-management,
RIFF-WAVE header validation, and path traversal protection.
"""
import os
import sys
import re
import subprocess
import tempfile
import threading

MAX_AUDIO_TMP_BYTES = 10 * 1024 * 1024  # 10 MB quota limit
MAX_SINGLE_AUDIO_BYTES = 2 * 1024 * 1024  # 2 MB per clip


def sanitize_slot_name(slot_name: str) -> str:
    """Membersihkan dan memvalidasi nama slot agar bebas dari path traversal."""
    raw = str(slot_name or "").strip()
    base = os.path.basename(raw).lower()
    clean = re.sub(r"[^a-z0-9_\-]", "", base)
    if not clean or len(clean) > 64:
        raise ValueError(f"Nama slot audio tidak valid: '{slot_name}'")
    return clean


def enforce_audio_storage_quota(target_dir: str, max_bytes: int = MAX_AUDIO_TMP_BYTES):
    """Memastikan direktori audio tidak melebihi kuota dengan kebijakan LRU."""
    if not os.path.exists(target_dir):
        return
    try:
        entries = [
            os.path.join(target_dir, f)
            for f in os.listdir(target_dir)
            if os.path.isfile(os.path.join(target_dir, f))
        ]
        total_size = sum(os.path.getsize(p) for p in entries)

        if total_size > max_bytes:
            # Urutkan berdasarkan waktu modifikasi terakhir (paling lama ke terbaru)
            entries.sort(key=lambda p: os.path.getmtime(p))
            target_safe_size = int(max_bytes * 0.7)  # Bersihkan hingga 70%

            while total_size > target_safe_size and entries:
                oldest = entries.pop(0)
                try:
                    size = os.path.getsize(oldest)
                    os.remove(oldest)
                    total_size -= size
                    print(f"[AudioHAL] Auto-cleanup: menghapus cache audio lama: {oldest}")
                except Exception as e:
                    print(f"[AudioHAL] Gagal menghapus file lama {oldest}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"[AudioHAL] Gagal memeriksa kuota audio: {e}", file=sys.stderr)


class AudioHAL:
    def __init__(self):
        self._root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.preset_dir = os.path.join(self._root_dir, "sounds", "presets")
        self.custom_dir = os.path.join(self._root_dir, "sounds", "custom")

        # Direktori RAM tmpfs untuk melindungi MicroSD dan zero wear pada Pi 3B
        if sys.platform.startswith("linux"):
            self.tmp_custom_dir = "/tmp/xploria/sounds/custom"
        else:
            self.tmp_custom_dir = os.path.join(tempfile.gettempdir(), "xploria", "sounds", "custom")

        os.makedirs(self.preset_dir, exist_ok=True)
        os.makedirs(self.custom_dir, exist_ok=True)
        os.makedirs(self.tmp_custom_dir, exist_ok=True)

        self._current_process = None
        self._lock = threading.Lock()

    def save_custom_audio(self, slot_name: str, audio_bytes: bytes) -> str:
        """Menyimpan berkas rekaman siswa (PCM WAV) ke RAM-disk /tmp secara atomik dengan validasi."""
        target = sanitize_slot_name(slot_name)

        if not isinstance(audio_bytes, (bytes, bytearray)):
            raise ValueError("Payload audio harus berupa bytes.")
        if len(audio_bytes) < 44:
            raise ValueError("Ukuran audio terlalu kecil untuk berkas WAV (minimal 44 bytes).")
        if len(audio_bytes) > MAX_SINGLE_AUDIO_BYTES:
            raise ValueError(f"Ukuran audio melebihi batas maksimal ({MAX_SINGLE_AUDIO_BYTES // (1024*1024)} MB).")

        # Validasi header RIFF...WAVE
        if not (audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE"):
            raise ValueError("Format audio tidak valid: header berkas harus berupa format WAV (RIFF...WAVE).")

        os.makedirs(self.tmp_custom_dir, exist_ok=True)
        enforce_audio_storage_quota(self.tmp_custom_dir, MAX_AUDIO_TMP_BYTES)

        filename = os.path.join(self.tmp_custom_dir, f"{target}.wav")
        tmp_target = os.path.join(self.tmp_custom_dir, f".{target}_{os.getpid()}_{threading.get_ident()}.tmp")

        # Penulisan atomik: tulis ke tmp file dulu lalu replace agar tidak ada race condition
        with open(tmp_target, "wb") as f:
            f.write(audio_bytes)
        os.replace(tmp_target, filename)

        print(f"[AudioHAL] Audio rekaman disimpan ke RAM: {filename} ({len(audio_bytes)} bytes)")
        return filename

    def _resolve_custom_path(self, slot_name: str) -> str:
        """Mencari berkas audio: prioritas RAM-disk /tmp, fallback ke folder repositori."""
        try:
            target = sanitize_slot_name(slot_name)
        except ValueError:
            target = "slot_1"

        tmp_path = os.path.join(self.tmp_custom_dir, f"{target}.wav")
        if os.path.exists(tmp_path):
            return tmp_path

        repo_path = os.path.join(self.custom_dir, f"{target}.wav")
        if os.path.exists(repo_path):
            return repo_path

        return tmp_path

    def play(self, sound_name: str, wait: bool = False):
        """Memutar file suara preset (misal: DOORBELL, WARNING)."""
        self.stop()
        try:
            target = sanitize_slot_name(sound_name)
        except ValueError:
            target = "doorbell"
        filename = os.path.join(self.preset_dir, f"{target}.wav")
        if not os.path.exists(filename):
            print(f"[AudioHAL] File suara preset tidak ditemukan: {filename}", file=sys.stderr)
            return
        self._play_file(filename, wait=wait)

    def play_custom(self, slot_name: str, wait: bool = True):
        """Memutar file suara rekaman siswa (misal: slot_1, slot_2) dari /tmp atau repo."""
        self.stop()
        filename = self._resolve_custom_path(slot_name)
        if not os.path.exists(filename):
            print(f"[AudioHAL] Suara rekaman slot '{slot_name}' belum tersedia ({filename})", file=sys.stderr)
            return
        print(f"[AudioHAL] Memutar suara rekaman {slot_name} di speaker (wait={wait})...")
        self._play_file(filename, wait=wait)

    def record(self, slot_name: str, duration: int = 3) -> bool:
        """Perekaman suara dilakukan dari aplikasi HP siswa. Raspberry Pi tidak menjalankan fungsi merekam fisik."""
        try:
            target = sanitize_slot_name(slot_name)
        except ValueError:
            target = "slot_1"
        filename = os.path.join(self.tmp_custom_dir, f"{target}.wav")
        if os.path.exists(filename) and os.path.getsize(filename) >= 44:
            print(f"[AudioHAL] Slot '{target}' menggunakan rekaman suara dari aplikasi HP siswa ({filename})")
            return True
        else:
            print(f"[AudioHAL] Info: Slot '{target}' direkam melalui aplikasi HP siswa (berkas fisik di Pi belum sinkron).")
            return True

    def stop(self):
        """Menghentikan pemutaran audio yang sedang berjalan."""
        with self._lock:
            proc = self._current_process
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
            self._current_process = None

            if sys.platform.startswith("win"):
                try:
                    import winsound
                    winsound.PlaySound(None, winsound.SND_PURGE)
                except Exception:
                    pass

    def _play_file(self, filepath: str, wait: bool = False):
        """Memutar berkas audio via ALSA aplay (Linux) atau winsound (Windows) bebas race condition."""
        try:
            if sys.platform.startswith("linux"):
                proc = None
                with self._lock:
                    proc = subprocess.Popen(
                        ["aplay", "-q", filepath],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    self._current_process = proc
                if wait and proc:
                    try:
                        proc.wait(timeout=15.0)
                    except subprocess.TimeoutExpired:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    with self._lock:
                        if self._current_process is proc:
                            self._current_process = None
            elif sys.platform.startswith("win"):
                import winsound
                flags = winsound.SND_FILENAME
                if not wait:
                    flags |= winsound.SND_ASYNC
                winsound.PlaySound(filepath, flags)
            print(f"[AudioHAL] Selesai memutar suara: {filepath}")
        except Exception as e:
            print(f"[AudioHAL] Gagal memutar file audio: {e}", file=sys.stderr)


# Singleton HAL instance
_default_audio_hal = AudioHAL()

# Module-level delegates untuk modul virtual 'xploria_hal.audio'
def play(sound_name: str, wait: bool = False):
    return _default_audio_hal.play(sound_name, wait=wait)

def play_custom(slot_name: str, wait: bool = True):
    return _default_audio_hal.play_custom(slot_name, wait=wait)

def record(slot_name: str, duration: int = 3):
    return _default_audio_hal.record(slot_name, duration=duration)

def stop():
    return _default_audio_hal.stop()

def save_custom_audio(slot_name: str, audio_bytes: bytes) -> str:
    return _default_audio_hal.save_custom_audio(slot_name, audio_bytes)
