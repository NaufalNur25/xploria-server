import time
from .pin import PinHAL

class LEDHAL(PinHAL):
    def __init__(self):
        super().__init__()
        self._brightness = 100
        self._led_pins = {1: 17, 2: 27, 3: 22}

    def _resolve_targets(self, target):
        if str(target) == "ALL":
            return list(self._led_pins.keys())
        return [int(target)]

    def display_color(self, target, color, secs=None):
        for t in self._resolve_targets(target):
            p = self._led_pins.get(t, t)
            self.set_digital(p, "HIGH" if color != "black" else "LOW")
            
        if secs is not None:
            time.sleep(secs)
            for t in self._resolve_targets(target):
                p = self._led_pins.get(t, t)
                self.set_digital(p, "LOW")

    def turn_off(self, target):
        for t in self._resolve_targets(target):
            p = self._led_pins.get(t, t)
            self.set_digital(p, "LOW")
