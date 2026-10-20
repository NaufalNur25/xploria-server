"""Optional UART face HAL. Importing this module requires no AI dependencies."""
import base64
from contextlib import contextmanager
import hashlib
import math
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
import uuid

_context = threading.local()
_lock = threading.Lock()
_service = None
COMMANDS = {'camera_capture', 'face_enroll', 'face_recognized', 'face_name', 'face_clear'}


class FaceCountError(ValueError):
    pass


@contextmanager
def session(emit=None, stopped=None, source='blockly', request_id=None, block_uid=None):
    previous = getattr(_context, 'state', None)
    _context.state = dict(emit=emit, stopped=stopped, source=source,
                          request_id=request_id, block_uid=block_uid, last=None)
    try:
        yield
    finally:
        _context.state = previous


def check_stop():
    state = getattr(_context, 'state', None) or {}
    if state.get('stopped') and state['stopped'].is_set():
        raise RuntimeError('Operasi kamera dibatalkan.')


def read_jpeg(port, timeout=12):
    """Team HW UART protocol: FACE + uint32 LE length + JPEG bytes."""
    deadline = time.monotonic() + timeout

    def exact(size):
        result = bytearray()
        while len(result) < size:
            check_stop()
            if time.monotonic() >= deadline:
                raise TimeoutError('Kamera UART tidak mengirim foto lengkap.')
            result.extend(port.read(size - len(result)))
        return bytes(result)

    marker = b''
    while marker != b'FACE':
        marker = (marker + exact(1))[-4:]
    size = struct.unpack('<I', exact(4))[0]
    if not 4 <= size <= 500_000:
        raise ValueError('Ukuran JPEG kamera tidak valid atau terlalu besar.')
    jpeg = exact(size)
    if not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
        raise ValueError('JPEG rusak saat dikirim melalui UART.')
    return jpeg


class FaceService:
    def __init__(self):
        self.root = Path(os.environ.get('XPLORIA_FACE_DIR', '/var/lib/xploria/faces'))
        self.dataset = self.root / 'faces.npz'
        self.engine = None

    def capture(self):
        import serial
        with serial.Serial(os.environ.get('XPLORIA_CAMERA_PORT', '/dev/serial0'),
                           int(os.environ.get('XPLORIA_CAMERA_BAUD', '460800')),
                           timeout=0.1, write_timeout=2, exclusive=True) as port:
            # The team's Raspberry Pi script waits after opening this UART.
            time.sleep(0.5)
            port.reset_input_buffer()
            port.write(b'CAPTURE\n')
            port.flush()
            return read_jpeg(port)

    def load_engine(self):
        if self.engine is not None:
            return self.engine
        import cv2
        import numpy as np
        detector_path = Path(os.environ.get('XPLORIA_FACE_DETECTOR', str(self.root / 'yunet.onnx')))
        recognizer_path = Path(os.environ.get('XPLORIA_FACE_RECOGNIZER', str(self.root / 'sface.onnx')))
        if not detector_path.is_file() or not recognizer_path.is_file():
            raise RuntimeError('Model yunet.onnx/sface.onnx belum dipasang.')
        model_id = hashlib.sha256(recognizer_path.read_bytes()).hexdigest()
        detector = cv2.FaceDetectorYN.create(str(detector_path), '', (320, 320), 0.6)
        recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), '')
        self.engine = cv2, np, detector, recognizer, model_id
        return self.engine

    def feature(self, jpeg):
        cv2, np, detector, recognizer, _ = self.load_engine()
        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError('JPEG tidak bisa dibaca.')
        detector.setInputSize((frame.shape[1], frame.shape[0]))
        _, faces = detector.detect(frame)
        if faces is None or len(faces) != 1:
            raise FaceCountError('Pastikan tepat satu wajah terlihat jelas di kamera.')
        vector = recognizer.feature(recognizer.alignCrop(frame, faces[0])).flatten()
        norm = np.linalg.norm(vector)
        if not np.isfinite(vector).all() or norm <= 0:
            raise ValueError('Fitur wajah tidak valid.')
        return (vector / norm).astype(np.float32)

    def load_dataset(self, dimension):
        _, np, _, _, model_id = self.load_engine()
        if not self.dataset.exists():
            return np.array([], dtype='<U60'), np.empty((0, dimension), dtype=np.float32)
        with np.load(self.dataset, allow_pickle=False) as data:
            if int(data['schema']) != 1 or str(data['model_id']) != model_id:
                raise ValueError('Dataset dibuat dengan format/model berbeda. Cadangkan lalu migrasikan dataset.')
            names, vectors = data['names'].copy(), data['embeddings'].copy()
        if (names.ndim != 1 or names.dtype.kind != 'U' or
                vectors.shape != (len(names), dimension) or not np.isfinite(vectors).all()):
            raise ValueError('Dataset wajah tidak valid; file tidak ditimpa.')
        norms = np.linalg.norm(vectors, axis=1)
        if len(norms) and not np.allclose(norms, 1, atol=0.001):
            raise ValueError('Embedding dataset tidak ternormalisasi.')
        return names, vectors

    def load_legacy_dataset(self, dimension):
        """Read the HW team's embeddings/<name>.npz files, without modifying them.

        This format does not record a model ID, so the operator must configure
        the same SFace ONNX file used to create the original embeddings.
        """
        _, np, _, _, _ = self.load_engine()
        directory = os.environ.get('XPLORIA_FACE_LEGACY_EMBEDDINGS_DIR')
        if not directory:
            return np.array([], dtype='<U60'), np.empty((0, dimension), dtype=np.float32)
        folder = Path(directory)
        if not folder.is_dir():
            raise ValueError('Folder embeddings lama tidak ditemukan: ' + str(folder))
        names, vectors = [], []
        for path in sorted(folder.glob('*.npz')):
            if not path.stem or len(path.stem) > 60:
                raise ValueError('Nama berkas NPZ lama tidak valid: ' + path.name)
            with np.load(path, allow_pickle=False) as data:
                if 'embeddings' in data:
                    raw = data['embeddings']
                elif len(data.files) == 1:
                    raw = data[data.files[0]]
                else:
                    raise ValueError('NPZ lama harus berisi key embeddings: ' + path.name)
            raw = np.asarray(raw, dtype=np.float32)
            if raw.ndim == 1:
                raw = raw.reshape(1, -1)
            if raw.ndim != 2 or raw.shape[1] != dimension or not np.isfinite(raw).all():
                raise ValueError('Embedding lama tidak valid: ' + path.name)
            norms = np.linalg.norm(raw, axis=1)
            if np.any(norms <= 0):
                raise ValueError('Embedding lama bernorma nol: ' + path.name)
            for vector in raw / norms[:, None]:
                names.append(path.stem)
                vectors.append(vector)
        if not names:
            return np.array([], dtype='<U60'), np.empty((0, dimension), dtype=np.float32)
        return np.asarray(names, dtype='<U60'), np.asarray(vectors, dtype=np.float32)

    def save_dataset(self, names, vectors):
        _, np, _, _, model_id = self.load_engine()
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.root, suffix='.npz')
        try:
            with os.fdopen(fd, 'wb') as stream:
                np.savez_compressed(stream, schema=np.array(1), model_id=np.array(model_id),
                                    names=names, embeddings=vectors)
                stream.flush()
                os.fsync(stream.fileno())
            check_stop()
            os.replace(temporary, self.dataset)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def operate(self, command, name=None):
        check_stop()
        if command == 'face_clear':
            self.dataset.unlink(missing_ok=True)
            legacy = os.environ.get('XPLORIA_FACE_LEGACY_EMBEDDINGS_DIR')
            message = ('Data wajah aplikasi dihapus; NPZ tim HW tetap aktif.' if legacy
                       else 'Semua data wajah aplikasi dihapus.')
            return {'message': message, 'recognized': False, 'name': ''}
        if command == 'face_enroll' and (not isinstance(name, str) or not name.strip() or len(name.strip()) > 60):
            raise ValueError('Nama harus berisi 1 sampai 60 karakter.')
        jpeg = self.capture()
        result = {'jpeg_base64': base64.b64encode(jpeg).decode('ascii')}
        check_stop()
        if command == 'camera_capture':
            return dict(result, message='Foto berhasil diambil.')
        try:
            vector = self.feature(jpeg)
        except FaceCountError as error:
            if command == 'face_enroll':
                raise
            return dict(result, recognized=False, name='', similarity=None, message=str(error))
        names, vectors = self.load_dataset(len(vector))
        _, np, _, _, _ = self.load_engine()
        check_stop()
        if command == 'face_enroll':
            name = name.strip()
            # Keep existing samples, including datasets created by earlier releases.
            count = int(np.count_nonzero(names == name))
            limit = 5
            if count >= limit:
                return dict(result, name=name, sample_count=count, max_samples=limit,
                            sample_added=False,
                            message='Sampel %s sudah lengkap (%s/%s).' % (name, count, limit))
            self.save_dataset(np.append(names, name), np.vstack((vectors, vector)))
            return dict(result, name=name, sample_count=count + 1, max_samples=limit,
                        sample_added=True,
                        message='Sampel %s tersimpan (%s/%s).' % (name, count + 1, limit))
        old_names, old_vectors = self.load_legacy_dataset(len(vector))
        if len(old_names):
            names = np.concatenate((names, old_names))
            vectors = np.vstack((vectors, old_vectors))
        scores = np.clip(vectors @ vector, -1., 1.) if len(names) else np.array([])
        score = float(np.max(scores)) if len(names) else None
        threshold = (float(name) if command == 'face_recognized' and name is not None
                     else float(os.environ.get('XPLORIA_FACE_THRESHOLD', '0.363')))
        if not -1 <= threshold <= 1:
            raise ValueError('Threshold cosine harus antara -1 dan 1.')
        recognized = score is not None and score >= threshold
        candidate = str(names[int(np.argmax(scores))]) if len(names) else ''
        name = candidate if recognized else ''
        return dict(result, recognized=recognized, name=name, similarity=score,
                    candidate_name=candidate, threshold=threshold,
                    sample_count=int(np.count_nonzero(names == candidate)) if candidate else 0,
                    message=('Dikenali: ' + name) if recognized else 'Wajah tidak dikenali.')


def perform(command, value=None):
    global _service
    if command not in COMMANDS:
        raise ValueError('Perintah kamera tidak didukung.')
    state = getattr(_context, 'state', None) or {}
    state['last'] = None
    packet = dict(type='camera_result', source=state.get('source', 'blockly'),
                  request_id=state.get('request_id') or uuid.uuid4().hex,
                  block_uid=state.get('block_uid'), hw_type='esp32_cam', channel=command)
    acquired = _lock.acquire(blocking=False)
    try:
        if not acquired:
            raise RuntimeError('Kamera sedang digunakan. Coba lagi setelah selesai.')
        check_stop()
        if _service is None:
            _service = FaceService()
        result = _service.operate(command, value)
        check_stop()
        state['last'] = result
        packet.update(result, status='ok')
        return result
    except Exception as error:
        packet.update(status='error', message=str(error))
        raise
    finally:
        if acquired:
            _lock.release()
        if state.get('emit') and not (state.get('stopped') and state['stopped'].is_set()):
            state['emit'](packet)


def capture_snapshot():
    perform('camera_capture')
    return True


def enroll(name):
    perform('face_enroll', name)
    return True


def is_recognized():
    return perform('face_recognized')['recognized']


def is_recognized_at_least(percent):
    """Capture once and compare its cosine score to a Blockly percentage (0-100)."""
    if isinstance(percent, bool):
        raise ValueError('Batas kemiripan harus angka antara 0 dan 100.')
    try:
        percent = float(percent)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError('Batas kemiripan harus angka antara 0 dan 100.') from error
    if not math.isfinite(percent) or not 0 <= percent <= 100:
        raise ValueError('Batas kemiripan harus angka antara 0 dan 100.')
    return perform('face_recognized', percent / 100)['recognized']


def get_last_similarity_percent():
    """Read the most recent recognition score without asking the camera again."""
    result = (getattr(_context, 'state', None) or {}).get('last') or {}
    score = result.get('similarity') if 'recognized' in result else None
    return round(max(0.0, min(1.0, float(score))) * 100, 1) if score is not None else 0.0


def get_recognized_name():
    state = getattr(_context, 'state', None) or {}
    result = state.get('last')
    if result is None or 'recognized' not in result:
        result = perform('face_name')
    return result.get('name', '')


def clear_database():
    perform('face_clear')
    return True
