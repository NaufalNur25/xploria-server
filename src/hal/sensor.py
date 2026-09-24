import time
import logging
import threading
from .core import get_gpio, get_gpio_lib

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background worker: DHT22
# ---------------------------------------------------------------------------

class _DHTWorker(threading.Thread):
    """
    Dedicated daemon thread yang membaca sensor DHT22 secara kontinu.

    Arsitektur:
    - Thread ini berjalan selamanya di background (daemon=True).
    - Setiap selesai membaca (berhasil atau gagal) langsung update _cache
      yang dilindungi oleh _lock.
    - read_temperature() / read_humidity() di SensorHAL hanya perlu baca
      nilai dari _cache — 100% non-blocking, tidak pernah menyentuh GPIO
      dari event loop utama.
    - Interval minimum antar baca adalah DHT22_MIN_INTERVAL (2 detik),
      sesuai spesifikasi sensor. Saat gagal cooldown diperpendek (0.5 detik)
      agar retry lebih cepat tanpa spam.
    """

    DHT22_MIN_INTERVAL = 2.0   # detik, minimum antar pembacaan
    RETRY_BASE         = 0.5   # detik base untuk backoff
    MAX_FAILURES       = 5     # batas maksimal gagal sebelum pause panjang
    MAX_COOLDOWN       = 60.0  # detik, pause panjang jika sensor mati

    def __init__(self, pin: int):
        super().__init__(name=f"DHT-worker-GPIO{pin}", daemon=True)
        self.pin = pin
        self._lock = threading.Lock()
        self._cache = {"temperature": None, "humidity": None, "last_ok": 0.0}
        self._stop_event = threading.Event()
        self._fail_count = 0
        self._dht_device = None

    def stop(self):
        self._stop_event.set()
        if self._dht_device is not None:
            try:
                self._dht_device.exit()
            except:
                pass

    def get(self, key: str):
        """Non-blocking: kembalikan nilai cache saat ini (None jika belum ada data)."""
        with self._lock:
            return self._cache[key]

    # ------------------------------------------------------------------
    # Internal: DHT22 via adafruit_dht
    # ------------------------------------------------------------------

    def _init_device(self):
        if self._dht_device is None:
            try:
                import adafruit_dht
                import board
                pin_name = f"D{self.pin}"
                if hasattr(board, pin_name):
                    self._dht_device = adafruit_dht.DHT22(getattr(board, pin_name))
                else:
                    logger.error(f"Board does not have pin {pin_name}")
            except Exception as e:
                logger.error(f"Failed to initialize adafruit_dht for pin {self.pin}: {e}")

    def _read_raw(self):
        """
        Baca satu sampel dari sensor DHT22 via adafruit_dht.
        Return (temperature_float, humidity_float) atau (None, None).
        Dipanggil HANYA dari dalam thread ini.
        """
        self._init_device()
        if self._dht_device is None:
            return None, None
            
        try:
            t = self._dht_device.temperature
            h = self._dht_device.humidity
            return t, h
        except RuntimeError as e:
            # RuntimeError wajar dilempar oleh adafruit_dht saat gagal baca (checksum, timeout)
            logger.debug(f"DHT22 pin {self.pin} read error: {e}")
            return None, None
        except Exception as e:
            logger.warning(f"DHT22 pin {self.pin} unexpected error: {e}")
            return None, None

    # ------------------------------------------------------------------
    # Thread loop
    # ------------------------------------------------------------------

    def run(self):
        logger.info(f"DHT worker started for GPIO {self.pin}")
        while not self._stop_event.is_set():
            t, h = self._read_raw()

            with self._lock:
                if t is not None and h is not None:
                    self._cache["temperature"] = t
                    self._cache["humidity"]    = h
                    self._cache["last_ok"]     = time.time()
                    self._fail_count = 0  # Reset fail count
                    logger.debug(f"DHT22 GPIO{self.pin}: {t:.1f}°C  {h:.1f}%")
                    sleep_s = self.DHT22_MIN_INTERVAL
                else:
                    self._fail_count += 1
                    if self._fail_count >= self.MAX_FAILURES:
                        sleep_s = self.MAX_COOLDOWN
                        logger.warning(f"DHT22 GPIO{self.pin} failed {self._fail_count} times, pausing for {sleep_s}s")
                    else:
                        sleep_s = self.RETRY_BASE * (2 ** (self._fail_count - 1))  # Exponential backoff
                        logger.debug(f"DHT22 GPIO{self.pin} failed, backoff {sleep_s}s (fail {self._fail_count})")

            # Tunggu sebelum baca berikutnya; bisa diinterupsi oleh stop()
            self._stop_event.wait(timeout=sleep_s)

        logger.info(f"DHT worker stopped for GPIO {self.pin}")


# ---------------------------------------------------------------------------
# Background worker: HC-SR04 Ultrasonic
# ---------------------------------------------------------------------------

class _UltrasonicWorker(threading.Thread):
    """
    Dedicated daemon thread yang membaca sensor HC-SR04 secara kontinu.

    Alasan dipisah ke thread sendiri:
    - HC-SR04 bisa memblokir hingga 200ms (menunggu echo pulse).
    - Satu thread di-pin ke pasangan (trig, echo) sehingga tidak ada
      GPIO contention dengan sensor lain.
    - Event loop WebSocket hanya perlu read float dari _cache.
    """

    POLL_INTERVAL = 2.0   # detik antar pembacaan (sinkron dengan push interval)
    ECHO_TIMEOUT  = 0.1   # timeout echo (100ms = ~1700cm, lebih dari cukup)
    RETRY_BASE    = 0.5
    MAX_FAILURES  = 5
    MAX_COOLDOWN  = 60.0

    def __init__(self, trig: int, echo: int):
        super().__init__(name=f"Ultrasonic-worker-TRIG{trig}", daemon=True)
        self.trig = trig
        self.echo = echo
        self._lock = threading.Lock()
        self._cache: float = 0.0
        self._stop_event = threading.Event()
        self._fail_count = 0

    def stop(self):
        self._stop_event.set()

    def get(self) -> float:
        """Non-blocking: kembalikan jarak terakhir dalam cm."""
        with self._lock:
            return self._cache

    def _read_raw(self) -> float:
        _gpio = get_gpio_lib()
        if not _gpio:
            return 0.0

        c_trig, o_trig = get_gpio(self.trig)
        c_echo, o_echo = get_gpio(self.echo)
        if not c_trig or not c_echo:
            return 0.0

        try:
            _gpio.gpio_free(c_trig, o_trig)
            _gpio.gpio_free(c_echo, o_echo)
        except Exception:
            pass

        try:
            _gpio.gpio_claim_output(c_trig, o_trig)
            _gpio.gpio_claim_input(c_echo, o_echo, getattr(_gpio, 'SET_PULL_DOWN', 1))

            # Settle
            _gpio.gpio_write(c_trig, o_trig, 0)
            time.sleep(0.002)

            # 10µs trigger pulse
            _gpio.gpio_write(c_trig, o_trig, 1)
            time.sleep(0.00001)
            _gpio.gpio_write(c_trig, o_trig, 0)

            # Tunggu echo HIGH
            deadline = time.time() + self.ECHO_TIMEOUT
            while _gpio.gpio_read(c_echo, o_echo) == 0:
                if time.time() > deadline:
                    return 0.0
            pulse_start = time.time()

            # Tunggu echo LOW
            deadline = time.time() + self.ECHO_TIMEOUT
            while _gpio.gpio_read(c_echo, o_echo) == 1:
                if time.time() > deadline:
                    return 0.0
            pulse_end = time.time()

            dist = ((pulse_end - pulse_start) * 34300) / 2.0
            return round(min(dist, 400.0), 1)

        except Exception as e:
            logger.debug(f"Ultrasonic TRIG{self.trig} error: {e}")
            return 0.0
        finally:
            try:
                _gpio.gpio_free(c_trig, o_trig)
                _gpio.gpio_free(c_echo, o_echo)
            except Exception:
                pass

    def run(self):
        logger.info(f"Ultrasonic worker started for TRIG GPIO{self.trig} / ECHO GPIO{self.echo}")
        while not self._stop_event.is_set():
            dist = self._read_raw()
            with self._lock:
                if dist > 0.0:  # Valid reading (assuming 0.0 is failure/timeout)
                    self._cache = dist
                    self._fail_count = 0
                    sleep_s = self.POLL_INTERVAL
                    logger.debug(f"Ultrasonic TRIG{self.trig}: {dist} cm")
                else:
                    self._fail_count += 1
                    if self._fail_count >= self.MAX_FAILURES:
                        sleep_s = self.MAX_COOLDOWN
                        logger.warning(f"Ultrasonic TRIG{self.trig} failed {self._fail_count} times, pausing for {sleep_s}s")
                    else:
                        sleep_s = self.RETRY_BASE * (2 ** (self._fail_count - 1))
                        logger.debug(f"Ultrasonic TRIG{self.trig} failed, backoff {sleep_s}s (fail {self._fail_count})")
                        
            self._stop_event.wait(timeout=sleep_s)

        logger.info(f"Ultrasonic worker stopped for TRIG GPIO{self.trig}")


# ---------------------------------------------------------------------------
# Registry worker: satu instance per pin agar tidak dobel
# ---------------------------------------------------------------------------

_dht_workers: dict[int, _DHTWorker] = {}
_dht_workers_lock = threading.Lock()

_ultrasonic_workers: dict[tuple, _UltrasonicWorker] = {}
_ultrasonic_workers_lock = threading.Lock()


def _get_dht_worker(pin: int) -> _DHTWorker:
    with _dht_workers_lock:
        if pin not in _dht_workers:
            w = _DHTWorker(pin)
            w.start()
            _dht_workers[pin] = w
        return _dht_workers[pin]


def _get_ultrasonic_worker(trig: int, echo: int) -> _UltrasonicWorker:
    key = (trig, echo)
    with _ultrasonic_workers_lock:
        if key not in _ultrasonic_workers:
            w = _UltrasonicWorker(trig, echo)
            w.start()
            _ultrasonic_workers[key] = w
        return _ultrasonic_workers[key]


def stop_all_workers():
    """Hentikan semua background worker (dipanggil saat shutdown)."""
    with _dht_workers_lock:
        for w in _dht_workers.values():
            w.stop()
        _dht_workers.clear()
    with _ultrasonic_workers_lock:
        for w in _ultrasonic_workers.values():
            w.stop()
        _ultrasonic_workers.clear()


# ---------------------------------------------------------------------------
# SensorHAL
# ---------------------------------------------------------------------------

class SensorHAL:
    def __init__(self):
        self._in_pins = {}   # { pin: pull_mode }
        self._ads = None
        self._ads_initialized = False

    def _init_ads(self):
        if not self._ads_initialized:
            try:
                import board
                import busio
                import adafruit_ads1x15.ads1115 as ADS
                from adafruit_ads1x15.analog_in import AnalogIn
                
                # Menggunakan board.I2C() agar bisa berbagi (share) bus dengan modul lain seperti RFID
                i2c = board.I2C()
                self._ads = ADS.ADS1115(i2c)
                self._ads_initialized = True
                logger.info("ADS1115 initialized successfully for Analog Sensors (LDR GL5528)")
            except Exception as e:
                self._ads = None
                self._ads_initialized = True # Mark as tried
                logger.warning(f"ADS1115 init failed (Analog Sensors disabled): {e}")
        return self._ads

    # ------------------------------------------------------------------
    # Helper: claim input pin (untuk sensor digital sederhana)
    # ------------------------------------------------------------------

    def _claim_in(self, chip, offset, p_name, pull=0):
        _gpio = get_gpio_lib()
        if not _gpio:
            return

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
        logger.warning(f"Failed to claim input pin {p_name} pull={pull}: {err}")

    def _read_raw(self, p, pull=0):
        _gpio = get_gpio_lib()
        if not _gpio:
            return None

        chip, offset = get_gpio(p)
        if not chip:
            return None

        self._claim_in(chip, offset, p, pull)
        try:
            return _gpio.gpio_read(chip, offset)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Sensor digital sederhana (non-blocking, GPIO read instan)
    # ------------------------------------------------------------------

    def read_gas(self, p=5):
        """MQ Gas sensor: active-low. Default GPIO 5 (tidak konflik dengan PIR GPIO17)."""
        raw = self._read_raw(p, pull=0)
        return (raw == 0) if raw is not None else False

    def read_motion(self, p=27):
        """PIR sensor: active-high dengan pull-down."""
        _gpio = get_gpio_lib()
        pull_down = getattr(_gpio, 'SET_PULL_DOWN', 1) if _gpio else 1
        raw = self._read_raw(p, pull=pull_down)
        return bool(raw) if raw is not None else False

    def read_ir_obstacle(self, p=25):
        """IR obstacle: active-low. Default GPIO 25 (tidak konflik ultrasonic TRIG GPIO23)."""
        _gpio = get_gpio_lib()
        pull_up = getattr(_gpio, 'SET_PULL_UP', 2) if _gpio else 2
        raw = self._read_raw(p, pull=pull_up)
        return (raw == 0) if raw is not None else False

    def read_soil_moisture(self, p=26):
        _gpio = get_gpio_lib()
        pull_up = getattr(_gpio, 'SET_PULL_UP', 2) if _gpio else 2
        raw = self._read_raw(p, pull=pull_up)
        return (raw == 0) if raw is not None else False

    def read_line(self, p=25):
        _gpio = get_gpio_lib()
        pull_up = getattr(_gpio, 'SET_PULL_UP', 2) if _gpio else 2
        raw = self._read_raw(p, pull=pull_up)
        return 'BLACK' if raw == 0 else 'WHITE'

    def read_light(self, p=24, analog=True, adc_channel=0) -> float:
        """
        Membaca sensor cahaya (LDR).
        - Jika analog=True (Default): Membaca LDR GL5528 via I2C ADS1115 (AO). 
          adc_channel (0-3) menentukan pin A0-A3 pada ADS1115. Mengembalikan persentase 0.0 - 100.0%.
        - Jika analog=False: Membaca Pin Digital (DO) active-low. Mengembalikan 100 atau 0.
        """
        if analog:
            ads = self._init_ads()
            if not ads:
                return 0.0
                
            try:
                from adafruit_ads1x15.analog_in import AnalogIn
                import adafruit_ads1x15.ads1115 as ADS
                
                # Petakan integer ke pin konstan milik library
                chan_map = {0: ADS.P0, 1: ADS.P1, 2: ADS.P2, 3: ADS.P3}
                chan = AnalogIn(ads, chan_map.get(adc_channel, ADS.P0))
                
                # Hitung persentase berdasarkan tegangan (Asumsi VCC 3.3V)
                # Raw voltage ADS1115 bergantung pada pencahayaan dan R-Divider (umumnya 10k)
                # Semakin terang, resistansi LDR GL5528 menurun, V_out berubah.
                volts = chan.voltage
                
                # Normalisasi tegangan (0v - 3.3v) ke persentase (0 - 100)
                # Jika dirangkai pull-down (GND - 10k - A0 - LDR - VCC), tegangan naik saat terang.
                intensity = (volts / 3.3) * 100.0
                return max(0.0, min(100.0, round(intensity, 1)))
                
            except Exception as e:
                logger.error(f"Failed to read LDR via ADS1115 channel {adc_channel}: {e}")
                return 0.0
        else:
            _gpio = get_gpio_lib()
            pull_up = getattr(_gpio, 'SET_PULL_UP', 2) if _gpio else 2
            raw = self._read_raw(p, pull=pull_up)
            return 100.0 if raw == 0 else 0.0

    def read_rain(self, p=6):
        """
        Sensor hujan CN15 (rain detector): active-low, pull-up internal.
        DO pin LOW  → hujan terdeteksi  → return True
        DO pin HIGH → permukaan kering  → return False
        Default GPIO 6 (tidak konflik dengan sensor lain).
        """
        _gpio = get_gpio_lib()
        pull_up = getattr(_gpio, 'SET_PULL_UP', 2) if _gpio else 2
        raw = self._read_raw(p, pull=pull_up)
        return (raw == 0) if raw is not None else False

    # ------------------------------------------------------------------
    # DHT22 — non-blocking: hanya baca cache dari background worker
    # ------------------------------------------------------------------

    def read_temperature(self, p=4) -> float:
        """
        Non-blocking. Membaca suhu dari cache DHT22 worker.
        Worker thread akan otomatis di-spawn saat pertama kali dipanggil.
        Return None jika belum ada data valid (worker baru mulai).
        """
        worker = _get_dht_worker(p)
        val = worker.get("temperature")
        return val if val is not None else 0

    def read_humidity(self, p=4) -> float:
        """
        Non-blocking. Membaca kelembaban dari cache DHT22 worker.
        Berbagi worker yang sama dengan read_temperature() — tidak ada
        double read untuk satu pin.
        """
        worker = _get_dht_worker(p)
        val = worker.get("humidity")
        return val if val is not None else 0

    # ------------------------------------------------------------------
    # HC-SR04 Ultrasonic — non-blocking: hanya baca cache dari worker
    # ------------------------------------------------------------------

    def read_ultrasonic(self, trig=23, echo=24) -> float:
        """
        Non-blocking. Membaca jarak dari cache ultrasonic worker.
        Worker thread akan otomatis di-spawn saat pertama kali dipanggil.
        """
        worker = _get_ultrasonic_worker(trig, echo)
        return worker.get()
