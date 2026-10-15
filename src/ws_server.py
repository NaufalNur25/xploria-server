import asyncio
import base64
import os
import json
import logging
import re
import builtins
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import websockets
import traceback
import threading

from hal.hospital_widgets import HospitalWidgetSession

from hal import sensor, motor, led, rgb, ledstrip, power, rfid, telemetry, pin, audio, display, motion, lan, ai, hospital, voice
from hal.sensor import stop_all_workers
from hal import face

# Wrapper global untuk proxy
class HalProxy:
    def __init__(self, target, check_stop_func=None):
        self.target = target
        self.check_stop_func = check_stop_func

    def __getattr__(self, name):
        attr = getattr(self.target, name)
        if callable(attr):
            def wrapper(*args, **kwargs):
                if self.check_stop_func:
                    self.check_stop_func()
                return attr(*args, **kwargs)
            return wrapper
        return attr

# Kita simpan global proxy instances, check_stop_func akan diset saat eksekusi
global_proxies = {
    "sensor": HalProxy(sensor),
    "motor": HalProxy(motor),
    "led": HalProxy(led),
    "rgb": HalProxy(rgb),
    "ledstrip": HalProxy(ledstrip),
    "power": HalProxy(power),
    "rfid": HalProxy(rfid),
    "telemetry": HalProxy(telemetry),
    "pin": HalProxy(pin),
    "audio": HalProxy(audio),
    "display": HalProxy(display),
    "motion": HalProxy(motion),
    "lan": HalProxy(lan),
    "ai": HalProxy(ai),
    "hospital": HalProxy(hospital),
    "voice": HalProxy(voice),
    "face": HalProxy(face)
}

# Buat modul virtual 'xploria_hal' agar kode Blockly yang menggunakan
# 'from xploria_hal import sensor' (atau modul HAL lainnya) bisa resolve
# tanpa error ModuleNotFoundError.
_xploria_hal_module = types.ModuleType("xploria_hal")
for k, v in global_proxies.items():
    setattr(_xploria_hal_module, k, v)
sys.modules["xploria_hal"] = _xploria_hal_module

connected_clients = set()

# Global execution tracker untuk membunuh zombie thread secara server-wide
_global_execution_lock = threading.Lock()
_global_primary_execution = None
_global_telemetry_execution = None

def stop_execution_global(target):
    if target is not None:
        target["stop"].set()
        if target["runtime"] is not None:
            target["runtime"].stop()

# Simpan referensi ke running event loop agar thread bisa mengirim ke queue dengan aman
_main_loop: asyncio.AbstractEventLoop = None

# Pool khusus program pengguna: terpisah dari default executor asyncio sehingga
# program yang macet tidak menghalangi asyncio.to_thread milik bagian lain
# (mis. kontrol servo) dan jumlah program serentak dibatasi.
USER_EXECUTOR_WORKERS = 4
_user_executor = None
_user_executor_lock = threading.Lock()

# --- Batas unggah audio rekaman siswa (Pi 3B, multi-client) ---
# Frame WebSocket dibatasi 1 MiB (max_size di start_server); base64 menggembung 4/3,
# sehingga payload audio maksimum praktis ~768 KB. Gerbang di sini lebih ketat (~512 KB
# audio = ~16 detik PCM 16kHz mono) dan dicek SEBELUM decode.
MAX_UPLOAD_B64_CHARS = 700_000
# Hanya 1 upload diproses serentak di seluruh klien; sisanya antre tanpa memblokir event loop.
_audio_upload_semaphore: "asyncio.Semaphore" = None


def _store_uploaded_audio(slot: str, base64_data: str):
    """Jalan di worker thread: decode base64, lewati penulisan bila isi identik.

    Mengembalikan (path, changed). Dedupe mencegah tulis ulang + churn LRU ketika
    banyak klien/penekanan 'Run' berulang mengirim rekaman yang sama.
    """
    audio_bytes = base64.b64decode(base64_data.strip())
    existing = audio._resolve_custom_path(slot)
    try:
        if os.path.exists(existing) and os.path.getsize(existing) == len(audio_bytes):
            with open(existing, "rb") as f:
                if f.read() == audio_bytes:
                    return str(existing), False
    except OSError:
        pass
    return str(audio.save_custom_audio(slot, audio_bytes)), True


def get_user_executor():
    global _user_executor
    with _user_executor_lock:
        if _user_executor is None:
            _user_executor = ThreadPoolExecutor(
                max_workers=USER_EXECUTOR_WORKERS,
                thread_name_prefix="xploria-user",
            )
        return _user_executor


def shutdown_user_executor():
    """Hentikan semua program pengguna lalu tutup pool tanpa menunggu thread macet."""
    global _user_executor, _global_primary_execution, _global_telemetry_execution
    with _global_execution_lock:
        stop_execution_global(_global_primary_execution)
        stop_execution_global(_global_telemetry_execution)
        _global_primary_execution = None
        _global_telemetry_execution = None
    with _user_executor_lock:
        executor, _user_executor = _user_executor, None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)


async def adhoc_telemetry_loop():
    """Kirim pesan ad-hoc (delta) dari Blockly (telemetry.send()) ke semua klien.
    Jika antrean kosong selama 10 detik, kirim heartbeat agar koneksi WebSocket tetap hidup.
    """
    telemetry._ensure_queue()
    if not getattr(telemetry, '_queue', None):
        logging.warning("adhoc_telemetry_loop: queue not available, telemetry disabled")
        return

    while True:
        try:
            # Tunggu data masuk antrean dengan timeout 10 detik
            msg = await asyncio.wait_for(telemetry._queue.get(), timeout=10.0)
            if connected_clients:
                websockets.broadcast(connected_clients, msg)
            telemetry._queue.task_done()
        except asyncio.TimeoutError:
            # Tidak ada data telemetry selama 10 detik, kirim heartbeat
            if connected_clients:
                heartbeat_msg = json.dumps({
                    "type": "telemetry_heartbeat",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                websockets.broadcast(connected_clients, heartbeat_msg)
        except Exception as e:
            logging.error(f"Error in adhoc_telemetry_loop: {e}")
            await asyncio.sleep(1)

class StopExecution(Exception):
    pass

def reject_json_constant(value):
    raise ValueError("Angka JSON tidak valid: " + value)


def unescape_single_line_code(code_str):
    """Kode lama dikirim sebagai satu baris dengan '\\n' literal.

    Hanya kode satu baris yang di-unescape. Kode multi-baris sudah benar, dan
    '\\n' di dalam string-nya (mis. split('\\n')) tidak boleh diubah menjadi
    baris baru karena merusak literal string.
    """
    if not isinstance(code_str, str) or "\n" in code_str:
        return code_str
    return (code_str.replace("\\n", "\n")
                    .replace("\\r", "\r")
                    .replace("\\t", "\t"))


def _release_global_execution(stop_event):
    """Kosongkan pelacak global hanya bila masih milik eksekusi ini."""
    global _global_primary_execution, _global_telemetry_execution
    with _global_execution_lock:
        if _global_primary_execution and _global_primary_execution["stop"] is stop_event:
            _global_primary_execution = None
        if _global_telemetry_execution and _global_telemetry_execution["stop"] is stop_event:
            _global_telemetry_execution = None


def execute_python_code(code_str, client_ws, loop, stop_event=None, widget_session=None):
    """Mengeksekusi raw Python code dan menangkap outputnya (streaming)."""
    code_str = unescape_single_line_code(code_str)

    stop_event = stop_event or threading.Event()

    def check_stop():
        if stop_event.is_set():
            raise StopExecution("Execution stopped by user")

    def custom_print(*args, **kwargs):
        check_stop()
        sep = kwargs.get('sep', ' ')
        end = kwargs.get('end', '\n')
        msg = sep.join(str(a) for a in args) + end

        payload = json.dumps({"type": "output", "payload": msg})
        try:
            asyncio.run_coroutine_threadsafe(client_ws.send(payload), loop)
        except Exception:
            pass

        import time as _time
        _time.sleep(0.05)

    import time

    def custom_sleep(secs):
        check_stop()
        if stop_event.wait(max(0, secs)):
            check_stop()
        check_stop()

    # Buat modul virtual time kustom agar sleep bisa di-intercept
    custom_time = types.ModuleType("time")
    custom_time.__dict__.update(time.__dict__)
    custom_time.sleep = custom_sleep

    # Buat proxy lokal untuk execution ini agar stop signal terisolasi per-client
    local_proxies = {}
    for k, proxy in global_proxies.items():
        local_proxy = HalProxy(proxy.target, check_stop)
        local_proxies[k] = local_proxy

    # Pre-import modul yang sering dipakai Blockly/Custom Code
    try: import gpiod
    except ImportError: gpiod = None
    try: import board
    except ImportError: board = None
    try: import adafruit_dht
    except ImportError: adafruit_dht = None

    exec_globals = {
        "__builtins__": None,
        **local_proxies,
        "time": custom_time,
        "math": __import__("math"),
        "print": custom_print,
        "gpiod": gpiod,
        "board": board,
        "adafruit_dht": adafruit_dht,
    }

    if widget_session is not None:
        widget_session._sleep = custom_sleep
        exec_globals["hospital"] = HalProxy(widget_session, check_stop)

    # 'import time' / 'from xploria_hal import ...' di dalam program siswa
    # biasanya melewati nama global di atas dan mengambil modul asli dari
    # sys.modules (tanpa pemeriksaan stop). __import__ lokal ini mengarahkan
    # keduanya ke versi per-eksekusi sehingga loop bisa dihentikan.
    local_hal_module = types.ModuleType("xploria_hal")
    for name, proxy in local_proxies.items():
        setattr(local_hal_module, name, exec_globals.get(name, proxy))

    real_import = builtins.__import__

    def local_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0:
            if name == "xploria_hal":
                return local_hal_module
            if name == "time":
                return custom_time
        return real_import(name, globals, locals, fromlist, level)

    local_builtins = dict(vars(builtins))
    local_builtins["__import__"] = local_import
    exec_globals["__builtins__"] = local_builtins

    try:
        check_stop()
        def emit_camera(packet):
            asyncio.run_coroutine_threadsafe(client_ws.send(json.dumps(packet)), loop)
        with face.session(emit_camera, stop_event):
            exec(code_str, exec_globals)
        if widget_session is not None and (widget_session.handlers or widget_session.forms):
            widget_session.run()
        check_stop()
        return {"type": "output", "payload": "\n[Proses Selesai]"}
    except StopExecution:
        return {"type": "output", "payload": "\n[Proses Dihentikan]"}
    except Exception as error:
        if widget_session is not None and widget_session.active:
            widget_session.emit("error", message=str(error))
        return {"type": "error", "payload": traceback.format_exc()}
    finally:
        if widget_session is not None:
            widget_session.close()
        _release_global_execution(stop_event)
        # Putuskan referensi (proxy HAL, widget_session, closure) agar tidak
        # tertahan setelah program selesai.
        exec_globals.clear()


async def handler(websocket):
    global _global_primary_execution, _global_telemetry_execution
    client_addr = websocket.remote_address
    logging.info(f"Client connected: {client_addr}")
    connected_clients.add(websocket)
    execution = None
    telemetry_execution = None
    executions = set()
    tasks = set()
    camera_stop = None

    async def camera_job(data, stopped):
        loop = asyncio.get_running_loop()
        def emit(packet):
            asyncio.run_coroutine_threadsafe(websocket.send(json.dumps(packet)), loop)
        def work():
            with face.session(emit, stopped, 'widget', data.get('request_id'), data.get('block_uid')):
                try:
                    face.perform(data.get('command'), data.get('value'))
                except Exception:
                    pass  # face.perform already returns a correlated error packet.
        await asyncio.to_thread(work)

    def stop_execution(target):
        if target is not None:
            target["stop"].set()
            if target["runtime"] is not None:
                target["runtime"].stop()

    def current_runtime(data):
        runtime = execution["runtime"] if execution else None
        if runtime is None or not runtime.active or data.get("project_id") != runtime.project_id or data.get("session_id") != runtime.session_id:
            raise ValueError("Proyek atau sesi program tidak aktif pada koneksi ini.")
        return runtime

    async def run_in_background(code, target):
        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                get_user_executor(), execute_python_code,
                code, websocket, loop, target["stop"], target["runtime"],
            )
            await websocket.send(json.dumps(response))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            executions.discard(target["stop"])


    try:
        async for message in websocket:
            data = None
            try:
                data = json.loads(message, parse_constant=reject_json_constant)

                if not isinstance(data, dict):
                    raise ValueError("Pesan harus berupa objek JSON.")
                if data.get("type") == "capabilities":
                    await websocket.send(json.dumps({"type": "capabilities", "request_id": data.get("request_id"), "hospital_widgets": 1, "voice_commands": 1, "actuator_control": 1}))
                    continue

                if data.get("type") == "run":
                    code = data.get("code", "")
                    if not isinstance(code, str):
                        raise ValueError("Program harus berupa string Python.")
                    metadata = data.get("widget_session")
                    runtime = None
                    if metadata is not None:
                        if not isinstance(metadata, dict) or metadata.get("protocol_version") != 1:
                            raise ValueError("Versi protokol Hospital tidak didukung.")
                        for key in ("project_id", "session_id"):
                            if not isinstance(metadata.get(key), str) or not metadata[key]:
                                raise ValueError(key + " diperlukan.")
                        sources = metadata.get("sources")
                        snapshot = metadata.get("snapshot", {})
                        version = metadata.get("snapshot_version", 0)
                        if not isinstance(sources, list) or any(not isinstance(uid, str) or not uid for uid in sources) or not isinstance(snapshot, dict) or isinstance(version, bool) or not isinstance(version, int) or version < 0:
                            raise ValueError("Metadata program tidak valid.")
                        loop = asyncio.get_running_loop()
                        def send_widget(**packet):
                            payload = json.dumps({"type": "telemetry", "telemetry": packet}, ensure_ascii=False, allow_nan=False)
                            asyncio.run_coroutine_threadsafe(websocket.send(payload), loop)
                        runtime = HospitalWidgetSession(metadata["project_id"], metadata["session_id"], snapshot, send_widget, lambda _: None, sources, hospital)
                        runtime.data_version = version
                    execution_role = data.get("execution_role", "primary")
                    if execution_role not in ("primary", "telemetry"):
                        raise ValueError("Peran eksekusi tidak didukung.")
                    target = {"stop": threading.Event(), "runtime": runtime, "role": execution_role}
                    with _global_execution_lock:
                        if execution_role == "telemetry":
                            stop_execution_global(_global_telemetry_execution)
                            _global_telemetry_execution = target
                            telemetry_execution = target
                        else:
                            stop_execution_global(_global_primary_execution)
                            voice.clear()
                            _global_primary_execution = target
                            execution = target
                    executions.add(target["stop"])
                    task = asyncio.create_task(run_in_background(code, target))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                    continue

                if data.get("type") == "hospital_widget_event":
                    runtime = current_runtime(data)
                    status = runtime.accept_event(data)
                    await websocket.send(json.dumps({"type": "telemetry", "telemetry": {
                        "action": "hospital_widget", "kind": "event_ack", "project_id": runtime.project_id,
                        "session_id": runtime.session_id, "block_uid": data.get("source_uid"),
                        "event_id": data.get("event_id"), "status": status}}))
                    continue

                if data.get("type") == "hospital_widget_result":
                    runtime = current_runtime(data)
                    if not isinstance(data.get("result"), dict):
                        raise ValueError("Hasil penyimpanan harus berupa objek.")
                    runtime.accept_result(data.get("request_id"), data["result"])
                    continue

                cmd = data.get("command")
                msg_type = data.get("type")

                if msg_type == "upload_audio":
                    slot = str(data.get("slot", "slot_1")).lower().strip()
                    base64_data = data.get("data", "")
                    if not isinstance(base64_data, str):
                        base64_data = ""
                    if "," in base64_data[:128]:
                        base64_data = base64_data.split(",", 1)[1]
                    base64_data = base64_data.strip()
                    try:
                        if not re.match(r"^[a-zA-Z0-9_\-]+$", slot):
                            raise ValueError(f"Nama slot '{slot}' tidak valid. Hanya alfanumerik, underscore, dan dash yang diizinkan.")
                        # Gerbang murah SEBELUM decode: tolak payload raksasa tanpa memakan CPU/RAM.
                        if len(base64_data) > MAX_UPLOAD_B64_CHARS:
                            raise ValueError("Ukuran audio melebihi batas unggah.")
                        # Decode + tulis file di worker thread (bukan event loop) dan dibatasi
                        # 1 upload serentak agar multi-client tidak membuat telemetry/servo lag.
                        async with _audio_upload_semaphore:
                            saved_path, changed = await asyncio.to_thread(
                                _store_uploaded_audio, slot, base64_data
                            )
                        logging.info(f"[AudioWS] Upload slot '{slot}' berhasil: {saved_path} (changed={changed}, clients={len(connected_clients)})")
                        response = {
                            "type": "audio_upload_result",
                            "slot": slot,
                            "status": "ok",
                            "unchanged": not changed,
                            "client_count": len(connected_clients),
                            "message": f"Audio {slot} {'berhasil disimpan' if changed else 'sudah up-to-date'}",
                            "path": saved_path,
                        }
                    except Exception as e:
                        logging.error(f"[AudioWS] Gagal memproses upload slot '{slot}': {e}")
                        response = {
                            "type": "audio_upload_result",
                            "slot": slot,
                            "status": "error",
                            "message": f"Gagal menyimpan audio: {e}",
                        }
                    await websocket.send(json.dumps(response))
                    continue

                if msg_type == "voice_command":
                    request_id = data.get("request_id")
                    if data.get("is_final") is False:
                        response = {
                            "type": "voice_result",
                            "request_id": request_id,
                            "status": "ignored_partial",
                        }
                    else:
                        spoken_text = data.get("text", "")
                        if not isinstance(spoken_text, str) or not spoken_text.strip():
                            response = {
                                "type": "voice_result",
                                "request_id": request_id,
                                "status": "error",
                                "message": "Voice text must be a non-empty string",
                            }
                        elif len(spoken_text) > 500:
                            response = {
                                "type": "voice_result",
                                "request_id": request_id,
                                "status": "error",
                                "message": "Voice text is too long",
                            }
                        else:
                            normalized = voice.set_voice_text(
                                spoken_text,
                                request_id=request_id,
                            )
                            response = {
                                "type": "voice_result",
                                "request_id": request_id,
                                "status": "stored",
                                "normalized_text": normalized,
                            }
                    await websocket.send(json.dumps(response))
                    continue

                if msg_type == "control" and data.get("hw_type") == "esp32_cam":
                    if not isinstance(data.get("request_id"), str) or not data["request_id"]:
                        raise ValueError("request_id kamera diperlukan.")
                    if data.get("command") not in face.COMMANDS:
                        await websocket.send(json.dumps({"type": "camera_result",
                            "request_id": data["request_id"], "status": "error",
                            "message": "Perintah kamera tidak didukung."}))
                        continue
                    if camera_stop is not None and not camera_stop.is_set():
                        await websocket.send(json.dumps({"type": "camera_result",
                            "request_id": data["request_id"], "status": "error",
                            "message": "Kamera sedang digunakan."}))
                        continue
                    camera_stop = threading.Event()
                    task = asyncio.create_task(camera_job(dict(data), camera_stop))
                    task.add_done_callback(lambda _, event=camera_stop: event.set())
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                    continue

                # Metadata v2 pilot: only the Smart Home door-lock servo is
                # accepted here. Other actuators keep using their legacy path
                # until their device catalog entries are migrated.
                if msg_type == "control":
                    request_id = data.get("request_id")
                    block_uid = data.get("block_uid")
                    block_type = data.get("block_type")
                    device_key = data.get("device_key")
                    hw_type = data.get("hw_type")
                    channel = data.get("channel")
                    command = data.get("command")
                    value = data.get("value")

                    if not isinstance(request_id, str) or not request_id:
                        raise ValueError("request_id kontrol diperlukan.")
                    if not isinstance(block_uid, str) or not block_uid:
                        raise ValueError("block_uid kontrol diperlukan.")

                    if (block_type, device_key, hw_type, channel, command) != (
                        "sh_door_lock", "servo.door_lock", "servo",
                        "lock_state", "set_lock_state"
                    ):
                        response = {
                            "type": "control_result",
                            "request_id": request_id,
                            "block_uid": block_uid,
                            "device_key": device_key,
                            "status": "error",
                            "message": "Perangkat atau perintah kontrol belum didukung.",
                        }
                        await websocket.send(json.dumps(response))
                        continue

                    if isinstance(value, bool):
                        is_open = value
                    elif isinstance(value, (int, float)) and value in (0, 1):
                        is_open = value == 1
                    elif isinstance(value, str) and value.upper() in ("OPEN", "LOCK"):
                        is_open = value.upper() == "OPEN"
                    else:
                        response = {
                            "type": "control_result",
                            "request_id": request_id,
                            "block_uid": block_uid,
                            "device_key": device_key,
                            "status": "error",
                            "message": "Nilai kunci pintu harus OPEN/LOCK atau 1/0.",
                        }
                        await websocket.send(json.dumps(response))
                        continue

                    speed = 100 if is_open else -100
                    await asyncio.to_thread(motor.set_servo360, 12, speed, 1.0)
                    normalized_value = 1 if is_open else 0
                    await websocket.send(json.dumps({
                        "type": "control_result",
                        "request_id": request_id,
                        "block_uid": block_uid,
                        "device_key": device_key,
                        "status": "ok",
                        "value": normalized_value,
                    }))
                    await websocket.send(json.dumps({
                        "type": "telemetry_delta",
                        "telemetry": {
                            "servo.door_lock.lock_state": normalized_value,
                        },
                    }))
                    continue

                if msg_type == "stop" or cmd == "stop":
                    if camera_stop is not None:
                        camera_stop.set()
                    if "session_id" in data or "project_id" in data:
                        current_runtime(data)
                    with _global_execution_lock:
                        if data.get("execution_role") == "telemetry":
                            stop_execution_global(_global_telemetry_execution)
                            _global_telemetry_execution = None
                        else:
                            stop_execution_global(_global_primary_execution)
                            _global_primary_execution = None
                            voice.clear()
                            audio.stop()
                    response = {"type": "ack", "command": "stop", "status": "ok", "message": "Stop signal sent"}
                    await websocket.send(json.dumps(response))
                    continue

                if cmd == "subscribe_telemetry" or msg_type == "subscribe_telemetry":
                    response = {"type": "ack", "command": "subscribe_telemetry", "status": "ok", "message": "Deprecated: Server runs in Pure HAL mode."}
                    await websocket.send(json.dumps(response))
                    continue
                elif cmd == "unsubscribe_telemetry" or msg_type == "unsubscribe_telemetry":
                    response = {"type": "ack", "command": "unsubscribe_telemetry", "status": "ok", "message": "Deprecated: Server runs in Pure HAL mode."}
                    await websocket.send(json.dumps(response))
                    continue

                if msg_type == "pin_mapping" or cmd == "pin_mapping":
                    action = data.get("action")
                    if action == "reload":
                        try:
                            from hal.core import reload_pin_map
                            reload_pin_map()
                            response = {"type": "ack", "command": "pin_mapping", "action": "reload", "status": "ok"}
                        except Exception as e:
                            response = {"type": "ack", "command": "pin_mapping", "action": "reload", "status": "error", "message": str(e)}
                        await websocket.send(json.dumps(response))
                    elif action == "set":
                        logical = data.get("logical_pin")
                        physical = data.get("physical_pin")
                        desc = data.get("description", "")
                        try:
                            from database import update_pin_mapping
                            update_pin_mapping(int(logical), int(physical), desc)
                            from hal.core import reload_pin_map
                            reload_pin_map()
                            response = {"type": "ack", "command": "pin_mapping", "action": "set", "status": "ok"}
                        except Exception as e:
                            response = {"type": "ack", "command": "pin_mapping", "action": "set", "status": "error", "message": str(e)}
                        await websocket.send(json.dumps(response))
                    elif action == "list":
                        try:
                            from database import get_all_pin_mappings
                            mappings = get_all_pin_mappings()
                            response = {"type": "pin_mapping_list", "data": mappings}
                        except Exception as e:
                            response = {"type": "error", "message": str(e)}
                        await websocket.send(json.dumps(response))
                    continue

                response = {"type": "ack", "command": data.get("command", "unknown"), "status": "error", "message": "Unknown command"}
                await websocket.send(json.dumps(response))

            except json.JSONDecodeError:
                pass
            except Exception as e:
                logging.error(f"Error handling message: {e}")
                if isinstance(data, dict) and data.get("type") == "hospital_widget_event":
                    packet = {"action": "hospital_widget", "kind": "event_ack", "status": "rejected",
                              "project_id": data.get("project_id"), "session_id": data.get("session_id"),
                              "block_uid": data.get("source_uid"), "event_id": data.get("event_id"), "message": str(e)}
                    await websocket.send(json.dumps({"type": "telemetry", "telemetry": packet}))
                else:
                    await websocket.send(json.dumps({"type": "error", "payload": str(e)}))

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        # Gunakan discard agar tidak raise KeyError jika client belum sempat ditambahkan
        if camera_stop is not None:
            camera_stop.set()
        stop_execution(execution)
        stop_execution(telemetry_execution)
        for stop_event in executions:
            stop_event.set()
        connected_clients.discard(websocket)
        logging.info(f"Client disconnected: {client_addr}")


async def start_server(host="0.0.0.0", port=9002):
    global _main_loop, _audio_upload_semaphore
    _main_loop = asyncio.get_running_loop()
    _audio_upload_semaphore = asyncio.Semaphore(1)
    telemetry._ensure_queue()
    telemetry._loop = _main_loop  # Simpan loop reference untuk thread-safe queue access

    logging.info(f"Starting Xploria Raspberry Pi Daemon on ws://{host}:{port}")

    # Buat server dulu, lalu jalankan background tasks di dalam context server
    async with websockets.serve(handler, host, port, max_size=1_048_576):
        logging.info(f"server listening on {host}:{port}")
        adhoc_task = asyncio.create_task(adhoc_telemetry_loop())
        try:
            await asyncio.Future()  # Run forever
        finally:
            adhoc_task.cancel()
            try:
                await asyncio.gather(adhoc_task, return_exceptions=True)
            except Exception:
                pass
            shutdown_user_executor()
            stop_all_workers()
