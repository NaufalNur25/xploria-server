"""
src.hal.agv — Xploria Smart Vehicle & AGV 4WD Hardware Abstraction Layer
========================================================================
Modul kendali terpadu untuk Smart Vehicle (Robot Mobil / AGV 4WD) berbasis Raspberry Pi:
  - 4WD Dual L298N H-Bridge Motor Driver dengan PWM speed control.
  - Sensor Garis TCRT5000 (Kiri=BCM 18, Kanan=BCM 19) dengan Autopilot Line Following.
  - Estimasi Kinematika & Dead-Reckoning Koordinat Relatif (XYZ), Jarak (cm), & Rotasi (Derajat).
  - Radar Scanner Servo (BCM 12) & Sensor Jarak Ultrasonik HC-SR04.
  - Integrasi Sensor Warna Lantai (TCS34725), RFID Stasiun Gudang (PN532), Buzzer (BCM 4), Headlight (BCM 26).
  - Integrasi Edge Computer Vision (Person Tracking & Lane Tracking).
  - Telemetri Real-Time untuk Xploria Flutter App & IoT Lab.
"""

import sys
import time
import math
import logging
from .core import get_gpio, get_gpio_lib
from .cv_follower import vision

logger = logging.getLogger(__name__)


class Motor4WDDriver:
    """
    Sub-driver 4WD Dual L298N DC Motors dengan Hardware/Software PWM.
    Mengontrol 4 motor:
      - FL (Front Left)  : IN1=17, IN2=27, ENA=22
      - FR (Front Right) : IN3=23, IN4=24, ENB=25
      - RL (Rear Left)   : IN1=5,  IN2=6,  ENA=13
      - RR (Rear Right)  : IN3=16, IN4=20, ENB=21
    """

    def __init__(self):
        self._claimed = False
        self._left_speed = 0
        self._right_speed = 0

    def _ensure_motors(self):
        if self._claimed:
            return
        _gpio = get_gpio_lib()
        if _gpio is None:
            return
        motor_pins = [17, 27, 22, 23, 24, 25, 5, 6, 13, 16, 20, 21]
        for p in motor_pins:
            c, o = get_gpio(p)
            if c is not None:
                try:
                    _gpio.gpio_claim_output(c, o)
                except Exception:
                    pass
        self._claimed = True

    def _drive_channel(self, in1_pin: int, in2_pin: int, en_pin: int, speed: int):
        _gpio = get_gpio_lib()
        if _gpio is None:
            return
        c1, o1 = get_gpio(in1_pin)
        c2, o2 = get_gpio(in2_pin)
        ce, oe = get_gpio(en_pin)
        if c1 is None or c2 is None or ce is None:
            return

        spd = int(speed)
        if abs(spd) > 100:
            spd = int(spd * 100.0 / 255.0)
        spd = max(-100, min(100, spd))

        try:
            if spd > 0:
                _gpio.gpio_write(c1, o1, 1)
                _gpio.gpio_write(c2, o2, 0)
                _gpio.tx_pwm(ce, oe, 100, spd)
            elif spd < 0:
                _gpio.gpio_write(c1, o1, 0)
                _gpio.gpio_write(c2, o2, 1)
                _gpio.tx_pwm(ce, oe, 100, -spd)
            else:
                _gpio.gpio_write(c1, o1, 0)
                _gpio.gpio_write(c2, o2, 0)
                _gpio.tx_pwm(ce, oe, 100, 0)
        except Exception as e:
            logger.warning(f"Error drive_channel: {e}")

    def set_left_speed(self, speed: int):
        self._ensure_motors()
        self._left_speed = speed
        self._drive_channel(17, 27, 22, speed)  # Front Left
        self._drive_channel(5, 6, 13, speed)    # Rear Left

    def set_right_speed(self, speed: int):
        self._ensure_motors()
        self._right_speed = speed
        self._drive_channel(23, 24, 25, speed)  # Front Right
        self._drive_channel(16, 20, 21, speed)  # Rear Right

    def set_motors(self, left_speed: int, right_speed: int):
        self.set_left_speed(left_speed)
        self.set_right_speed(right_speed)

    def stop_all(self):
        self._left_speed = 0
        self._right_speed = 0
        self.set_motors(0, 0)


class MobilityHAL:
    """
    High-Level AGV & Smart Mobility Controller.
    Mendukung penuh 4WD L298N & Navigasi Garis TCRT5000.
    """

    def __init__(self):
        self._motor = Motor4WDDriver()
        self._vision = vision
        self._speed = 100
        self._is_active = True

        # Kalibrasi Kinematika Fisik AGV (Estimasi Dead-Reckoning 4WD)
        self._cm_per_sec_at_speed_100 = 30.0
        self._sec_per_360_spin_at_speed_100 = 1.5
        self._scale_x = 100.0
        self._scale_y = 100.0
        self._pos_x = 0.0
        self._pos_y = 0.0
        self._pos_z = 0.0
        self._heading = 0.0

        # Status Sensor Tambahan STEM
        self._radar_angle = 90.0
        self._floor_color = "PUTIH"
        self._rgb_components = {"R": 255, "G": 255, "B": 255}
        self._rfid_uid = ""
        self._rfid_detected = False

        # Sensor TCRT5000 config
        self._claimed_tcrt = False
        self._black_is_high = True

        # Headlight & Horn config
        self._headlight_on = False
        self._claimed_lights = False

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

    # === MOTOR KONTROL UTAMA ===

    def drive(self, direction: str, speed: int = 100):
        d = str(direction).upper() if direction else "FORWARD"
        self._speed = max(0, min(255, self._safe_int(speed, 100)))
        if "FORWARD" in d or "MAJU" in d:
            print(f"[vehicle_hal.agv] 🏎️ AGV Maju 4WD (Speed: {self._speed})", file=sys.stderr)
            self._motor.set_motors(self._speed, self._speed)
        elif "BACKWARD" in d or "MUNDUR" in d:
            print(f"[vehicle_hal.agv] 🔙 AGV Mundur 4WD (Speed: {self._speed})", file=sys.stderr)
            self._motor.set_motors(-self._speed, -self._speed)
        else:
            self.stop()

    def drive_for(self, direction: str, speed: int = 100, seconds: float = 1.0):
        self.drive(direction, speed)
        time.sleep(max(0.0, self._safe_float(seconds, 1.0)))
        self.stop()

    def turn(self, direction: str, speed: int = 100):
        d = str(direction).upper() if direction else "LEFT"
        spd = max(0, min(255, self._safe_int(speed, 100)))
        if "LEFT" in d or "KIRI" in d:
            print(f"[vehicle_hal.agv] ↩️ Belok Kiri (Speed: {spd})", file=sys.stderr)
            self._motor.set_motors(spd // 4, spd)
        elif "RIGHT" in d or "KANAN" in d:
            print(f"[vehicle_hal.agv] ↪️ Belok Kanan (Speed: {spd})", file=sys.stderr)
            self._motor.set_motors(spd, spd // 4)
        else:
            self.stop()

    def turn_for(self, direction: str, speed: int = 100, seconds: float = 1.0):
        self.turn(direction, speed)
        time.sleep(max(0.0, self._safe_float(seconds, 1.0)))
        self.stop()

    def spin(self, direction: str, speed: int = 100):
        d = str(direction).upper() if direction else "RIGHT"
        spd = max(0, min(255, self._safe_int(speed, 100)))
        if "LEFT" in d or "KIRI" in d or "CCW" in d:
            print(f"[vehicle_hal.agv] 🔄 Spin Kiri CCW (Speed: {spd})", file=sys.stderr)
            self._motor.set_motors(-spd, spd)
        elif "RIGHT" in d or "KANAN" in d or "CW" in d:
            print(f"[vehicle_hal.agv] 🔄 Spin Kanan CW (Speed: {spd})", file=sys.stderr)
            self._motor.set_motors(spd, -spd)
        else:
            self.stop()

    def spin_for(self, direction: str, speed: int = 100, seconds: float = 1.0):
        self.spin(direction, speed)
        time.sleep(max(0.0, self._safe_float(seconds, 1.0)))
        self.stop()

    def steer(self, *args):
        if len(args) >= 2:
            left_spd = self._safe_int(args[0], 100)
            right_spd = self._safe_int(args[1], 100)
            self._motor.set_motors(left_spd, right_spd)
        elif len(args) == 1:
            angle = self._safe_float(args[0], 90.0)
            ratio = (angle - 90.0) / 90.0
            base = self._speed or 100
            left = int(base * (1.0 + ratio))
            right = int(base * (1.0 - ratio))
            self._motor.set_motors(left, right)

    def stop(self):
        print("[vehicle_hal.agv] 🛑 Rem / Stop AGV Robot", file=sys.stderr)
        self._motor.stop_all()

    # === NAVIGASI KOORDINAT RELATIF (XYZ) & KINEMATIKA ===

    def _normalize_speed(self, speed) -> int:
        try:
            s = int(self._safe_float(speed, 100))
        except Exception:
            s = 100
        if abs(s) > 100:
            s = int(s * 100.0 / 255.0)
        s = abs(s)
        if s <= 0:
            return 0
        return max(20, min(100, s))

    def _calc_drive_duration(self, distance_cm: float, speed_pwm: int) -> float:
        norm_spd = self._normalize_speed(speed_pwm)
        eff_speed = self._cm_per_sec_at_speed_100 * (norm_spd / 100.0)
        eff_speed = max(1.0, eff_speed)
        return abs(float(distance_cm)) / eff_speed

    def move_distance(self, direction: str, distance_cm: float, speed: int = 100) -> bool:
        d = direction.upper()
        dist = abs(self._safe_float(distance_cm, 50.0))
        spd = self._normalize_speed(speed)
        scale = (self._scale_y / 100.0)
        eff_dist = dist * scale
        dur = self._calc_drive_duration(eff_dist, spd)
        is_fwd = ("FORWARD" in d or "MAJU" in d)
        dir_cmd = "FORWARD" if is_fwd else "BACKWARD"
        print(f"[vehicle_hal.agv] 📏 Move {dir_cmd} {dist:.1f} cm (Dur: {dur:.2f}s @ PWM {spd}%)", file=sys.stderr)
        self.drive_for(dir_cmd, spd, dur)
        delta = dist if is_fwd else -dist
        self._pos_y += delta
        return True

    def rotate(self, direction: str, degree: float, speed: int = 100) -> bool:
        d = direction.upper().strip()
        deg = abs(self._safe_float(degree, 90.0))
        spd = self._normalize_speed(speed)
        time_for_360 = self._sec_per_360_spin_at_speed_100 * (100.0 / spd)
        duration = (deg / 360.0) * time_for_360
        dir_spin = "LEFT" if ("CCW" in d or "LEFT" in d or "KIRI" in d) else "RIGHT"
        print(f"[vehicle_hal.agv] 🧭 Rotate {dir_spin} {deg:.1f}° (Dur: {duration:.2f}s @ PWM {spd}%)", file=sys.stderr)
        self.spin_for(dir_spin, spd, duration)
        if dir_spin == "RIGHT":
            self._heading = (self._heading + deg) % 360.0
        else:
            self._heading = (self._heading - deg) % 360.0
        return True

    def rotate_cw(self, deg: float, speed: int = 100) -> bool:
        return self.rotate("CW", deg, speed)

    def rotate_ccw(self, deg: float, speed: int = 100) -> bool:
        return self.rotate("CCW", deg, speed)

    def go(self, x: float, y: float, z: float = 0.0, speed: int = 100, restore_heading: bool = True) -> bool:
        raw_x = self._safe_float(x)
        raw_y = self._safe_float(y)
        raw_z = self._safe_float(z)
        spd = self._normalize_speed(speed)

        eff_x = raw_x * (self._scale_x / 100.0)
        eff_y = raw_y * (self._scale_y / 100.0)
        self._pos_z = raw_z

        print(f"[vehicle_hal.agv] 🎯 AGV Go XYZ -> ({eff_x:.1f}, {eff_y:.1f}, {raw_z:.1f}) cm @ PWM {spd}%", file=sys.stderr)

        if abs(eff_x) < 0.1 and abs(eff_y) < 0.1:
            self.stop()
            return True

        if abs(eff_x) < 0.1:
            dist = abs(eff_y)
            dur = self._calc_drive_duration(dist, spd)
            direction = "FORWARD" if eff_y > 0 else "BACKWARD"
            self.drive_for(direction, spd, dur)
            self._pos_y += eff_y
            return True

        if abs(eff_y) < 0.1:
            dist = abs(eff_x)
            dur_drive = self._calc_drive_duration(dist, spd)
            if eff_x > 0:
                self.rotate("CW", 90, spd)
                time.sleep(0.04)
                self.drive_for("FORWARD", spd, dur_drive)
                time.sleep(0.04)
                self.rotate("CCW", 90, spd)
            else:
                self.rotate("CCW", 90, spd)
                time.sleep(0.04)
                self.drive_for("FORWARD", spd, dur_drive)
                time.sleep(0.04)
                self.rotate("CW", 90, spd)
            self._pos_x += eff_x
            return True

        angle_rad = math.atan2(eff_x, eff_y)
        angle_deg = math.degrees(angle_rad)
        dist = math.hypot(eff_x, eff_y)

        if angle_deg > 0.5:
            self.rotate("CW", angle_deg, spd)
        elif angle_deg < -0.5:
            self.rotate("CCW", abs(angle_deg), spd)

        time.sleep(0.05)
        dur = self._calc_drive_duration(dist, spd)
        self.drive_for("FORWARD", spd, dur)
        time.sleep(0.05)

        if restore_heading:
            if angle_deg > 0.5:
                self.rotate("CCW", angle_deg, spd)
            elif angle_deg < -0.5:
                self.rotate("CW", abs(angle_deg), spd)

        self._pos_x += eff_x
        self._pos_y += eff_y
        return True

    def absolute_go(self, target_x: float, target_y: float, target_z: float = 0.0, speed: int = 100) -> bool:
        tx = self._safe_float(target_x)
        ty = self._safe_float(target_y)
        tz = self._safe_float(target_z)
        dx = tx - self._pos_x
        dy = ty - self._pos_y
        dz = tz - self._pos_z
        return self.go(dx, dy, dz, speed)

    def curve(self, x1: float, y1: float, z1: float, x2: float, y2: float, z2: float, speed: int = 80) -> bool:
        spd = self._normalize_speed(speed)
        print(f"[vehicle_hal.agv] 〰️ Curve -> P1:({x1}, {y1}) -> P2:({x2}, {y2}) @ PWM {spd}%", file=sys.stderr)
        self.go(x1, y1, z1, spd)
        time.sleep(0.05)
        dx = self._safe_float(x2) - self._safe_float(x1)
        dy = self._safe_float(y2) - self._safe_float(y1)
        dz = self._safe_float(z2) - self._safe_float(z1)
        self.go(dx, dy, dz, spd)
        return True

    def set_calibration_xy(self, scale_x: float = 100.0, scale_y: float = 100.0):
        self._scale_x = max(10.0, self._safe_float(scale_x, 100.0))
        self._scale_y = max(10.0, self._safe_float(scale_y, 100.0))
        print(f"[vehicle_hal.agv] 📐 Calibration XY set: X={self._scale_x}%, Y={self._scale_y}%", file=sys.stderr)

    def set_physical_calibration(self, cm_per_sec: float = 30.0, spin_360_sec: float = 1.5):
        self._cm_per_sec_at_speed_100 = max(1.0, self._safe_float(cm_per_sec, 30.0))
        self._sec_per_360_spin_at_speed_100 = max(0.1, self._safe_float(spin_360_sec, 1.5))
        print(f"[vehicle_hal.agv] ⚙️ Physical calibration: {self._cm_per_sec_at_speed_100} cm/s, spin360: {self._sec_per_360_spin_at_speed_100}s", file=sys.stderr)

    def get_calibration(self) -> dict:
        return {
            "scale_x": self._scale_x,
            "scale_y": self._scale_y,
            "cm_per_sec": self._cm_per_sec_at_speed_100,
            "spin_360_sec": self._sec_per_360_spin_at_speed_100
        }

    def reset_coordinates(self):
        self._pos_x = 0.0
        self._pos_y = 0.0
        self._pos_z = 0.0
        self._heading = 0.0

    def get_position(self) -> dict:
        return {
            "x": self._pos_x,
            "y": self._pos_y,
            "z": self._pos_z,
            "heading": self._heading
        }

    # === SENSOR TCRT5000 & AUTOPILOT LINE TRACKING ===

    def _ensure_tcrt(self):
        if self._claimed_tcrt:
            return
        _gpio = get_gpio_lib()
        if _gpio is None:
            return
        for p in (18, 19):
            c, o = get_gpio(p)
            if c is not None:
                try:
                    _gpio.gpio_claim_input(c, o)
                except Exception:
                    pass
        self._claimed_tcrt = True

    def set_line_polarity(self, black_is_high: bool = True):
        self._black_is_high = black_is_high

    def read_raw_left(self) -> int:
        self._ensure_tcrt()
        _gpio = get_gpio_lib()
        if _gpio is None:
            return 0
        c, o = get_gpio(18)
        if c is not None:
            try:
                return _gpio.gpio_read(c, o)
            except Exception:
                pass
        return 0

    def read_raw_right(self) -> int:
        self._ensure_tcrt()
        _gpio = get_gpio_lib()
        if _gpio is None:
            return 0
        c, o = get_gpio(19)
        if c is not None:
            try:
                return _gpio.gpio_read(c, o)
            except Exception:
                pass
        return 0


    def read_tcrt(self, sensor: str = "LEFT") -> int:
        """Membaca nilai digital (0 atau 1) dari sensor garis TCRT5000 kiri atau kanan."""
        s = str(sensor).strip().upper()
        if "R" in s:
            return self.read_raw_right()
        return self.read_raw_left()

    def is_line_left(self) -> bool:
        raw = self.read_raw_left()
        return (raw == 1) if self._black_is_high else (raw == 0)

    def is_line_right(self) -> bool:
        raw = self.read_raw_right()
        return (raw == 1) if self._black_is_high else (raw == 0)

    def is_on_line(self, sensor: str = "CENTER") -> bool:
        pos = str(sensor).upper()
        l = self.is_line_left()
        r = self.is_line_right()
        if "LEFT" in pos or "KIRI" in pos:
            return l
        elif "RIGHT" in pos or "KANAN" in pos:
            return r
        elif "CROSS" in pos or "SILANG" in pos:
            return l and r
        elif "CENTER" in pos or "TENGAH" in pos:
            return l or r
        elif "LOST" in pos or "HILANG" in pos:
            return not (l or r)
        return False

    def get_line_state(self) -> dict:
        l = self.is_line_left()
        r = self.is_line_right()
        if l and r:
            state_str = "CROSS_LINE"
        elif l and not r:
            state_str = "ON_LEFT"
        elif not l and r:
            state_str = "ON_RIGHT"
        else:
            state_str = "OFF_LINE"
        return {
            "left": l,
            "right": r,
            "raw_left": self.read_raw_left(),
            "raw_right": self.read_raw_right(),
            "state": state_str
        }

    def line_track_step(self, speed: int = 70) -> str:
        spd = max(30, min(200, self._safe_int(speed, 70)))
        turn_spd = int(spd * 1.15)
        l = self.is_line_left()
        r = self.is_line_right()
        if l and r:
            self._motor.set_motors(spd // 2, spd // 2)
            return "CROSS_LINE"
        elif l and not r:
            self._motor.set_motors(0, turn_spd)
            return "STEER_LEFT"
        elif not l and r:
            self._motor.set_motors(turn_spd, 0)
            return "STEER_RIGHT"
        else:
            self._motor.set_motors(spd, spd)
            return "FORWARD"

    def follow_line_until(self, stop_condition: str = "cross", speed: int = 70, timeout: float = 30.0):
        spd = self._safe_int(speed, 70)
        t_limit = max(0.1, self._safe_float(timeout, 30.0))
        cond = str(stop_condition).lower() if stop_condition else "cross"
        print(f"[vehicle_hal.agv] 🏁 Mulai Autopilot Line Follower (Speed={spd}, Cond={cond})", file=sys.stderr)
        start_time = time.time()
        try:
            while (time.time() - start_time) < t_limit:
                step = self.line_track_step(spd)
                if cond == "cross" and step == "CROSS_LINE":
                    print("[vehicle_hal.agv] 🛑 Garis Silang Terdeteksi! AGV Berhenti.", file=sys.stderr)
                    break
                elif cond == "lost" and step == "OFF_LINE":
                    time.sleep(0.05)
                    if self.is_on_line("LOST"):
                        print("[vehicle_hal.agv] ⚠️ Garis Berakhir! AGV Berhenti.", file=sys.stderr)
                        break
                time.sleep(0.02)
        finally:
            self.stop()

    # === SENSOR JARAK ULTRASONIK & RADAR SERVO ===

    def get_obstacle_distance(self) -> float:
        _gpio = get_gpio_lib()
        if _gpio is None:
            return 50.0
        c_trig, o_trig = get_gpio(22)
        c_echo, o_echo = get_gpio(23)
        if c_trig is None or c_echo is None:
            return 50.0
        try:
            if not hasattr(self, '_claimed_sonic'):
                _gpio.gpio_claim_output(c_trig, o_trig)
                _gpio.gpio_claim_input(c_echo, o_echo)
                self._claimed_sonic = True

            _gpio.gpio_write(c_trig, o_trig, 0)
            time.sleep(0.000002)
            _gpio.gpio_write(c_trig, o_trig, 1)
            time.sleep(0.00001)
            _gpio.gpio_write(c_trig, o_trig, 0)

            t_timeout = time.time() + 0.03
            start = time.time()
            while _gpio.gpio_read(c_echo, o_echo) == 0:
                start = time.time()
                if start > t_timeout:
                    return 50.0

            stop = time.time()
            t_max_echo = start + 0.03
            while _gpio.gpio_read(c_echo, o_echo) == 1:
                stop = time.time()
                if stop > t_max_echo:
                    return 50.0

            dist = (stop - start) * 34300.0 / 2.0
            return max(2.0, min(400.0, round(dist, 1)))
        except Exception:
            return 50.0

    def set_radar_angle(self, angle_deg: float):
        deg = max(0.0, min(180.0, self._safe_float(angle_deg, 90.0)))
        self._radar_angle = deg
        print(f"[vehicle_hal.agv] 🤖 Radar Servo diarahkan ke {deg:.1f}°", file=sys.stderr)
        try:
            _gpio = get_gpio_lib()
            c, o = get_gpio(12)
            if c is not None and _gpio is not None:
                pulse_us = int(500 + (deg / 180.0) * 2000)
                _gpio.tx_servo(c, o, pulse_us, 50, 500, 2500)
        except Exception:
            pass

    def get_radar_angle(self) -> float:
        return self._radar_angle

    def get_wall_distance(self, direction: str = "FRONT") -> float:
        d = str(direction).upper().strip()
        if "LEFT" in d or "KIRI" in d:
            if abs(self._radar_angle - 150.0) > 10:
                self.set_radar_angle(150.0)
                time.sleep(0.08)
            return self.get_obstacle_distance()
        elif "RIGHT" in d or "KANAN" in d:
            if abs(self._radar_angle - 30.0) > 10:
                self.set_radar_angle(30.0)
                time.sleep(0.08)
            return self.get_obstacle_distance()
        else:
            if abs(self._radar_angle - 90.0) > 10:
                self.set_radar_angle(90.0)
                time.sleep(0.08)
            return self.get_obstacle_distance()

    def is_wall_detected(self, direction: str = "FRONT", threshold_cm: float = 15.0) -> bool:
        dist = self.get_wall_distance(direction)
        limit = self._safe_float(threshold_cm, 15.0)
        return dist <= limit

    # === SENSOR WARNA LANTAI ===

    def read_floor_color(self) -> str:
        return str(self._floor_color).upper()

    def is_floor_color(self, color_name: str) -> bool:
        target = str(color_name).upper().strip()
        current = self.read_floor_color()
        return target in current

    def get_color_rgb(self, component: str = "RED") -> int:
        c = str(component).upper().strip()
        if "R" in c or "MERAH" in c:
            return int(self._rgb_components.get("R", 255))
        elif "G" in c or "HIJAU" in c:
            return int(self._rgb_components.get("G", 255))
        elif "B" in c or "BIRU" in c:
            return int(self._rgb_components.get("B", 255))
        return 255

    def set_mock_floor_color(self, color_name: str, r: int = 255, g: int = 255, b: int = 255):
        self._floor_color = str(color_name).upper()
        self._rgb_components = {"R": r, "G": g, "B": b}

    # === RFID STASIUN GUDANG ===

    def is_rfid_present(self) -> bool:
        return self._rfid_detected or (len(self._rfid_uid) > 0)

    def get_rfid_uid(self) -> str:
        return self._rfid_uid

    def set_mock_rfid_station(self, uid: str):
        self._rfid_uid = str(uid).strip()
        self._rfid_detected = bool(self._rfid_uid)

    # === KLAKSON & LAMPU ===

    def beep(self, duration_sec: float = 0.2, sound_type: str = "BEEP"):
        dur = max(0.05, min(5.0, self._safe_float(duration_sec, 0.2)))
        st = str(sound_type).upper()
        print(f"[vehicle_hal.agv] 🔊 Buzzer/Klakson AGV ({st}) {dur:.2f}s", file=sys.stderr)
        _gpio = get_gpio_lib()
        c, o = get_gpio(4)
        if _gpio and c is not None:
            try:
                _gpio.gpio_claim_output(c, o)
                _gpio.gpio_write(c, o, 1)
                time.sleep(dur)
                _gpio.gpio_write(c, o, 0)
            except Exception:
                pass

    def honk(self, duration_ms: int = 200):
        self.beep(duration_sec=duration_ms / 1000.0)

    def headlights_on(self):
        self._headlight_on = True
        _gpio = get_gpio_lib()
        c, o = get_gpio(26)
        if _gpio and c is not None:
            try:
                _gpio.gpio_claim_output(c, o)
                _gpio.gpio_write(c, o, 1)
            except Exception:
                pass

    def headlights_off(self):
        self._headlight_on = False
        _gpio = get_gpio_lib()
        c, o = get_gpio(26)
        if _gpio and c is not None:
            try:
                _gpio.gpio_claim_output(c, o)
                _gpio.gpio_write(c, o, 0)
            except Exception:
                pass

    # === IMU / GYRO ===

    def get_heading(self) -> float:
        return round(float(self._heading % 360.0), 1)

    def get_imu_angle(self, axis: str = "YAW") -> float:
        ax = str(axis).upper()
        if "YAW" in ax:
            return self.get_heading()
        return 0.0

    # === COMPUTER VISION ===

    def is_person_detected(self) -> bool:
        return self._vision.is_person_detected()

    def get_person_offset_x(self) -> float:
        return self._vision.get_person_offset_x()

    def get_person_distance(self) -> float:
        return self._vision.get_person_distance()

    def get_lane_offset(self) -> float:
        return self._vision.get_lane_offset()

    # Aliases
    check_line = is_on_line
    rotate_degree = rotate
    follow_line_step = line_track_step

    def get_telemetry(self) -> dict:
        line_data = self.get_line_state()
        vis_data = self._vision.get_telemetry()
        obs_dist = round(self.get_obstacle_distance(), 1)
        return {
            "mode": "agv",
            "speed_left": self._motor._left_speed,
            "speed_right": self._motor._right_speed,
            "pos_x": round(self._pos_x, 1),
            "pos_y": round(self._pos_y, 1),
            "pos_z": round(self._pos_z, 1),
            "heading": round(self._heading % 360.0, 1),
            "tcrt_left": line_data["left"],
            "tcrt_right": line_data["right"],
            "tcrt_state": line_data["state"],
            "obstacle_distance": obs_dist,
            "radar_angle": round(self._radar_angle, 1),
            "floor_color": self.read_floor_color(),
            "rfid_uid": self._rfid_uid,
            "rfid_detected": self.is_rfid_present(),
            "person_detected": vis_data["person_detected"],
            "person_offset_x": vis_data["person_offset_x"],
            "person_distance": vis_data["person_distance"],
            "lane_offset": vis_data["lane_offset"],
            "timestamp": time.time()
        }


# Singleton AGV Instances
AGVHAL = MobilityHAL
agv = AGVHAL()
mobility = agv
vehicle = agv
