import time
import sys
from .core import get_gpio, get_gpio_lib

class SensorHAL:
    def __init__(self):
        self._in_pins = set()
        self._dht_pins = {}
        # Menambahkan cache untuk DHT agar tidak crash saat di-polling cepat
        self._dht_cache = {} 

    def _claim_in(self, chip, offset, p_name):
        _gpio = get_gpio_lib()
        if not _gpio: return
        
        if p_name not in self._in_pins:
            err = None
            for _ in range(10):
                try:
                    _gpio.gpio_claim_input(chip, offset, getattr(_gpio, 'SET_PULL_UP', 0))
                    self._in_pins.add(p_name)
                    return
                except Exception as e:
                    err = e
                    time.sleep(0.2)
            print(f"[xploria_hal] Failed to claim input pin {p_name}: {err}", file=sys.stderr)

    def _read_digital_bool(self, p, active_high=True):
        _gpio = get_gpio_lib()
        if not _gpio: return False
        
        chip, offset = get_gpio(p)
        if not chip: return False
        
        self._claim_in(chip, offset, p)
        try:
            val = _gpio.gpio_read(chip, offset)
            return (val == 1) if active_high else (val == 0)
        except Exception:
            return False

    def read_gas(self, p=17):
        return self._read_digital_bool(p, active_high=True)

    def read_motion(self, p=27):
        return self._read_digital_bool(p, active_high=True)

    def read_ir_obstacle(self, p=23):
        return self._read_digital_bool(p, active_high=False)

    def read_soil_moisture(self, p=22):
        return self._read_digital_bool(p, active_high=False)

    def _release_lgpio_pin(self, p):
        """
        Bebaskan klaim lgpio pada pin p sebelum adafruit_dht menggunakannya.
        lgpio dan adafruit_dht (libgpiod/pulseio) tidak bisa memegang pin yang sama
        secara bersamaan — salah satunya harus melepas klaim terlebih dahulu.
        """
        from .core import get_gpio, get_gpio_lib
        _gpio = get_gpio_lib()
        if not _gpio:
            return
        chip, offset = get_gpio(p)
        if not chip:
            return
        try:
            _gpio.gpio_free(chip, offset)
        except Exception:
            pass
        # Hapus dari set agar bisa di-claim ulang oleh lgpio jika perlu nanti
        self._in_pins.discard(p)

    def _get_dht_cached_reading(self, p, key):
        """
        Membaca DHT22 dengan:
        1. Throttle 2 detik (hardware limit DHT22)
        2. Melepas klaim lgpio sebelum adafruit_dht membaca
        3. Tidak memanggil .measure() yang tidak ada di adafruit_dht
        """
        now = time.time()

        # Inisialisasi cache jika belum ada
        if p not in self._dht_cache:
            self._dht_cache[p] = {'last_read': 0, 'temperature': 0, 'humidity': 0}

        # Kembalikan nilai cache jika belum waktunya baca hardware lagi
        if now - self._dht_cache[p]['last_read'] < 2.0:
            return self._dht_cache[p][key]

        # Bebaskan pin dari lgpio SEBELUM adafruit_dht mencoba menggunakannya
        self._release_lgpio_pin(p)

        try:
            import adafruit_dht, board

            if p not in self._dht_pins:
                pin_attr = getattr(board, f'D{p}', None)
                if pin_attr is None:
                    print(f"[xploria_hal] board.D{p} tidak ditemukan", file=sys.stderr)
                    return self._dht_cache[p][key]
                self._dht_pins[p] = adafruit_dht.DHT22(pin_attr)

            # adafruit_dht TIDAK memiliki .measure() — langsung baca property
            val_temp = self._dht_pins[p].temperature
            val_hum  = self._dht_pins[p].humidity

            if val_temp is not None:
                self._dht_cache[p]['temperature'] = val_temp
            if val_hum is not None:
                self._dht_cache[p]['humidity'] = val_hum

            self._dht_cache[p]['last_read'] = now

        except Exception as e:
            # Catat error ke stderr agar bisa di-debug, tapi tetap return cache terakhir
            print(f"[xploria_hal] DHT error pin {p}: {e}", file=sys.stderr)
            # Reset instance DHT yang mungkin rusak agar percobaan berikutnya membuat ulang
            if p in self._dht_pins:
                try:
                    self._dht_pins[p].exit()
                except Exception:
                    pass
                del self._dht_pins[p]
            # Tetap update last_read agar tidak spam hardware saat error berturut-turut
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

    def read_line(self, p=25):
        val = self._read_digital_bool(p, active_high=False)
        return 'BLACK' if val else 'WHITE'

    def read_light(self, p=24):
        val = self._read_digital_bool(p, active_high=False)
        return 100 if val else 0
