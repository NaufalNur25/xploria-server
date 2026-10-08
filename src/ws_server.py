import asyncio
import json
import logging
import sys
import types
from datetime import datetime, timezone
import websockets
import traceback

from hal import sensor, motor, led, rgb, ledstrip, power, rfid, telemetry, pin, audio, display, motion, lan, ai, hospital
from hal.sensor import stop_all_workers

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
    "hospital": HalProxy(hospital)
}

# Buat modul virtual 'xploria_hal' agar kode Blockly yang menggunakan
# 'from xploria_hal import sensor' (atau modul HAL lainnya) bisa resolve
# tanpa error ModuleNotFoundError.
_xploria_hal_module = types.ModuleType("xploria_hal")
for k, v in global_proxies.items():
    setattr(_xploria_hal_module, k, v)
sys.modules["xploria_hal"] = _xploria_hal_module

connected_clients = set()
subscribed_clients = set()

# Simpan referensi ke running event loop agar thread bisa mengirim ke queue dengan aman
_main_loop: asyncio.AbstractEventLoop = None


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

def execute_python_code(code_str, client_ws, loop):
    """Mengeksekusi raw Python code dan menangkap outputnya (streaming)."""
    
    # Flag to signal stopping — per-execution closure, tidak dishare
    setattr(client_ws, 'stop_requested', False)

    def check_stop():
        if getattr(client_ws, 'stop_requested', False):
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
    original_sleep = time.sleep

    def custom_sleep(secs):
        check_stop()
        if secs > 0.1:
            end_time = time.time() + secs
            while time.time() < end_time:
                check_stop()
                original_sleep(0.1)
        else:
            original_sleep(secs)
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
        "__builtins__": __builtins__,
        **local_proxies,
        "time": custom_time,
        "math": __import__("math"),
        "print": custom_print,
        "gpiod": gpiod,
        "board": board,
        "adafruit_dht": adafruit_dht,
    }

    try:
        exec(code_str, exec_globals)
        return {"type": "output", "payload": "\n[Proses Selesai]"}
    except StopExecution:
        return {"type": "output", "payload": "\n[Proses Dihentikan]"}
    except Exception:
        return {"type": "error", "payload": traceback.format_exc()}


async def handler(websocket):
    client_addr = websocket.remote_address
    logging.info(f"Client connected: {client_addr}")
    connected_clients.add(websocket)

    try:
        async for message in websocket:
            try:
                data = json.loads(message)

                if data.get("type") == "run":
                    code = data.get("code", "")
                    loop = asyncio.get_running_loop()

                    async def run_in_background():
                        setattr(websocket, 'stop_requested', False)
                        response = await asyncio.to_thread(execute_python_code, code, websocket, loop)
                        try:
                            await websocket.send(json.dumps(response))
                        except Exception:
                            pass

                    asyncio.create_task(run_in_background())
                    continue

                cmd = data.get("command")
                msg_type = data.get("type")

                if msg_type == "stop" or cmd == "stop":
                    setattr(websocket, 'stop_requested', True)
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

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        # Gunakan discard agar tidak raise KeyError jika client belum sempat ditambahkan
        connected_clients.discard(websocket)
        subscribed_clients.discard(websocket)
        if not subscribed_clients:
            telemetry.stop_stream()
        logging.info(f"Client disconnected: {client_addr}")


async def start_server(host="0.0.0.0", port=9002):
    global _main_loop
    _main_loop = asyncio.get_running_loop()
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
            stop_all_workers()
