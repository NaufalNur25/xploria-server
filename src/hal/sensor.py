import time
import sys
from .core import get_gpio, get_gpio_lib

class SensorHAL:
    def __init__(self):
        self._in_pins = set()
        self._dht_pins = {}
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

    def _read_dht22_lgpio(self, p):
        """
        Membaca DHT22 langsung via lgpio tanpa adafruit_dht atau RPi.GPIO.
        Protokol DHT22:
          1. Kirim sinyal START: pull LOW 1ms, lalu pull HIGH dan lepas
          2. Sensor merespons: LOW 80us, HIGH 80us
          3. 40 bit data: setiap bit dimulai LOW 50us, lalu HIGH
             - HIGH ~26-28us = bit 0
             - HIGH ~70us    = bit 1
          4. Parse 40 bit → 2 byte humidity + 2 byte temp + 1 byte checksum
        """
        _gpio = get_gpio_lib()
        if not _gpio:
            return None, None

        chip, offset = get_gpio(p)
        if not chip:
            return None, None

        # Bebaskan pin dulu jika sebelumnya diklaim sebagai input
        try:
            _gpio.gpio_free(chip, offset)
        except Exception:
            pass
        self._in_pins.discard(p)

        try:
            # --- KIRIM SINYAL START ---
            _gpio.gpio_claim_output(chip, offset, 0, 1)  # HIGH
            time.sleep(0.05)
            _gpio.gpio_write(chip, offset, 0)            # LOW
            time.sleep(0.001)                            # 1ms LOW
            _gpio.gpio_write(chip, offset, 1)            # HIGH

            # --- SWITCH KE INPUT untuk baca respons sensor ---
            _gpio.gpio_free(chip, offset)
            _gpio.gpio_claim_input(chip, offset, 0)      # no pull

            # Tunggu sensor menarik LOW (respons awal)
            timeout = time.time() + 0.1
            while _gpio.gpio_read(chip, offset) == 1:
                if time.time() > timeout:
                    return None, None

            # Baca 40 bit data
            bits = []
            for _ in range(40):
                # Tunggu LOW (start of bit) selesai
                timeout = time.time() + 0.1
                while _gpio.gpio_read(chip, offset) == 0:
                    if time.time() > timeout:
                        return None, None

                # Hitung durasi HIGH
                t_start = time.time()
                timeout = time.time() + 0.1
                while _gpio.gpio_read(chip, offset) == 1:
                    if time.time() > timeout:
                        return None, None
                t_high = time.time() - t_start

                # HIGH > 40us = bit 1, HIGH < 40us = bit 0
                bits.append(1 if t_high > 0.00004 else 0)

            # --- PARSE 40 BIT ---
            if len(bits) != 40:
                return None, None

            def bits_to_int(b):
                val = 0
                for bit in b:
                    val = (val << 1) | bit
                return val

            hum_int  = bits_to_int(bits[0:8])
            hum_dec  = bits_to_int(bits[8:16])
            temp_int = bits_to_int(bits[16:24])
            temp_dec = bits_to_int(bits[24:32])
            checksum = bits_to_int(bits[32:40])

            # Validasi checksum
            calc = (hum_int + hum_dec + temp_int + temp_dec) & 0xFF
            if calc != checksum:
                return None, None

            humidity    = hum_int + hum_dec / 10.0
            temperature = temp_int + temp_dec / 10.0

            # DHT22 bisa encode suhu negatif dengan MSB bit 16
            if bits[16] == 1:
                temperature = -temperature

            return temperature, humidity

        except Exception as e:
            print(f"[xploria_hal] DHT22 lgpio read error pin {p}: {e}", file=sys.stderr)
            return None, None
        finally:
            # Kembalikan pin ke INPUT biasa setelah selesai
            try:
                _gpio.gpio_free(chip, offset)
                _gpio.gpio_claim_input(chip, offset, getattr(_gpio, 'SET_PULL_UP', 0))
                self._in_pins.add(p)
            except Exception:
                pass

    def _get_dht_cached_reading(self, p, key):
        """
        Membaca DHT22 dengan throttle 2 detik (hardware limit DHT22).
        Menggunakan lgpio langsung — tanpa adafruit_dht, tanpa RPi.GPIO.
        """
        now = time.time()

        if p not in self._dht_cache:
            self._dht_cache[p] = {'last_read': 0, 'temperature': 0, 'humidity': 0}

        if now - self._dht_cache[p]['last_read'] < 2.0:
            return self._dht_cache[p][key]

        temperature, humidity = self._read_dht22_lgpio(p)

        if temperature is not None:
            self._dht_cache[p]['temperature'] = temperature
        if humidity is not None:
            self._dht_cache[p]['humidity'] = humidity

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
