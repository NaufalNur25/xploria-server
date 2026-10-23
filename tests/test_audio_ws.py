import os
import pathlib
import tempfile
import unittest

from src.hal import audio
from src.hal.audio import AudioHAL, sanitize_slot_name, enforce_audio_storage_quota


class AudioWsAndHalTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.hal = AudioHAL()
        self.hal.tmp_custom_dir = self.tmp_dir

    def tearDown(self):
        self.hal.stop()

    def test_sanitize_slot_name(self):
        self.assertEqual(sanitize_slot_name("slot_1"), "slot_1")
        self.assertEqual(sanitize_slot_name("my-sound_2"), "my-sound_2")
        with self.assertRaises(ValueError):
            sanitize_slot_name("!@#$%^&*()")
        with self.assertRaises(ValueError):
            sanitize_slot_name("///")
        with self.assertRaises(ValueError):
            sanitize_slot_name("a" * 65)

    def test_save_custom_audio_valid_wav(self):
        # Valid RIFF WAVE header 44 bytes
        header = bytearray(44)
        header[0:4] = b"RIFF"
        header[8:12] = b"WAVE"
        header[12:16] = b"fmt "
        path = self.hal.save_custom_audio("slot_1", bytes(header))
        self.assertTrue(os.path.exists(path))
        self.assertEqual(os.path.basename(path), "slot_1.wav")

    def test_save_custom_audio_rejects_non_wav(self):
        fake_data = b"NOT_A_WAV_HEADER_DATA_1234567890123456789012345678901234"
        with self.assertRaises(ValueError) as ctx:
            self.hal.save_custom_audio("slot_1", fake_data)
        self.assertIn("header berkas harus berupa format WAV", str(ctx.exception))

    def test_save_custom_audio_rejects_invalid_slot(self):
        header = bytearray(44)
        header[0:4] = b"RIFF"
        header[8:12] = b"WAVE"
        with self.assertRaises(ValueError):
            self.hal.save_custom_audio("???", bytes(header))

    def test_quota_eviction(self):
        header = bytearray(44)
        header[0:4] = b"RIFF"
        header[8:12] = b"WAVE"
        path = self.hal.save_custom_audio("slot_1", bytes(header))
        self.assertTrue(os.path.exists(path))
        enforce_audio_storage_quota(self.tmp_dir, max_bytes=10)
        self.assertFalse(os.path.exists(path))

    def test_play_custom_audio_missing(self):
        self.assertFalse(self.hal.play_custom("non_existent_slot", wait=False))


if __name__ == "__main__":
    unittest.main()
