class MockDevice:
    def __getattr__(self, name):
        def method(*args, **kwargs):
            return 0
        return method

class AudioHAL(MockDevice): pass
class DisplayHAL(MockDevice): pass
class MotionHAL(MockDevice): pass
class LANHAL(MockDevice): pass
class AIHAL(MockDevice): pass

# Optional PowerHAL Mock
class PowerHAL:
    def read_house_power(self):
        return {"volt": 0, "current_ma": 0, "power_mw": 0}
        
    def read_solar_power(self):
        return {"volt": 0, "current_ma": 0, "power_mw": 0}
