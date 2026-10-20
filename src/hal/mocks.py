class MockDevice:
    def __getattr__(self, name):
        def method(*args, **kwargs):
            return 0
        return method

class AudioHAL(MockDevice): pass
class DisplayHAL(MockDevice):
    def update_digital_factory_dashboard(self):
        return True

class MotionHAL(MockDevice): pass
class LANHAL(MockDevice): pass
class CityHAL(MockDevice): pass

class WMSHAL(MockDevice):
    def calculate_oee_efficiency(self):
        return 88.5

    def check_in(self, item):
        return True

    def check_out(self, item):
        return True

    def get_inventory(self):
        return []

class AIHAL(MockDevice):
    def inspect_vision_code(self):
        return "PROD-A01"

    def is_defect_detected(self):
        return False

    def verify_supply_chain_yield(self):
        return 98.5

    def forecast_production_release_time(self):
        return "14:30"

# Optional PowerHAL Mock
class PowerHAL:
    def read_house_power(self):
        return {"volt": 0, "current_ma": 0, "power_mw": 0}
        
    def read_solar_power(self):
        return {"volt": 0, "current_ma": 0, "power_mw": 0}
