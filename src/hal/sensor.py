import time
import sys
from .core import get_gpio, get_gpio_lib

class SensorHAL:
    def __init__(self):
        self._in_pins  = {}   # { pin: pull_mode } agar bisa re-claim jika mode berbeda
        self._dht_cache = {}

    def _claim_in(self, chip, offset, p_name, pull=0):
        _gpio = get_gpio_lib()
        if not _gpio: return

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
        _gpio = get_gpio_lib()
        pull_up = getattr(_gpio, 'SET_PULL_UP', 2) if _gpio else 2
        raw = self._read_raw(p, pull=pull_up)
        return (raw == 0) if raw is not None else False

    def read_soil_moisture(self, p=22):
        _gpio = get_gpio_lib()
        pull_up = getattr(_gpio, 'SET_PULL_UP', 2) if _gpio else 2
        raw = self._read_raw(p, pull=pull_up)
        return (raw == 0) if raw is not None else False

    def read_line(self, p=25):
        _gpio = get_gpio_lib()
        pull_up = getattr(_gpio, 'SET_PULL_UP', 2) if _gpio else 2
        raw = self._read_raw(p, pull=pull_up)
        return 'BLACK' if raw == 0 else 'WHITE'

    def read_light(self, p=24):
        _gpio = get_gpio_lib()
        pull_up = getattr(_gpio, 'SET_PULL_UP', 2) if _gpio else 2
        raw = self._read_raw(p, pull=pull_up)
        return 100 if raw == 0 else 0

    def _read_dht22_lgpio(self, p):
        """
        Implementasi native bit-banging DHT22 dengan lgpio murni.
        Sangat anti-crash: tidak menggunakan library blinka, tidak ada IPC queue,
        timeout yang jelas sehingga tidak bisa hang.
        """
        _gpio = get_gpio_lib()
        if not _gpio: return None, None

        chip, offset = get_gpio(p)
        if not chip: return None, None

        # Bebaskan pin dan lupakan dari registry claim sementara
        try:
            _gpio.gpio_free(chip, offset)
        except Exception:
            pass
        self._in_pins.pop(p, None)

        try:
            # 1. Kirim START Signal (LOW 2ms lalu HIGH dan lepas)
            _gpio.gpio_claim_output(chip, offset, 1)
            time.sleep(0.01)
            _gpio.gpio_write(chip, offset, 0)
            time.sleep(0.002) # 2 milidetik (cukup untuk DHT11 maupun DHT22)
            _gpio.gpio_write(chip, offset, 1)

            # 2. Switch pin jadi input untuk mendengarkan balasan sensor
            _gpio.gpio_free(chip, offset)
            _gpio.gpio_claim_input(chip, offset, getattr(_gpio, 'SET_PULL_UP', 0))

            # Fungsi timeout sederhana (aman dari IPC blocking)
            def wait_for(target_state, timeout_s=0.01):
                start = time.time()
                while _gpio.gpio_read(chip, offset) != target_state:
                    if time.time() - start > timeout_s:
                        return False
                return True

            # Tunggu sensor merespon: pull LOW lalu pull HIGH
            if not wait_for(0, 0.01): return None, None
            if not wait_for(1, 0.01): return None, None
            if not wait_for(0, 0.01): return None, None

            # 3. Baca 40 bit data
            bits = []
            for _ in range(40):
                # Tunggu sinyal mulai LOW (selesai masa HIGH tunggu)
                if not wait_for(1, 0.01): return None, None
                
                # Hitung durasi sinyal HIGH (ini yang menentukan bit 0 atau 1)
                t_start = time.time()
                if not wait_for(0, 0.01): return None, None
                t_high = time.time() - t_start

                # High signal > 40 microseconds adalah 1, kalau tidak 0
                bits.append(1 if t_high > 0.000040 else 0)

            # 4. Parsing dan Checksum
            if len(bits) != 40: return None, None

            def bits_to_int(start_idx, end_idx):
                res = 0
                for bit in bits[start_idx:end_idx]:
                    res = (res << 1) | bit
                return res

            h_int = bits_to_int(0, 8)
            h_dec = bits_to_int(8, 16)
            t_int = bits_to_int(16, 24)
            t_dec = bits_to_int(24, 32)
            checksum = bits_to_int(32, 40)

            if ((h_int + h_dec + t_int + t_dec) & 0xFF) != checksum:
                return None, None

            humidity = h_int + h_dec / 10.0
            temperature = t_int + t_dec / 10.0

            # Suhu negatif
            if bits[16] == 1:
                temperature = -temperature

            return temperature, humidity

        except Exception as e:
            import sys
            print(f"[sensor] DHT read error on pin {p}: {e}", file=sys.stderr)
            return None, None
        finally:
            try:
                _gpio.gpio_free(chip, offset)
            except Exception:
                pass

    def _get_dht_cached_reading(self, p, key):
        now = time.time()
        
        if p not in self._dht_cache:
            self._dht_cache[p] = {'last_read': 0, 'temperature': 0, 'humidity': 0}

        # Kembalikan cache jika belum lewat 2 detik
        if now - self._dht_cache[p]['last_read'] < 2.0:
            return self._dht_cache[p][key]

        temp, hum = self._read_dht22_lgpio(p)

        if temp is not None and hum is not None:
            self._dht_cache[p]['temperature'] = temp
            self._dht_cache[p]['humidity'] = hum
            self._dht_cache[p]['last_read'] = now

        # Tetap update timestamp meskipun gagal, agar tidak memborbardir pin yang mati
        # dengan polling berturut-turut tanpa jeda
        if temp is None:
            import sys
            self._dht_cache[p]['last_read'] = now
            print(f"[sensor] DHT read failed on pin {p}, returning cached value: {self._dht_cache[p][key]}", file=sys.stderr)

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

        # Pastikan pin dibebaskan dulu (dari bacaan sebelumnya)
        try:
            _gpio.gpio_free(c_trig, o_trig)
            _gpio.gpio_free(c_echo, o_echo)
        except Exception:
            pass

        try:
            # 1. Setup Pin
            _gpio.gpio_claim_output(c_trig, o_trig)
            # Echo butuh PULL DOWN agar idle = 0
            _gpio.gpio_claim_input(c_echo, o_echo, getattr(_gpio, 'SET_PULL_DOWN', 1))

            # 2. Trigger
            _gpio.gpio_write(c_trig, o_trig, 0)
            time.sleep(0.002) # Settle time

            _gpio.gpio_write(c_trig, o_trig, 1)
            time.sleep(0.00001) # 10us pulse
            _gpio.gpio_write(c_trig, o_trig, 0)

            # 3. Tunggu balasan HIGH
            t_timeout = time.time() + 0.1
            pulse_start = time.time()
            while _gpio.gpio_read(c_echo, o_echo) == 0:
                pulse_start = time.time()
                if pulse_start > t_timeout:
                    return 0

            # 4. Tunggu balasan kembali LOW (selesai mantul)
            t_timeout = time.time() + 0.1
            pulse_end = time.time()
            while _gpio.gpio_read(c_echo, o_echo) == 1:
                pulse_end = time.time()
                if pulse_end > t_timeout:
                    return 0

            # 5. Hitung jarak (Durasi * Kecepatan Suara / 2)
            duration = pulse_end - pulse_start
            distance_cm = (duration * 34300) / 2.0
            
            # Batasi nilai logika ultrasonik HC-SR04 (maks ~400 cm)
            if distance_cm > 400:
                return 400
                
            return round(distance_cm, 1)

        except Exception as e:
            print(f"[xploria_hal] Ultrasonic Error: {e}", file=sys.stderr)
            return 0
        finally:
            # SANGAT PENTING: Bebaskan pin agar iterasi berikutnya tidak error
            try:
                _gpio.gpio_free(c_trig, o_trig)
                _gpio.gpio_free(c_echo, o_echo)
            except Exception:
                pass

