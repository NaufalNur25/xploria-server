import asyncio
import json
import logging
import sys
import types
from datetime import datetime, timezone
import websockets
import traceback

from hal import sensor, motor, led, power, rfid, telemetry, pin, audio, display, motion, lan, ai

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
    "power": HalProxy(power),
    "rfid": HalProxy(rfid),
    "telemetry": HalProxy(telemetry),
    "pin": HalProxy(pin),
    "audio": HalProxy(audio),
    "display": HalProxy(display),
    "motion": HalProxy(motion),
    "lan": HalProxy(lan),
    "ai": HalProxy(ai)
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

async def push_telemetry_loop(interval=1.0):
    """Loop for periodically pushing real sensor data to subscribed clients."""
    while True:
        # Check if flutter explicitly started it or if they subscribed
        if subscribed_clients and getattr(telemetry, '_running', True):
            try:
                house_power = power.read_house_power()
                solar_power = power.read_solar_power()

                telemetry_data = {
                    "temperature": sensor.read_temperature(4),
                    "humidity": sensor.read_humidity(4),
                    "gas": sensor.read_gas(),
                    "light": sensor.read_light(),
                    "motion_pir1": sensor.read_motion(17),
                    "motion_pir2": sensor.read_motion(27),
                    "distance_cm": sensor.read_ultrasonic(23, 24),
                    "house_power": house_power,
                    "solar_power": solar_power,
                    "rfid_uid": rfid.read_uid()
                }

                payload = {
                    "type": "telemetry",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "telemetry": telemetry_data
                }
                
                msg = json.dumps(payload)
                websockets.broadcast(subscribed_clients, msg)
                
            except Exception as e:
                logging.error(f"Error gathering/sending telemetry: {e}")
                
        await asyncio.sleep(interval)

async def adhoc_telemetry_loop():
    telemetry._ensure_queue()
    if not getattr(telemetry, '_queue', None):
        return
        
    while True:
        msg = await telemetry._queue.get()
        if connected_clients:
            websockets.broadcast(connected_clients, msg)
        telemetry._queue.task_done()

class StopExecution(Exception):
    pass

def execute_python_code(code_str, client_ws, loop):
    """Mengeksekusi raw Python code dan menangkap outputnya (streaming)."""
    
    # Flag to signal stopping
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
        
        import time
        time.sleep(0.05)
        
    import time
    original_sleep = time.sleep
    
    def custom_sleep(secs):
        check_stop()
        # Jika sleep-nya panjang, kita bagi-bagi agar bisa di-interupsi
        if secs > 0.1:
            end_time = time.time() + secs
            while time.time() < end_time:
                check_stop()
                original_sleep(0.1)
        else:
            original_sleep(secs)
        check_stop()

    # Buat modul virtual time kustom agar sleep bisa di-intercept
    import types
    custom_time = types.ModuleType("time")
    custom_time.__dict__.update(time.__dict__)
    custom_time.sleep = custom_sleep
    
    # Set the check_stop function for all proxies during this execution
    for proxy in global_proxies.values():
        proxy.check_stop_func = check_stop

    exec_globals = {
        "__builtins__": __builtins__,
        **global_proxies,
        "time": custom_time,
        "math": __import__("math"),
        "print": custom_print,
    }
    
    try:
        exec(code_str, exec_globals)
        return {"type": "output", "payload": "\n[Proses Selesai]"}
    except StopExecution:
        return {"type": "output", "payload": "\n[Proses Dihentikan]"}
    except Exception as e:
        return {"type": "error", "payload": traceback.format_exc()}
    finally:
        # Bersihkan reference
        for proxy in global_proxies.values():
            proxy.check_stop_func = None


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
                    
                    # Fungsi untuk menjalankan eksekusi dan mengirim hasil akhir
                    async def run_in_background():
                        # Pastikan flag reset saat mulai
                        setattr(websocket, 'stop_requested', False)
                        response = await asyncio.to_thread(execute_python_code, code, websocket, loop)
                        try:
                            await websocket.send(json.dumps(response))
                        except Exception:
                            pass
                            
                    # Spawn sebagai task agar TIDAK MEMBLOKIR pembacaan pesan websocket (seperti "stop")
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
                    subscribed_clients.add(websocket)
                    # Automatically set telemetry flag to true
                    telemetry.start_stream() 
                    response = {"type": "ack", "command": "subscribe_telemetry", "status": "ok", "message": "Telemetry subscribed"}
                    await websocket.send(json.dumps(response))
                    continue
                elif cmd == "unsubscribe_telemetry" or msg_type == "unsubscribe_telemetry":
                    subscribed_clients.discard(websocket)
                    response = {"type": "ack", "command": "unsubscribe_telemetry", "status": "ok"}
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
        connected_clients.remove(websocket)
        subscribed_clients.discard(websocket)
        logging.info(f"Client disconnected: {client_addr}")

async def start_server(host="0.0.0.0", port=9002):
    telemetry._ensure_queue()
    
    asyncio.create_task(push_telemetry_loop())
    asyncio.create_task(adhoc_telemetry_loop())
    
    logging.info(f"Starting Xploria Raspberry Pi Daemon on ws://{host}:{port}")
    async with websockets.serve(handler, host, port):
        await asyncio.Future()
