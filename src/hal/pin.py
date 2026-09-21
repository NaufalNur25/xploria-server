import time
import sys
from .core import get_gpio, get_gpio_lib

class PinHAL:
    def __init__(self):
        self._out_pins = set()

    def _claim_out(self, chip, offset, p_name):
        _gpio = get_gpio_lib()
        if not _gpio: return
        
        err = None
        for _ in range(10):
            try:
                _gpio.gpio_claim_output(chip, offset)
                self._out_pins.add(p_name)
                return
            except Exception as e:
                err = e
                time.sleep(0.2)
        print(f"[xploria_hal] Failed to claim output pin {p_name}: {err}", file=sys.stderr)

    def set_digital(self, p, state):
        _gpio = get_gpio_lib()
        if not _gpio: return
        
        chip, offset = get_gpio(p)
        if not chip: return
        
        if p not in self._out_pins:
            self._claim_out(chip, offset, p)
            
        val = 1 if state == 'HIGH' else 0
        try:
            _gpio.gpio_write(chip, offset, val)
        except Exception:
            pass

    def set_analog(self, p, value):
        _gpio = get_gpio_lib()
        if not _gpio: return
        
        chip, offset = get_gpio(p)
        if not chip: return
        
        if p not in self._out_pins:
            self._claim_out(chip, offset, p)
            
        try:
            _gpio.tx_pwm(chip, offset, 100, max(0, min(100, int(value))))
        except Exception:
            pass

    def read_digital(self, p):
        _gpio = get_gpio_lib()
        if not _gpio: return 0
        
        chip, offset = get_gpio(p)
        if not chip: return 0
        
        try:
            _gpio.gpio_claim_input(chip, offset)
            return _gpio.gpio_read(chip, offset)
        except Exception:
            return 0

    def read_analog(self, p):
        # Raspbery Pi natively lacks Analog input without ADC
        return 0
