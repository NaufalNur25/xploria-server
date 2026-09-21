import sys
import time
import atexit
import signal
import warnings

warnings.simplefilter('ignore')

try:
    import lgpio as _gpio
except ImportError:
    _gpio = None
    print("[xploria_hal] WARNING: lgpio tidak ditemukan - GPIO fisik tidak akan berfungsi.", file=sys.stderr)

_PIN_MAP = {}
_chips = {}

def get_gpio(p):
    if not _gpio:
        return None, None
    gpio = _PIN_MAP.get(int(p), int(p))
    chip_idx = 1 if gpio >= 352 else 0
    offset = gpio - 352 if chip_idx == 1 else gpio
    
    if chip_idx not in _chips:
        try:
            _chips[chip_idx] = _gpio.gpiochip_open(chip_idx)
        except Exception:
            return None, None
            
    return _chips[chip_idx], offset

def cleanup_gpio():
    if not _gpio:
        return
    for c in _chips.values():
        try:
            _gpio.gpiochip_close(c)
        except Exception:
            pass
    _chips.clear()

atexit.register(cleanup_gpio)

def _sig_handler(sig, frame):
    cleanup_gpio()
    sys.exit(0)

signal.signal(signal.SIGTERM, _sig_handler)
signal.signal(signal.SIGINT, _sig_handler)

def get_gpio_lib():
    return _gpio
