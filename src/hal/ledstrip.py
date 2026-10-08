import time
import logging
import re

from .pin import PinHAL

logger = logging.getLogger(__name__)

try:
    from rpi_ws281x import PixelStrip, Color
except ImportError:
    PixelStrip = None
    Color = None
    logger.warning(
        "rpi_ws281x tidak ditemukan. Fitur WS2812B dinonaktifkan."
    )


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
    "off": (0, 0, 0),
}


class LedStripHAL(PinHAL):
    def __init__(self):
        super().__init__()

        self._brightness = 100
        self._led_pins = {1: 17, 2: 27, 3: 22}

        self._strip = None
        self._strip_pin = None
        self._strip_count = None

    # =====================================================
    # WS2812B / NEOPIXEL
    # =====================================================

    def init_strip(self, pin=10, count=30, brightness=80):
        """
        pin: nomor GPIO BCM.
        count: jumlah LED.
        brightness: 0-255, bukan persen.
        """
        if PixelStrip is None:
            raise RuntimeError(
                "Library rpi_ws281x belum terinstall pada "
                "Python yang menjalankan server."
            )

        try:
            self._strip = PixelStrip(
                num=count,
                pin=pin,
                freq_hz=800000,
                dma=10,
                invert=False,
                brightness=brightness,
                channel=0,
            )

            self._strip.begin()
            self._strip_pin = pin
            self._strip_count = count

            return True

        except Exception as e:
            self._strip = None
            raise RuntimeError(
                f"Gagal inisialisasi WS2812B di GPIO {pin}: {e}"
            ) from e

    def _ensure_strip(self, pin=10, count=30):
        """Inisialisasi otomatis saat pertama digunakan."""
        if self._strip is None:
            self.init_strip(pin=pin, count=count)

    def _parse_color(self, color, r=None, g=None, b=None):
        """Menerima nama warna, HEX, atau RGB."""
        if r is not None and g is not None and b is not None:
            rgb = (int(r), int(g), int(b))

        elif any(value is not None for value in (r, g, b)):
            raise ValueError(
                "Parameter r, g, b harus diisi lengkap."
            )

        elif isinstance(color, str):
            name = color.strip().lower()

            if name in COLOR_PALETTE:
                return COLOR_PALETTE[name]

            if re.fullmatch(r"#?[0-9a-f]{6}", name):
                code = name.removeprefix("#")
                return tuple(
                    int(code[i:i + 2], 16)
                    for i in (0, 2, 4)
                )

            raise ValueError(
                "Warna harus nama yang dikenal atau "
                "HEX seperti #7F00FF."
            )

        elif isinstance(color, (tuple, list)) and len(color) == 3:
            rgb = tuple(int(value) for value in color)

        else:
            raise ValueError(
                "Warna harus nama, HEX, atau tiga nilai RGB."
            )

        if not all(0 <= value <= 255 for value in rgb):
            raise ValueError(
                "Nilai RGB harus antara 0 dan 255."
            )

        return rgb

    def set_strip_color(
        self,
        color="red",
        r=None,
        g=None,
        b=None,
        pin=10,
        count=30,
    ):
        """Mengatur warna seluruh LED pada strip."""
        red, green, blue = self._parse_color(color, r, g, b)
        self._ensure_strip(pin=pin, count=count)

        color_val = Color(red, green, blue)

        for i in range(self._strip.numPixels()):
            self._strip.setPixelColor(i, color_val)

        self._strip.show()

    def set_pixel(
        self,
        index=0,
        color="red",
        r=None,
        g=None,
        b=None,
        pin=10,
        count=30,
    ):
        """Mengatur satu LED. Index dimulai dari 0."""
        self._ensure_strip(pin=pin, count=count)

        if not 0 <= index < self._strip.numPixels():
            raise ValueError(
                "Index LED harus antara 0 dan "
                f"{self._strip.numPixels() - 1}."
            )

        red, green, blue = self._parse_color(color, r, g, b)

        self._strip.setPixelColor(
            index,
            Color(red, green, blue),
        )
        self._strip.show()

    def set_strip_brightness(self, brightness=255):
        """Mengatur brightness pada skala 0-255."""
        self._ensure_strip()

        if self._strip:
            value = max(0, min(255, int(brightness)))
            self._strip.setBrightness(value)
            self._strip.show()

    def clear_strip(self):
        """Mematikan seluruh LED pada strip."""
        if self._strip:
            for i in range(self._strip.numPixels()):
                self._strip.setPixelColor(i, Color(0, 0, 0))

            self._strip.show()

    def rainbow_strip(self, wait_ms=20, iterations=1):
        """Menampilkan animasi pelangi."""
        self._ensure_strip()

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
                position = (
                    int(i * 256 / self._strip.numPixels()) + j
                ) & 255

                self._strip.setPixelColor(i, wheel(position))

            self._strip.show()
            time.sleep(wait_ms / 1000.0)

    # =====================================================
    # LED DIGITAL BIASA: FUNGSI LAMA, BUKAN WS2812B
    # =====================================================

    def _resolve_targets(self, target):
        if str(target) == "ALL":
            return list(self._led_pins.keys())

        return [int(target)]

    def display_color(self, target, color, secs=None):
        for t in self._resolve_targets(target):
            p = self._led_pins.get(t, t)
            self.set_digital(
                p,
                "HIGH" if color != "black" else "LOW",
            )

        if secs is not None:
            time.sleep(secs)

            for t in self._resolve_targets(target):
                p = self._led_pins.get(t, t)
                self.set_digital(p, "LOW")

    def turn_off(self, target):
        for t in self._resolve_targets(target):
            p = self._led_pins.get(t, t)
            self.set_digital(p, "LOW")
