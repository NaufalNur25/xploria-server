# Export Library — Xploria HAL Blockly Mapping

Dokumen ini memetakan seluruh modul dan fungsi yang tersedia di `xploria_hal` untuk digunakan dalam kode generator Blockly. Setiap fungsi dapat dipanggil melalui `window._hal_require("nama_modul")` agar Blockly otomatis menambahkan import yang tepat.

---

## Cara Penggunaan di Blockly Generator

```js
Blockly.Python["nama_block"] = function (block) {
  window._hal_require("nama_modul"); // daftarkan modul yang dibutuhkan
  // ... generate kode Python
};
```

Import yang dihasilkan:
```python
from xploria_hal import nama_modul
import time
import math
```

---

## Daftar Modul `xploria_hal`

| Modul | Kelas | Deskripsi |
|---|---|---|
| `pin` | `PinHAL` | Kontrol GPIO digital & analog (PWM) |
| `sensor` | `SensorHAL` | Baca semua jenis sensor |
| `motor` | `MotorHAL` | Kontrol servo, DC motor, kipas |
| `led` | `LEDHAL` | Kontrol LED tunggal |
| `ledstrip` | `LedStripHAL` | Kontrol LED strip WS2812B (NeoPixel) |
| `rgb` | `RGBHAL` | Kontrol LED RGB (common-anode) |
| `rfid` | `RFIDHAL` | Baca kartu RFID/NFC via PN532 |
| `telemetry` | `TelemetryHAL` | Kirim data ke Flutter secara realtime |
| `power` | `PowerHAL` | Baca data daya rumah & solar *(stub)* |
| `audio` | `AudioHAL` | *(Mock — belum diimplementasi)* |
| `display` | `DisplayHAL` | *(Mock — belum diimplementasi)* |
| `motion` | `MotionHAL` | *(Mock — belum diimplementasi)* |
| `lan` | `LANHAL` | *(Mock — belum diimplementasi)* |
| `ai` | `AIHAL` | *(Mock — belum diimplementasi)* |

---

## Modul: `pin`

```js
window._hal_require("pin");
```

Kelas: `PinHAL` — sumber: `src/hal/pin.py`

| Fungsi Python | Parameter | Return | Keterangan |
|---|---|---|---|
| `pin.set_digital(p, state)` | `p`: nomor pin GPIO BCM, `state`: `'HIGH'` / `'LOW'` | `None` | Set pin digital HIGH atau LOW |
| `pin.set_analog(p, value)` | `p`: nomor pin GPIO BCM, `value`: 0–100 (%) | `None` | Output PWM di pin. Nilai 0–100 (persen duty cycle) |
| `pin.read_digital(p)` | `p`: nomor pin GPIO BCM | `int` (0 atau 1) | Baca nilai digital dari pin input |
| `pin.read_analog(p)` | `p`: nomor pin GPIO BCM | `int` (selalu 0) | *(Raspberry Pi tidak punya ADC native — gunakan `sensor` untuk baca analog)* |

**Contoh Blockly:**
```js
Blockly.Python["sa_pin_set_digital"] = function (block) {
  window._hal_require("pin");
  let p = block.getFieldValue("PIN");
  let state = block.getFieldValue("STATE");
  return `pin.set_digital(${p}, "${state}")\n`;
};

Blockly.Python["sa_pin_read_digital"] = function (block) {
  window._hal_require("pin");
  let p = block.getFieldValue("PIN");
  return [`pin.read_digital(${p})`, Blockly.Python.ORDER_ATOMIC];
};
```

---

## Modul: `sensor`

```js
window._hal_require("sensor");
```

Kelas: `SensorHAL` — sumber: `src/hal/sensor.py`

| Fungsi Python | Parameter | Return | Keterangan |
|---|---|---|---|
| `sensor.read_temperature(p=4)` | `p`: pin GPIO (default 4) | `float` (°C) | Suhu dari DHT22. Non-blocking (background thread). |
| `sensor.read_humidity(p=4)` | `p`: pin GPIO (default 4) | `float` (%) | Kelembaban dari DHT22. Non-blocking (background thread). |
| `sensor.read_ultrasonic(trig=23, echo=24)` | `trig`: pin trigger, `echo`: pin echo | `float` (cm) | Jarak dari HC-SR04. Non-blocking, max 400 cm. |
| `sensor.read_motion(p=27)` | `p`: pin GPIO | `bool` | PIR HC-SR501. `True` = gerakan terdeteksi. |
| `sensor.read_ir_obstacle(p=25)` | `p`: pin GPIO | `bool` | IR obstacle. `True` = ada rintangan (active-low). |
| `sensor.read_soil_moisture(p=26)` | `p`: pin GPIO | `bool` | Kelembaban tanah. `True` = lembab/basah (active-low). |
| `sensor.read_rain(p=6)` | `p`: pin GPIO (default 6) | `bool` | Sensor hujan. `True` = sedang hujan (active-low). |
| `sensor.read_line(p=25)` | `p`: pin GPIO | `str` | Line tracking. Return `'BLACK'` atau `'WHITE'`. |
| `sensor.read_light(p=24, analog=True, adc_channel=0)` | `p`: pin DO, `analog`: mode baca, `adc_channel`: 0–3 | `float` (%) | Intensitas cahaya LDR GL5528. `analog=True` → via ADS1115 (0–100%), `analog=False` → pin digital (100 atau 0). |
| `sensor.read_gas(p=5)` | `p`: pin DO GPIO | `bool` | Sensor gas digital (DO). `True` = gas terdeteksi (active-low). |
| `sensor.read_gas_status(p=5, analog=True, adc_channel=0)` | `p`: pin DO, `analog`: mode baca, `adc_channel`: 0–3 | `float` (%) | MQ-9 kadar gas dalam persen. `analog=True` → via ADS1115 A0, `analog=False` → pin digital. |
| `sensor.read_air_quality_status(p=5, analog=True, adc_channel=0)` | `p`: pin DO, `analog`: mode baca, `adc_channel`: 0–3 | `float` / `bool` | Alias `read_gas_status`. Mode analog → % 0–100, mode digital → bool. |
| `sensor.read_water_level(adc_channel=2)` | `adc_channel`: channel ADS1115 (default 2) | `float` (%) | Ketinggian air Funduino via ADS1115 A2. Kalibrasi: 0V=0%, 1.70V=100%. |

> **Catatan ADS1115:** Sensor analog (cahaya, gas, air) menggunakan ADC eksternal ADS1115 via I2C.
> Channel default: A0=MQ-9 gas, A1=*(unused)*, A2=water level, A3=*(spare)*.

**Contoh Blockly:**
```js
Blockly.Python["sa_sensor_rain"] = function (block) {
  window._hal_require("sensor");
  let pin = block.getFieldValue("PIN");
  return [`sensor.read_rain(${pin})`, Blockly.Python.ORDER_ATOMIC];
};

Blockly.Python["sa_sensor_temperature"] = function (block) {
  window._hal_require("sensor");
  let pin = block.getFieldValue("PIN");
  return [`sensor.read_temperature(${pin})`, Blockly.Python.ORDER_ATOMIC];
};

Blockly.Python["sa_sensor_ultrasonic"] = function (block) {
  window._hal_require("sensor");
  let trig = block.getFieldValue("TRIG");
  let echo = block.getFieldValue("ECHO");
  return [`sensor.read_ultrasonic(${trig}, ${echo})`, Blockly.Python.ORDER_ATOMIC];
};
```

---

## Modul: `motor`

```js
window._hal_require("motor");
```

Kelas: `MotorHAL` — sumber: `src/hal/motor.py`

| Fungsi Python | Parameter | Return | Keterangan |
|---|---|---|---|
| `motor.set_servo(p=18, degree=90)` | `p`: pin GPIO (default 18), `degree`: 0–180 | `None` | Servo 180° standar. Mapping: 500–2500 µs, 50 Hz. |
| `motor.set_servo360(p=18, speed=0, duration=None)` | `p`: pin GPIO, `speed`: -100 s/d +100, `duration`: detik (opsional) | `None` | Servo 360° continuous. `speed=0` → berhenti. `duration` → auto-stop setelah N detik. |
| `motor.stop_servo(p=18)` | `p`: pin GPIO | `None` | Matikan pulsa PWM servo (diam total, bebas getar). |
| `motor.run_dc(motor="M1", speed=0)` | `motor`: `"M1"` atau `"M2"`, `speed`: -100 s/d +100 | `None` | Motor DC via driver L298N. Positif=maju, negatif=mundur, 0=berhenti. |
| `motor.set_fan(speed=100)` | `speed`: 0–100 | `None` | Kontrol kipas (shortcut Motor M1). |
| `motor.stop_dc(motor="ALL")` | `motor`: `"M1"`, `"M2"`, atau `"ALL"` | `None` | Hentikan satu atau semua motor DC. |

**Pin Mapping Motor DC (L298N):**

| Motor | IN1 | IN2 | ENA (PWM) |
|---|---|---|---|
| `"M1"` | GPIO 11 | GPIO 13 | GPIO 15 |
| `"M2"` | GPIO 19 | GPIO 21 | GPIO 23 |

**Contoh Blockly:**
```js
Blockly.Python["sa_motor_servo"] = function (block) {
  window._hal_require("motor");
  let pin = block.getFieldValue("PIN");
  let degree = block.getFieldValue("DEGREE");
  return `motor.set_servo(${pin}, ${degree})\n`;
};

Blockly.Python["sa_motor_dc"] = function (block) {
  window._hal_require("motor");
  let m = block.getFieldValue("MOTOR");
  let speed = block.getFieldValue("SPEED");
  return `motor.run_dc("${m}", ${speed})\n`;
};
```

---

## Modul: `led`

```js
window._hal_require("led");
```

Kelas: `LEDHAL` (extends `PinHAL`) — sumber: `src/hal/led.py`

**Pin Mapping LED Default:**

| Target | GPIO Pin |
|---|---|
| `1` | GPIO 17 |
| `2` | GPIO 27 |
| `3` | GPIO 22 |
| `"ALL"` | semua LED di atas |

| Fungsi Python | Parameter | Return | Keterangan |
|---|---|---|---|
| `led.display_color(target, color, secs=None)` | `target`: 1/2/3/`"ALL"`, `color`: nama warna (selain `"black"` = ON), `secs`: detik (opsional) | `None` | Nyalakan LED. Warna apapun kecuali `"black"` akan menyalakan LED. Jika `secs` diisi, LED mati otomatis setelah durasi tersebut. |
| `led.turn_off(target)` | `target`: 1/2/3/`"ALL"` | `None` | Matikan LED secara langsung. |

**Contoh Blockly:**
```js
Blockly.Python["sa_led_on"] = function (block) {
  window._hal_require("led");
  let target = block.getFieldValue("TARGET");
  let color = block.getFieldValue("COLOR");
  return `led.display_color(${target}, "${color}")\n`;
};

Blockly.Python["sa_led_off"] = function (block) {
  window._hal_require("led");
  let target = block.getFieldValue("TARGET");
  return `led.turn_off(${target})\n`;
};
```

---

## Modul: `ledstrip`

```js
window._hal_require("ledstrip");
```

Kelas: `LedStripHAL` (extends `PinHAL`) — sumber: `src/hal/ledstrip.py`

**Color Palette yang Didukung:**
`red`, `green`, `blue`, `yellow`, `purple`, `cyan`, `white`, `orange`, `pink`, `black`, `off`

Juga mendukung: HEX string (`"#FF0000"`), atau nilai RGB terpisah via parameter `r`, `g`, `b`.

| Fungsi Python | Parameter | Return | Keterangan |
|---|---|---|---|
| `ledstrip.init_strip(pin=10, count=30, brightness=80)` | `pin`: GPIO BCM, `count`: jumlah LED, `brightness`: 0–255 | `True` / error | Inisialisasi strip WS2812B. Harus dipanggil pertama kali (atau auto-called). |
| `ledstrip.set_strip_color(color="red", r=None, g=None, b=None, pin=18, count=30)` | `color`: nama/hex, `r,g,b`: 0–255, `pin`, `count` | `None` | Set warna semua pixel strip. |
| `ledstrip.set_pixel(index=0, color="red", r=None, g=None, b=None, pin=18, count=30)` | `index`: 0-based, `color`, `r,g,b`, `pin`, `count` | `None` | Set warna satu pixel berdasarkan index. |
| `ledstrip.set_strip_brightness(brightness=255)` | `brightness`: 0–255 | `None` | Ubah brightness global strip. |
| `ledstrip.clear_strip()` | *(tanpa parameter)* | `None` | Matikan semua LED pada strip (set semua ke hitam). |
| `ledstrip.rainbow_strip(wait_ms=20, iterations=1)` | `wait_ms`: ms delay, `iterations`: jumlah putaran | `None` | Animasi rainbow cycle pada strip. |
| `ledstrip.display_color(target, color, secs=None)` | `target`: 1/2/3/`"ALL"`, `color`, `secs` | `None` | LED digital biasa (pin 17/27/22), bukan WS2812B. |
| `ledstrip.turn_off(target)` | `target`: 1/2/3/`"ALL"` | `None` | Matikan LED digital biasa. |

**Contoh Blockly:**
```js
Blockly.Python["sa_ledstrip_color"] = function (block) {
  window._hal_require("ledstrip");
  let color = block.getFieldValue("COLOR");
  let pin = block.getFieldValue("PIN");
  let count = block.getFieldValue("COUNT");
  return `ledstrip.set_strip_color("${color}", pin=${pin}, count=${count})\n`;
};

Blockly.Python["sa_ledstrip_pixel"] = function (block) {
  window._hal_require("ledstrip");
  let idx = block.getFieldValue("INDEX");
  let color = block.getFieldValue("COLOR");
  return `ledstrip.set_pixel(${idx}, "${color}")\n`;
};
```

---

## Modul: `rgb`

```js
window._hal_require("rgb");
```

Kelas: `RGBHAL` (extends `PinHAL`) — sumber: `src/hal/rgb.py`

**Pin Mapping RGB Default:**

| Target | R (GPIO) | G (GPIO) | B (GPIO) | Lokasi |
|---|---|---|---|---|
| `13` | GPIO 13 | GPIO 19 | GPIO 26 | Pintu Utama |
| `15` | GPIO 15 | GPIO 18 | GPIO 23 | Garasi |

**Warna yang Didukung:** `red`, `green`, `blue`, `yellow`, `purple`, `cyan`, `white`, `orange`, `black`, `off`

Mode: Common Anode (sinyal dibalik — aktif LOW)

| Fungsi Python | Parameter | Return | Keterangan |
|---|---|---|---|
| `rgb.set_color(target, color, secs=None)` | `target`: 13 atau 15, `color`: nama warna, `secs`: detik (opsional) | `None` | Set warna LED RGB common-anode. Auto-off setelah `secs` jika diisi. |
| `rgb.turn_off(target)` | `target`: 13 atau 15 | `None` | Matikan LED RGB (set ke `"off"`). |

**Contoh Blockly:**
```js
Blockly.Python["sa_rgb_color"] = function (block) {
  window._hal_require("rgb");
  let target = block.getFieldValue("TARGET");
  let color = block.getFieldValue("COLOR");
  return `rgb.set_color(${target}, "${color}")\n`;
};
```

---

## Modul: `rfid`

```js
window._hal_require("rfid");
```

Kelas: `RFIDHAL` — sumber: `src/hal/rfid.py`

Hardware: PN532 via I2C (`board.SCL` / `board.SDA`)

| Fungsi Python | Parameter | Return | Keterangan |
|---|---|---|---|
| `rfid.read_uid(timeout=0.1)` | `timeout`: detik | `str` / `None` | Baca UID kartu NFC/RFID. Return format `"04:AB:CD:EF"` atau `None` jika tidak ada kartu. |
| `rfid.register_card(uid, access_type="ALLOW")` | `uid`: string UID, `access_type`: `"ALLOW"` / `"DENY"` | `None` | Daftarkan kartu ke registry dengan status akses. |
| `rfid.unregister_card(uid)` | `uid`: string UID | `None` | Hapus kartu dari registry. |
| `rfid.check_status(uid=None)` | `uid`: string UID (opsional, baca live jika dikosongkan) | `str` | Return `"DIIZINKAN"`, `"DITOLAK"`, atau `"TIDAK_TERDAFTAR"`. |
| `rfid.is_allowed(uid=None)` | `uid`: string UID (opsional) | `bool` | Return `True` jika kartu terdaftar dengan status `ALLOW`. |

**Contoh Blockly:**
```js
Blockly.Python["sa_rfid_read"] = function (block) {
  window._hal_require("rfid");
  return [`rfid.read_uid()`, Blockly.Python.ORDER_ATOMIC];
};

Blockly.Python["sa_rfid_check"] = function (block) {
  window._hal_require("rfid");
  return [`rfid.check_status()`, Blockly.Python.ORDER_ATOMIC];
};

Blockly.Python["sa_rfid_register"] = function (block) {
  window._hal_require("rfid");
  let uid = Blockly.Python.valueToCode(block, "UID", Blockly.Python.ORDER_ATOMIC);
  let access = block.getFieldValue("ACCESS");
  return `rfid.register_card(${uid}, "${access}")\n`;
};
```

---

## Modul: `telemetry`

```js
window._hal_require("telemetry");
```

Kelas: `TelemetryHAL` — sumber: `src/hal/telemetry.py`

| Fungsi Python | Parameter | Return | Keterangan |
|---|---|---|---|
| `telemetry.send(**kwargs)` | key-value data sembarang | `None` | Kirim data realtime ke Flutter sebagai JSON `{"type": "telemetry", "telemetry": {...}}`. Thread-safe. |
| `telemetry.start_stream(interval=1.0)` | `interval`: detik | `None` | Aktifkan push loop telemetri otomatis. |
| `telemetry.stop_stream()` | *(tanpa parameter)* | `None` | Nonaktifkan push loop. |

**Contoh Blockly:**
```js
Blockly.Python["sa_telemetry_send"] = function (block) {
  window._hal_require("telemetry");
  let key = block.getFieldValue("KEY");
  let val = Blockly.Python.valueToCode(block, "VALUE", Blockly.Python.ORDER_ATOMIC);
  return `telemetry.send(${key}=${val})\n`;
};
```

---

## Modul: `power`

```js
window._hal_require("power");
```

Kelas: `PowerHAL` — sumber: `src/hal/mocks.py`

> **Status:** Stub/Mock — semua nilai return 0. Implementasi INA226 belum aktif.

| Fungsi Python | Parameter | Return | Keterangan |
|---|---|---|---|
| `power.read_house_power()` | *(tanpa parameter)* | `dict` | `{"volt": 0, "current_ma": 0, "power_mw": 0}` — data daya rumah |
| `power.read_solar_power()` | *(tanpa parameter)* | `dict` | `{"volt": 0, "current_ma": 0, "power_mw": 0}` — data daya solar panel |

**Contoh Blockly:**
```js
Blockly.Python["sa_power_house"] = function (block) {
  window._hal_require("power");
  return [`power.read_house_power()`, Blockly.Python.ORDER_ATOMIC];
};
```

---

## Modul Mock (Stub)

Modul berikut **belum diimplementasi** — semua method call mengembalikan `0` tanpa error (graceful degradation).

| Modul | `_hal_require` | Kelas | Status |
|---|---|---|---|
| `audio` | `window._hal_require("audio")` | `AudioHAL` | Mock |
| `display` | `window._hal_require("display")` | `DisplayHAL` | Mock |
| `motion` | `window._hal_require("motion")` | `MotionHAL` | Mock |
| `lan` | `window._hal_require("lan")` | `LANHAL` | Mock |
| `ai` | `window._hal_require("ai")` | `AIHAL` | Mock |

---

## Referensi: `window._hal_require`

```js
window._hal_require = function (moduleName, halPackage = "xploria_hal") { ... }
```

Fungsi ini secara otomatis:
1. Menambahkan `moduleName` ke `Blockly.Python._required_hal[halPackage]`
2. Mengisi `Blockly.Python.definitions_[halPackage]` dengan import yang benar
3. Selalu menambahkan `import time` dan `import math`

**Import yang dihasilkan (contoh memanggil `sensor` dan `motor`):**
```python
from xploria_hal import sensor, motor
import time
import math
```

**Import fallback (jika dipanggil tanpa `moduleName`):**
```python
from xploria_hal import pin, sensor, motor, led, audio, display, rfid, power, city, ai, lan, wms, robot, telemetry
import time
import math
```

---

## Ringkasan Cepat — Semua Fungsi

| Modul | Fungsi | Contoh Pemanggilan Python |
|---|---|---|
| `pin` | `set_digital` | `pin.set_digital(17, "HIGH")` |
| `pin` | `set_analog` | `pin.set_analog(18, 75)` |
| `pin` | `read_digital` | `pin.read_digital(4)` |
| `sensor` | `read_temperature` | `sensor.read_temperature(4)` |
| `sensor` | `read_humidity` | `sensor.read_humidity(4)` |
| `sensor` | `read_ultrasonic` | `sensor.read_ultrasonic(23, 24)` |
| `sensor` | `read_motion` | `sensor.read_motion(27)` |
| `sensor` | `read_ir_obstacle` | `sensor.read_ir_obstacle(25)` |
| `sensor` | `read_soil_moisture` | `sensor.read_soil_moisture(26)` |
| `sensor` | `read_rain` | `sensor.read_rain(6)` |
| `sensor` | `read_line` | `sensor.read_line(25)` |
| `sensor` | `read_light` | `sensor.read_light(24, True, 0)` |
| `sensor` | `read_gas` | `sensor.read_gas(5)` |
| `sensor` | `read_gas_status` | `sensor.read_gas_status(5, True, 0)` |
| `sensor` | `read_water_level` | `sensor.read_water_level(2)` |
| `motor` | `set_servo` | `motor.set_servo(18, 90)` |
| `motor` | `set_servo360` | `motor.set_servo360(18, 50, 2)` |
| `motor` | `stop_servo` | `motor.stop_servo(18)` |
| `motor` | `run_dc` | `motor.run_dc("M1", 80)` |
| `motor` | `set_fan` | `motor.set_fan(100)` |
| `motor` | `stop_dc` | `motor.stop_dc("ALL")` |
| `led` | `display_color` | `led.display_color(1, "red")` |
| `led` | `turn_off` | `led.turn_off("ALL")` |
| `ledstrip` | `init_strip` | `ledstrip.init_strip(10, 30, 80)` |
| `ledstrip` | `set_strip_color` | `ledstrip.set_strip_color("blue")` |
| `ledstrip` | `set_pixel` | `ledstrip.set_pixel(0, "green")` |
| `ledstrip` | `set_strip_brightness` | `ledstrip.set_strip_brightness(128)` |
| `ledstrip` | `clear_strip` | `ledstrip.clear_strip()` |
| `ledstrip` | `rainbow_strip` | `ledstrip.rainbow_strip(20, 3)` |
| `rgb` | `set_color` | `rgb.set_color(13, "red")` |
| `rgb` | `turn_off` | `rgb.turn_off(13)` |
| `rfid` | `read_uid` | `rfid.read_uid()` |
| `rfid` | `register_card` | `rfid.register_card("04:AB:CD", "ALLOW")` |
| `rfid` | `unregister_card` | `rfid.unregister_card("04:AB:CD")` |
| `rfid` | `check_status` | `rfid.check_status()` |
| `rfid` | `is_allowed` | `rfid.is_allowed()` |
| `telemetry` | `send` | `telemetry.send(suhu=28.5, jarak=10.2)` |
| `telemetry` | `start_stream` | `telemetry.start_stream(1.0)` |
| `telemetry` | `stop_stream` | `telemetry.stop_stream()` |
| `power` | `read_house_power` | `power.read_house_power()` |
| `power` | `read_solar_power` | `power.read_solar_power()` |
