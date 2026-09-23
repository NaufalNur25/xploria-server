# Xploria Raspberry Pi Daemon

Project ini adalah **Production-Ready Python Server** khusus untuk di-deploy ke Raspberry Pi. Project ini berdiri sendiri dan dilengkapi dengan server WebSocket bawaan, modul baca sensor hardware yang lengkap, serta eksekutor dinamis (Remote Code Execution) untuk mendukung Blockly dari aplikasi Flutter.

## Fitur Utama
1. **Server WebSocket Bawaan (`websockets`)**: Mendengarkan port `9002` secara default, bisa di-hit langsung dari aplikasi Flutter.
2. **Pub/Sub Telemetri Otomatis**: Secara efisien menge-push data dari Pin Raspberry Pi (Sensor Suhu, Kelembaban, Gas, dsb) hanya kepada client yang ter-subscribe.
3. **Eksekusi Blockly Real-Time**: Client Flutter bisa mengirim payload `{"type": "run", "code": "..."}` dan Daemon ini akan mengeksekusi script Python tersebut secara aman tanpa mem-blokir proses (Asynchronous).
4. **Real-time Log Streaming**: Fungsi `print()` di dalam Blockly Anda akan langsung di-stream kembali ke terminal UI Flutter.
5. **Aman untuk Hardware**: Import hardware (GPIO, I2C) diproteksi. Daemon tidak akan crash apabila pin atau komponen sensor ada yang belum terpasang.
6. **Pemetaan Pin Dinamis (SQLite)**: Memetakan Pin Logis ke Pin Fisik secara dinamis menggunakan SQLite (`peewee` ORM).

## Pemetaan Pin Dinamis (SQLite) & CLI
Proyek ini mendukung pemetaan pin secara dinamis tanpa mengubah *source code*. Misalnya, Anda dapat mengatur "Pin Logis 1" terhubung ke "Pin Fisik 17". Pemetaan ini disimpan di dalam database SQLite (`pin_config.db`).

Anda dapat mengelola pemetaan ini menggunakan aplikasi CLI bawaan:
```bash
python3 pin_config_cli.py --help
```

**Mode Interaktif:**
Sangat disarankan karena menampilkan menu yang mudah digunakan.
```bash
python3 pin_config_cli.py interactive
```

**Perintah Langsung CLI:**
* Melihat (List) pemetaan saat ini:
  ```bash
  python3 pin_config_cli.py list
  ```
* Menambah / Mengubah pemetaan (Contoh: Logis 1 -> Fisik 17):
  ```bash
  python3 pin_config_cli.py set 1 17 --desc "LED Ruang Tamu"
  ```
* Menghapus pemetaan:
  ```bash
  python3 pin_config_cli.py delete 1
  ```

*Catatan: Saat Anda mengubah konfigurasi melalui CLI, script secara otomatis akan memberitahu daemon (via WebSocket) untuk memperbarui pemetaan seketika (real-time) tanpa perlu me-restart server.*

## Cara Install dan Menjalankan di Raspberry Pi

### 1. Prasyarat (Requirements)
Pastikan Python 3 sudah terinstal di Raspberry Pi Anda.
Lalu install dependencies:
```bash
pip3 install -r requirements.txt
```

### 2. Menjalankan Daemon
Jalankan file `main.py` menggunakan python:
```bash
python3 main.py
```

Setelah log memunculkan `Starting Xploria Raspberry Pi Daemon on ws://0.0.0.0:9002`, server ini sudah siap di-hit oleh aplikasi Flutter menggunakan IP lokal Raspberry Pi (contoh: `ws://192.168.1.10:9002`).

## Deploy Production (systemd)

Agar daemon berjalan otomatis saat boot dan restart jika crash:

```bash
# Salin service file ke systemd
sudo cp xploria-daemon.service /etc/systemd/system/

# Sesuaikan WorkingDirectory dan ExecStart di file service jika path berbeda
# sudo nano /etc/systemd/system/xploria-daemon.service

# Aktifkan dan jalankan
sudo systemctl daemon-reload
sudo systemctl enable xploria-daemon
sudo systemctl start xploria-daemon

# Cek status dan log
sudo systemctl status xploria-daemon
sudo journalctl -u xploria-daemon -f
```

## Struktur Project
```text
xploria-rpi-daemon/
├── main.py               # Titik awal untuk menjalankan daemon WebSocket
├── pin_config_cli.py     # Aplikasi CLI untuk konfigurasi pemetaan pin
├── requirements.txt      # Daftar dependensi library
└── src/
    ├── ws_server.py      # Core WebSocket Server & Pub/Sub Logic
    ├── database.py       # Pengaturan SQLite dan Peewee ORM
    └── hal/              # Hardware Abstraction Layer
        ├── __init__.py   # Instances manager
        ├── core.py       # Manajemen koneksi GPIO Lgpio
        ├── pin.py        # Kontrol pin digital/analog
        ├── sensor.py     # Logika sensor kompleks (DHT, HC-SR04, LDR, dll)
        ├── motor.py      # Kontrol motor DC & Servo
        ├── led.py        # Kontrol LED
        ├── rfid.py       # Kontrol PN532 via I2C
        ├── telemetry.py  # Modul Telemetry
        └── mocks.py      # Perangkat palsu untuk kompatibilitas Blockly
```
