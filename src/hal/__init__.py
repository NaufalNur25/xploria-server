from .pin import PinHAL
from .sensor import SensorHAL
from .motor import MotorHAL
from .led import LEDHAL
from .ledstrip import LedStripHAL
from .rfid import RFIDHAL
from .telemetry import TelemetryHAL
from .rgb import RGBHAL
from .hospital import HospitalHAL
from .mocks import DisplayHAL, MotionHAL, LANHAL, AIHAL, PowerHAL, WMSHAL, CityHAL
from .audio import AudioHAL
from . import voice

# Modul Smart Vehicle (AGV), Robotic Arm, Drone Tello, & Vision
from .agv import AGVHAL, agv, mobility, vehicle
from .robotic_arm import RoboticArmHAL, arm, robotic_arm
from .tello import TelloHAL
from .cv_follower import VisionFollowerHAL, vision, cv_follower

pin         = PinHAL()
sensor      = SensorHAL()
motor       = MotorHAL()
led         = LEDHAL()
rgb         = RGBHAL()
ledstrip    = LedStripHAL()
rfid        = RFIDHAL()
telemetry   = TelemetryHAL()
power       = PowerHAL()
hospital    = HospitalHAL()

audio       = AudioHAL()
display     = DisplayHAL()
motion      = MotionHAL()
lan         = LANHAL()
ai          = AIHAL()

# Smart Warehouse, Smart City & Vehicle Aliases
wms         = WMSHAL()
city        = CityHAL()
robot       = agv

tello       = TelloHAL()
drone       = tello

__all__ = [
    "pin",
    "sensor",
    "motor",
    "led",
    "rgb",
    "ledstrip",
    "rfid",
    "telemetry",
    "power",
    "hospital",
    "audio",
    "display",
    "motion",
    "lan",
    "ai",
    "voice",
    "wms",
    "city",
    "robot",
    "agv",
    "mobility",
    "vehicle",
    "arm",
    "robotic_arm",
    "tello",
    "drone",
    "vision",
    "cv_follower",
    "PinHAL",
    "SensorHAL",
    "MotorHAL",
    "LEDHAL",
    "RGBHAL",
    "LedStripHAL",
    "RFIDHAL",
    "TelemetryHAL",
    "HospitalHAL",
    "WMSHAL",
    "CityHAL",
    "AGVHAL",
    "RoboticArmHAL",
    "TelloHAL",
    "VisionFollowerHAL"
]
