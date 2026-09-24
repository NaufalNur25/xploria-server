import logging
import time
from .core import get_gpio, get_gpio_lib

logger = logging.getLogger(__name__)

class MotorHAL:
    def __init__(self):
        self._servo_pins = {}
        self._claimed_pins = set()  # Track pin yang sudah di-claim

    def _ensure_pin_output(self, chip, offset, pin_num):
        """Helper untuk memastikan pin telah di-claim sebagai output."""
        _gpio = get_gpio_lib()
        if pin_num not in self._claimed_pins:
            try:
                _gpio.gpio_claim_output(chip, offset)
                self._claimed_pins.add(pin_num)
            except Exception as e:
                logger.warning(f"Motor claim pin {pin_num} error: {e}")

    # =========================================================================
    # KONTROL SERVO 180° STANDAR (Posisi Sudut 0 - 180)
    # =========================================================================
    def set_servo(self, p=18, degree=90):
        """
        Kontrol Servo 180 derajat standar.
        - degree: 0 s/d 180 derajat
        """
        _gpio = get_gpio_lib()
        if not _gpio: return

        chip, offset = get_gpio(p)
        if not chip: return

        self._ensure_pin_output(chip, offset, p)
        pulse_us = int(500 + (degree / 180.0) * 2000)

        try:
            _gpio.tx_servo(chip, offset, pulse_us, 50, 500, 2500)
            self._servo_pins[p] = True
        except Exception as e:
            logger.warning(f"Servo error on pin {p}: {e}")

    # =========================================================================
    # KONTROL SERVO 360° (Continuous Rotation - Arah & Kecepatan)
    # =========================================================================
    def set_servo360(self, p=18, speed=0, duration=None):
        """
        Kontrol Servo 360 derajat (Continuous Rotation):
        - p        : Nomor pin GPIO BCM (default 18)
        - speed    : -100 (Mundur Penuh) s/d +100 (Maju Penuh)
                     0 = STOP TOTAL (Pulsa PWM dimatikan, bebas getar)
        - duration : (Opsional) Berputar selama sekian detik lalu otomatis STOP
        """
        _gpio = get_gpio_lib()
        if not _gpio: return

        chip, offset = get_gpio(p)
        if not chip: return

        self._ensure_pin_output(chip, offset, p)

        # Jika speed == 0, matikan pulsa seketika agar servo DIAM & TIDAK GETAR
        if speed == 0:
            self.stop_servo(p)
            return

        # Batasi rentang kecepatan -100 s/d 100
        speed = max(-100, min(100, int(speed)))

        # Pemetaan: 1500us netral, 1000us mundur penuh, 2000us maju penuh
        pulse_us = int(1500 + (speed / 100.0) * 500)

        try:
            _gpio.tx_servo(chip, offset, pulse_us, 50, 500, 2500)
            self._servo_pins[p] = True

            # Jika ada batas durasi waktu berputar:
            if duration and duration > 0:
                time.sleep(duration)
                self.stop_servo(p)

        except Exception as e:
            logger.warning(f"Servo 360 error on pin {p}: {e}")

    def stop_servo(self, p=18):
        """Mematikan pulsa PWM servo seketika (diam total & bebas getar)."""
        _gpio = get_gpio_lib()
        if not _gpio: return

        chip, offset = get_gpio(p)
        if not chip: return

        try:
            # Di lgpio, pulse_us = 0 mematikan pulsa PWM pada pin tersebut
            _gpio.tx_servo(chip, offset, 0, 0, 0, 0)
        except Exception:
            try:
                _gpio.tx_pwm(chip, offset, 0, 0)
            except Exception:
                pass

    # =========================================================================
    # KONTROL MOTOR DC & KIPAS (Driver L298N / MOSFET)
    # =========================================================================
    def run_dc(self, motor="M1", speed=0):
        _gpio = get_gpio_lib()
        if not _gpio: return

        pins = {"M1": (11, 13, 15), "M2": (19, 21, 23)}
        if motor not in pins:
            return

        in1, in2, ena = pins[motor]
        c1, o1 = get_gpio(in1)
        c2, o2 = get_gpio(in2)
        ce, oe = get_gpio(ena)

        if not c1 or not c2 or not ce: return

        for chip, offset, pin_num in [(c1, o1, in1), (c2, o2, in2), (ce, oe, ena)]:
            self._ensure_pin_output(chip, offset, pin_num)

        speed = max(-100, min(100, int(speed)))

        try:
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
        except Exception as e:
            logger.error(f"Motor {motor} run error: {e}")

    def set_fan(self, speed=100):
        """Mengontrol kecepatan kipas (Motor M1) dari 0 sampai 100%"""
        self.run_dc("M1", speed)

    def stop_dc(self, motor="ALL"):
        if motor == "ALL":
            self.run_dc("M1", 0)
            self.run_dc("M2", 0)
        else:
            self.run_dc(motor, 0)
