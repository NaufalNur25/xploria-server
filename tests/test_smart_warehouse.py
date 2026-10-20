import unittest
import sys
import os

SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVER_ROOT)
sys.path.insert(0, os.path.join(SERVER_ROOT, "src"))

from hal import pin, sensor, motor, led, audio, display, rfid, power, city, ai, lan, wms, robot, telemetry, robotic_arm, arm

class TestSmartWarehouseServerHAL(unittest.TestCase):
    def test_hal_imports_and_proxies(self):
        # Memastikan seluruh modul HAL yang di-inject oleh Blockly dapat diakses
        self.assertIsNotNone(sensor)
        self.assertIsNotNone(motor)
        self.assertIsNotNone(led)
        self.assertIsNotNone(rfid)
        self.assertIsNotNone(telemetry)
        self.assertIsNotNone(wms)
        self.assertIsNotNone(city)
        self.assertIsNotNone(robot)
        self.assertIsNotNone(robotic_arm)
        self.assertIsNotNone(ai)
        self.assertIsNotNone(display)

    def test_warehouse_sensors(self):
        # 1. Timbangan Presisi HX711 (desimal gram)
        weight = sensor.read_precision_weight()
        self.assertIsInstance(weight, float)
        self.assertGreater(weight, 0)

        # 2. Sensor Warna TCS3200
        rgb = sensor.read_color_rgb()
        self.assertIsInstance(rgb, str)
        self.assertTrue(sensor.is_color_matched("RED"))

        # 3. Konsumsi Daya INA226 (Watt)
        power_w = sensor.read_power_consumption()
        self.assertIsInstance(power_w, float)

        # 4. Dimensi cm
        dim = sensor.read_object_dimension()
        self.assertIsInstance(dim, float)

        # 5. Inkrementasi Counter
        c1 = sensor.increment_object_counter()
        c2 = sensor.increment_object_counter()
        self.assertEqual(c2, c1 + 1)

        # 6. IR Proximity
        ir = sensor.read_ir_obstacle(25)
        self.assertIsInstance(ir, bool)

        # 7. Gas MQ-9
        gas = sensor.read_gas(5)
        self.assertIsInstance(gas, bool)

    def test_warehouse_actuators(self):
        # 1. Motor DC Konveyor
        motor.run_dc("M1", 150)
        motor.stop_dc("M1")

        # 2. Servo Pemilah Diverter
        motor.set_servo(18, 90)
        motor.stop_servo(18)

        # 3. Ejector
        motor.push_defective_ejector(pin=18, push_angle=90, reset_angle=0, duration=0.01)

        # 4. AI Speed Optimization
        motor.optimize_conveyor_speed_ai("M1", 100)
        motor.stop_dc("ALL")

        # 5. Lampu Indikator Pabrik
        led.display_color(1, "GREEN")

    def test_robotic_arm_owi535(self):
        # 1. Gerak Sendi Lengan Robot
        robotic_arm.drive("M1", "open")
        robotic_arm.stop("M1")
        robotic_arm.drive("M3", "down")
        robotic_arm.stop("ALL")

        # 2. Lampu LED Arm
        robotic_arm.set_light(True)
        self.assertTrue(robotic_arm.is_light_on)
        robotic_arm.set_light(False)

        # 3. Presets
        robotic_arm.home()
        robotic_arm.pick_conveyor_1()
        robotic_arm.place_conveyor_2()

    def test_wms_and_ai_analytics(self):
        # 1. WMS OEE Efficiency
        oee = wms.calculate_oee_efficiency()
        self.assertIsInstance(oee, (int, float))
        self.assertGreater(oee, 0)

        # 2. AI Vision QR Code
        qr = ai.inspect_vision_code()
        self.assertEqual(qr, "PROD-A01")

        # 3. AI Defect Detection
        defect = ai.is_defect_detected()
        self.assertIsInstance(defect, bool)

        # 4. AI Yield Verify
        yield_rate = ai.verify_supply_chain_yield()
        self.assertIsInstance(yield_rate, (int, float))

        # 5. AI Release Forecast
        fc = ai.forecast_production_release_time()
        self.assertIsInstance(fc, str)

        # 6. Display Dashboard Update
        disp = display.update_digital_factory_dashboard()
        self.assertTrue(disp)

    def test_telemetry_iiot(self):
        # Telemetry send & gateway push
        telemetry.send(wms_check_in="BOX_01", conveyor_speed=150)
        telemetry.push_iiot_gateway()

if __name__ == "__main__":
    unittest.main()
