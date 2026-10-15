# XPLORIA SERVER — PROJECT CONTEXT & ARCHITECTURE SPECIFICATION

> **Dokumentasi Konteks Proyek Komprehensif & Menyeluruh**  
> *Versi:* 1.0.0  
> *Target Hardware:* Raspberry Pi 4B / Compute Module  
> *Platform:* Python 3.9+ (Linux / Raspberry Pi OS)  
> *Protokol:* WebSocket (ws://) Port 9002  

---

## 1. Ikhtisar Proyek (Executive Overview)

**Xploria Server (`xploria-server`)** adalah daemon Python *production-ready* yang dirancang untuk berjalan di atas Raspberry Pi. Server ini berfungsi sebagai jembatan *real-time* (Hardware Bridge) dan mesin eksekusi kode dinamis (Remote Code Execution / RCE Engine) untuk platform edukasi/IoT **Xploria**.

Server ini menghubungkan aplikasi klien (seperti aplikasi mobile/desktop **Flutter**) dengan perangkat keras fisik (sensor, motor, LED, RFID, display, relay) melalui koneksi WebSocket dua arah.

### Fitur & Tanggung Jawab Utama:
1. **WebSocket Communication Gateway (`ws_server.py`)**:
   - Mendengarkan koneksi pada port default `9002`.
   - Mengelola koneksi klien aktif dan status langganan telemetri (*Pub/Sub pattern*).
2. **Safe Remote Code Execution (RCE) untuk Blockly**:
   - Menerima kode Python yang di-generate dari block-based programming (Blockly).
   - Menjalankan kode secara *asynchronous* dan *non-blocking* di thread pool terisolasi.
   - Mengintersepsi perintah `print()` untuk di-stream secara real-time ke terminal UI Flutter.
   - Mengintersepsi perintah `time.sleep()` agar proses dapat dihentikan (*cancellable*) seketika saat user menekan tombol stop.
3. **Hardware Abstraction Layer (HAL) Modular**:
   - Mengisolasi interaksi perangkat keras ke dalam modul-modul independen (`pin`, `sensor`, `motor`, `led`, `rfid`, `telemetry`, `mocks`).
   - Proteksi impor hardware: jika library hardware (`lgpio`, `adafruit_dht`, `board`, dll.) tidak tersedia, daemon tidak crash dan tetap beroperasi dengan gracefully degraded/mocked devices.
4. **Background Worker Threads & Zero-Blocking Telemetry**:
   - Pembacaan sensor berat atau rentan delay (DHT22 dan HC-SR04 ultrasonic) didelegasikan ke daemon worker thread independen yang memiliki cache thread-safe dengan *exponential backoff*.
   - Event loop WebSocket membaca data dari cache memori, mencegah stutter atau lag pada koneksi jaringan.
5. **Systemd Production Integration**:
   - Dilengkapi template unit systemd (`xploria-daemon.service`) untuk auto-start saat booting, auto-restart jika terjadi crash, serta isolasi privilege.

---

## 2. Struktur Direktori & File (Comprehensive Directory Map)

```text
xploria-server/
├── README.md                  # Dokumentasi ringkas instalasi dan penggunaan
├── requirements.txt           # Dependensi pustaka Python
├── main.py                    # Entry point eksekusi daemon
├── xploria-daemon.service     # Konfigurasi Linux systemd service unit
├── xploria_hal.py             # File HAL monolitik (arsitektur lama / referensi)
└── src/
    ├── ws_server.py           # Core WebSocket server, RCE sandbox, dan handler Pub/Sub
    └── hal/                   # Paket Hardware Abstraction Layer modular
        ├── __init__.py        # Inisialisasi singleton instance HAL (sensor, motor, dll.)
        ├── core.py            # Abstraksi chip GPIO via library lgpio & sinyal terminasi
        ├── pin.py             # Abstraksi Pin digital (GPIO read/write) dan analog (PWM)
        ├── sensor.py          # Logika pembacaan sensor (DHT22, Ultrasonik, MQ Gas, PIR, LDR, dll.)
        ├── motor.py           # Kontrol Motor DC (L298N driver), Servo, dan Kipas
        ├── led.py             # Kontrol lampu LED digital & multi-target
        ├── rfid.py            # Driver pembaca RFID PN532 via I2C & whitelist kartu akses
        ├── telemetry.py       # Manajer stream telemetri ad-hoc dan status streaming
        └── mocks.py           # Perangkat tiruan (Audio, Display, Motion, LAN, AI, Power)
```

### Rincian Fungsi Tiap File:

| Path File | Kategori | Peran & Deskripsi Teknis |
|:---|:---|:---|
| `main.py` | Entry Point | Inisialisasi logging, mendaftarkan path `src/` ke `sys.path`, memicu `asyncio.run(start_server())`, serta menangani penutupan bersih GPIO via `cleanup_gpio()`. |
| `requirements.txt` | Dependency | Menentukan dependensi: `websockets>=12.0`, `lgpio`, `gpiod`, `adafruit-circuitpython-pn532`, `adafruit-blinka`, `adafruit-circuitpython-dht`. |
| `xploria-daemon.service` | DevOps / Systemd | Unit systemd untuk menjalankan daemon sebagai user `xploria`, auto-restart saat failure, akses grup `gpio`, `i2c`, dan `spi`. |
| `xploria_hal.py` | Legacy / Monolitik | Implementasi HAL tunggal sebelum di-refactor ke `src/hal/`. Berguna sebagai acuan konfigurasi pinout historis. |
| `src/ws_server.py` | Server & Runtime | Server WebSocket asinkron, sandbox `exec()`, broadcast telemetri, proxy interupsi eksekusi, injeksi modul virtual `xploria_hal`. |
| `src/hal/__init__.py` | HAL Manager | Mengimpor seluruh kelas HAL, menginisialisasi objek singleton (`sensor`, `motor`, `led`, `pin`, `rfid`, `telemetry`, `power`, dll.). |
| `src/hal/core.py` | Low-Level GPIO | Manajemen file descriptor `gpiochip` menggunakan `lgpio`, penanganan pembersihan otomatis saat exit (`atexit`, `SIGTERM`, `SIGINT`). |
| `src/hal/pin.py` | GPIO Primitive | Operasi digital `gpio_claim_output`, `gpio_write`, `gpio_read`, serta PWM analog `tx_pwm`. |
| `src/hal/sensor.py` | Sensor Subsystem | Mengatur `_DHTWorker` dan `_UltrasonicWorker` di background thread dengan cache & lock, plus sensor digital (`read_gas`, `read_motion`, `read_light`, dll.). |
| `src/hal/motor.py` | Actuator Subsystem | Kontrol servo PWM 50Hz via `tx_servo`, driver motor DC (IN1, IN2, ENA), serta shortcut `set_fan()`. |
| `src/hal/led.py` | Actuator Subsystem | Warisan dari `PinHAL` untuk mengontrol LED individual atau serentak (`ALL`) dengan dukungan durasi otomatis (`secs`). |
| `src/hal/rfid.py` | Security / Sensor | Komunikasi I2C dengan PN532, normalisasi UID kartu, penyimpanan izin akses (`ALLOW` / `DENY`), validasi `is_allowed()`. |
| `src/hal/telemetry.py` | Telemetri Subsystem | Menyediakan antrean `asyncio.Queue` thread-safe untuk pesan telemetri kustom yang dikirimkan oleh kode pengguna. |
| `src/hal/mocks.py` | Fallback / Stubs | Implementasi `MockDevice` dengan `__getattr__` dinamis untuk peripheral yang belum terpasang (Audio, Display, AI, dll.) agar kode Blockly tidak melempar error. |

---

## 3. Arsitektur Sistem & Alur Kerja (System Architecture)

```
+-------------------------------------------------------------------------+
|                         Flutter Client (App / UI)                       |
+-------------------------------------------------------------------------+
                                    |
                    WebSocket ws://<RPI_IP>:9002
                                    v
+-------------------------------------------------------------------------+
|                        src/ws_server.py                                 |
|                                                                         |
|  +------------------------+  +-------------------+  +----------------+  |
|  |   Connection Manager   |  | Telemetry Broad-  |  |  RCE Executor  |  |
|  | - connected_clients    |  |   caster (2s loop)|  | - async thread |  |
|  | - subscribed_clients   |  | - push & ad-hoc   |  | - output stream|  |
|  +------------------------+  +-------------------+  +----------------+  |
+-------------------------------------------------------------------------+
               |                                            |
        Reads Sensor Cache                        Executes Python Script
               |                                            |
               v                                            v
+-------------------------------------------------------------------------+
|                    Hardware Abstraction Layer (HAL)                     |
|                                                                         |
|  +---------------------+  +---------------------+  +-----------------+  |
|  | Background Workers  |  |  Direct HAL Modules |  |  Virtual Module |  |
|  | - _DHTWorker (GPIO4)|  | - PinHAL            |  |  sys.modules    |  |
|  | - _UltrasonicWorker |  | - MotorHAL          |  |  ['xploria_hal']|  |
|  |   (TRIG23, ECHO24)  |  | - LEDHAL / RFIDHAL  |  |                 |  |
|  | [Cached & Lock-safe]|  | - Mocks (Audio, etc)|  | [HalProxy Guard]|  |
|  +---------------------+  +---------------------+  +-----------------+  |
+-------------------------------------------------------------------------+
               |                                            |
               +----------------------+---------------------+
                                      |
                                      v
+-------------------------------------------------------------------------+
|                   Raspberry Pi 4B Physical Hardware                     |
|      - GPIO (lgpio / gpiod)                                             |
|      - I2C Bus (SDA / SCL) -> PN532 RFID, PCA9685, ADS1115, INA226      |
|      - Sensors: DHT22, HC-SR04, MQ-9, PIR, LDR                          |
|      - Actuators: Servo Motor, DC Motor / Fan, Status LEDs              |
+-------------------------------------------------------------------------+
```

---

## 4. Spesifikasi Protokol WebSocket (WebSocket Protocol)

Port Server: **`9002`** (dapat diakses pada semua antarmuka: `0.0.0.0:9002`).

### 4.1. Dari Client ke Server (Inbound Messages)

#### A. Menjalankan Kode Python / Blockly (`run`)
```json
{
  "type": "run",
  "code": "for i in range(5):\n    print(f'Hitungan: {i}')\n    time.sleep(1)"
}
```
*Tindakan Server:* Mengeksekusi script secara asinkron di worker thread, mengarahkan output `print` kembali ke klien.

#### B. Menghentikan Eksekusi (`stop`)
```json
{
  "type": "stop"
}
```
*atau:*
```json
{
  "command": "stop"
}
```
*Tindakan Server:* Mengaktifkan flag `stop_requested = True` pada koneksi websocket terkait. Eksekusi `time.sleep` dan setiap pemanggilan HAL melalui `HalProxy` akan melempar exception `StopExecution`.

#### C. Berlangganan Telemetri (`subscribe_telemetry`)
```json
{
  "command": "subscribe_telemetry"
}
```
*Tindakan Server:* Memasukkan klien ke `subscribed_clients`. Server mulai mem-broadcast data sensor setiap interval (~2 detik).

#### D. Berhenti Langganan Telemetri (`unsubscribe_telemetry`)
```json
{
  "command": "unsubscribe_telemetry"
}
```
*Tindakan Server:* Menghapus klien dari `subscribed_clients`. Jika subscriber kosong, polling otomatis dinonaktifkan untuk menghemat daya/sumber daya.

---

### 4.2. Dari Server ke Client (Outbound Messages)

#### A. Streaming Log / Output Konsol
```json
{
  "type": "output",
  "payload": "Hitungan: 0\n"
}
```
Saat eksekusi selesai normal:
```json
{
  "type": "output",
  "payload": "\n[Proses Selesai]"
}
```
Jika dihentikan oleh user:
```json
{
  "type": "output",
  "payload": "\n[Proses Dihentikan]"
}
```

#### B. Pesan Kesalahan Runtime (Error Traceback)
```json
{
  "type": "error",
  "payload": "Traceback (most recent call last):\n  File ...\nZeroDivisionError: division by zero\n"
}
```

#### C. Stream Telemetri Berkala
```json
{
  "type": "telemetry",
  "timestamp": "2026-09-23T04:32:00.000000+00:00",
  "telemetry": {
    "temperature": 28.5,
    "humidity": 65.0,
    "gas": false,
    "light": 100,
    "motion_pir1": false,
    "motion_pir2": true,
    "distance_cm": 15.4,
    "house_power": {"volt": 0, "current_ma": 0, "power_mw": 0},
    "solar_power": {"volt": 0, "current_ma": 0, "power_mw": 0},
    "rfid_uid": "3A:F2:8B:11"
  }
}
```

#### D. Acknowledgment (Konfirmasi Perintah)
```json
{
  "type": "ack",
  "command": "subscribe_telemetry",
  "status": "ok",
  "message": "Telemetry subscribed"
}
```

---

## 5. Rincian Teknis Modul HAL & Concurrency Model

### 5.1. Concurrency Model Sensor (`src/hal/sensor.py`)
Sensor seperti **DHT22** (protokol *single-wire timing-sensitive*) dan **HC-SR04** (pengukuran *pulse timing echo*) memerlukan waktu tunggu I/O yang dapat memblokir eksekusi hingga ratusan milidetik. Jika dipanggil di event loop utama, WebSocket akan membeku (*freeze*).

**Solusi Arsitektur:**
1. **Background Workers (`_DHTWorker`, `_UltrasonicWorker`)**:
   - Berjalan sebagai `daemon thread`.
   - Mengambil data secara periodik (default interval: 2 detik).
   - Menyimpan hasil ke dalam kamus `_cache` yang dilindungi oleh `threading.Lock()`.
2. **Exponential Backoff on Failure**:
   - Jika sensor gagal terbaca (misal timeout atau checksum error), interval diperpendek dengan backoff eksponensial (`RETRY_BASE = 0.5s`).
   - Jika gagal mencapai ambang batas `MAX_FAILURES = 5`, worker masuk mode istirahat panjang (`MAX_COOLDOWN = 60.0s`) agar tidak menyita CPU akibat sensor mati/lepas.
3. **Non-Blocking Public API**:
   - Panggilan `sensor.read_temperature()`, `sensor.read_humidity()`, dan `sensor.read_ultrasonic()` hanya mengambil nilai terakhir dari cache memory. Kompleksitasnya $O(1)$ dan 100% non-blocking.

### 5.2. Runtime Sandboxing & HalProxy (`src/ws_server.py`)
Ketika kode Blockly dijalankan:
- Setiap modul HAL (`sensor`, `motor`, `led`, dll.) dibungkus menggunakan `HalProxy`.
- Sebelum memanggil fungsi hardware yang sebenarnya, `HalProxy` menjalankan `check_stop()`. Jika user mengirim perintah `stop`, proses langsung diputus tanpa menunggu siklus kode selesai.
- Fungsi bawaan `print` digantikan oleh `custom_print` yang mengirimkan teks via `asyncio.run_coroutine_threadsafe(client_ws.send(...), loop)`.
- Fungsi bawaan `time.sleep` digantikan oleh modul virtual `custom_time.sleep` yang memecah interval tidur panjang menjadi iterasi potongan 100 milidetik (`0.1s`), sehingga interupsi `stop` responsif dalam waktu <100ms.
- Virtual Module `xploria_hal`: Didaftarkan langsung ke `sys.modules["xploria_hal"]`. Skrip Blockly yang memanggil:
  ```python
  from xploria_hal import sensor, motor, led
  ```
  dapat berjalan tanpa perlu berkas fisik `xploria_hal.py` di folder lokal eksekusi.

---

## 6. Pemetaan Pin Hardware (Default Pinout Map)

Berdasarkan implementasi aktif di `src/hal/` dan `src/ws_server.py`:

| Komponen / Sensor | Tipe Pin / Mode | Pin BCM / GPIO | Keterangan & Konfigurasi |
|:---|:---|:---|:---|
| **DHT22** (Suhu & Lembab) | Direct Digital 1-Wire | **GPIO 4** (atau GPIO 27 pada loop telemetri) | Dibaca via worker `adafruit_dht.DHT22` |
| **HC-SR04 Trigger** | Digital Output | **GPIO 23** | 10µs pulse output |
| **HC-SR04 Echo** | Digital Input | **GPIO 24** | Menghitung durasi echo pulse (Pull-Down) |
| **PIR 1** (Motion) | Digital Input | **GPIO 17** | Active-High, sensor gerak 1 |
| **PIR 2** (Motion) | Digital Input | **GPIO 4** / GPIO 27 | Active-High, sensor gerak 2 |
| **MQ Gas Sensor** | Digital Input | **GPIO 5** | Active-Low |
| **LDR / Light Sensor** | Digital Input | **GPIO 24** | Active-Low (Pull-Up, return 100/0) |
| **IR Obstacle** | Digital Input | **GPIO 25** | Active-Low (Pull-Up) |
| **Soil Moisture** | Digital Input | **GPIO 26** | Active-Low (Pull-Up) |
| **Line Tracking** | Digital Input | **GPIO 25** | Active-Low ('BLACK' / 'WHITE') |
| **Servo Motor** | Hardware PWM | **GPIO 18** | Frekuensi 50Hz, pulse 500µs - 2500µs |
| **DC Motor M1 (Kipas)**| GPIO Output + PWM | **IN1: 11, IN2: 13, ENA: 15** | Driver L298N / H-Bridge |
| **DC Motor M2** | GPIO Output + PWM | **IN1: 19, IN2: 21, ENA: 23** | Driver L298N / H-Bridge |
| **LED Indikator** | Digital Output | **LED 1: 17, LED 2: 27, LED 3: 22**| Digital On/Off |
| **RFID PN532** | I2C Bus | **SDA: GPIO 2 / GPIO 20, SCL: GPIO 3 / GPIO 21** | I2C standard bus via Adafruit CircuitPython |

---

## 7. Petunjuk Deployment & Konfigurasi Operasional

### 7.1. Instalasi Lingkungan Virtual di Raspberry Pi
```bash
# Update paket sistem
sudo apt update && sudo apt install -y python3-pip python3-venv python3-lgpio

# Buat virtual environment dengan akses sistem package (agar lgpio sistem terbaca)
python3 -m venv --system-site-packages /home/xploria/xploria-server/.venv

# Masuk ke venv dan instal dependensi
source /home/xploria/xploria-server/.venv/bin/activate
pip install -r requirements.txt
```

### 7.2. Menjalankan Server Secara Manual
```bash
python3 main.py
```
*Output indikator berhasil:*
```text
2026-09-23 11:32:00 [INFO] Starting Xploria Raspberry Pi Daemon on ws://0.0.0.0:9002
2026-09-23 11:32:00 [INFO] server listening on 0.0.0.0:9002
```

### 7.3. Konfigurasi Systemd Service (Production Mode)
Salin file konfigurasi service ke direktori systemd:
```bash
sudo cp xploria-daemon.service /etc/systemd/system/xploria-daemon.service
sudo systemctl daemon-reload
sudo systemctl enable xploria-daemon
sudo systemctl start xploria-daemon

# Memeriksa log dan status
sudo systemctl status xploria-daemon
sudo journalctl -u xploria-daemon -f
```

---

## 8. Analisis Rekayasa & Catatan Pengembangan (Engineering Insights)

1. **Dualitas File HAL (`xploria_hal.py` vs `src/hal/`)**:
   - Di root proyek terdapat berkas `xploria_hal.py` berukuran ~16KB. Berkas ini adalah versi monolitik lama yang belum modular dan belum memiliki pemisahan thread worker sensor.
   - Aplikasi utama (`main.py` dan `src/ws_server.py`) sepenuhnya menggunakan paket modular `src/hal/`. Berkas `xploria_hal.py` di root dapat dipertahankan sebagai referensi atau di-refactor menjadi modul wrapper yang mengekspor `src/hal` agar tidak terjadi divergensi kode.
2. **Kesesuaian Pin DHT22 & PIR**:
   - Di `src/ws_server.py:65`, fungsi `_gather_telemetry()` membaca `sensor.read_temperature(27)`, sedangkan default parameter pada `src/hal/sensor.py` adalah pin `4`. Pastikan pinout pada rangkaian fisik disesuaikan dengan konfigurasi ini.
3. **Keamanan Eksekusi Kode (`exec`)**:
   - Eksekutor saat ini menggunakan built-in `exec(code_str, exec_globals)`. Fitur ini ditujukan untuk lingkungan sandbox IoT lokal Xploria. Apabila server diekspos ke jaringan publik di luar jaringan lokal tertutup, disarankan menambahkan batasan AST parser atau timeout thread eksekusi untuk mencegah *denial of service*.
4. **Mock Subsystems (`src/hal/mocks.py`)**:
   - Kelas seperti `AudioHAL`, `DisplayHAL`, `MotionHAL`, `LANHAL`, `AIHAL`, dan `PowerHAL` saat ini mengembalikan nilai mock (0 atau dictionary nol). Modul ini siap diimplementasikan secara bertahap saat modul hardware tambahan dihubungkan ke Raspberry Pi.
