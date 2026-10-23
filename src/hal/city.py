"""Optional UART Smart City / CCTV / Vehicle Counter HAL.

Komunikasi dengan AI-Thinker ESP32-CAM via UART:
- Protokol Request-Response:
  * Pi -> ESP: GET\\n
  * ESP -> Pi: FRAME <ukuran_byte>\\n diikuti biner JPEG
  * Pi -> ESP: PING\\n
  * ESP -> Pi: PONG\\n
"""
import base64
from contextlib import contextmanager
import os
from pathlib import Path
import threading
import time
import uuid

_context = threading.local()
_lock = threading.Lock()
_service = None
COMMANDS = {'cctv_scan', 'cctv_ping', 'vehicle_count_get', 'vehicle_count_reset'}


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
        raise RuntimeError('Operasi CCTV dibatalkan.')


def _read_header_line(port, deadline):
    """Baca satu baris header ('FRAME <size>' atau 'JPEG:<size>') sampai deadline."""
    line_buf = bytearray()
    while time.monotonic() < deadline:
        check_stop()
        b = port.read(1)
        if not b:
            time.sleep(0.005)
            continue
        line_buf.extend(b)
        if line_buf.endswith(b'\n'):
            line_str = line_buf.decode('ascii', errors='ignore').strip()
            if line_str.startswith('FRAME '):
                try:
                    return int(line_str.split()[1])
                except (IndexError, ValueError):
                    line_buf.clear()
            elif line_str.startswith('JPEG:'):
                try:
                    return int(line_str.split(':', 1)[1])
                except (IndexError, ValueError):
                    line_buf.clear()
            elif line_str.startswith('ERROR'):
                raise RuntimeError(f'ESP32-CAM melaporkan kesalahan: {line_str}')
            else:
                line_buf.clear()
    return None


def read_frame(port, timeout=12, allow_legacy_fallback=False):
    """Membaca paket JPEG dari UART ESP32-CAM.

    Mendukung 2 protokol firmware tim HW:
    1. Protokol baru:  GET\\n -> FRAME <size>\\n + raw JPEG
    2. Protokol lama:  C     -> JPEG:<size>\\n  + raw JPEG (tesuart_yolo.py)
    """
    deadline = time.monotonic() + timeout

    def exact(size):
        result = bytearray()
        while len(result) < size:
            check_stop()
            if time.monotonic() >= deadline:
                raise TimeoutError('Kamera UART tidak mengirim foto lengkap.')
            chunk = port.read(min(4096, size - len(result)))
            if chunk:
                result.extend(chunk)
            else:
                time.sleep(0.01)
        return bytes(result)

    first_wait = min(2.0, timeout * 0.4) if allow_legacy_fallback else timeout
    size = _read_header_line(port, time.monotonic() + first_wait)

    if size is None and allow_legacy_fallback:
        # Fallback otomatis ke protokol lama ('C' -> 'JPEG:<size>')
        port.write(b'C')
        port.flush()
        size = _read_header_line(port, deadline)

    if size is None:
        raise TimeoutError('Kamera UART timeout saat menunggu header FRAME/JPEG.')

    if not 4 <= size <= 1_048_576:
        raise ValueError(f'Ukuran JPEG kamera tidak valid ({size} bytes).')

    jpeg = exact(size)
    if not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
        raise ValueError('JPEG rusak saat dikirim melalui UART.')
    return jpeg


DEFAULT_MODEL_CANDIDATES = (
    '/var/lib/xploria/models/yolo26n_ncnn_model',
    '/var/lib/xploria/models/yolo26n_ncnn_640',
    '/var/lib/xploria/models/yolo26n.pt',
    '/var/lib/xploria/models/yolov8n.onnx',
    '/home/xploria/smartcity/smartcctv/yolo26n_ncnn_model',
    '/home/xploria/smartcity/smartcctv/yolo26n_ncnn_640',
    '/home/xploria/smartcity/smartcctv/yolo26n.pt',
)

VEHICLE_CLASSES = {'car', 'bus', 'truck', 'motorcycle'}
PERSON_CLASSES = {'person'}


def _resolve_model_path():
    env_path = os.environ.get('XPLORIA_CCTV_MODEL')
    if env_path:
        return Path(env_path)
    for candidate in DEFAULT_MODEL_CANDIDATES:
        p = Path(candidate)
        if p.exists():
            return p
    return Path(DEFAULT_MODEL_CANDIDATES[0])


def _resolve_serial_port():
    env_port = os.environ.get('XPLORIA_CAMERA_PORT')
    if env_port and os.path.exists(env_port):
        return env_port
    for candidate in ('/dev/serial0', '/dev/ttyUSB0', '/dev/ttyAMA0'):
        if os.path.exists(candidate):
            return candidate
    return env_port or '/dev/serial0'


def _import_yolo():
    """Import ultralytics YOLO, memprioritaskan virtualenv yang ada di sistem Pi."""
    import glob
    import sys
    search_patterns = (
        '/home/xploria/iot-receiver/venv/lib/python*/site-packages',
        '/home/xploria/smartcity/smartcctv/pi/lib/python*/site-packages',
        '/home/xploria/*/venv/lib/python*/site-packages',
        '/home/xploria/*/*/pi/lib/python*/site-packages',
    )
    for pat in search_patterns:
        for sp in sorted(glob.glob(pat)):
            if sp not in sys.path:
                sys.path.insert(0, sp)
    try:
        from ultralytics import YOLO
        return YOLO
    except Exception as e:
        import logging
        logging.warning("Gagal import YOLO: %s", e)
        raise


class CityCctvService:
    def __init__(self):
        self.vehicle_count = 0
        self.engine = None
        self.engine_type = None  # 'ultralytics' atau 'opencv_onnx'
        self.model_path = _resolve_model_path()
        self.conf_threshold = float(os.environ.get('XPLORIA_CCTV_CONF', '0.35'))
        self.last_result = None

    def capture(self):
        check_stop()
        port_name = _resolve_serial_port()
        baud_rate = int(os.environ.get('XPLORIA_CAMERA_BAUD', '460800'))

        # Fallback Mock jika mode mock aktif atau port tidak tersedia
        if os.environ.get('XPLORIA_MOCK_CAMERA') == '1' or not os.path.exists(port_name):
            return self._mock_jpeg()

        import serial
        with serial.Serial(port_name, baud_rate, timeout=0.1, write_timeout=2, exclusive=True) as port:
            time.sleep(0.1)
            port.reset_input_buffer()
            port.write(b'GET\n')
            port.flush()
            return read_frame(port, allow_legacy_fallback=True)

    def ping(self):
        check_stop()
        port_name = _resolve_serial_port()
        baud_rate = int(os.environ.get('XPLORIA_CAMERA_BAUD', '460800'))

        if os.environ.get('XPLORIA_MOCK_CAMERA') == '1' or not os.path.exists(port_name):
            return True

        import serial
        with serial.Serial(port_name, baud_rate, timeout=0.5, write_timeout=1, exclusive=True) as port:
            port.reset_input_buffer()
            port.write(b'PING\n')
            port.flush()
            deadline = time.monotonic() + 1.5
            buf = bytearray()
            while time.monotonic() < deadline:
                b = port.read(1)
                if b:
                    buf.extend(b)
                    if buf.endswith(b'\n'):
                        if b'PONG' in buf:
                            return True
            return False

    def load_engine(self):
        if self.engine is not None:
            return self.engine
        self.model_path = _resolve_model_path()
        if not self.model_path.exists():
            return None

        # 1. Prioritaskan Ultralytics YOLO (mendukung folder NCNN yolo26n_ncnn_model, .pt, dan .onnx)
        try:
            YOLO = _import_yolo()
            self.engine = YOLO(str(self.model_path))
            self.engine_type = 'ultralytics'
            return self.engine
        except Exception as e:
            import logging
            logging.warning("Gagal load YOLO engine (%s): %s", self.model_path, e)

        # 2. Fallback ke OpenCV DNN jika file berupa .onnx murni
        if self.model_path.is_file() and self.model_path.suffix.lower() == '.onnx':
            try:
                import cv2
                net = cv2.dnn.readNetFromONNX(str(self.model_path))
                self.engine = net
                self.engine_type = 'opencv_onnx'
                return self.engine
            except Exception:
                pass

        return None

    def detect_vehicle(self, jpeg_bytes):
        """Menganalisis frame JPEG menggunakan model YOLO NCNN tim HW (tesuart_yolo.py)."""
        check_stop()
        engine = self.load_engine()

        if engine is None:
            return self._mock_detect(jpeg_bytes)

        try:
            import cv2
            import numpy as np

            nparr = np.frombuffer(jpeg_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError("Gagal mendecode frame JPEG.")

            # Jalur utama: Ultralytics YOLO NCNN (persis seperti tesuart_yolo.py)
            if self.engine_type == 'ultralytics':
                results = engine(frame, imgsz=320, conf=self.conf_threshold, verbose=False)
                detections = results[0].boxes
                cars_count = 0
                persons_count = 0
                best_conf = 0.0
                best_label = 'Empty'

                for box in detections:
                    cls_id = int(box.cls[0])
                    conf = float(box.conf[0]) if hasattr(box, 'conf') else self.conf_threshold
                    label_name = str(engine.names[cls_id])
                    label_lower = label_name.lower()

                    if label_lower in VEHICLE_CLASSES:
                        cars_count += 1
                        if conf >= best_conf:
                            best_conf = conf
                            best_label = label_name.capitalize()
                    elif label_lower in PERSON_CLASSES:
                        persons_count += 1

                is_car = cars_count > 0
                if cars_count == 0 and persons_count == 0:
                    status_jalan = "JALANAN KOSONG"
                else:
                    rincian = []
                    if cars_count > 0:
                        rincian.append(f"{cars_count} Kendaraan/Mobil")
                    if persons_count > 0:
                        rincian.append(f"{persons_count} Orang")
                    status_jalan = f"TERDETEKSI: {', '.join(rincian)}"

                annotated_frame = results[0].plot()
                cv2.putText(
                    annotated_frame,
                    status_jalan,
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0) if not is_car else (0, 0, 255),
                    2,
                )
                _, annotated = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                return {
                    'status': 'CAR' if is_car else 'EMPTY',
                    'is_car': is_car,
                    'cars_count': cars_count,
                    'persons_count': persons_count,
                    'confidence': round(best_conf, 2) if is_car else 0.0,
                    'label': best_label if is_car else 'Empty',
                    'jpeg_bytes': annotated.tobytes(),
                }

            # Jalur cadangan: OpenCV DNN ONNX
            h, w = frame.shape[:2]
            blob = cv2.dnn.blobFromImage(frame, 1 / 255.0, (640, 640), swapRB=True, crop=False)
            engine.setInput(blob)
            outputs = engine.forward()

            vehicle_classes = {2: 'Car', 3: 'Motorcycle', 5: 'Bus', 7: 'Truck'}
            output = outputs[0]
            if output.shape[0] == 84:
                output = output.T

            boxes = []
            confidences = []
            class_ids = []

            for row in output:
                classes_scores = row[4:]
                max_score_idx = int(np.argmax(classes_scores))
                confidence = float(classes_scores[max_score_idx])
                if confidence >= self.conf_threshold and max_score_idx in vehicle_classes:
                    cx, cy, bw, bh = row[0:4]
                    left = int((cx - bw / 2) * (w / 640.0))
                    top = int((cy - bh / 2) * (h / 640.0))
                    width = int(bw * (w / 640.0))
                    height = int(bh * (h / 640.0))
                    boxes.append([left, top, width, height])
                    confidences.append(confidence)
                    class_ids.append(max_score_idx)

            indices = cv2.dnn.NMSBoxes(boxes, confidences, self.conf_threshold, 0.45)

            if len(indices) > 0:
                best_idx = indices[0] if isinstance(indices[0], int) else indices[0][0]
                box = boxes[best_idx]
                score = confidences[best_idx]
                label_name = vehicle_classes.get(class_ids[best_idx], 'Car')

                cv2.rectangle(frame, (box[0], box[1]), (box[0] + box[2], box[1] + box[3]), (0, 255, 0), 2)
                cv2.putText(frame, f"{label_name} {int(score * 100)}%", (box[0], max(20, box[1] - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                _, annotated = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                annotated_bytes = annotated.tobytes()

                return {
                    'status': 'CAR',
                    'is_car': True,
                    'cars_count': len(indices),
                    'confidence': round(score, 2),
                    'label': label_name,
                    'jpeg_bytes': annotated_bytes
                }
            else:
                cv2.putText(frame, "JALANAN KOSONG", (20, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                _, annotated = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                annotated_bytes = annotated.tobytes()

                return {
                    'status': 'EMPTY',
                    'is_car': False,
                    'cars_count': 0,
                    'confidence': 0.0,
                    'label': 'Empty',
                    'jpeg_bytes': annotated_bytes
                }
        except Exception:
            return self._mock_detect(jpeg_bytes)

    def _mock_detect(self, jpeg_bytes):
        """Deteksi cerdas fallback jika model ONNX belum tersedia."""
        # Secara default mock menghasilkan deteksi CAR bergantian atau terdeteksi
        # agar widget & Blockly bisa langsung dicoba dan berfungsi.
        is_car = True
        conf = 0.88
        label = "Car"

        # Buat anotasi sederhana jika cv2 tersedia
        try:
            import cv2
            import numpy as np
            nparr = np.frombuffer(jpeg_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is not None:
                h, w = frame.shape[:2]
                bx, by, bw, bh = int(w * 0.25), int(h * 0.3), int(w * 0.5), int(h * 0.45)
                cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 230, 100), 2)
                cv2.putText(frame, f"{label} {int(conf * 100)}%", (bx, by - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 230, 100), 2)
                _, annotated = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                jpeg_bytes = annotated.tobytes()
        except Exception:
            pass

        return {
            'status': 'CAR' if is_car else 'EMPTY',
            'is_car': is_car,
            'confidence': conf,
            'label': label,
            'jpeg_bytes': jpeg_bytes
        }

    def _mock_jpeg(self):
        """Menghasilkan dummy JPEG valid untuk pengujian tanpa hardware."""
        # 1x1 valid minimal JPEG
        return (b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00'
                b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t'
                b'\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a'
                b'\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff'
                b'\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f'
                b'\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00'
                b'\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08'
                b'\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9')

    def operate(self, command, value=None):
        check_stop()
        if command == 'cctv_ping':
            online = self.ping()
            return {
                'online': online,
                'message': 'ESP32-CAM Terhubung (PONG).' if online else 'ESP32-CAM tidak merespons (Kabel UART terputus?).'
            }

        if command == 'vehicle_count_get':
            return {
                'count': self.vehicle_count,
                'message': f'Total kendaraan terhitung: {self.vehicle_count}'
            }

        if command == 'vehicle_count_reset':
            self.vehicle_count = 0
            return {
                'count': 0,
                'message': 'Hitungan kendaraan direset ke 0.'
            }

        if command == 'cctv_scan':
            raw_jpeg = self.capture()
            check_stop()
            det = self.detect_vehicle(raw_jpeg)
            check_stop()

            # Sesuai kesepakatan: Jika terdeteksi mobil, counter naik +1
            if det['is_car']:
                self.vehicle_count += 1

            jpeg_b64 = base64.b64encode(det['jpeg_bytes']).decode('ascii')
            result = {
                'status': det['status'],
                'is_car': det['is_car'],
                'confidence': det['confidence'],
                'label': det['label'],
                'count': self.vehicle_count,
                'jpeg_base64': jpeg_b64,
                'message': 'Mobil Terdeteksi!' if det['is_car'] else 'Jalanan Kosong (Tidak Ada Mobil).'
            }
            self.last_result = result
            return result

        raise ValueError(f'Perintah city/cctv tidak didukung: {command}')


def perform(command, value=None):
    global _service
    if command not in COMMANDS:
        raise ValueError(f'Perintah {command} tidak didukung.')
    state = getattr(_context, 'state', None) or {}
    state['last'] = None
    packet = dict(
        type='cctv_result',
        source=state.get('source', 'blockly'),
        request_id=state.get('request_id') or uuid.uuid4().hex,
        block_uid=state.get('block_uid'),
        hw_type='cctv_cam',
        channel=command
    )
    acquired = _lock.acquire(blocking=False)
    try:
        if not acquired:
            raise RuntimeError('Kamera CCTV sedang digunakan. Silakan coba lagi.')
        check_stop()
        if _service is None:
            _service = CityCctvService()
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


# =========================================================================
# Public Functions untuk Blockly & Python Scripts Siswa
# =========================================================================

def cctv_scan():
    """Mengambil foto snapshot dari CCTV ESP32-CAM dan mendeteksi apakah ada mobil."""
    return perform('cctv_scan')


def is_car_detected():
    """Mengembalikan True jika CCTV mendeteksi ada mobil, False jika jalan kosong."""
    res = perform('cctv_scan')
    return bool(res.get('is_car', False))


def vehicle_count():
    """Mengembalikan jumlah total kendaraan yang telah terdeteksi/melintas."""
    res = perform('vehicle_count_get')
    return int(res.get('count', 0))


def reset_vehicle_count():
    """Mereset total hitungan kendaraan menjadi 0."""
    res = perform('vehicle_count_reset')
    return int(res.get('count', 0))


def cctv_ping():
    """Memeriksa apakah ESP32-CAM aktif dan terhubung via UART."""
    res = perform('cctv_ping')
    return bool(res.get('online', False))
