# Face recognition UART — metadata lama

## Alur

Widget Flutter / Python Blockly → WebSocket Pi → `hal.face` → UART → ESP32-CAM.
ESP32-CAM → JPEG UART → Pi → YuNet mendeteksi wajah → SFace membuat embedding → dibandingkan dengan `faces.npz`.
Pi → `camera_result` (JPEG Base64, nama, recognized, similarity) → Flutter menampilkan foto.

**Protokol UART mengikuti firmware tim hardware yang sudah diuji**: perintah `CAPTURE\n`,
balasan `FACE` + panjang JPEG 4 byte little-endian + JPEG. Firmware contoh `XPLC`
terdahulu tidak digunakan untuk konfigurasi ini dan tidak perlu di-upload.

Foto JPEG tidak disimpan permanen secara otomatis. NPZ berisi embedding, bukan kumpulan JPEG.
Implementasi mendukung satu kamera, hingga lima sampel per nama, tepat satu wajah per foto.
Nama sensitif huruf besar/kecil. Daftar ulang nama yang sama menambah sampel hingga batas lima. Dataset schema 1 lama tetap terbaca dan sampel lama tetap disimpan.
Balasan pendaftaran menambahkan sample_count, max_samples, dan sample_added. Jika sudah lima, sample_added bernilai false dan dataset tidak diubah.
Balasan pengenalan tetap memakai similarity (cosine), recognized, dan name; ditambah candidate_name, threshold, dan sample_count milik kandidat. name tetap kosong bila tidak dikenali. Skor maksimum dihitung dari seluruh sampel, termasuk data legacy bila dikonfigurasi.
Flutter menampilkan clamp(similarity, 0, 1) * 100 sebagai skor kemiripan, bukan probabilitas identitas. Daftar dan Kenali tetap mengambil satu foto baru per permintaan. Hapus tetap menghapus seluruh faces.npz aplikasi; model dan NPZ legacy tidak dihapus.

## Ambang kemiripan dari Blockly

Blok `Kenali wajah jika skor minimal <angka>%` menghasilkan `face.is_recognized_at_least(angka)`. Fungsi memvalidasi angka 0–100, mengambil satu foto, lalu membandingkan skor cosine dengan angka/100 untuk pemeriksaan itu saja. Nilai `XPLORIA_FACE_THRESHOLD` global tidak diubah; blok lama `face.is_recognized()` tetap menggunakan batas global. Hasil `camera_result` memuat threshold yang benar untuk pemindaian tersebut.

Blok `Skor kemiripan wajah terakhir (%)` memanggil `face.get_last_similarity_percent()`, yang membaca hasil pemindaian terakhir pada konteks program yang sama tanpa memotret ulang. Nama juga dibaca dari hasil yang sama melalui `face.get_recognized_name()`. Skor bernilai 0 bila belum ada hasil pengenalan atau wajah tidak terdeteksi. Pembacaan skor/nama sebelum kondisi kenali belum memberikan data pemindaian baru. Skor 70% adalah skor cosine 0,70, bukan probabilitas identitas 70%.

Contoh Blockly secara konseptual:

```python
from xploria_hal import face

if face.is_recognized_at_least(70):
    print(face.get_recognized_name())
    print(face.get_last_similarity_percent())
```
Tidak ada liveness detection; ini fitur pembelajaran, belum cocok menjadi autentikasi pintu sungguhan.

## File

- `src/hal/face.py`: akses UART tim HW, validasi JPEG, engine, dataset atomik, pembaca NPZ lama opsional, API Python dan lock kamera.
- `src/ws_server.py`: ekspor `face` di `xploria_hal`, konteks eksekusi Blockly, kontrol kamera asynchronous.
- `requirements-face.txt`: dependensi opsional. Server biasa tetap bisa import tanpa dependensi kamera.
- `face.env.example`: konfigurasi UART/model/dataset.
- `tests/test_face.py`, `tests/test_camera_ws.py`: tes protokol, dataset dan jalur WebSocket.

Metadata Blockly tetap `uid`, `block_type`, `hw_type`, `channel`, `name`, `fields` dan script yang sudah ada.
Tidak mewajibkan `device_key` atau profil Smart baru. Jalur servo dan sensor yang sudah ada tetap dipertahankan.
Pemisahan resource lintas Smart belum ditambahkan.

## Pasang di Pi

Pada instalasi tim ini, Git checkout berada di `~/xploria-server`, sedangkan daemon
menjalankan salinan yang dipasang di `/opt/xploria`. Pastikan `git pull` di checkout
**sudah berhasil** sebelum menjalankan installer. Jika Git melaporkan divergent
branches, selesaikan commit lokal terlebih dahulu; installer tidak memperbaiki Git.

Perintah ini dijalankan di SSH Pi, bukan CMD Windows:

```bash
cd ~/xploria-server
sudo APP_USER=xploria APP_DIR=/opt/xploria ./install.sh
sudo -u xploria /opt/xploria/.venv/bin/python3 -m pip install -r /opt/xploria/requirements-face.txt
sudo install -d -o xploria -g xploria -m 700 /var/lib/xploria/faces
sudo usermod -aG dialout xploria
sudo install -d /etc/xploria
sudo cp -n /opt/xploria/face.env.example /etc/xploria/face.env
```

`install.sh` memakai `rsync --delete` menuju `/opt/xploria`; simpan model dan NPZ
di luar folder itu, misalnya `/var/lib/xploria/faces` dan folder tim HW tersendiri.
Installer mempertahankan `pin_config.db`, tetapi tidak melindungi file wajah yang
disimpan sembarang di `/opt/xploria`.

Tim HW menguji `face_detection_yunet_2026may.onnx` dan
`face_recognition_sface_2021dec_int8.onnx`. Jika ingin memakai NPZ lama dari tim,
**gunakan persis model SFace yang dipakai membuat NPZ tersebut**. Salin dua model
yang mereka gunakan ke Pi lalu set `XPLORIA_FACE_DETECTOR` dan
`XPLORIA_FACE_RECOGNIZER` pada `/etc/xploria/face.env` ke path absolutnya.
Jika belum ada model dari tim, dapat memakai model resmi OpenCV Zoo di bawah;
buat pendaftaran wajah baru karena embedding model lain tidak dijamin cocok.

- https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
- https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface

Pastikan kedua file bisa dibaca user `xploria`. Model tidak disertakan dalam repo.
Instalasi OpenCV wheel tergantung OS/arsitektur Pi; gunakan Raspberry Pi OS 64-bit yang mendukung wheel tersebut.

Jalankan `sudo systemctl edit xploria-daemon`, lalu isi:

```ini
[Service]
EnvironmentFile=/etc/xploria/face.env
SupplementaryGroups=dialout
```

Gunakan `raspi-config`: aktifkan serial hardware, nonaktifkan serial login console.
Reboot jika konfigurasi UART berubah. Cek `ls -l /dev/serial0` dan sesuaikan env bila port berbeda.
Jangan gunakan GPIO UART untuk aktuator lain secara bersamaan.

## Firmware dan kabel

Gunakan firmware yang sudah diuji tim HW. Tidak perlu flash ulang bila ESP32-CAM
memang sudah merespons `CAPTURE\n` dengan frame `FACE`.
Gunakan baud 460800 di kedua sisi; jika tidak stabil, turunkan keduanya.

- Pi TX GPIO14 (pin fisik 8) → ESP RX GPIO3.
- Pi RX GPIO15 (pin fisik 10) ← ESP TX GPIO1.
- GND disambungkan bersama.
- Sinyal UART harus 3.3V; jangan masukkan sinyal 5V ke GPIO Pi.
- Catu ESP32-CAM sesuai spesifikasi board dengan sumber stabil; jangan mengambil daya kamera dari pin GPIO.
- Lepaskan adapter flashing dari RX/TX saat dipakai Pi.

Protokol: host mengirim ASCII `CAPTURE\n`. Kamera menjawab `FACE`, lalu satu
uint32 little-endian panjang JPEG dan data JPEG. Maksimal 500.000 byte,
timeout 12 detik; JPEG wajib diawali `FFD8` dan diakhiri `FFD9`.
Noise boot sebelum header diabaikan. Protokol tim HW tidak memiliki request ID atau CRC
di sisi ESP; server mengunci satu permintaan kamera setiap saat dan membersihkan buffer
sebelum mengirim perintah. Firmware gagal inisialisasi akan menghasilkan timeout host.

Pada Raspberry Pi 5, `/dev/serial0` bisa menunjuk konektor debug, bukan UART GPIO14/15
di pin fisik 8/10. Periksa model Pi serta hasil `ls -l /dev/serial*`; atur port dan
overlay UART sesuai kabel nyata sebelum menguji.

## Menggunakan dataset NPZ tim HW

Script tim HW (`test-recognition.py`) membaca `embeddings/<nama>.npz`, termasuk beberapa
embedding per orang. Agar file tersebut ikut dipakai aplikasi, tambahkan pada
`/etc/xploria/face.env`:

```ini
XPLORIA_FACE_LEGACY_EMBEDDINGS_DIR=/path/absolut/ke/embeddings
XPLORIA_FACE_DETECTOR=/path/absolut/ke/face_detection_yunet_2026may.onnx
XPLORIA_FACE_RECOGNIZER=/path/absolut/ke/face_recognition_sface_2021dec_int8.onnx
```

File NPZ lama dibaca dengan `allow_pickle=False`; key `embeddings` diutamakan.
Semua embedding lama dinormalisasi untuk cosine similarity dan file asal tidak ditulis.
Format lama tidak menyimpan identitas model. Kesamaan model harus dipastikan tim HW.
Pendaftaran baru lewat widget masuk ke `/var/lib/xploria/faces/faces.npz`.
Tombol Hapus hanya menghapus NPZ yang dibuat aplikasi; NPZ tim HW tetap tersimpan dan
akan tetap dipakai untuk pengenalan selama folder lama dikonfigurasi.

## Coba

```bash
sudo systemctl daemon-reload
sudo systemctl restart xploria-daemon
sudo journalctl -u xploria-daemon -f
```

1. Hubungkan Flutter ke WebSocket Pi, tambahkan block kamera lalu widget kamera IoT Lab.
2. Klik Foto: wajah harus terlihat dalam JPEG.
3. Klik Daftar, isi nama, hadapkan satu wajah ke kamera. Tunggu konfirmasi server.
4. Klik Kenali: nama cocok atau “Wajah tidak dikenali”; uji orang lain juga.
5. Restart daemon lalu Kenali lagi untuk memeriksa persistensi dataset.
6. Uji block: `face.enroll('Andi')`, lalu `face.is_recognized()` dan `face.get_recognized_name()`.
7. Uji cabut UART, gambar gelap, dua wajah, Stop dan dua permintaan bersamaan.
8. Uji kembali servo, DHT22, speech input, dan Hospital untuk regresi pada hardware.

`is_recognized()` mengambil foto baru setiap pemanggilan. `get_recognized_name()` memakai hasil terakhir
dalam eksekusi program yang sama; jika belum ada hasil, ia mengenali foto baru.
`capture_snapshot()` hanya mengambil foto; bukan pengenalan wajah.
Jangan meletakkan enroll dalam loop selamanya. Beri jeda beberapa detik jika mengenali berulang.
IoT Lab tidak memasukkan kamera ke polling telemetry otomatis.

## Data dan perilaku gagal

NPZ aplikasi dibuat otomatis pada pendaftaran pertama. Schema 1: `names` Unicode, `embeddings` float32
ternormalisasi, `model_id` SHA256 model SFace, `schema` integer. Dibaca dengan `allow_pickle=False`.
Dataset aplikasi beda model/rusak ditolak tanpa ditimpa. File baru ditulis sementara lalu diganti secara atomik.
Cadangkan `faces.npz` sebelum menghapus data atau mengganti model. Folder `/var/lib` terpisah dari git pull.

Cosine threshold awal 0.363 mengikuti contoh OpenCV; wajib kalibrasi dengan kamera/lokasi sebenarnya.
Similarity bukan persentase kepastian. Acuan API/model: https://docs.opencv.org/4.x/d0/dd4/tutorial_dnn_face.html

Operasi kamera dikerjakan di worker, bukan memblokir penerimaan WebSocket. Satu lock melindungi UART,
engine dan dataset; pemanggilan bersamaan mendapat pesan sibuk. Hasil dikirim ke koneksi peminta saja.
Stop/disconnect memberi tanda pembatalan; pembacaan UART memeriksa tanda itu. Inferensi OpenCV yang
sedang berlangsung selesai dahulu, tetapi hasil tidak dikirim sesudah dibatalkan.
Error dependensi, model atau kamera diteruskan ke widget/program; tidak ada sukses palsu.

Jalur kontrol belum menambahkan autentikasi WebSocket. Gunakan jaringan lab yang dipercaya.
Belum ada pemisahan dataset per siswa/proyek, liveness, multi-camera, atau panel hapus per nama.
