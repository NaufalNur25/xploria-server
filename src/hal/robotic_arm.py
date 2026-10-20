"""
src.hal.robotic_arm — OWI-535 Robotic Arm Edge Driver for Raspberry Pi
======================================================================
Mengendalikan 5 Motor DC dan 1 Lampu Sorot LED pada OWI-535 Robotic Arm Edge
yang dikoneksikan ke Raspberry Pi 3/4/5 melalui Driver Motor DC (H-Bridge).

Pemetaan Default Pin GPIO (BCM):
  - Motor 1 (Gripper)       : IN1 = 11, IN2 = 13
  - Motor 2 (Wrist Motion)  : IN1 = 19, IN2 = 26
  - Motor 3 (Elbow Motion)  : IN1 = 17, IN2 = 27
  - Motor 4 (Base Motion)   : IN1 = 22, IN2 = 23
  - Motor 5 (Base Rotation) : IN1 = 24, IN2 = 25
  - Search Light (LED)      : LED_PIN = 18
"""

import sys
import time
import logging
from .core import get_gpio, get_gpio_lib

logger = logging.getLogger(__name__)


class RoboticArmHAL:
    def __init__(self):
        # Format: { motor_id: (IN1, IN2) }
        self.motor_pins = {
            "M1": (11, 13),  # Gripper
            "M2": (19, 26),  # Wrist
            "M3": (17, 27),  # Elbow
            "M4": (22, 23),  # Base Motion
            "M5": (24, 25),  # Base Rotation
        }
        self.light_pin = 18
        self._claimed_pins = set()
        self.is_light_on = False

    def _claim_out(self, pin):
        _gpio = get_gpio_lib()
        if pin in self._claimed_pins or _gpio is None:
            return
        c, o = get_gpio(pin)
        if c is not None:
            try:
                _gpio.gpio_claim_output(c, o)
                self._claimed_pins.add(pin)
            except Exception as e:
                logger.warning(f"[RoboticArmHAL] Gagal claim output pin {pin}: {e}")

    def drive(self, motor: str, action: str, speed: int = 100):
        motor = str(motor).upper().strip()
        if motor not in self.motor_pins:
            logger.warning(f"[RoboticArmHAL] Motor tidak dikenal: {motor}")
            return

        in1_pin, in2_pin = self.motor_pins[motor]
        self._claim_out(in1_pin)
        self._claim_out(in2_pin)

        _gpio = get_gpio_lib()
        c1, o1 = get_gpio(in1_pin)
        c2, o2 = get_gpio(in2_pin)

        act = str(action).lower().strip()
        if act in ("open", "up", "left", "forward", "start"):
            if _gpio and c1 is not None and c2 is not None:
                _gpio.gpio_write(c1, o1, 1)
                _gpio.gpio_write(c2, o2, 0)
            print(f"[RoboticArmHAL] ▶️ Motor {motor}: {act.upper()}", file=sys.stderr)
        elif act in ("close", "down", "right", "backward"):
            if _gpio and c1 is not None and c2 is not None:
                _gpio.gpio_write(c1, o1, 0)
                _gpio.gpio_write(c2, o2, 1)
            print(f"[RoboticArmHAL] ◀️ Motor {motor}: {act.upper()}", file=sys.stderr)
        else:
            self.stop(motor)

    def stop(self, motor: str = "ALL"):
        motor_str = str(motor).upper().strip()
        if motor_str == "ALL":
            for m in self.motor_pins:
                self.stop(m)
            return

        if motor_str in self.motor_pins:
            in1_pin, in2_pin = self.motor_pins[motor_str]
            _gpio = get_gpio_lib()
            c1, o1 = get_gpio(in1_pin)
            c2, o2 = get_gpio(in2_pin)
            if _gpio and c1 is not None and c2 is not None:
                _gpio.gpio_write(c1, o1, 0)
                _gpio.gpio_write(c2, o2, 0)
            print(f"[RoboticArmHAL] 🛑 Motor {motor_str}: STOP", file=sys.stderr)

    def set_light(self, state: bool):
        self.is_light_on = bool(state)
        self._claim_out(self.light_pin)
        _gpio = get_gpio_lib()
        c, o = get_gpio(self.light_pin)
        if _gpio and c is not None:
            _gpio.gpio_write(c, o, 1 if self.is_light_on else 0)
        print(f"[RoboticArmHAL] 💡 Search Light: {'ON' if self.is_light_on else 'OFF'}", file=sys.stderr)
        try:
            from . import telemetry
            telemetry.send(arm_light=self.is_light_on)
        except Exception:
            pass

    # Smart Warehouse Presets
    def home(self):
        """Kembali ke posisi istirahat / parkir aman."""
        print("[RoboticArmHAL] Menjalankan Preset: Home / Parkir Aman...", file=sys.stderr)
        self.drive("M1", "open")
        time.sleep(0.5)
        self.stop("M1")
        self.drive("M2", "up")
        time.sleep(0.5)
        self.stop("M2")
        self.drive("M3", "down")
        time.sleep(0.6)
        self.stop("M3")
        self.drive("M4", "down")
        time.sleep(0.8)
        self.stop("M4")
        self.stop("ALL")

    def pick_conveyor_1(self):
        """Ambil produk dari Konveyor 1."""
        print("[RoboticArmHAL] Menjalankan Preset: Pick dari Konveyor 1...", file=sys.stderr)
        self.set_light(True)
        self.drive("M1", "open")
        time.sleep(0.6)
        self.stop("M1")
        self.drive("M4", "up")
        time.sleep(0.8)
        self.stop("M4")
        self.drive("M1", "close")
        time.sleep(1.0)
        self.stop("M1")
        self.drive("M3", "up")
        time.sleep(0.8)
        self.stop("M3")

    def place_conveyor_2(self):
        """Letakkan produk ke Konveyor 2."""
        print("[RoboticArmHAL] Menjalankan Preset: Place ke Konveyor 2...", file=sys.stderr)
        self.drive("M5", "right")
        time.sleep(1.2)
        self.stop("M5")
        self.drive("M4", "down")
        time.sleep(0.7)
        self.stop("M4")
        self.drive("M1", "open")
        time.sleep(0.8)
        self.stop("M1")
        self.drive("M4", "up")
        time.sleep(0.5)
        self.stop("M4")
        self.drive("M5", "left")
        time.sleep(1.2)
        self.stop("ALL")

    def inspection_pose(self):
        """Posisikan objek di depan kamera inspeksi visi AI."""
        print("[RoboticArmHAL] Menjalankan Preset: Posisi Inspeksi...", file=sys.stderr)
        self.set_light(True)
        self.drive("M3", "up")
        time.sleep(0.8)
        self.stop("M3")
        self.drive("M2", "up")
        time.sleep(0.5)
        self.stop("ALL")


# Global Singleton Instance
arm = RoboticArmHAL()
robotic_arm = arm
