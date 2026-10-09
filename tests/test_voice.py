import importlib.util
import pathlib
import threading
import unittest


VOICE_PATH = pathlib.Path(__file__).resolve().parents[1] / "src" / "hal" / "voice.py"
SPEC = importlib.util.spec_from_file_location("xploria_voice_test", VOICE_PATH)
voice = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(voice)


class VoiceHalTest(unittest.TestCase):
    def tearDown(self):
        voice.clear()

    def test_matches_all_words_in_any_order(self):
        voice.set_voice_text("Pintu tolong buka")
        self.assertTrue(voice.contains_all("buka", "pintu"))

    def test_matches_simple_indonesian_affixes(self):
        voice.set_voice_text("Pintunya tolong dibuka")
        self.assertTrue(voice.contains_all("buka", "pintu"))

    def test_rejects_negated_command(self):
        voice.set_voice_text("Jangan buka pintu")
        self.assertFalse(voice.contains_all("buka", "pintu"))

    def test_clear_removes_command(self):
        voice.set_voice_text("buka pintu", request_id="req-1")
        voice.clear()
        self.assertFalse(voice.contains_all("buka"))
        self.assertEqual(voice.snapshot()["text"], "")

    def test_concurrent_updates_are_safe(self):
        threads = [
            threading.Thread(target=voice.set_voice_text, args=(f"buka pintu {i}",))
            for i in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertTrue(voice.contains_all("buka", "pintu"))


if __name__ == "__main__":
    unittest.main()
