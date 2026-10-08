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

Agar daemon berjalan otomatis saat boot dan restart jika crash, gunakan installer:

```bash
sudo ./install.sh
```

Installer akan: membuat user `xploria` (+ grup `gpio`, `i2c`, `spi`), menyalin kode ke `/home/xploria/xploria-server`, membuat `.venv`, meng-install dependency, mengatur ownership (agar `pin_config.db` bisa ditulis), lalu memasang & menjalankan `xploria-daemon.service`. Aman dijalankan ulang untuk update kode; `pin_config.db` di target tidak akan ditimpa.

Path/user bisa diganti: `sudo APP_USER=xploria APP_DIR=/opt/xploria ./install.sh`

```bash
# Cek status dan log
sudo systemctl status xploria-daemon
sudo journalctl -u xploria-daemon -f
```

> **Penting:** Jalankan `pin_config_cli.py` sebagai user service, bukan `sudo` biasa, agar `pin_config.db` tidak berpindah kepemilikan ke root:
> `sudo -u xploria /home/xploria/xploria-server/.venv/bin/python3 /home/xploria/xploria-server/pin_config_cli.py list`

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


## Formulir Blockly pada IoT Lab

Server menyediakan `hospital` khusus setiap program Hospital. Siswa menentukan
pertanyaan melalui kategori Blockly yang sudah tersedia; aplikasi menampilkan
formulir pada widget canvas yang ditambahkan siswa, bukan dialog otomatis.
Contoh API Python yang digunakan generator:

```python
hospital.form("form-uid", "Pendaftaran", [
    {"label": "Nama pasien", "type": "text"},
    {"label": "Usia", "type": "number"},
    {"label": "Keluhan", "type": "choice", "options": ["Demam", "Batuk"]},
])

def submitted():
    # Jawaban hanya tersedia di dalam kejadian formulir terkait.
    hospital.report("output-uid", "display", hospital.answer("Nama pasien"))
    # Pendaftaran memerlukan aksi eksplisit dari blok siswa:
    # hospital.register_patient(hospital.answer("Nama pasien"),
    #                           hospital.answer("Keluhan"), "UGD")

hospital.on_form("handler-uid", "Pendaftaran", submitted)
```

`src/hal/hospital_widgets.py` merupakan runtime bawaan; aplikasi tidak mengirim
salinan runtime. API scanner, tombol, keluaran, dan tindakan Hospital tetap
tersedia. API Jitsi didelegasikan ke `HospitalHAL` yang sudah ada.

### Protokol WebSocket versi 1

- `{"type":"capabilities","request_id":"..."}` dibalas dengan
  `{"type":"capabilities","request_id":"...","hospital_widgets":1}`.
- `run` menerima `code` dan `widget_session` berisi `protocol_version: 1`,
  `project_id`, `session_id`, `sources` (UID blok aktif), `snapshot`, dan
  `snapshot_version`. `run` tanpa metadata tetap mendukung program kit lain.
- `hospital_widget_event` membawa `project_id`, `session_id`, `source_uid`,
  `event_id`, `topic` (`form`/`scan`/`button`), dan input. Form memakai `answers`;
  scan memakai `barcode`, `mode`, `jumlah`. Snapshot dan versi dapat ikut dikirim.
- `hospital_widget_result` membawa proyek/sesi, `request_id`, dan `result`
  (`ok`, nilai/error, snapshot serta versinya). Hasil hanya diterima untuk
  permintaan penyimpanan yang masih menunggu pada sesi pemiliknya.
- `stop` dapat membawa proyek/sesi. Stop tanpa identitas tetap didukung.
- Server mengirim paket lengkap `{"type":"telemetry","telemetry":{...}}`
  dengan `action: hospital_widget`, `project_id`, `session_id`, `kind`, serta UID
  terkait. Jenisnya meliputi `form`, `binding`, `ready`, `event_ack`, `command`,
  `value`, `error`, dan `closed`.

Paket widget dikirim hanya ke koneksi pemilik sesi dan tidak melewati broadcast
atau penyaringan delta telemetry. ACK event (`accepted`, `duplicate`, `rejected`)
menyatakan penerimaan input; ACK penyimpanan terpisah. Jawaban tidak otomatis
membuat pasien, obat, atau antrean. Penyimpanan tetap dilakukan aplikasi setelah
aksi siswa, lalu dikonfirmasi sebelum Python melanjutkan pembacaan hasil.

Nama formulir unik dalam sesi dan label pertanyaan unik dalam formulir. Semua
pertanyaan wajib diisi; angka harus finite dan jawaban pilihan harus tersedia.
Stop, disconnect, atau penggantian program menutup sesi lama. Event lama dan
pengiriman ulang tidak menjalankan handler kedua kali.

Perbarui kode server sebelum menguji aplikasi versi ini, lalu restart daemon
melalui alur update yang digunakan. Tidak diperlukan dependensi Python baru
atau migrasi database; `pin_config.db` dan data aplikasi tetap dipertahankan.

### Pengujian tanpa perangkat GPIO

```bash
python -m unittest discover -s tests -v
```

Tes mengganti objek hardware dengan mock, tetapi memakai modul Hospital dan
handler WebSocket asli melalui koneksi lokal. Pengujian fisik dilakukan pada Pi
setelah pembaruan server.
