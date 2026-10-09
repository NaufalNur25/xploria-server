# Pemetaan & Abstraksi Fungsi Hardware (Xploria Server HAL)

Dokumen ini berisi pemetaan seluruh fungsi hardware yang ada pada server Raspberry Pi (`xploria_hal`), identifikasi fungsi-fungsi yang secara teknis cara kerjanya identik (redundan), serta perancangan **Fungsi Universal** agar integrasi dengan Flutter dan Blockly menjadi ringkas dan modular melalui parameterisasi pin dan mode.

---

## 1. Pemetaan Fungsi Berdasarkan Komponen

| Komponen / Modul | File Sumber | Nama Fungsi | Parameter Utama | Return Value | Deskripsi Logika Hardware |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Pin GPIO Dasar** | `src/hal/pin.py` | `pin.set_digital(p, state)` | `p` (pin), `state` ('HIGH'/'LOW') | `None` | Menulis status logika digital (0 atau 1) ke GPIO. |
| | | `pin.set_analog(p, value)` | `p` (pin), `value` (0-100%) | `None` | Output sinyal PWM (duty cycle 0–100%). |
| | | `pin.read_digital(p)` | `p` (pin) | `int` (0 / 1) | Membaca status input digital pin. |
| | | `pin.read_analog(p)` | `p` (pin) | `0` | Stub (Raspberry Pi tidak memiliki ADC native). |
| **LED Biasa** | `src/hal/led.py` | `led.display_color(target, color, secs=None)` | `target` (1,2,3/'ALL'), `color`, `secs` | `None` | Set HIGH pada GPIO pin LED tertentu; jika ada `secs`, sleep lalu set LOW. |
| | | `led.turn_off(target)` | `target` (1,2,3/'ALL') | `None` | Set LOW pada GPIO pin LED target. |
| **LED RGB** | `src/hal/rgb.py` | `rgb.set_color(target, color, secs=None)` | `target` (13/15), `color`, `secs` | `None` | Menyalakan RGB (Common Anode / Active-LOW pada 3 pin R, G, B). |
| | | `rgb.turn_off(target)` | `target` (13/15) | `None` | Mematikan LED RGB (set 3 pin ke non-aktif). |
| **LED Strip WS2812B** | `src/hal/ledstrip.py` | `ledstrip.init_strip(pin, count, brightness)` | `pin`, `count`, `brightness` | `bool` | Inisialisasi rpi_ws281x driver. |
| | | `ledstrip.set_strip_color(color, r, g, b, pin, count)` | `color`/`r,g,b`, `pin`, `count` | `None` | Mengatur seluruh LED pada strip ke warna yang sama. |
| | | `ledstrip.set_pixel(index, color, r, g, b, pin, count)` | `index`, `color`/`r,g,b`, `pin`, `count` | `None` | Mengatur warna satu piksel spesifik (index 0..N). |
| | | `ledstrip.set_strip_brightness(brightness)` | `brightness` (0–255) | `None` | Mengatur intensitas kecerahan strip. |
| | | `ledstrip.clear_strip()` | *(none)* | `None` | Mematikan seluruh LED strip (set semua piksel ke 0,0,0). |
| | | `ledstrip.rainbow_strip(wait_ms, iterations)` | `wait_ms`, `iterations` | `None` | Efek animasi pelangi berjalan. |
| | | `ledstrip.display_color(target, color, secs)` | `target`, `color`, `secs` | `None` | *Duplikat dari LEDHAL (kontrol LED digital biasa).* |
| | | `ledstrip.turn_off(target)` | `target` | `None` | *Duplikat dari LEDHAL (kontrol LED digital biasa).* |
| **Motor & Kipas** | `src/hal/motor.py` | `motor.set_servo(p=18, degree=90)` | `p` (pin), `degree` (0–180) | `None` | Kontrol servo 180° standar via sinyal pulsa PWM 50Hz (500–2500 µs). |
| | | `motor.set_servo360(p=18, speed=0, duration=None)` | `p` (pin), `speed` (-100..100), `duration` | `None` | Kontrol servo continuous 360° (kecepatan & arah, 0 = diam bebas getar). |
| | | `motor.stop_servo(p=18)` | `p` (pin) | `None` | Mematikan pulsa sinyal PWM servo seketika. |
| | | `motor.run_dc(motor="M1", speed=0)` | `motor` ("M1"/"M2"), `speed` (-100..100) | `None` | Driver L298N (IN1, IN2 via digital, ENA via PWM). |
| | | `motor.set_fan(speed=100)` | `speed` (0–100) | `None` | Mengatur kecepatan kipas (alias dari `run_dc("M1", speed)`). |
| | | `motor.stop_dc(motor="ALL")` | `motor` ("M1"/"M2"/"ALL") | `None` | Menghentikan motor DC (alias dari `run_dc(m, 0)`). |
| **Sensor Digital** | `src/hal/sensor.py` | `sensor.read_gas(p=5)` | `p` (pin DO) | `bool` | Baca pin digital DO, pull-up, active-low (`raw == 0`). |
| | | `sensor.read_motion(p=27)` | `p` (pin DO) | `bool` | Baca PIR sensor, pull-down, active-high (`raw == 1`). |
| | | `sensor.read_ir_obstacle(p=25)` | `p` (pin DO) | `bool` | Baca sensor rintangan IR, pull-up, active-low (`raw == 0`). |
| | | `sensor.read_soil_moisture(p=26)` | `p` (pin DO) | `bool` | Baca kelembaban tanah DO, pull-up, active-low (`raw == 0`). |
| | | `sensor.read_rain(p=6)` | `p` (pin DO) | `bool` | Baca sensor air hujan DO, pull-up, active-low (`raw == 0`). |
| | | `sensor.read_line(p=25)` | `p` (pin DO) | `str` | Baca line follower DO: `'BLACK'` jika 0, `'WHITE'` jika 1. |
| **Sensor Analog (ADS1115)** | `src/hal/sensor.py` | `sensor.read_water_level(adc_channel=2)` | `adc_channel` (0–3) | `float` (%) | Baca tegangan via I2C ADS1115, konversi 0V–1.7V ke 0.0–100.0%. |
| | | `sensor.read_light(p=24, analog=True, adc_channel=0)` | `p`, `analog`, `adc_channel` | `float` (%) | LDR: jika analog baca via ADS1115 (0–3.3V ke 0–100%); jika digital baca DO. |
| | | `sensor.read_gas_status(p=5, analog=True, adc_channel=0)` | `p`, `analog`, `adc_channel` | `float` (%) | Alias memanggil `read_air_quality_status`. |
| | | `sensor.read_air_quality_status(p=5, analog=True, adc_channel=0)` | `p`, `analog`, `adc_channel` | `float` (%) / `bool` | MQ-9: baca analog ADS1115 dengan voltage divider 1.5x (0–100%) atau digital DO. |
| **Sensor Khusus** | `src/hal/sensor.py` | `sensor.read_temperature(p=4)` | `p` (pin DHT) | `float` (°C) | Non-blocking DHT22 cache via background thread worker. |
| | | `sensor.read_humidity(p=4)` | `p` (pin DHT) | `float` (%) | Non-blocking DHT22 cache via background thread worker. |
| | | `sensor.read_ultrasonic(trig=23, echo=24)` | `trig`, `echo` | `float` (cm) | Non-blocking HC-SR04 ultrasonic distance via thread worker. |
| **RFID / NFC** | `src/hal/rfid.py` | `rfid.read_uid(timeout=0.1)` | `timeout` | `str` / `None` | Baca UID kartu NFC/RFID PN532 via I2C. |
| | | `rfid.register_card(uid, access_type)` | `uid`, `access_type` ('ALLOW'/'DENY') | `None` | Simpan kartu ke memori lokal daemon. |
| | | `rfid.unregister_card(uid)` | `uid` | `None` | Hapus kartu dari memori. |
| | | `rfid.check_status(uid=None)` | `uid` (opsional) | `str` | Cek status izin kartu ('DIIZINKAN'/'DITOLAK'/'TIDAK_TERDAFTAR'). |
| | | `rfid.is_allowed(uid=None)` | `uid` (opsional) | `bool` | Cek apakah status kartu bernilai 'DIIZINKAN'. |
| **Telemetri & WebSocket** | `src/hal/telemetry.py` | `telemetry.send(**kwargs)` | Key-value pairs bebas | `None` | Masukkan data ke antrean WebSocket push realtime ke Flutter. |
| **Hospital** | `src/hal/hospital.py` | `hospital.open_jitsi(roomName, displayName, role, subject)` | Data sesi video | `None` | Telemetry action trigger membuka tampilan Jitsi Meet di Flutter. |
| | | `hospital.close_jitsi()` | *(none)* | `None` | Telemetry action trigger menutup tampilan Jitsi Meet di Flutter. |

---

## 2. Analisis Fungsi Redundan (Eksekusi Sama, Nama Berbeda)

Di level firmware hardware (GPIO / I2C), fungsi-fungsi di bawah ini sebenarnya **menjalankan eksekusi yang identik**:

### A. Kategori Sensor Digital Biner (Active-LOW Pull-Up)
* **Daftar Fungsi:**
  - `sensor.read_gas(p)`
  - `sensor.read_rain(p)`
  - `sensor.read_soil_moisture(p)`
  - `sensor.read_ir_obstacle(p)`
  - `sensor.read_air_quality_status(p, analog=False)`
* **Kesamaan Cara Kerja:**
  Semuanya mengaktifkan internal resistor pull-up (`SET_PULL_UP`), membaca level pin (`raw`), dan mengembalikan logika terbalik:
  ```python
  raw = _gpio.gpio_read(chip, offset)
  return (raw == 0)  # Active-LOW: bernilai True jika pin tertarik ke GND
  ```
* **Varian Terkait:**
  - `sensor.read_motion(p)`: Hanya berbeda polaritas (`SET_PULL_DOWN`, Active-HIGH di mana `raw == 1` menghasilkan `True`).
  - `sensor.read_line(p)`: Hanya berbeda output format string (`'BLACK'` jika 0, `'WHITE'` jika 1).
  - `sensor.read_light(p, analog=False)`: Hanya mengembalikan `100.0` jika 0, `0.0` jika 1.

### B. Kategori Sensor Analog Persentase (ADS1115 ADC I2C)
* **Daftar Fungsi:**
  - `sensor.read_gas_status(analog=True)`
  - `sensor.read_air_quality_status(analog=True)`
  - `sensor.read_water_level()`
  - `sensor.read_light(analog=True)`
* **Kesamaan Cara Kerja:**
  Semuanya mengakses ADC ADS1115 via I2C, mengambil pembacaan voltase dari salah satu channel (A0–A3), lalu mengalikan/membagi ke skala persentase `0.0 – 100.0%`:
  $$\text{Persen} = \frac{V_{\text{read}} - V_{\min}}{V_{\max} - V_{\min}} \times 100$$
  *(Bahkan `read_gas_status` di kode sumber hanyalah fungsi pembungkus langsung ke `read_air_quality_status`)*.

### C. Kategori Kontrol Aktuator Output Digital On/Off
* **Daftar Fungsi:**
  - `pin.set_digital(p, state)`
  - `led.display_color(target, color)`
  - `led.turn_off(target)`
  - `ledstrip.display_color(target, color)`
  - `ledstrip.turn_off(target)`
* **Kesamaan Cara Kerja:**
  Pada akhirnya semua fungsi ini hanya memanggil `gpio_write(chip, offset, 1)` untuk ON dan `0` untuk OFF.
  `led.turn_off()` sama saja dengan `led.display_color(target, "black")` atau `set_digital(pin, "LOW")`.

### D. Kategori Kontrol Motor DC
* **Daftar Fungsi:**
  - `motor.run_dc(motor, speed)`
  - `motor.set_fan(speed)`
  - `motor.stop_dc(motor)`
* **Kesamaan Cara Kerja:**
  - `set_fan(speed)` hanyalah pemanggilan `run_dc("M1", speed)`.
  - `stop_dc(motor)` hanyalah pemanggilan `run_dc(motor, 0)`.

### E. Kategori Servo PWM
* **Daftar Fungsi:**
  - `motor.set_servo(p, degree)`
  - `motor.set_servo360(p, speed, duration)`
  - `motor.stop_servo(p)`
* **Kesamaan Cara Kerja:**
  Semuanya menghasilkan pulsa 50Hz PWM ke pin yang sama. `stop_servo(p)` identik dengan mematikan pulsa PWM atau `set_servo360(p, speed=0)`.

---

## 3. Desain Fungsi Universal untuk Flutter & Blockly

Untuk menyederhanakan kode Flutter dan Blockly, kita cukup membuat **7 Fungsi Universal**. Pembeda antar-alat hanya berupa **parameter definisi perangkat**:

```
                       ┌────────────────────────────────────────────────────────┐
                       │          UNIVERSAL HARDWARE ABSTRACTION LAYER          │
                       └───────────────────────────┬────────────────────────────┘
                                                   │
    ┌─────────────────────────┬────────────────────┴────────────────┬────────────────────────┐
    ▼                         ▼                                     ▼                        ▼
┌───────────────────┐  ┌───────────────────┐              ┌───────────────────┐    ┌───────────────────┐
│   read_digital    │  │    read_analog    │              │    set_digital    │    │     set_motor     │
│  (Sensor Biner)   │  │  (Sensor ADC/Volt)│              │ (Relay/LED/Buzzer)│    │   (DC & Kipas)    │
└───────────────────┘  └───────────────────┘              └───────────────────┘    └───────────────────┘
```

### 1. Sensor Digital Universal
```python
def read_digital_sensor(pin: int, active_low: bool = True, pull_up: bool = True) -> bool:
    """Universal untuk: Gas, Hujan, Soil Moisture, IR Obstacle, PIR Motion, Saklar Magnet, Touch Button."""
    pull = 2 if pull_up else 1
    raw = hal_pin_read_raw(pin, pull=pull)
    return (raw == 0) if active_low else (raw == 1)
```
* **Pemakaian di Flutter:**
  - Sensor Gas/Hujan/IR/Soil: `read_digital_sensor(pin: 5, active_low: true, pull_up: true)`
  - PIR Gerak: `read_digital_sensor(pin: 27, active_low: false, pull_up: false)`

### 2. Sensor Analog Universal (ADC)
```python
def read_analog_sensor(adc_channel: int, v_min: float = 0.0, v_max: float = 3.3, divider_ratio: float = 1.0) -> float:
    """Universal untuk: Water Level, LDR Cahaya, MQ Gas Analog, Potensiometer, Sensor Kelembaban Analog."""
    volts = hal_read_ads1115(adc_channel) * divider_ratio
    percentage = ((volts - v_min) / (v_max - v_min)) * 100.0
    return max(0.0, min(100.0, round(percentage, 1)))
```
* **Pemakaian di Flutter:**
  - Water Level: `read_analog_sensor(adc_channel: 2, v_min: 0.0, v_max: 1.7)`
  - LDR Cahaya: `read_analog_sensor(adc_channel: 0, v_min: 0.0, v_max: 3.3)`
  - MQ-9 Gas: `read_analog_sensor(adc_channel: 0, v_min: 0.0, v_max: 5.0, divider_ratio: 1.5)`

### 3. Aktuator Output Digital Universal
```python
def set_digital_output(pin: int, state: bool, duration: float = None):
    """Universal untuk: Semua LED tunggal, Relay, Solenoid Lock, Active Buzzer."""
    hal_pin_write(pin, 1 if state else 0)
    if duration and duration > 0:
        time.sleep(duration)
        hal_pin_write(pin, 0)
```
* **Pemakaian di Flutter:**
  - Nyalakan Lampu/LED: `set_digital_output(pin: 17, state: true)`
  - Buzzer Beep 0.5 detik: `set_digital_output(pin: 22, state: true, duration: 0.5)`
  - Buka Kunci Solenoid: `set_digital_output(pin: 26, state: true, duration: 3.0)`

### 4. Kontrol Motor DC / PWM Universal
```python
def set_motor(motor_id_or_pins, speed: int):
    """Universal untuk: Kipas angin, Motor Roda M1, Motor M2, Pompa Air DC.
    speed: -100 (mundur penuh) s/d +100 (maju penuh), 0 = berhenti."""
    ...
```
* **Pemakaian di Flutter:**
  - Kipas kecepatan 80%: `set_motor("M1", speed: 80)`
  - Matikan Motor/Kipas: `set_motor("M1", speed: 0)`

### 5. Kontrol Servo Universal
```python
def set_servo(pin: int, value: int, is_continuous: bool = False, duration: float = None):
    """Universal untuk: Servo Sudut 180° dan Servo Continuous 360°.
    value: Sudut (0-180) jika standard, Kecepatan (-100 s/d 100) jika continuous."""
    ...
```

### 6. Kontrol RGB LED Universal
```python
def set_rgb(pins: dict, color: str, common_anode: bool = True, duration: float = None):
    """pins: {'r': 13, 'g': 19, 'b': 26}"""
    ...
```

### 7. Sensor & Aktuator dengan Protokol Komunikasi Tertentu (Tetap Mandiri)
Komponen ini menggunakan protokol serial bit-banging/timing mikrosekon khusus dan tidak dapat dilebur ke digital standar:
1. **DHT22 (Single-Wire Timing):** `read_dht(pin, metric='temperature'|'humidity')`
2. **HC-SR04 (Ultrasonic Trigger-Echo Timing):** `read_ultrasonic(trig_pin, echo_pin)`
3. **PN532 (NFC/RFID I2C):** `rfid_read()`, `rfid_check_status()`
4. **WS2812B (NeoPixel PWM/DMA Data Stream):** `set_strip_color()`, `set_pixel()`

---

## 4. Rekomendasi Format Hardware Profile di Flutter

Di aplikasi Flutter, cukup simpan konfigurasi hardware per proyek dalam format JSON:

```json
{
  "project_name": "Smart Home",
  "components": {
    "sensor_gas": {
      "type": "digital_input",
      "pin": 5,
      "active_low": true,
      "pull_up": true
    },
    "sensor_gerak": {
      "type": "digital_input",
      "pin": 27,
      "active_low": false,
      "pull_up": false
    },
    "sensor_air": {
      "type": "analog_input",
      "adc_channel": 2,
      "v_max": 1.7
    },
    "kipas_ruang": {
      "type": "dc_motor",
      "motor_id": "M1"
    },
    "lampu_kamar": {
      "type": "digital_output",
      "pin": 17
    }
  }
}
```

Dengan skema ini:
- **Blockly generator** hanya perlu membaca profil di atas untuk menghasilkan satu baris kode universal.
- Setiap kali ada sensor digital baru (misal *flame sensor*), **tidak perlu ada fungsi baru di Python server maupun Flutter**, cukup definisikan pin dan polaritasnya.
