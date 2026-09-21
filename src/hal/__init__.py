from .pin import PinHAL
from .sensor import SensorHAL
from .motor import MotorHAL
from .led import LEDHAL
from .rfid import RFIDHAL
from .telemetry import TelemetryHAL
from .mocks import AudioHAL, DisplayHAL, MotionHAL, LANHAL, AIHAL, PowerHAL

pin       = PinHAL()
sensor    = SensorHAL()
motor     = MotorHAL()
led       = LEDHAL()
rfid      = RFIDHAL()
telemetry = TelemetryHAL()
power     = PowerHAL()

audio     = AudioHAL()
display   = DisplayHAL()
motion    = MotionHAL()
lan       = LANHAL()
ai        = AIHAL()
