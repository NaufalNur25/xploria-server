"""
vehicle_hal.cv_follower — OpenCV-Based Person & Lane Tracker (Edge Computer Vision on Raspberry Pi)
====================================================================================================
Modul visi komputer real-time yang dieksekusi secara lokal di Raspberry Pi (bukan di aplikasi mobile).
Mendukung:
  1. Deteksi Keberadaan Orang (HOG / Haar Cascade Person Detector).
  2. Kalkulasi Koordinat Offset Horizontal X (-100 s/d +100) relatif terhadap pusat frame.
  3. Estimasi Jarak Orang (cm) berbasis luas dan tinggi bounding box kamera.
  4. Deteksi Marka Lajur Jalan (Lane Line Offset) untuk proyek Autonomous Vehicle.
"""

import sys
import time
import threading

# Coba impor OpenCV lokal Raspberry Pi
_cv2 = None
try:
    import cv2
    _cv2 = cv2
except Exception:
    _cv2 = None


def _safe_log(msg: str):
    try:
        if hasattr(sys, 'is_finalizing') and sys.is_finalizing():
            return
        if sys and hasattr(sys, 'stderr') and sys.stderr is not None:
            sys.stderr.write(str(msg) + "\n")
            sys.stderr.flush()
    except Exception:
        pass


class VisionFollowerHAL:
    """
    Edge Computer Vision Tracker running locally on Raspberry Pi.
    Menyediakan data sensor visi untuk logika kendali robot (STEM problem-solving).
    """

    def __init__(self, camera_index: int = 0):
        self._cam_idx = camera_index
        self._cap = None
        self._running = False
        self._thread = None
        self._lock = threading.Lock()

        # Telemetri Visi Terkini
        self._person_detected = False
        self._person_offset_x = 0.0     # -100 (kiri) s/d +100 (kanan), 0 = tengah
        self._person_distance_cm = 100.0 # estimasi jarak 30 - 300 cm
        self._lane_offset_x = 0.0       # deviasi lajur jalan (-100 s/d +100)
        self._frame_width = 640
        self._frame_height = 480
        self._last_process_time = 0.0

        # Detektor OpenCV
        self._hog = None
        if _cv2 is not None:
            try:
                self._hog = _cv2.HOGDescriptor()
                self._hog.setSVMDetector(_cv2.HOGDescriptor_getDefaultPeopleDetector())
            except Exception as e:
                _safe_log(f"[vehicle_hal.vision] Warning HOG init: {e}")

    def start_camera(self):
        """Mulai worker thread pembaca kamera lokal jika belum aktif."""
        with self._lock:
            if self._running:
                return
            self._running = True

        def _worker():
            _safe_log("[vehicle_hal.vision] 📷 Memulai kamera lokal OpenCV di Raspberry Pi...")
            if _cv2 is not None:
                try:
                    self._cap = _cv2.VideoCapture(self._cam_idx)
                    self._cap.set(_cv2.CAP_PROP_FRAME_WIDTH, 320)
                    self._cap.set(_cv2.CAP_PROP_FRAME_HEIGHT, 240)
                except Exception as e:
                    _safe_log(f"[vehicle_hal.vision] Error VideoCapture: {e}")
                    self._cap = None

            while self._running:
                try:
                    if self._cap is not None and self._cap.isOpened():
                        ret, frame = self._cap.read()
                        if ret and frame is not None:
                            self._process_frame(frame)
                    else:
                        # Fallback jika tidak ada kamera hardware fisik terpasang
                        time.sleep(0.1)
                except Exception:
                    time.sleep(0.1)

                time.sleep(0.05)  # Batasi ~15-20 FPS agar hemat daya CPU RPi

            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
            _safe_log("[vehicle_hal.vision] 🛑 Kamera lokal OpenCV dihentikan.")

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def stop_camera(self):
        """Hentikan pembacaan kamera lokal."""
        with self._lock:
            self._running = False

    def _process_frame(self, frame):
        """Memproses satu frame untuk deteksi orang & marka lajur jalan."""
        h, w = frame.shape[:2]
        self._frame_width = w
        self._frame_height = h

        # 1. Deteksi Orang (People Tracking via HOG)
        detected = False
        off_x = 0.0
        dist_cm = 100.0

        if self._hog is not None and _cv2 is not None:
            try:
                # Resize cepat untuk performa real-time
                small = _cv2.resize(frame, (320, 240))
                boxes, weights = self._hog.detectMultiScale(small, winStride=(8, 8), padding=(4, 4), scale=1.05)
                if len(boxes) > 0:
                    # Ambil bounding box orang terbesar / terdekat
                    largest_box = max(boxes, key=lambda b: b[2] * b[3])
                    bx, by, bw, bh = largest_box
                    center_x = bx + (bw / 2.0)
                    # Normalisasi koordinat X terhadap tengah frame (-100 s/d +100)
                    off_x = ((center_x - 160.0) / 160.0) * 100.0
                    off_x = max(-100.0, min(100.0, round(off_x, 1)))

                    # Estimasi jarak ToF berbasis perbandingan optik tinggi bbox (240px frame)
                    # Tinggi bh orang ~ 180px saat jarak 50cm, ~ 60px saat jarak 150cm
                    if bh > 10:
                        dist_calc = (50.0 * 180.0) / float(bh)
                        dist_cm = max(20.0, min(300.0, round(dist_calc, 1)))
                    detected = True
            except Exception:
                pass

        # 2. Deteksi Marka Lajur Jalan (Lane Tracking via Grayscale & Threshold)
        lane_off = 0.0
        if _cv2 is not None:
            try:
                gray = _cv2.cvtColor(frame, _cv2.COLOR_BGR2GRAY)
                # Ambil Region of Interest (ROI) bagian bawah frame (jalan)
                roi = gray[int(h * 0.7):, :]
                _, thresh = _cv2.threshold(roi, 200, 255, _cv2.THRESH_BINARY)
                moments = _cv2.moments(thresh)
                if moments["m00"] > 0:
                    cx = int(moments["m10"] / moments["m00"])
                    lane_off = ((cx - (w / 2.0)) / (w / 2.0)) * 100.0
                    lane_off = max(-100.0, min(100.0, round(lane_off, 1)))
            except Exception:
                pass

        with self._lock:
            self._person_detected = detected
            self._person_offset_x = off_x
            self._person_distance_cm = dist_cm
            self._lane_offset_x = lane_off
            self._last_process_time = time.time()

    # === METODE PUBLIK SENSOR VISI (UNTUK BLOK BLOCKLY SISWA) ===

    def is_person_detected(self) -> bool:
        """Reporter: True jika terdapat manusia terdeteksi di kamera."""
        if not self._running:
            self.start_camera()
        with self._lock:
            return self._person_detected

    def get_person_offset_x(self) -> float:
        """
        Reporter: Nilai deviasi posisi orang (-100.0 s/d +100.0):
        - Nilai negatif (< 0) : Orang berada di sisi Kiri
        - Nilai nol (0.0)     : Orang berada tepat di Tengah
        - Nilai positif (> 0) : Orang berada di sisi Kanan
        """
        if not self._running:
            self.start_camera()
        with self._lock:
            return self._person_offset_x

    def get_person_distance(self) -> float:
        """Reporter: Estimasi jarak orang ke kamera dalam centimeter (cm)."""
        if not self._running:
            self.start_camera()
        with self._lock:
            return self._person_distance_cm

    def get_lane_offset(self) -> float:
        """Reporter: Posisi garis marka jalan di kamera (-100 s/d +100)."""
        if not self._running:
            self.start_camera()
        with self._lock:
            return self._lane_offset_x

    def set_mock_person(self, detected: bool, offset_x: float = 0.0, distance_cm: float = 80.0):
        """Memungkinkan pengujian logika STEM pada simulator atau saat kamera offline."""
        with self._lock:
            self._person_detected = detected
            self._person_offset_x = max(-100.0, min(100.0, float(offset_x)))
            self._person_distance_cm = max(10.0, min(400.0, float(distance_cm)))

    def get_telemetry(self) -> dict:
        with self._lock:
            return {
                "person_detected": self._person_detected,
                "person_offset_x": self._person_offset_x,
                "person_distance": self._person_distance_cm,
                "lane_offset": self._lane_offset_x
            }


# Singleton Visi Komputer
vision = VisionFollowerHAL()
cv_follower = vision
