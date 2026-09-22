import time
import sys
from .core import get_gpio, get_gpio_lib

class SensorHAL:
    def __init__(self):
        self._in_pins  = {}   # { pin: pull_mode } agar bisa re-claim jika mode berbeda
        self._dht_pins = {}
        self._dht_cache = {}

    def _claim_in(self, chip, offset, p_name, pull=0):
        """
        Klaim pin sebagai input.
        pull=0           → no pull (untuk active-high seperti MQ gas, PIR)
        pull=SET_PULL_UP → internal pull-up (untuk active-low seperti soil, IR)
        
        PENTING: SET_PULL_UP pada sensor active-high akan menyebabkan nilai
        selalu True karena pin di-pull ke HIGH saat sensor tidak aktif.
        """
        _gpio = get_gpio_lib()
        if not _gpio: return

        # Re-claim jika pull mode berubah
        if self._in_pins.get(p_name) == pull:
            return

        try:
            _gpio.gpio_free(chip, offset)
        except Exception:
            pass

        err = None
        for _ in range(10):
            try:
                _gpio.gpio_claim_input(chip, offset, pull)
                self._in_pins[p_name] = pull
                return
            except Exception as e:
                err = e
                time.sleep(0.2)
        print(f"[xploria_hal] Failed to claim input pin {p_name} pull={pull}: {err}", file=sys.stderr)

    def _read_raw(self, p, pull=0):
        """Baca nilai raw GPIO (0 atau 1) dengan pull mode yang ditentukan."""
        _gpio = get_gpio_lib()
        if not _gpio: return None

        chip, offset = get_gpio(p)
        if not chip: return None

        self._claim_in(chip, offset, p, pull)
        try:
            return _gpio.gpio_read(chip, offset)
        except Exception:
            return None

    def read_gas(self, p=17):
        """MQ Gas sensor: active-low (DO LOW saat gas terdeteksi, modul LM393)."""
        raw = self._read_raw(p, pull=0)
        return (raw == 0) if raw is not None else False

    def read_motion(self, p=27):
        """
        PIR sensor: active-high.
        Menggunakan SET_PULL_DOWN agar pin tidak floating saat sensor idle.
        Idle  = pin LOW  → False
        Gerak = pin HIGH → True
        """
        _gpio = get_gpio_lib()
        pull_down = getattr(_gpio, 'SET_PULL_DOWN', 1) if _gpio else 1
        raw = self._read_raw(p, pull=pull_down)
        return bool(raw) if raw is not None else False

    def read_ir_obstacle(self, p=23):
        """IR obstacle: active-low (output LOW saat ada halangan)."""
        _gpio = get_gpio_lib()
        pull_up = getattr(_gpio, 'SET_PULL_UP', 2) if _gpio else 2
        raw = self._read_raw(p, pull=pull_up)
        return (raw == 0) if raw is not None else False

    def read_soil_moisture(self, p=22):
        """Soil moisture: active-low (output LOW saat lembab)."""
        _gpio = get_gpio_lib()
        pull_up = getattr(_gpio, 'SET_PULL_UP', 2) if _gpio else 2
        raw = self._read_raw(p, pull=pull_up)
        return (raw == 0) if raw is not None else False

    def read_line(self, p=25):
        """Line sensor: active-low untuk garis hitam."""
        _gpio = get_gpio_lib()
        pull_up = getattr(_gpio, 'SET_PULL_UP', 2) if _gpio else 2
        raw = self._read_raw(p, pull=pull_up)
        return 'BLACK' if raw == 0 else 'WHITE'

    def read_light(self, p=24):
        """LDR: active-low (output LOW saat ada cahaya)."""
        _gpio = get_gpio_lib()
        pull_up = getattr(_gpio, 'SET_PULL_UP', 2) if _gpio else 2
        raw = self._read_raw(p, pull=pull_up)
        return 100 if raw == 0 else 0

    def _get_dht_cached_reading(self, p, key):
        """
        Membaca DHT22 via adafruit_dht dengan cache throttle 2 detik.
        DHT22 default pin adalah 4 sesuai wiring fisik aktual.
        """
        now = time.time()

        if p not in self._dht_cache:
            self._dht_cache[p] = {'last_read': 0, 'temperature': 0, 'humidity': 0}

        if now - self._dht_cache[p]['last_read'] < 2.0:
            return self._dht_cache[p][key]

        try:
            import adafruit_dht, board
            if p not in self._dht_pins:
                self._dht_pins[p] = adafruit_dht.DHT22(getattr(board, f'D{p}'))

            val_temp = self._dht_pins[p].temperature
            val_hum  = self._dht_pins[p].humidity

            if val_temp is not None:
                self._dht_cache[p]['temperature'] = val_temp
            if val_hum is not None:
                self._dht_cache[p]['humidity'] = val_hum

        except Exception as e:
            print(f"[xploria_hal] DHT error pin {p}: {e}", file=sys.stderr)
            if p in self._dht_pins:
                try:
                    self._dht_pins[p].exit()
                except Exception:
                    pass
                del self._dht_pins[p]

        self._dht_cache[p]['last_read'] = now
        return self._dht_cache[p][key]

    def read_temperature(self, p=4):
        return self._get_dht_cached_reading(p, 'temperature')

    def read_humidity(self, p=4):
        return self._get_dht_cached_reading(p, 'humidity')

    def read_ultrasonic(self, trig=23, echo=24):
        _gpio = get_gpio_lib()
        if not _gpio: return 0

        c_trig, o_trig = get_gpio(trig)
        c_echo, o_echo = get_gpio(echo)

        if not c_trig or not c_echo: return 0

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
            timeout = start + 0.04

            while _gpio.gpio_read(c_echo, o_echo) == 0:
                start = time.time()
                if start > timeout: return 0

            stop = time.time()
            while _gpio.gpio_read(c_echo, o_echo) == 1:
                stop = time.time()
                if stop > timeout: return 0

            return (stop - start) * 34300 / 2
        except Exception:
            return 0

