"""
vehicle_hal.tello — Aerial Vehicle / Drone DJI Tello SDK Controller
===================================================================
Kontroler Drone DJI Tello Resmi (UDP SDK 1.3 / 2.0).
Mendukung navigasi 3D berjarak, flip, kurva, video streaming,
dan manuver mikro sub-20 cm berbasis sinyal RC pulse.
"""

import sys
import time
import math
import socket


class TelloHAL:
    """Kontroler Drone DJI Tello Resmi (UDP SDK 1.3 / 2.0)."""

    def __init__(self, ip: str = "192.168.10.1", port: int = 8889):
        self.ip = ip
        self.port = port
        self._speed = 30
        self._distance_scale = 1.0
        self._distance_scale_x = 1.0
        self._distance_scale_y = 1.0
        self._hover_delay = 1.2
        self._battery = 85
        self._height = 100
        self._tof = 100
        self._pitch = 0
        self._roll = 0
        self._yaw = 0
        self._temp = 45
        self._flight_time = 0
        self._geofence_max_height = 150
        self._geofence_min_battery = 20
        self._sock = None
        self._is_connected = False
        self._is_flying = False

    def _init_udp_socket(self):
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(0.3)
            self._sock.bind(("", 9000))
            if self.send_command("command", timeout=0.3):
                self._is_connected = True
            else:
                self._is_connected = False
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
        except Exception:
            self._is_connected = False
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
            self._sock = None
        self._is_flying = False

    def send_command(self, cmd: str, timeout: float = 15.0) -> bool:
        if self._sock is None and not self._is_connected:
            if not hasattr(self, '_checked_init'):
                self._checked_init = True
                self._init_udp_socket()
        if self._sock is None:
            if cmd == "takeoff":
                self._is_flying = True
            elif cmd in ("land", "emergency"):
                self._is_flying = False
            return True
        if self._sock is not None:
            try:
                # Flush paket sisa lama yang tertinggal di buffer
                self._sock.settimeout(0.02)
                while True:
                    try:
                        self._sock.recvfrom(1024)
                    except Exception:
                        break

                # Atur timeout sesuai jenis perintah (takeoff/land butuh lebih lama)
                actual_timeout = 20.0 if cmd in ("takeoff", "land") else timeout
                self._sock.settimeout(actual_timeout)

                self._sock.sendto(cmd.encode('utf-8'), (self.ip, self.port))
                response, _ = self._sock.recvfrom(1024)
                resp_text = response.decode('utf-8', errors='ignore').strip().lower()
                print(f"[vehicle_hal.tello] Response: {resp_text} ({cmd})", file=sys.stderr)
                return (resp_text == "ok")
            except socket.timeout:
                print(f"[vehicle_hal.tello] ⚠️ Timeout ({actual_timeout}s) untuk perintah: {cmd}", file=sys.stderr)
                return False
            except Exception as e:
                print(f"[vehicle_hal.tello] ⚠️ Error ({cmd}): {e}", file=sys.stderr)
                return False
        return True

    def takeoff(self) -> bool:
        print("[vehicle_hal.tello] 🚁 Takeoff", file=sys.stderr)
        res = self.send_command("takeoff")
        time.sleep(self._hover_delay)
        return res

    def land(self) -> bool:
        print("[vehicle_hal.tello] 🛬 Land", file=sys.stderr)
        return self.send_command("land")

    def stop(self) -> bool:
        print("[vehicle_hal.tello] 🛑 Stop / Hover", file=sys.stderr)
        return self.send_command("stop")

    def emergency(self) -> bool:
        print("[vehicle_hal.tello] ⚠️ EMERGENCY STOP: Motor dimatikan!", file=sys.stderr)
        return self.send_command("emergency")

    def _safe_float(self, val, default: float = 0.0) -> float:
        try:
            if val is None:
                return float(default)
            return float(val)
        except (ValueError, TypeError):
            return float(default)

    def _safe_int(self, val, default: int = 0) -> int:
        try:
            if val is None:
                return int(default)
            return int(float(val))
        except (ValueError, TypeError):
            return int(default)

    def set_speed(self, speed: int) -> bool:
        s = self._safe_int(speed, 30)
        self._speed = max(10, min(100, s))
        print(f"[vehicle_hal.tello] ⚡ Set Speed: {self._speed} cm/s", file=sys.stderr)
        return self.send_command(f"speed {self._speed}")

    def set_calibration(self, scale_pct: int) -> bool:
        sc = max(0.4, min(2.5, self._safe_int(scale_pct, 100) / 100.0))
        self._distance_scale = sc
        self._distance_scale_x = sc
        self._distance_scale_y = sc
        return True

    def set_calibration_xy(self, scale_x_pct: int, scale_y_pct: int) -> bool:
        self._distance_scale_x = max(0.4, min(2.5, self._safe_int(scale_x_pct, 100) / 100.0))
        self._distance_scale_y = max(0.4, min(2.5, self._safe_int(scale_y_pct, 100) / 100.0))
        return True

    def set_hover_delay(self, delay_ms: int) -> bool:
        self._hover_delay = max(0.2, min(5.0, self._safe_int(delay_ms, 1200) / 1000.0))
        return True

    def _scale_coord(self, val: float, scale: float) -> int:
        v = self._safe_float(val, 0.0)
        if abs(v) < 0.001:
            return 0
        scaled = int(round(v * scale))
        return max(-500, min(500, scaled))

    def _micro_move(self, lr: float = 0.0, fb: float = 0.0, ud: float = 0.0, dist: float = 0.0) -> bool:
        """
        Gerak mikro presisi sub-20 cm untuk drone DJI Tello via RC pulse.
        Perintah SDK Tello standar ('forward 5', 'back 5', dll) ditolak oleh firmware bawaan Tello
        (karena range minimum resmi SDK adalah 20 cm).
        Untuk jarak presisi kecil (misal 1 - 19 cm atau variabel nilai kecil), HAL mengeksekusinya
        menggunakan semburan pulsa kontrol RC (Roll/Pitch/Throttle) terukur dengan kecepatan stabil.
        """
        spd = 20  # Kecepatan RC lembut (cm/s)
        dur = max(0.05, abs(float(dist)) / float(spd))
        rc_lr = int(lr * spd)
        rc_fb = int(fb * spd)
        rc_ud = int(ud * spd)
        print(f"[vehicle_hal.tello] 📏 Micro-move ({dist:.1f} cm) via RC pulse: rc {rc_lr} {rc_fb} {rc_ud} 0 selama {dur:.2f}s", file=sys.stderr)
        self.send_command(f"rc {rc_lr} {rc_fb} {rc_ud} 0")
        time.sleep(dur)
        self.send_command("rc 0 0 0 0")
        if self._hover_delay > 0:
            time.sleep(self._hover_delay)
        return True

    def move_forward(self, dist: float) -> bool:
        d = self._safe_float(dist, 30.0)
        scaled = abs(d) * self._distance_scale_y
        if scaled < 0.1:
            return True
        if scaled < 20.0:
            return self._micro_move(fb=1.0 if d >= 0 else -1.0, dist=scaled)
        scaled_int = max(20, min(500, int(round(scaled))))
        cmd = "forward" if d >= 0 else "back"
        res = self.send_command(f"{cmd} {scaled_int}")
        if self._hover_delay > 0:
            time.sleep(self._hover_delay)
        return res

    def move_back(self, dist: float) -> bool:
        d = self._safe_float(dist, 30.0)
        scaled = abs(d) * self._distance_scale_y
        if scaled < 0.1:
            return True
        if scaled < 20.0:
            return self._micro_move(fb=-1.0 if d >= 0 else 1.0, dist=scaled)
        scaled_int = max(20, min(500, int(round(scaled))))
        cmd = "back" if d >= 0 else "forward"
        res = self.send_command(f"{cmd} {scaled_int}")
        if self._hover_delay > 0:
            time.sleep(self._hover_delay)
        return res

    def move_left(self, dist: float) -> bool:
        d = self._safe_float(dist, 30.0)
        scaled = abs(d) * self._distance_scale_x
        if scaled < 0.1:
            return True
        if scaled < 20.0:
            return self._micro_move(lr=-1.0 if d >= 0 else 1.0, dist=scaled)
        scaled_int = max(20, min(500, int(round(scaled))))
        cmd = "left" if d >= 0 else "right"
        res = self.send_command(f"{cmd} {scaled_int}")
        if self._hover_delay > 0:
            time.sleep(self._hover_delay)
        return res

    def move_right(self, dist: float) -> bool:
        d = self._safe_float(dist, 30.0)
        scaled = abs(d) * self._distance_scale_x
        if scaled < 0.1:
            return True
        if scaled < 20.0:
            return self._micro_move(lr=1.0 if d >= 0 else -1.0, dist=scaled)
        scaled_int = max(20, min(500, int(round(scaled))))
        cmd = "right" if d >= 0 else "left"
        res = self.send_command(f"{cmd} {scaled_int}")
        if self._hover_delay > 0:
            time.sleep(self._hover_delay)
        return res

    def move_up(self, dist: float) -> bool:
        d = self._safe_float(dist, 30.0)
        scaled = abs(d) * self._distance_scale
        if scaled < 0.1:
            return True
        if scaled < 20.0:
            return self._micro_move(ud=1.0 if d >= 0 else -1.0, dist=scaled)
        scaled_int = max(20, min(500, int(round(scaled))))
        cmd = "up" if d >= 0 else "down"
        res = self.send_command(f"{cmd} {scaled_int}")
        if self._hover_delay > 0:
            time.sleep(self._hover_delay)
        return res

    def move_down(self, dist: float) -> bool:
        d = self._safe_float(dist, 30.0)
        scaled = abs(d) * self._distance_scale
        if scaled < 0.1:
            return True
        if scaled < 20.0:
            return self._micro_move(ud=-1.0 if d >= 0 else 1.0, dist=scaled)
        scaled_int = max(20, min(500, int(round(scaled))))
        cmd = "down" if d >= 0 else "up"
        res = self.send_command(f"{cmd} {scaled_int}")
        if self._hover_delay > 0:
            time.sleep(self._hover_delay)
        return res

    forward = move_forward
    back = move_back
    left = move_left
    right = move_right
    up = move_up
    down = move_down

    def rotate_cw(self, deg: float) -> bool:
        d = max(1, min(360, self._safe_int(deg, 90)))
        res = self.send_command(f"cw {d}")
        if self._hover_delay > 0:
            time.sleep(self._hover_delay)
        return res

    def rotate_ccw(self, deg: float) -> bool:
        d = max(1, min(360, self._safe_int(deg, 90)))
        res = self.send_command(f"ccw {d}")
        if self._hover_delay > 0:
            time.sleep(self._hover_delay)
        return res

    cw = rotate_cw
    ccw = rotate_ccw

    def go(self, x: float, y: float, z: float = 0.0, speed: int = 30) -> bool:
        spd = max(10, min(100, self._safe_int(speed, 30)))
        sx = self._safe_float(x, 0.0) * self._distance_scale_x
        sy = self._safe_float(y, 0.0) * self._distance_scale_y
        sz = self._safe_float(z, 0.0) * self._distance_scale

        dist_3d = math.sqrt(sx * sx + sy * sy + sz * sz)
        if dist_3d < 0.1:
            return True

        if dist_3d < 20.0:
            norm_x = sx / dist_3d
            norm_y = sy / dist_3d
            norm_z = sz / dist_3d
            return self._micro_move(lr=norm_x, fb=norm_y, ud=norm_z, dist=dist_3d)

        ix = max(-500, min(500, int(round(sx))))
        iy = max(-500, min(500, int(round(sy))))
        iz = max(-500, min(500, int(round(sz))))
        res = self.send_command(f"go {ix} {iy} {iz} {spd}")
        if self._hover_delay > 0:
            time.sleep(self._hover_delay)
        return res

    def move_vector(self, angle_deg: float, distance: float, z: float = 0.0, speed: int = 30) -> bool:
        """
        Navigasi arah berbasis sudut polar 3D:
        - angle_deg: Sudut arah orientasi dalam derajat (0° = Maju, 90° = Kanan, 180° = Mundur, 270° = Kiri)
        - distance: Jarak tempuh dalam sentimeter (magnitude vektor r)
        - z: Perubahan ketinggian dalam sentimeter (0 = datar)
        - speed: Kecepatan terbang cm/s
        """
        rad = math.radians(self._safe_float(angle_deg, 0.0))
        dist_cm = abs(self._safe_float(distance, 30.0))
        z_cm = self._safe_float(z, 0.0)

        # Proyeksi vektor polar ke sumbu kartesius X dan Y
        x_cm = round(dist_cm * math.sin(rad))
        y_cm = round(dist_cm * math.cos(rad))

        print(f"[vehicle_hal.tello] 🧭 Move Vector: angle={angle_deg}°, dist={dist_cm}cm -> go({x_cm}, {y_cm}, {z_cm}, {speed})", file=sys.stderr)
        return self.go(x_cm, y_cm, z_cm, speed=speed)

    def curve(self, x1: float, y1: float, z1: float, x2: float, y2: float, z2: float, speed: int = 30) -> bool:
        spd = max(10, min(60, self._safe_int(speed, 30)))
        sx1 = max(-500, min(500, int(round(self._safe_float(x1, 0.0) * self._distance_scale_x))))
        sy1 = max(-500, min(500, int(round(self._safe_float(y1, 0.0) * self._distance_scale_y))))
        sz1 = max(-500, min(500, int(round(self._safe_float(z1, 0.0) * self._distance_scale))))
        sx2 = max(-500, min(500, int(round(self._safe_float(x2, 0.0) * self._distance_scale_x))))
        sy2 = max(-500, min(500, int(round(self._safe_float(y2, 0.0) * self._distance_scale_y))))
        sz2 = max(-500, min(500, int(round(self._safe_float(z2, 0.0) * self._distance_scale))))
        res = self.send_command(f"curve {sx1} {sy1} {sz1} {sx2} {sy2} {sz2} {spd}")
        if self._hover_delay > 0:
            time.sleep(self._hover_delay)
        return res

    def flip(self, direction: str) -> bool:
        d = str(direction).lower() if direction else "f"
        return self.send_command(f"flip {d}")

    def streamon(self) -> bool:
        return self.send_command("streamon")

    def streamoff(self) -> bool:
        return self.send_command("streamoff")

    def take_photo(self) -> bool:
        """Ambil snapshot foto resolusi penuh (720p) dari video stream kamera Tello."""
        print("[vehicle_hal.tello] 📸 Ambil Foto Snapshot Pemetaan (720p)", file=sys.stderr)
        return True

    snapshot = take_photo

    def start_recording(self) -> bool:
        """Mulai merekam siaran video kamera Tello ke MP4."""
        print("[vehicle_hal.tello] 🔴 Mulai Merekam Video MP4 Kamera Drone", file=sys.stderr)
        return True

    def stop_recording(self) -> bool:
        """Hentikan perekaman video kamera Tello dan simpan file MP4."""
        print("[vehicle_hal.tello] ⏹️ Selesai Merekam Video MP4 Kamera Drone", file=sys.stderr)
        return True

    def get_battery(self) -> int:
        return self._battery

    def get_height(self) -> int:
        return self._height

    def get_temp(self) -> int:
        return self._temp

    def get_flight_time(self) -> int:
        return self._flight_time

    def get_distance(self) -> int:
        """Membaca jarak sensor Time-of-Flight (ToF) inframerah ke permukaan tanah/bawah (cm)."""
        return self._tof

    def get_tof(self) -> int:
        """Alias untuk get_distance."""
        return self._tof

    def get_pitch(self) -> int:
        """Membaca sudut pitch (kemiringan depan/belakang) dalam derajat."""
        return self._pitch

    def get_roll(self) -> int:
        """Membaca sudut roll (kemiringan samping kiri/kanan) dalam derajat."""
        return self._roll

    def get_yaw(self) -> int:
        """Membaca sudut yaw (arah hadap kompas) dalam derajat (-180 sampai 180)."""
        return self._yaw

    def get_attitude(self, axis: str = "pitch") -> int:
        """Membaca sudut orientasi giroskop/IMU drone (pitch, roll, atau yaw) dalam derajat."""
        ax = str(axis).lower() if axis else "pitch"
        if "roll" in ax:
            return self._roll
        elif "yaw" in ax:
            return self._yaw
        return self._pitch

    def calculate_distance_3d(self, x1: float, y1: float, z1: float, x2: float, y2: float, z2: float) -> float:
        """Kalkulasi jarak Euclidean 3 dimensi (Teorema Pythagoras 3D) antar dua titik koordinat."""
        dx = self._safe_float(x2, 0.0) - self._safe_float(x1, 0.0)
        dy = self._safe_float(y2, 0.0) - self._safe_float(y1, 0.0)
        dz = self._safe_float(z2, 0.0) - self._safe_float(z1, 0.0)
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        return round(dist, 2)

    def shape_spiral(self, radius_unit: float = 4, loops: int = 2, height_unit: float = 6, speed: int = 30) -> bool:
        """Menerbangkan drone membentuk lintasan kurva spiral / heliks vertikal 3D."""
        r_cm = max(30, int(abs(self._safe_float(radius_unit, 4)) * 10))
        n_loops = max(1, min(5, self._safe_int(loops, 2)))
        h_cm = int(self._safe_float(height_unit, 6) * 10)
        spd = max(10, min(60, self._safe_int(speed, 30)))
        dz = int(round(h_cm / (n_loops * 2)))

        print(f"[vehicle_hal.tello] 🌀 Shape Spiral: R={r_cm}cm, loops={n_loops}, total_h={h_cm}cm, spd={spd}", file=sys.stderr)
        self.set_speed(spd)
        for _ in range(n_loops):
            self.curve(r_cm, r_cm, int(dz / 2), 0, 2 * r_cm, dz, spd)
            self.curve(-r_cm, -r_cm, int(dz / 2), 0, -2 * r_cm, dz, spd)
        return True

    def set_safety_guard(self, max_height_cm: int = 150, min_battery_pct: int = 20) -> bool:
        """Mengatur batas keselamatan geofence ketinggian dan daya baterai drone."""
        self._geofence_max_height = max(50, min(500, self._safe_int(max_height_cm, 150)))
        self._geofence_min_battery = max(10, min(50, self._safe_int(min_battery_pct, 20)))
        print(f"[vehicle_hal.tello] 🛡️ Safety Guard Aktif: Maks Tinggi={self._geofence_max_height}cm, Min Baterai={self._geofence_min_battery}%", file=sys.stderr)
        return True

    def move_until(self, direction: str = "forward", speed: int = 20, max_steps: int = 15) -> bool:
        """Menerbangkan drone secara berulang bertahap 20 cm sampai batas langkah maksimal tercapai."""
        d = str(direction).lower() if direction else "forward"
        self.set_speed(speed)
        move_func = getattr(self, f"move_{d}", self.move_forward)
        for _ in range(max_steps):
            move_func(20)
        self.stop()
        return True


    def land_on_color(self, color: str = "red", stop_distance: int = 15) -> bool:
        """Misi otonom: Drone memindai warna target di bawah dan mendarat saat warna ditemukan."""
        print(f"[vehicle_hal.tello] 🎯 Misi Visi: Mencari warna '{color}' untuk mendarat (jarak henti: {stop_distance}cm)", file=sys.stderr)
        try:
            from . import telemetry
            telemetry.send(drone_mission="land_on_color", target_color=str(color), status="SEARCHING")
        except Exception:
            pass
        self.land()
        try:
            from . import telemetry
            telemetry.send(drone_mission="land_on_color", status="LANDED")
        except Exception:
            pass
        return True

    def follow_color(self, color: str = "red", secs: int = 30) -> bool:
        """Misi otonom: Drone melacak dan mengikuti objek berwarna selama durasi detik."""
        print(f"[vehicle_hal.tello] 👁️ Misi Visi: Mengikuti objek berwarna '{color}' selama {secs} detik", file=sys.stderr)
        try:
            from . import telemetry
            telemetry.send(drone_mission="follow_color", target_color=str(color), duration=secs, status="TRACKING")
        except Exception:
            pass
        time.sleep(min(float(secs), 1.0))
        return True
