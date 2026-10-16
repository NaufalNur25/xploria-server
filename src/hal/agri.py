"""
HAL Smart Agriculture (STEAM Kit).

Dipanggil oleh blok Blockly `sa_*` lewat `from xploria_hal import agri`.

Pola telemetri sama dengan Smart Home: HAL tidak mengirim telemetri sendiri.
IoT Lab menjalankan skrip telemetri (`telemetry.send(pin=<ekspresi>)` tiap
detik) dari `python_script`/`telemetry_script` metadata blok. Aksi hanya
menyimpan state; widget membacanya lewat getter `*_state()` / `*_log()` yang
tidak mengubah perangkat.

Perangkat proyek berlabel kuning (pompa dosing B2, katup tetes B4, model AI
C1/C2, dashboard D1) masih menunggu validasi; fungsinya berjalan aman
tanpa perangkat (mengembalikan nilai netral) sehingga program siswa tetap
bisa diuji dalam mode simulasi.
"""
import glob
import logging
import threading
import time
from collections import defaultdict, deque

from .core import get_gpio, get_gpio_lib

logger = logging.getLogger(__name__)

# Pin default kit (dapat disesuaikan setelah pemetaan pin per perangkat dibuat)
FLOW_PIN = 16
VALVE_PIN = 20
MIST_PIN = 21
PUMP_MOTOR = "M1"
DOSING_PINS = {"A": 5, "B": 6, "PH_UP": 19, "PH_DOWN": 26}
DOSING_ML_PER_SEC = 1.5          # kalibrasi debit pompa dosing
FLOW_PULSES_PER_LITER = 450.0     # YF-S201 ~450 pulsa/L
ROOF_SERVO_PIN = 12
AI_MIN_CONFIDENCE = 60.0
HISTORY_SIZE = 500
LOG_SIZE = 30


class _FlowMeter:
    """Menghitung pulsa flow meter lewat interrupt lgpio (non-blocking)."""

    def __init__(self, pin: int):
        self.pulses = 0
        self._lock = threading.Lock()
        self._callback = None
        gpio = get_gpio_lib()
        chip, offset = get_gpio(pin)
        if not gpio or not chip:
            return
        try:
            edge = getattr(gpio, "RISING_EDGE", 0)
            gpio.gpio_claim_alert(chip, offset, edge, getattr(gpio, "SET_PULL_UP", 0))
            self._callback = gpio.callback(chip, offset, edge, self._on_pulse)
        except Exception as exc:  # perangkat tidak tersedia -> mode simulasi
            logger.info("Flow meter tidak aktif: %s", exc)

    def _on_pulse(self, chip, gpio, level, tick):
        with self._lock:
            self.pulses += 1

    def reset(self):
        with self._lock:
            self.pulses = 0

    def volume_ml(self) -> float:
        with self._lock:
            return round(self.pulses / FLOW_PULSES_PER_LITER * 1000.0, 1)

    def stop(self):
        if self._callback is not None:
            try:
                self._callback.cancel()
            except Exception:
                pass


class AgriHAL:
    def __init__(self, sensor=None, motor=None, pin=None):
        self.sensor = sensor
        self.pin = pin
        self.motor = motor
        self._flow = None
        self._hysteresis_state = {}
        self._history = defaultdict(lambda: deque(maxlen=HISTORY_SIZE))
        self._ai_last = {}
        self._ai_latest_model = None
        self._outputs = {}
        self._state = {}
        self._logs = defaultdict(lambda: deque(maxlen=LOG_SIZE))

    # ------------------------------------------------------------------ util
    def _record(self, channel, value):
        """Simpan nilai terakhir + riwayat; dibaca oleh skrip telemetri IoT Lab."""
        self._history[channel].append(value)
        self._state[channel] = value
        return value

    def _log(self, channel, entry):
        entry = {**entry, "time": time.time()}
        self._logs[channel].append(entry)
        return entry

    def _set_output(self, gpio_pin, on: bool):
        self._outputs[gpio_pin] = on
        if self.pin is not None:
            try:
                self.pin.set_digital(gpio_pin, "HIGH" if on else "LOW")
            except Exception as exc:
                logger.debug("GPIO %s tidak tersedia: %s", gpio_pin, exc)

    def _flow_meter(self):
        if self._flow is None:
            self._flow = _FlowMeter(FLOW_PIN)
        return self._flow

    # --------------------------------------------------------------- sensor
    def _read_ds18b20(self, index: int):
        devices = sorted(glob.glob("/sys/bus/w1/devices/28-*/w1_slave"))
        if len(devices) <= index:
            return 0.0
        try:
            with open(devices[index]) as fh:
                lines = fh.read().splitlines()
            if lines and lines[0].endswith("YES"):
                return round(int(lines[1].split("t=")[1]) / 1000.0, 1)
        except Exception as exc:
            logger.debug("DS18B20 gagal: %s", exc)
        return 0.0

    def read_soil_temp(self):
        return self._record("soil_temperature", self._read_ds18b20(0))

    def read_water_temp(self):
        return self._record("water_temperature", self._read_ds18b20(1))

    def read_ph(self):
        """pH via ADS1115 AIN1 (modul PH-4502C): pH = 7 + (2.5 - V) / 0.18."""
        value = 7.0
        if self.sensor is not None:
            try:
                self.sensor._init_ads()
                volts = self.sensor._read_ads_channel(1, "pH")
                if volts is not None:
                    value = max(0.0, min(14.0, round(7.0 + (2.5 - volts) / 0.18, 2)))
            except Exception as exc:
                logger.debug("pH gagal: %s", exc)
        return self._record("ph", value)

    def read_tank_level(self, tank="WATER"):
        value = 0.0
        if self.sensor is not None and tank in ("WATER", "MIX"):
            try:
                value = self.sensor.read_water_level()
            except Exception:
                value = 0.0
        self._record(f"tank_level_{tank.lower()}", value)
        return self._record("tank_level", value)

    def read_storage_temp(self):
        value = self.sensor.read_temperature() if self.sensor is not None else 0.0
        return self._record("storage_temperature", value)

    def read_storage_humidity(self):
        value = self.sensor.read_humidity() if self.sensor is not None else 0.0
        return self._record("storage_humidity", value)

    # ----------------------------------------------------------- flow meter
    def flow_reset(self):
        self._flow_meter().reset()
        self._record("flow_volume_ml", 0.0)

    def flow_volume(self):
        return self._record("flow_volume_ml", self._flow_meter().volume_ml())

    # ------------------------------------------------------------ aktuator
    def _pump(self, on: bool):
        if self.motor is not None:
            self.motor.run_dc(PUMP_MOTOR, 100 if on else 0)
        self._record("pump_power", 1 if on else 0)

    def water_until_volume(self, target_ml, timeout_s=30):
        """Siram terukur: berhenti saat target volume tercapai atau waktu habis."""
        target_ml = float(target_ml)
        meter = self._flow_meter()
        meter.reset()
        self._record("pump_target_ml", target_ml)
        self._pump(True)
        deadline = time.time() + float(timeout_s)
        reason = "timeout"
        try:
            while time.time() < deadline:
                delivered = meter.volume_ml()
                if delivered >= target_ml:
                    reason = "target"
                    break
                self._record("flow_volume_ml", delivered)
                self._send_irrigation(target_ml, delivered, True, None)
                time.sleep(0.2)
        finally:
            self._pump(False)
        delivered = self.flow_volume()
        self._send_irrigation(target_ml, delivered, False, reason)
        return delivered

    def _send_irrigation(self, target_ml, delivered_ml, pump_on, stop_reason):
        """State widget Progres Siram (IoT Lab)."""
        self._record("irrigation", {
            "target_ml": target_ml,
            "delivered_ml": delivered_ml,
            "pump": pump_on,
            "stop_reason": stop_reason,
        })

    def valve(self, state="OFF"):
        on = str(state).upper() == "ON"
        self._set_output(VALVE_PIN, on)
        return self._record("drip_valve", 1 if on else 0)

    def mist(self, state="OFF"):
        on = str(state).upper() == "ON"
        self._set_output(MIST_PIN, on)
        return self._record("mist_power", 1 if on else 0)

    def roof(self, state="CLOSE"):
        opened = str(state).upper() == "OPEN"
        if self.motor is not None:
            try:
                self.motor.set_servo(ROOF_SERVO_PIN, 90 if opened else 0)
            except Exception as exc:
                logger.debug("servo atap gagal: %s", exc)
        return self._record("roof", 1 if opened else 0)

    def dose(self, pump="A", ml=5):
        pin = DOSING_PINS.get(str(pump).upper())
        ml = max(0.0, float(ml))
        if pin is None:
            raise ValueError(f"Pompa dosing tidak dikenal: {pump}")
        self._set_output(pin, True)
        time.sleep(ml / DOSING_ML_PER_SEC)
        self._set_output(pin, False)
        self._record(f"dose_ml_{str(pump).lower()}", ml)
        self._log("dose_ml", {"pump": str(pump).upper(), "ml": ml})
        return ml

    def ph_dose_cycle(self, target, ml=2, wait_s=10):
        """Satu siklus kendali umpan balik: ukur → dosis kecil → tunggu → ukur ulang."""
        target = float(target)
        current = self.read_ph()
        if abs(current - target) < 0.2:
            return current
        self.dose("PH_UP" if current < target else "PH_DOWN", ml)
        time.sleep(float(wait_s))
        return self.read_ph()

    # ---------------------------------------------------------- histeresis
    def hysteresis(self, name, value, on_at, off_at):
        value, on_at, off_at = float(value), float(on_at), float(off_at)
        active = self._hysteresis_state.get(name, False)
        if on_at >= off_at:      # mis. kipas: nyala saat panas
            if value >= on_at:
                active = True
            elif value <= off_at:
                active = False
        else:                    # mis. misting: nyala saat kelembapan rendah
            if value <= on_at:
                active = True
            elif value >= off_at:
                active = False
        self._hysteresis_state[name] = active
        return active

    # ------------------------------------------------------ jurnal/analitik
    def log_observation(self, height_cm=0, leaves=0, note=""):
        self._history["plant_height"].append(float(height_cm))
        return self._log("plant_observation", {
            "height_cm": float(height_cm),
            "leaves": int(leaves),
            "note": str(note),
        })

    def history_stat(self, stat="avg", source="flow_volume"):
        return self.history_summary(stat, source)["value"]

    def history_summary(self, stat="avg", source="flow_volume"):
        """Ringkasan lengkap untuk widget Statistik (read-only)."""
        key = {"flow_volume": "flow_volume_ml", "soil_moisture": "soil_moisture",
               "temperature": "temperature", "ph": "ph",
               "plant_height": "plant_height"}.get(source, source)
        data = [float(v) for v in self._history.get(key, []) if isinstance(v, (int, float))]
        if stat == "count":
            result = float(len(data))
        elif not data:
            result = 0.0
        elif stat == "sum":
            result = sum(data)
        elif stat == "min":
            result = min(data)
        elif stat == "max":
            result = max(data)
        else:
            result = sum(data) / len(data)
        result = round(result, 2)
        summary = {"stat": stat, "source": source, "value": result, "count": len(data)}
        if data:
            summary.update(avg=round(sum(data) / len(data), 2), min=min(data),
                           max=max(data), sum=round(sum(data), 2))
        return summary

    # ------------------------------------------------------------------ AI
    def camera_capture(self):
        self._ai_last = {}
        return self._record("camera_capture", time.time())

    def _send_ai_result(self, model):
        self._ai_latest_model = model

    def _ai_result(self, model):
        # Model ringan belum tersedia di kit → hasil netral "tidak yakin".
        return self._ai_last.setdefault(model, {"label": "tidak yakin", "confidence": 0.0, "count": 0})

    def ai_classify(self, model="disease"):
        result = self._ai_result(model)
        label = result["label"] if result["confidence"] >= AI_MIN_CONFIDENCE else "tidak yakin"
        self._send_ai_result(model)
        return self._record("ai_label", label)

    def ai_confidence(self, model="disease"):
        self._send_ai_result(model)
        return self._record("ai_confidence", self._ai_result(model)["confidence"])

    def ai_count(self, target="fruit"):
        self._send_ai_result(target)
        return self._record("fruit_count", self._ai_result(target)["count"])

    def ai_predict(self, target="days_to_harvest"):
        # Model lite: tren linier sederhana dari riwayat tinggi tanaman.
        heights = list(self._history.get("plant_height", []))
        if len(heights) < 2:
            value = 0.0
        else:
            growth = (heights[-1] - heights[0]) / (len(heights) - 1)
            value = round(max(0.0, (30.0 - heights[-1]) / growth), 1) if growth > 0 else 0.0
            if target == "yield_kg":
                value = round(heights[-1] * 0.05, 2)
        return self._record("ai_prediction", value)

    # ----------------------------------------------------------- dashboard
    def recommend(self, priority="MEDIUM", text="", reason=""):
        return self._log("recommendation", {"priority": priority, "text": str(text),
                                            "reason": str(reason)})

    def area_status(self, area, status):
        return self._log("area_status", {"area": str(area), "status": str(status)})

    # ------------------------------------------- getter telemetri (read-only)
    def state(self, channel, default=None):
        """Nilai terakhir sebuah channel aksi (pompa, katup, atap, dll)."""
        return self._state.get(channel, default)

    def log(self, channel):
        """Riwayat terstruktur (jurnal, dosis, rekomendasi, status area)."""
        return list(self._logs[channel])

    def irrigation_state(self):
        return self._state.get("irrigation") or {
            "target_ml": 0.0, "delivered_ml": 0.0, "pump": False, "stop_reason": None}

    def hysteresis_state(self, name):
        return bool(self._hysteresis_state.get(name, False))

    def ai_state(self, model=None):
        model = model or self._ai_latest_model or "disease"
        return {"model": model, **self._ai_result(model)}

    def stop_all(self):
        if self._flow is not None:
            self._flow.stop()
        for pin in list(self._outputs):
            self._set_output(pin, False)
