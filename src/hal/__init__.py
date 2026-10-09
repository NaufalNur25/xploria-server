from .pin import PinHAL
from .sensor import SensorHAL
from .motor import MotorHAL
from .led import LEDHAL
from .ledstrip import LedStripHAL
from .rfid import RFIDHAL
from .telemetry import TelemetryHAL
from .rgb import RGBHAL
from .hospital import HospitalHAL
from .mocks import DisplayHAL, MotionHAL, LANHAL, AIHAL, PowerHAL
from .audio import AudioHAL
from . import voice

pin       = PinHAL()
sensor    = SensorHAL()
motor     = MotorHAL()
led       = LEDHAL()
rgb       = RGBHAL()
ledstrip  = LedStripHAL()
rfid      = RFIDHAL()
telemetry = TelemetryHAL()
power     = PowerHAL()
hospital  = HospitalHAL()

audio     = AudioHAL()
display   = DisplayHAL()
motion    = MotionHAL()
lan       = LANHAL()
ai        = AIHAL()
