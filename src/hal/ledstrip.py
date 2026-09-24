import time
import logging
from .pin import PinHAL

logger = logging.getLogger(__name__)

# Import rpi_ws281x dengan penanganan error aman
try:
    from rpi_ws281x import PixelStrip, Color
except ImportError:
    PixelStrip = None
    Color = None
    logger.warning("rpi_ws281x tidak ditemukan. Fitur WS2812B LED strip dinonaktifkan.")

# Kamus warna standar
COLOR_PALETTE = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "purple": (128, 0, 128),
    "cyan": (0, 255, 255),
    "white": (255, 255, 255),
    "orange": (255, 100, 0),
    "pink": (255, 20, 147),
    "black": (0, 0, 0),
    "off": (0, 0, 0)
}

class LedStripHAL(PinHAL):
    def __init__(self):
        super().__init__()
        self._brightness = 100
        self._led_pins = {1: 17, 2: 27, 3: 22}  # Pin LED biasa

        # Properti untuk WS2812B NeoPixel Strip
        self._strip = None
        self._strip_pin = None
        self._strip_count = None

    # =========================================================================
    # 1. WS2812B / NEOPIXEL ADDRESSABLE LED STRIP
    # =========================================================================
    def init_strip(self, pin=18, count=8, brightness=255):
        """
        Inisialisasi LED Strip WS2812B:
        - pin        : Pin GPIO BCM (Rekomendasi pin 18 atau 12 - PWM0)
        - count      : Jumlah total mata LED pada strip
        - brightness : Kecerahan 0 s/d 255 (default 255)
        """
        if PixelStrip is None:
            logger.error("Library rpi_ws281x belum terinstall!")
            return False

        try:
            # Konfigurasi standar sinyal WS2812B (800kHz, DMA 10, PWM Ch 0)
            self._strip_pin = pin
            self._strip_count = count
            self._strip = PixelStrip(
                num=count,
                pin=pin,
                freq_hz=800000,
                dma=10,
                invert=False,
                brightness=brightness,
                channel=0
            )
            self._strip.begin()
            self.clear_strip()
            return True
        except Exception as e:
            logger.error(f"Gagal inisialisasi PixelStrip di GPIO {pin}: {e}")
            self._strip = None
            return False

    def _ensure_strip(self, pin=18, count=8):
        """Otomatis inisialisasi jika strip belum dibuat."""
        if self._strip is None:
            self.init_strip(pin=pin, count=count)

    def _parse_color(self, color, r=None, g=None, b=None):
        """Mengubah string warna atau parameter RGB menjadi tuple (R, G, B)."""
        if r is not None and g is not None and b is not None:
            return int(r), int(g), int(b)
        if isinstance(color, str):
            c_lower = color.lower()
            if c_lower.startswith("#") and len(c_lower) == 7:
                # Format HEX #RRGGBB
                return int(c_lower[1:3], 16), int(c_lower[3:5], 16), int(c_lower[5:7], 16)
            return COLOR_PALETTE.get(c_lower, (255, 255, 255))
        if isinstance(color, (tuple, list)) and len(color) >= 3:
            return int(color[0]), int(color[1]), int(color[2])
        return 255, 255, 255

    def set_strip_color(self, color="red", r=None, g=None, b=None, pin=18, count=8):
        """
        Mewarnai seluruh mata LED pada strip secara bersamaan.
        Contoh:
            led.set_strip_color("red")
            led.set_strip_color(r=255, g=100, b=0)
            led.set_strip_color("off")
        """
        self._ensure_strip(pin=pin, count=count)
        if not self._strip: return

        red, green, blue = self._parse_color(color, r, g, b)
        color_val = Color(red, green, blue)

        for i in range(self._strip.numPixels()):
            self._strip.setPixelColor(i, color_val)
        self._strip.show()

    def set_pixel(self, index=0, color="red", r=None, g=None, b=None, pin=18, count=8):
        """
        Mewarnai satu mata LED tertentu (index dimulai dari 0).
        Contoh:
            led.set_pixel(0, "green")
            led.set_pixel(1, r=0, g=0, b=255)
        """
        self._ensure_strip(pin=pin, count=count)
        if not self._strip: return

        if 0 <= index < self._strip.numPixels():
            red, green, blue = self._parse_color(color, r, g, b)
            self._strip.setPixelColor(index, Color(red, green, blue))
            self._strip.show()

    def set_strip_brightness(self, brightness=255):
        """Mengatur kecerahan strip (0 s/d 255)."""
        if self._strip:
            self._strip.setBrightness(max(0, min(255, int(brightness))))
            self._strip.show()

    def clear_strip(self):
        """Mematikan seluruh lampu LED strip."""
        if self._strip:
            for i in range(self._strip.numPixels()):
                self._strip.setPixelColor(i, Color(0, 0, 0))
            self._strip.show()

    def rainbow_strip(self, wait_ms=20, iterations=1):
        """Animasi pelangi pada LED strip."""
        if not self._strip: return

        def wheel(pos):
            if pos < 85:
                return Color(pos * 3, 255 - pos * 3, 0)
            elif pos < 170:
                pos -= 85
                return Color(255 - pos * 3, 0, pos * 3)
            else:
                pos -= 170
                return Color(0, pos * 3, 255 - pos * 3)

        for j in range(256 * iterations):
            for i in range(self._strip.numPixels()):
                self._strip.setPixelColor(i, wheel((int(i * 256 / self._strip.numPixels()) + j) & 255))
            self._strip.show()
            time.sleep(wait_ms / 1000.0)

    # =========================================================================
    # 2. LED BIASA / DIGITAL ON-OFF (Fungsi Lama)
    # =========================================================================
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