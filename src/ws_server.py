import asyncio
import json
import logging
import sys
import types
from datetime import datetime, timezone
import websockets
import traceback

from hal import sensor, motor, led, power, rfid, telemetry, pin, audio, display, motion, lan, ai

# Buat modul virtual 'xploria_hal' agar kode Blockly yang menggunakan
# 'from xploria_hal import sensor' (atau modul HAL lainnya) bisa resolve
# tanpa error ModuleNotFoundError.
_xploria_hal_module = types.ModuleType("xploria_hal")
_xploria_hal_module.sensor    = sensor
_xploria_hal_module.motor     = motor
_xploria_hal_module.led       = led
_xploria_hal_module.power     = power
_xploria_hal_module.rfid      = rfid
_xploria_hal_module.telemetry = telemetry
_xploria_hal_module.pin       = pin
_xploria_hal_module.audio     = audio
_xploria_hal_module.display   = display
_xploria_hal_module.motion    = motion
_xploria_hal_module.lan       = lan
_xploria_hal_module.ai        = ai
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
                    "temperature": sensor.read_temperature(27),
                    "humidity": sensor.read_humidity(27),
                    "gas": sensor.read_gas(),
                    "light": sensor.read_light(),
                    "motion_pir1": sensor.read_motion(17),
                    "motion_pir2": sensor.read_motion(22), # dipindah sementara agar tidak conflict dengan DHT di 27
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

def execute_python_code(code_str, client_ws, loop):
    """Mengeksekusi raw Python code dan menangkap outputnya (streaming)."""
    def custom_print(*args, **kwargs):
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
        
    exec_globals = {
        "__builtins__": __builtins__,
        "sensor": sensor,
        "motor": motor,
        "led": led,
        "power": power,
        "rfid": rfid,
        "telemetry": telemetry,
        "pin": pin,
        "audio": audio,
        "display": display,
        "motion": motion,
        "lan": lan,
        "ai": ai,
        "time": __import__("time"),
        "math": __import__("math"),
        "print": custom_print,
    }
    
    try:
        exec(code_str, exec_globals)
        return {"type": "output", "payload": "\n[Proses Selesai]"}
    except Exception as e:
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
                    response = await asyncio.to_thread(execute_python_code, code, websocket, loop)
                    await websocket.send(json.dumps(response))
                    continue

                cmd = data.get("command")
                msg_type = data.get("type")
                
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

async def start_server(host="0.0.0.0", port=8765):
    telemetry._ensure_queue()
    
    asyncio.create_task(push_telemetry_loop())
    asyncio.create_task(adhoc_telemetry_loop())
    
    logging.info(f"Starting Xploria Raspberry Pi Daemon on ws://{host}:{port}")
    async with websockets.serve(handler, host, port):
        await asyncio.Future()
