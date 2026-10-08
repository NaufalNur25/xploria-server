"""
Audio HAL implementation for Xploria Server.
Handles playback of preset sounds and custom recordings via Linux ALSA (aplay).
"""
import os
import sys
import subprocess

class AudioHAL:
    def __init__(self):
        self._root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.preset_dir = os.path.join(self._root_dir, "sounds", "presets")
        self.custom_dir = os.path.join(self._root_dir, "sounds", "custom")
        os.makedirs(self.preset_dir, exist_ok=True)
        os.makedirs(self.custom_dir, exist_ok=True)
        self._current_process = None

    def play(self, sound_name: str):
        """Memutar file suara preset (misal: DOORBELL, WARNING)"""
        self.stop()
        target = str(sound_name).lower().strip()
        filename = os.path.join(self.preset_dir, f"{target}.wav")
        if not os.path.exists(filename):
            print(f"[AudioHAL] File suara preset tidak ditemukan: {filename}", file=sys.stderr)
            return
        self._play_file(filename)

    def play_custom(self, slot_name: str):
        """Memutar file suara rekaman siswa (misal: slot_1, slot_2)"""
        self.stop()
        target = str(slot_name).lower().strip()
        filename = os.path.join(self.custom_dir, f"{target}.wav")
        if not os.path.exists(filename):
            print(f"[AudioHAL] File suara rekaman tidak ditemukan: {filename}", file=sys.stderr)
            return
        self._play_file(filename)

    def record(self, slot_name: str, duration: int = 3):
        """Merekam suara ke slot custom"""
        target = str(slot_name).lower().strip()
        filename = os.path.join(self.custom_dir, f"{target}.wav")
        print(f"[AudioHAL] Merekam audio ke {filename} selama {duration} detik...")
        if sys.platform.startswith("linux"):
            try:
                subprocess.run(
                    ["arecord", "-D", "default", "-d", str(int(duration)), "-f", "cd", "-t", "wav", filename],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=float(duration) + 2.0
                )
                print(f"[AudioHAL] Selesai merekam: {filename}")
            except Exception as e:
                print(f"[AudioHAL] Gagal merekam: {e}", file=sys.stderr)
        else:
            import time
            time.sleep(float(duration))
            print(f"[AudioHAL] [MOCK] Rekaman {target} selesai disimpan.")

    def stop(self):
        """Menghentikan pemutaran audio"""
        if self._current_process and self._current_process.poll() is None:
            try:
                self._current_process.terminate()
            except Exception:
                pass
            self._current_process = None

    def _play_file(self, filepath: str):
        try:
            if sys.platform.startswith("linux"):
                self._current_process = subprocess.Popen(
                    ["aplay", "-q", filepath],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            elif sys.platform.startswith("win"):
                import winsound
                winsound.PlaySound(filepath, winsound.SND_ASYNC | winsound.SND_FILENAME)
            print(f"[AudioHAL] Memutar suara: {filepath}")
        except Exception as e:
            print(f"[AudioHAL] Gagal memutar file audio: {e}", file=sys.stderr)
"""
Audio HAL implementation for Xploria Server.
Handles playback of preset sounds and custom recordings via Linux ALSA (aplay).
"""
import os
import sys
import subprocess

class AudioHAL:
    def __init__(self):
        self._root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.preset_dir = os.path.join(self._root_dir, "sounds", "presets")
        self.custom_dir = os.path.join(self._root_dir, "sounds", "custom")
        os.makedirs(self.preset_dir, exist_ok=True)
        os.makedirs(self.custom_dir, exist_ok=True)
        self._current_process = None

    def play(self, sound_name: str):
        """Memutar file suara preset (misal: DOORBELL, WARNING)"""
        self.stop()
        target = str(sound_name).lower().strip()
        filename = os.path.join(self.preset_dir, f"{target}.wav")
        if not os.path.exists(filename):
            print(f"[AudioHAL] File suara preset tidak ditemukan: {filename}", file=sys.stderr)
            return
        self._play_file(filename)

    def play_custom(self, slot_name: str):
        """Memutar file suara rekaman siswa (misal: slot_1, slot_2)"""
        self.stop()
        target = str(slot_name).lower().strip()
        filename = os.path.join(self.custom_dir, f"{target}.wav")
        if not os.path.exists(filename):
            print(f"[AudioHAL] File suara rekaman tidak ditemukan: {filename}", file=sys.stderr)
            return
        self._play_file(filename)

    def record(self, slot_name: str, duration: int = 3):
        """Merekam suara ke slot custom"""
        target = str(slot_name).lower().strip()
        filename = os.path.join(self.custom_dir, f"{target}.wav")
        print(f"[AudioHAL] Merekam audio ke {filename} selama {duration} detik...")
        if sys.platform.startswith("linux"):
            try:
                subprocess.run(
                    ["arecord", "-D", "default", "-d", str(int(duration)), "-f", "cd", "-t", "wav", filename],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=float(duration) + 2.0
                )
                print(f"[AudioHAL] Selesai merekam: {filename}")
            except Exception as e:
                print(f"[AudioHAL] Gagal merekam: {e}", file=sys.stderr)
        else:
            import time
            time.sleep(float(duration))
            print(f"[AudioHAL] [MOCK] Rekaman {target} selesai disimpan.")

    def stop(self):
        """Menghentikan pemutaran audio"""
        if self._current_process and self._current_process.poll() is None:
            try:
                self._current_process.terminate()
            except Exception:
                pass
            self._current_process = None

    def _play_file(self, filepath: str):
        try:
            if sys.platform.startswith("linux"):
                self._current_process = subprocess.Popen(
                    ["aplay", "-q", filepath],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            elif sys.platform.startswith("win"):
                import winsound
                winsound.PlaySound(filepath, winsound.SND_ASYNC | winsound.SND_FILENAME)
            print(f"[AudioHAL] Memutar suara: {filepath}")
        except Exception as e:
            print(f"[AudioHAL] Gagal memutar file audio: {e}", file=sys.stderr)
