from .core import get_gpio, get_gpio_lib

class MotorHAL:
    def __init__(self):
        self._servo_pins = {}

    def set_servo(self, p=18, degree=90):
        _gpio = get_gpio_lib()
        if not _gpio: return
        
        chip, offset = get_gpio(p)
        if not chip: return
        
        pulse_us = int(500 + (degree / 180.0) * 2000)
        
        if p not in self._servo_pins:
            try:
                _gpio.gpio_claim_output(chip, offset)
            except Exception:
                pass
            try:
                _gpio.tx_servo(chip, offset, pulse_us, 50, 500, 2500)
                self._servo_pins[p] = True
            except Exception:
                pass
        else:
            try:
                _gpio.tx_servo(chip, offset, pulse_us)
            except Exception:
                pass

    def run_dc(self, motor="M1", speed=0):
        _gpio = get_gpio_lib()
        if not _gpio: return
        
        pins = {"M1": (11, 13, 15), "M2": (19, 21, 23)}
        if motor not in pins:
            return
            
        in1, in2, ena = pins[motor]
        c1, o1 = get_gpio(in1)
        c2, o2 = get_gpio(in2)
        ce, oe = get_gpio(ena)
        
        if not c1 or not c2 or not ce: return
        
        try:
            _gpio.gpio_claim_output(c1, o1)
            _gpio.gpio_claim_output(c2, o2)
        except Exception:
            pass
            
        speed = max(-100, min(100, int(speed)))
        
        try:
            if speed > 0:
                _gpio.gpio_write(c1, o1, 1)
                _gpio.gpio_write(c2, o2, 0)
                _gpio.tx_pwm(ce, oe, 100, speed)
            elif speed < 0:
                _gpio.gpio_write(c1, o1, 0)
                _gpio.gpio_write(c2, o2, 1)
                _gpio.tx_pwm(ce, oe, 100, -speed)
            else:
                _gpio.gpio_write(c1, o1, 0)
                _gpio.gpio_write(c2, o2, 0)
                _gpio.tx_pwm(ce, oe, 100, 0)
        except Exception:
            pass

    def set_fan(self, speed=100):
        """Mengontrol kecepatan kipas (Motor M1) dari 0 sampai 100%"""
        self.run_dc("M1", speed)

    def stop_dc(self, motor="ALL"):
        if motor == "ALL":
            self.run_dc("M1", 0)
            self.run_dc("M2", 0)
        else:
            self.run_dc(motor, 0)
