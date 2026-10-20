import importlib.util
import io
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import numpy as np

root = Path(__file__).resolve().parents[1]
path = root / 'src/hal/face.py'
if not path.exists():
    path = Path(__file__).with_name('face.py')
spec = importlib.util.spec_from_file_location('face_under_test', path)
face = importlib.util.module_from_spec(spec)
spec.loader.exec_module(face)


class FaceTests(unittest.TestCase):
    def test_uart_team_hw_frame_and_invalid_jpeg(self):
        jpeg = b'\xff\xd8example\xff\xd9'
        packet = b'boot noiseFACE' + struct.pack('<I', len(jpeg)) + jpeg
        self.assertEqual(face.read_jpeg(io.BytesIO(packet)), jpeg)
        with self.assertRaises(ValueError):
            face.read_jpeg(io.BytesIO(packet[:-1] + b'x'))
        with self.assertRaises(ValueError):
            face.read_jpeg(io.BytesIO(b'FACE' + struct.pack('<I', 500001)))

    def test_capture_sends_team_hw_command(self):
        jpeg = b'\xff\xd8demo\xff\xd9'
        packet = b'FACE' + struct.pack('<I', len(jpeg)) + jpeg

        class FakePort(io.BytesIO):
            def __init__(self):
                super().__init__(packet)
                self.command = None
            def __enter__(self):
                return self
            def __exit__(self, *_):
                self.close()
            def reset_input_buffer(self):
                pass
            def write(self, value):
                self.command = value
                return len(value)
            def flush(self):
                pass

        port = FakePort()
        import sys
        from types import SimpleNamespace
        with patch.dict(sys.modules, {'serial': SimpleNamespace(Serial=lambda *a, **kw: port)}), \
                patch.object(face.time, 'sleep'):
            self.assertEqual(face.FaceService().capture(), jpeg)
        self.assertEqual(port.command, b'CAPTURE\n')

    def test_uart_truncated_and_stop(self):
        with self.assertRaises(TimeoutError):
            face.read_jpeg(io.BytesIO(b''), timeout=0.001)
        event = threading.Event()
        event.set()
        with face.session(stopped=event), self.assertRaises(RuntimeError):
            face.read_jpeg(io.BytesIO(b''))

    def test_legacy_npz_multiple_samples_and_normalization(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / 'embeddings'
            folder.mkdir()
            np.savez(folder / 'Andi.npz', embeddings=np.array([[2., 0.], [1., 0.]], dtype=np.float32))
            service = self.make_service(directory)
            with patch.dict(face.os.environ, {'XPLORIA_FACE_LEGACY_EMBEDDINGS_DIR': str(folder)}):
                self.assertEqual(service.operate('face_recognized')['name'], 'Andi')
                names, vectors = service.load_legacy_dataset(2)
                self.assertEqual(list(names), ['Andi', 'Andi'])
                self.assertTrue(np.allclose(np.linalg.norm(vectors, axis=1), 1))
                self.assertFalse(service.dataset.exists())

    def make_service(self, directory):
        service = face.FaceService()
        service.root = Path(directory)
        service.dataset = service.root / 'faces.npz'
        service.engine = None, np, None, None, 'test-model'
        service.capture = lambda: b'\xff\xd8fake\xff\xd9'
        service.feature = lambda jpeg: np.array([1., 0.], dtype=np.float32)
        return service

    def test_enroll_reload_recognize_append_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(directory)
            service.operate('face_enroll', 'Andi')
            reloaded = self.make_service(directory)
            self.assertEqual(reloaded.operate('face_recognized')['name'], 'Andi')
            reloaded.operate('face_enroll', 'Andi')
            names, _ = reloaded.load_dataset(2)
            self.assertEqual(list(names), ['Andi', 'Andi'])
            reloaded.feature = lambda _: np.array([0., 1.], dtype=np.float32)
            self.assertFalse(reloaded.operate('face_recognized')['recognized'])
            reloaded.operate('face_clear')
            self.assertFalse(reloaded.dataset.exists())

    def test_multiple_poses_count_limit_and_best_match(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(directory)
            first = service.operate('face_enroll', 'Andi')
            self.assertEqual(first['sample_count'], 1)
            service.feature = lambda _: np.array([0., 1.], dtype=np.float32)
            for expected in range(2, 6):
                packet = service.operate('face_enroll', 'Andi')
                self.assertEqual(packet['sample_count'], expected)
                self.assertTrue(packet['sample_added'])
            original = service.dataset.read_bytes()
            packet = service.operate('face_enroll', 'Andi')
            self.assertFalse(packet['sample_added'])
            self.assertEqual(service.dataset.read_bytes(), original)
            service.feature = lambda _: np.array([-1., 0.], dtype=np.float32)
            service.operate('face_enroll', 'Budi')
            service = self.make_service(directory)
            for pose in ([1., 0.], [0., 1.]):
                service.feature = lambda _, p=pose: np.array(p, dtype=np.float32)
                packet = service.operate('face_recognized')
                self.assertEqual(packet['name'], 'Andi')
                self.assertEqual(packet['sample_count'], 5)
                self.assertAlmostEqual(packet['similarity'], 1.)
                self.assertIn('threshold', packet)
            service.operate('face_clear')
            self.assertFalse(service.dataset.exists())

    def test_unrecognized_candidate_and_empty_score(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(directory)
            self.assertIsNone(service.operate('face_recognized')['similarity'])
            service.operate('face_enroll', 'Andi')
            service.feature = lambda _: np.array([0., 1.], dtype=np.float32)
            result = service.operate('face_recognized')
            self.assertFalse(result['recognized'])
            self.assertEqual(result['name'], '')
            self.assertEqual(result['candidate_name'], 'Andi')
            self.assertEqual(result['similarity'], 0.)

    def test_mismatched_dataset_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(directory)
            service.operate('face_enroll', 'Andi')
            original = service.dataset.read_bytes()
            service.engine = None, np, None, None, 'different-model'
            with self.assertRaises(ValueError):
                service.operate('face_enroll', 'Budi')
            self.assertEqual(service.dataset.read_bytes(), original)

    def test_missing_face_is_false_but_cannot_enroll(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(directory)
            with patch.object(service, 'feature', side_effect=face.FaceCountError('No face')):
                self.assertFalse(service.operate('face_recognized')['recognized'])
                with self.assertRaises(face.FaceCountError):
                    service.operate('face_enroll', 'Andi')
            self.assertFalse(service.dataset.exists())

    def test_result_correlation_cache_and_busy(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(directory)
            service.operate('face_enroll', 'Andi')
            packets = []
            with patch.object(face, '_service', service), face.session(packets.append, request_id='a'):
                self.assertTrue(face.is_recognized())
                self.assertEqual(face.get_recognized_name(), 'Andi')
                self.assertEqual(len(packets), 1)
                self.assertEqual(packets[0]['request_id'], 'a')
                with face._lock, self.assertRaises(RuntimeError):
                    face.capture_snapshot()
                self.assertEqual(packets[-1]['status'], 'error')


if __name__ == '__main__':
    unittest.main()
