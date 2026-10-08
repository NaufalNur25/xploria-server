import time
import logging
from .pin import PinHAL

logger = logging.getLogger(__name__)

COLOR_MAP = {
    "red":    (1, 0, 0),
    "green":  (0, 1, 0),
    "blue":   (0, 0, 1),
    "yellow": (1, 1, 0),
    "purple": (1, 0, 1),
    "cyan":   (0, 1, 1),
    "white":  (1, 1, 1),
    "orange": (1, 1, 0),
    "black":  (0, 0, 0),
    "off":    (0, 0, 0)
}

class RGBHAL(PinHAL):
    def __init__(self, common_anode=True):
        super().__init__()
        self.common_anode = common_anode
        # Mapping target ID -> {Red, Green, Blue} GPIO Pin
        self._rgb_pins = {
            13: {"r": 13, "g": 19, "b": 26},  # Pintu Utama
            15: {"r": 15, "g": 18, "b": 23},  # Garasi
        }

    def set_color(self, target, color, secs=None):
        try:
            target_int = int(target)
        except (ValueError, TypeError):
            logger.warning(f"Invalid RGB target: {target}")
            return

        pins = self._rgb_pins.get(target_int)
        if not pins:
            logger.warning(f"RGB target {target_int} not found in pin configuration")
            return

        r_val, g_val, b_val = COLOR_MAP.get(str(color).lower(), (0, 0, 0))
        
        # Untuk Common Anode: 1 (aktif) -> LOW, 0 (nonaktif) -> HIGH
        if self.common_anode:
            self.set_digital(pins["r"], "LOW" if r_val else "HIGH")
            self.set_digital(pins["g"], "LOW" if g_val else "HIGH")
            self.set_digital(pins["b"], "LOW" if b_val else "HIGH")
        else:
            self.set_digital(pins["r"], "HIGH" if r_val else "LOW")
            self.set_digital(pins["g"], "HIGH" if g_val else "LOW")
            self.set_digital(pins["b"], "HIGH" if b_val else "LOW")
        
        logger.info(f"RGB LED [{target_int}] set to '{color}' (Common Anode: {self.common_anode})")
        
        from . import telemetry
        telemetry.send(**{f"rgb_{target_int}": color})

        if secs is not None:
            time.sleep(secs)
            self.set_color(target, "off")

    def turn_off(self, target):
        self.set_color(target, "off")
