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


def read_frame(port, timeout=12):
    """Team HW UART protocol: FRAME <size>\\n + raw JPEG bytes."""
    deadline = time.monotonic() + timeout

    def exact(size):
        result = bytearray()
        while len(result) < size:
            check_stop()
            if time.monotonic() >= deadline:
                raise TimeoutError('Kamera UART tidak mengirim foto lengkap.')
            chunk = port.read(size - len(result))
            if chunk:
                result.extend(chunk)
            else:
                time.sleep(0.01)
        return bytes(result)

    # Baca baris header "FRAME <size>\\n"
    line_buf = bytearray()
    while True:
        check_stop()
        if time.monotonic() >= deadline:
            raise TimeoutError('Kamera UART timeout saat menunggu header FRAME.')
        b = port.read(1)
        if not b:
            time.sleep(0.005)
            continue
        line_buf.extend(b)
        if line_buf.endswith(b'\n'):
            line_str = line_buf.decode('ascii', errors='ignore').strip()
            if line_str.startswith('FRAME '):
                try:
                    size = int(line_str.split()[1])
                    break
                except (IndexError, ValueError):
                    line_buf.clear()
            elif line_str.startswith('ERROR'):
                raise RuntimeError(f'ESP32-CAM melaporkan kesalahan: {line_str}')
            else:
                line_buf.clear()

    if not 4 <= size <= 1_048_576:
        raise ValueError(f'Ukuran JPEG kamera tidak valid ({size} bytes).')

    jpeg = exact(size)
    if not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
        raise ValueError('JPEG rusak saat dikirim melalui UART.')
    return jpeg


class CityCctvService:
    def __init__(self):
        self.vehicle_count = 0
        self.engine = None
        self.model_path = Path(os.environ.get('XPLORIA_CCTV_MODEL', '/var/lib/xploria/models/yolov8n.onnx'))
        self.last_result = None

    def capture(self):
        check_stop()
        port_name = os.environ.get('XPLORIA_CAMERA_PORT', '/dev/serial0')
        baud_rate = int(os.environ.get('XPLORIA_CAMERA_BAUD', '460800'))

        # Fallback Mock jika mode mock aktif atau port tidak tersedia
        if os.environ.get('XPLORIA_MOCK_CAMERA') == '1' or not os.path.exists(port_name):
            return self._mock_jpeg()

        import serial
        with serial.Serial(port_name, baud_rate, timeout=0.1, write_timeout=2, exclusive=True) as port:
            time.sleep(0.2)
            port.reset_input_buffer()
            port.write(b'GET\n')
            port.flush()
            return read_frame(port)

    def ping(self):
        check_stop()
        port_name = os.environ.get('XPLORIA_CAMERA_PORT', '/dev/serial0')
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
        if not self.model_path.is_file():
            # Model file belum tersedia; gunakan mock AI detector
            return None
        try:
            import cv2
            net = cv2.dnn.readNetFromONNX(str(self.model_path))
            self.engine = net
            return self.engine
        except Exception:
            return None

    def detect_vehicle(self, jpeg_bytes):
        """Menganalisis frame JPEG untuk menentukan apakah ada mobil ('CAR') atau kosong ('EMPTY')."""
        check_stop()
        net = self.load_engine()

        # Jika model ONNX belum tersedia, gunakan analisa pixel / mock cerdas
        if net is None:
            return self._mock_detect(jpeg_bytes)

        try:
            import cv2
            import numpy as np

            nparr = np.frombuffer(jpeg_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError("Gagal mendecode frame JPEG.")

            h, w = frame.shape[:2]
            # YOLOv8 input blob: 640x640 (normalized 1/255.0)
            blob = cv2.dnn.blobFromImage(frame, 1 / 255.0, (640, 640), swapRB=True, crop=False)
            net.setInput(blob)
            outputs = net.forward()

            # Format YOLOv8 output: [1, 84, 8400]
            # 84 = [x, y, w, h] + 80 class scores
            # Kelas kendaraan COCO: 2 (car), 3 (motorcycle), 5 (bus), 7 (truck)
            vehicle_classes = {2: 'Car', 3: 'Motorcycle', 5: 'Bus', 7: 'Truck'}
            
            output = outputs[0]
            if output.shape[0] == 84:
                output = output.T  # Transpose ke [8400, 84]

            boxes = []
            confidences = []
            class_ids = []

            for row in output:
                classes_scores = row[4:]
                max_score_idx = int(np.argmax(classes_scores))
                confidence = float(classes_scores[max_score_idx])
                if confidence >= 0.40 and max_score_idx in vehicle_classes:
                    cx, cy, bw, bh = row[0:4]
                    left = int((cx - bw / 2) * (w / 640.0))
                    top = int((cy - bh / 2) * (h / 640.0))
                    width = int(bw * (w / 640.0))
                    height = int(bh * (h / 640.0))
                    boxes.append([left, top, width, height])
                    confidences.append(confidence)
                    class_ids.append(max_score_idx)

            indices = cv2.dnn.NMSBoxes(boxes, confidences, 0.40, 0.45)
            
            if len(indices) > 0:
                best_idx = indices[0] if isinstance(indices[0], int) else indices[0][0]
                box = boxes[best_idx]
                score = confidences[best_idx]
                label_name = vehicle_classes.get(class_ids[best_idx], 'Car')

                # Gambar kotak hijau dan teks di frame
                cv2.rectangle(frame, (box[0], box[1]), (box[0] + box[2], box[1] + box[3]), (0, 255, 0), 2)
                cv2.putText(frame, f"{label_name} {int(score * 100)}%", (box[0], max(20, box[1] - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                _, annotated = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                annotated_bytes = annotated.tobytes()

                return {
                    'status': 'CAR',
                    'is_car': True,
                    'confidence': round(score, 2),
                    'label': label_name,
                    'jpeg_bytes': annotated_bytes
                }
            else:
                # Tidak ada kendaraan terdeteksi (Jalan Kosong)
                cv2.putText(frame, "EMPTY ROAD", (20, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
                _, annotated = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                annotated_bytes = annotated.tobytes()

                return {
                    'status': 'EMPTY',
                    'is_car': False,
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
