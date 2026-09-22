"""
xploria_hal.py — Xploria Hardware Abstraction Layer (Hardened + Dynamic Telemetry)
===================================================================================
Hardware:
- Raspberry Pi 4B
- I2C Bus Software: GPIO 8 (SDA), GPIO 9 (SCL)
- ADS1115 ADC (0x48): MQ-9 Gas (AIN0), LDR Light (AIN3)
- PCA9685 PWM (0x40): 3x Servo, Kipas, 2x RGB, 3x LED Strip, Lampu Taman
- Dual INA226: Beban Rumah (0x44), Panel Surya (0x41)
- GPIO Direct: DHT22 (GPIO 4), PIR1 (GPIO 17), PIR2 (GPIO 27), HC-SR04 (GPIO 22/23)
- RFID PN532: GPIO 20 (SDA), GPIO 21 (SCL)
"""

import time
import math
import sys
import json
import warnings
import atexit
import signal

warnings.simplefilter('ignore')

# === GPIO Init ===
try:
    import lgpio as _gpio
except ImportError:
    _gpio = None
    print("[xploria_hal] WARNING: lgpio tidak ditemukan - GPIO tidak akan berfungsi.", file=sys.stderr)

_PIN_MAP = {}
_chips = {}

def _get_gpio(p):
    gpio = _PIN_MAP.get(int(p), int(p))
    chip_idx = 1 if gpio >= 352 else 0
    offset = gpio - 352 if chip_idx == 1 else gpio
    if chip_idx not in _chips:
        _chips[chip_idx] = _gpio.gpiochip_open(chip_idx)
    return _chips[chip_idx], offset

def _gpio_cleanup():
    for c in _chips.values():
        try:
            _gpio.gpiochip_close(c)
        except Exception:
            pass

atexit.register(_gpio_cleanup)
signal.signal(signal.SIGTERM, lambda s, f: (_gpio_cleanup(), exit(0)))
signal.signal(signal.SIGINT,  lambda s, f: (_gpio_cleanup(), exit(0)))

class MockDevice:
    def __getattr__(self, name):
        def method(*args, **kwargs):
            return 0
        return method

# =============================================================================
# TelemetryHAL - Modul Telemetri Generik Real-Time
# =============================================================================

import threading
from datetime import datetime, timezone

class TelemetryHAL:
    def __init__(self):
        self._running = False
        self._thread = None

    def send(self, **kwargs):
        """Kirim data telemetri generik ke aplikasi Flutter via JSON stream."""
        payload = {
            "type": "telemetry",
            "telemetry": kwargs
        }
        print(f"TELEMETRY:{json.dumps(payload)}", flush=True)

    def _auto_push_loop(self, interval):
        # We need to reference global objects: sensor, power, rfid
        # Since they are defined at the bottom, we access them via global scope
        global sensor, power, rfid
        while self._running:
            try:
                house_power = power.read_house_power() if power else {}
                solar_power = power.read_solar_power() if power else {}

                telemetry_data = {
                    "temperature": sensor.read_temperature(4) if sensor else 0,
                    "humidity": sensor.read_humidity(4) if sensor else 0,
                    "gas": sensor.read_gas() if sensor else 0,
                    "light": sensor.read_light() if sensor else 0,
                    "motion_pir1": sensor.read_motion(17) if sensor else False,
                    "motion_pir2": sensor.read_motion(27) if sensor else False,
                    "distance_cm": sensor.read_ultrasonic(22, 23) if sensor else 0,
                    "house_power": house_power,
                    "solar_power": solar_power,
                    "rfid_uid": rfid.read_uid() if rfid else None
                }

                payload = {
                    "type": "telemetry",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "telemetry": telemetry_data
                }
                print(f"TELEMETRY:{json.dumps(payload)}", flush=True)
            except Exception:
                pass

            time.sleep(interval)

    def start_stream(self, interval=1.0):
        """Memulai auto-push telemetri di background thread (Pub/Sub: Subscribe)."""
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._auto_push_loop, args=(interval,), daemon=True)
            self._thread.start()
            print('{"type": "output", "payload": "Telemetry stream started"}', flush=True)

    def stop_stream(self):
        """Menghentikan auto-push telemetri (Pub/Sub: Unsubscribe)."""
        self._running = False
        print('{"type": "output", "payload": "Telemetry stream stopped"}', flush=True)


# =============================================================================
# PinHAL - GPIO Digital & Analog (PWM)
# =============================================================================

class PinHAL:
    def __init__(self):
        self._out_pins = set()

    def _claim_out(self, chip, offset, p_name):
        err = None
        for _ in range(10):
            try:
                _gpio.gpio_claim_output(chip, offset)
                self._out_pins.add(p_name)
                return
            except Exception as e:
                err = e
                time.sleep(0.2)
        print(f"[xploria_hal] Failed to claim output pin {p_name}: {err}", file=sys.stderr)

    def set_digital(self, p, state):
        chip, offset = _get_gpio(p)
        if p not in self._out_pins:
            self._claim_out(chip, offset, p)
        val = 1 if state == 'HIGH' else 0
        _gpio.gpio_write(chip, offset, val)

    def set_analog(self, p, value):
        chip, offset = _get_gpio(p)
        if p not in self._out_pins:
            self._claim_out(chip, offset, p)
        _gpio.tx_pwm(chip, offset, 100, max(0, min(100, int(value))))

    def read_digital(self, p):
        chip, offset = _get_gpio(p)
        try:
            _gpio.gpio_claim_input(chip, offset)
        except Exception:
            pass
        return _gpio.gpio_read(chip, offset)

    def read_analog(self, p):
        return 0

# =============================================================================
# SensorHAL - Baca berbagai sensor
# =============================================================================

class SensorHAL:
    def __init__(self):
        self._in_pins = set()
        self._dht_pins = {}

    def _claim_in(self, chip, offset, p_name):
        if p_name not in self._in_pins:
            err = None
            for _ in range(10):
                try:
                    _gpio.gpio_claim_input(chip, offset, _gpio.SET_PULL_UP if hasattr(_gpio, 'SET_PULL_UP') else 0)
                    self._in_pins.add(p_name)
                    return
                except Exception as e:
                    err = e
                    time.sleep(0.2)
            print(f"[xploria_hal] Failed to claim input pin {p_name}: {err}", file=sys.stderr)

    def read_gas(self, p=17):
        chip, offset = _get_gpio(p)
        self._claim_in(chip, offset, p)
        return _gpio.gpio_read(chip, offset) == 1

    def read_motion(self, p=27):
        chip, offset = _get_gpio(p)
        self._claim_in(chip, offset, p)
        return _gpio.gpio_read(chip, offset) == 1

    def read_ir_obstacle(self, p=23):
        chip, offset = _get_gpio(p)
        self._claim_in(chip, offset, p)
        return _gpio.gpio_read(chip, offset) == 0

    def read_soil_moisture(self, p=22):
        chip, offset = _get_gpio(p)
        self._claim_in(chip, offset, p)
        return _gpio.gpio_read(chip, offset) == 0

    def read_temperature(self, p=4):
        try:
            import adafruit_dht, board
            if p not in self._dht_pins:
                self._dht_pins[p] = adafruit_dht.DHT22(getattr(board, f'D{p}'))
            val = self._dht_pins[p].temperature
            return val if val is not None else 0
        except Exception:
            return 0

    def read_humidity(self, p=4):
        try:
            import adafruit_dht, board
            if p not in self._dht_pins:
                self._dht_pins[p] = adafruit_dht.DHT22(getattr(board, f'D{p}'))
            val = self._dht_pins[p].humidity
            return val if val is not None else 0
        except Exception:
            return 0

    def read_ultrasonic(self, trig=23, echo=24):
        c_trig, o_trig = _get_gpio(trig)
        c_echo, o_echo = _get_gpio(echo)
        try:
            for _ in range(10):
                try:
                    _gpio.gpio_claim_output(c_trig, o_trig)
                    break
                except Exception:
                    time.sleep(0.2)
            for _ in range(10):
                try:
                    _gpio.gpio_claim_input(c_echo, o_echo)
                    break
                except Exception:
                    time.sleep(0.2)
            _gpio.gpio_write(c_trig, o_trig, 0)
            time.sleep(0.000002)
            _gpio.gpio_write(c_trig, o_trig, 1)
            time.sleep(0.00001)
            _gpio.gpio_write(c_trig, o_trig, 0)
            start = time.time()
            while _gpio.gpio_read(c_echo, o_echo) == 0:
                start = time.time()
            stop = time.time()
            while _gpio.gpio_read(c_echo, o_echo) == 1:
                stop = time.time()
            return (stop - start) * 34300 / 2
        except Exception:
            return 0

    def read_line(self, p=25):
        chip, offset = _get_gpio(p)
        self._claim_in(chip, offset, p)
        return 'BLACK' if _gpio.gpio_read(chip, offset) == 0 else 'WHITE'

    def read_light(self, p=24):
        chip, offset = _get_gpio(p)
        self._claim_in(chip, offset, p)
        val = _gpio.gpio_read(chip, offset)
        return 100 if val == 0 else 0

# =============================================================================
# MotorHAL - Servo, DC Motor, & Fan
# =============================================================================

class MotorHAL:
    def __init__(self):
        self._servo_pins = {}

    def set_servo(self, p=18, degree=90):
        chip, offset = _get_gpio(p)
        pulse_us = int(500 + (degree / 180.0) * 2000)
        if p not in self._servo_pins:
            try:
                _gpio.gpio_claim_output(chip, offset)
            except Exception:
                pass
            _gpio.tx_servo(chip, offset, pulse_us, 50, 500, 2500)
            self._servo_pins[p] = True
        else:
            _gpio.tx_servo(chip, offset, pulse_us)

    def run_dc(self, motor="M1", speed=0):
        pins = {"M1": (11, 13, 15), "M2": (19, 21, 23)}
        if motor not in pins:
            return
        in1, in2, ena = pins[motor]
        c1, o1 = _get_gpio(in1)
        c2, o2 = _get_gpio(in2)
        ce, oe = _get_gpio(ena)
        try:
            _gpio.gpio_claim_output(c1, o1)
            _gpio.gpio_claim_output(c2, o2)
        except Exception:
            pass
        speed = max(-100, min(100, int(speed)))
        if speed > 0:
            _gpio.gpio_write(c1, o1, 1)
            _gpio.gpio_write(c2, o2, 0)
            _gpio.tx_pwm(ce, oe, 100, speed)
        elif speed < 0:
            _gpio.gpio_write(c1, o1, 0)
            _gpio.gpio_write(c2, o2, 1)
            _gpio.tx_pwm(ce, oe, 100, -speed)
        else:
            _gpio.gpio_write(c1, o1, 0)
            _gpio.gpio_write(c2, o2, 0)
            _gpio.tx_pwm(ce, oe, 100, 0)

    def set_fan(self, speed=100):
        """Mengontrol kecepatan kipas (Motor M1) dari 0 sampai 100%"""
        self.run_dc("M1", speed)

    def stop_dc(self, motor="ALL"):
        if motor == "ALL":
            self.run_dc("M1", 0)
            self.run_dc("M2", 0)
        else:
            self.run_dc(motor, 0)

# =============================================================================
# LEDHAL - LED Digital
# =============================================================================

class LEDHAL(PinHAL):
    def __init__(self):
        super().__init__()
        self._brightness = 100
        self._led_pins = {1: 17, 2: 27, 3: 22}

    def _resolve_targets(self, target):
        if str(target) == "ALL":
            return list(self._led_pins.keys())
        return [int(target)]

    def display_color(self, target, color, secs=None):
        for t in self._resolve_targets(target):
            p = self._led_pins.get(t, t)
            self.set_digital(p, "HIGH" if color != "black" else "LOW")
        if secs is not None:
            time.sleep(secs)
            for t in self._resolve_targets(target):
                p = self._led_pins.get(t, t)
                self.set_digital(p, "LOW")

    def turn_off(self, target):
        for t in self._resolve_targets(target):
            p = self._led_pins.get(t, t)
            self.set_digital(p, "LOW")

# =============================================================================
# RFIDHAL - RFID PN532 (I2C) & Manajemen Kartu (Indentation Fixed)
# =============================================================================

class RFIDHAL:
    def __init__(self):
        self._pn532 = None
        self._initialized = False
        self._cards = {}  # { "1A2B3C4D": "ALLOW", ... }

    def _init_device(self):
        if not self._initialized:
            self._initialized = True
            try:
                import board
                import busio
                from adafruit_pn532.i2c import PN532_I2C

                i2c = busio.I2C(board.SCL, board.SDA)
                self._pn532 = PN532_I2C(i2c, debug=False)
                self._pn532.SAM_configuration()
            except Exception as e:
                self._pn532 = None

    def read_uid(self, timeout=0.1):
        self._init_device()
        if not self._pn532:
            return None
        try:
            uid = self._pn532.read_passive_target(timeout=timeout)
            if uid is not None:
                return ':'.join([f'{x:02X}' for x in uid])
            return None
        except Exception:
            return None

    def _normalize_uid(self, uid: str) -> str:
        """Membersihkan format UID agar tidak masalah jika ada titik dua/spasi."""
        if not uid:
            return ""
        return str(uid).replace(":", "").replace("-", "").replace(" ", "").strip().upper()

    def register_card(self, uid: str, access_type: str = "ALLOW"):
        """Daftarkan kartu RFID UID dengan jenis akses 'ALLOW' atau 'DENY'."""
        clean_uid = self._normalize_uid(uid)
        if not clean_uid:
            return
        self._cards[clean_uid] = access_type.upper()

    def unregister_card(self, uid: str):
        """Hapus kartu RFID UID dari daftar akses."""
        clean_uid = self._normalize_uid(uid)
        if not clean_uid:
            return
        self._cards.pop(clean_uid, None)

    def check_status(self, uid: str = None) -> str:
        """
        Mengembalikan status akses kartu:
        'DIIZINKAN', 'DITOLAK', atau 'TIDAK_TERDAFTAR'
        """
        target_uid = uid if uid else self.read_uid()
        clean_uid = self._normalize_uid(target_uid)
        if not clean_uid:
            return "TIDAK_TERDAFTAR"
        status = self._cards.get(clean_uid)
        if status == "ALLOW":
            return "DIIZINKAN"
        elif status == "DENY":
            return "DITOLAK"
        return "TIDAK_TERDAFTAR"

    def is_allowed(self, uid: str = None) -> bool:
        """Mengembalikan True jika kartu UID terdaftar dan diizinkan akses."""
        return self.check_status(uid) == "DIIZINKAN"

# Mock Devices
class AudioHAL(MockDevice): pass
class DisplayHAL(MockDevice): pass
class MotionHAL(MockDevice): pass
class LANHAL(MockDevice): pass
class AIHAL(MockDevice): pass

# Instances Siap Pakai
pin       = PinHAL()
sensor    = SensorHAL()
motor     = MotorHAL()
led       = LEDHAL()
audio     = AudioHAL()
display   = DisplayHAL()
motion    = MotionHAL()
lan       = LANHAL()
ai        = AIHAL()
telemetry = TelemetryHAL()
rfid      = RFIDHAL()