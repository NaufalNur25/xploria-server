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

try:
    from database import init_db, get_all_pin_mappings
    init_db()
    _PIN_MAP = get_all_pin_mappings()
except ImportError:
    try:
        from src.database import init_db, get_all_pin_mappings
        init_db()
        _PIN_MAP = get_all_pin_mappings()
    except ImportError:
        _PIN_MAP = {}
        print("[xploria_hal] WARNING: database module tidak ditemukan. _PIN_MAP kosong.", file=sys.stderr)

_chips = {}

def reload_pin_map():
    global _PIN_MAP
    try:
        from database import get_all_pin_mappings
        _PIN_MAP = get_all_pin_mappings()
        print(f"[xploria_hal] _PIN_MAP reloaded: {_PIN_MAP}")
    except ImportError:
        try:
            from src.database import get_all_pin_mappings
            _PIN_MAP = get_all_pin_mappings()
            print(f"[xploria_hal] _PIN_MAP reloaded: {_PIN_MAP}")
        except ImportError:
            pass

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
