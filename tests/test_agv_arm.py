import unittest
import sys
import os

# Add server root and src to sys.path
SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVER_ROOT)
sys.path.insert(0, os.path.join(SERVER_ROOT, "src"))

from hal import agv, mobility, vehicle, arm, robotic_arm, tello, drone, vision, cv_follower
from hal.agv import AGVHAL, Motor4WDDriver
from hal.robotic_arm import RoboticArmHAL


class TestAGVHAL(unittest.TestCase):
    def setUp(self):
        self.agv = agv

    def test_singleton_aliases(self):
        self.assertIs(agv, mobility)
        self.assertIs(agv, vehicle)
        self.assertIsInstance(self.agv, AGVHAL)

    def test_basic_motions(self):
        self.agv.drive("FORWARD", 100)
        self.assertEqual(self.agv._motor._left_speed, 100)
        self.assertEqual(self.agv._motor._right_speed, 100)

        self.agv.drive("BACKWARD", 80)
        self.assertEqual(self.agv._motor._left_speed, -80)
        self.assertEqual(self.agv._motor._right_speed, -80)

        self.agv.stop()
        self.assertEqual(self.agv._motor._left_speed, 0)
        self.assertEqual(self.agv._motor._right_speed, 0)

    def test_turns_and_spins(self):
        self.agv.turn("LEFT", 100)
        self.assertEqual(self.agv._motor._left_speed, 25)
        self.assertEqual(self.agv._motor._right_speed, 100)

        self.agv.turn("RIGHT", 100)
        self.assertEqual(self.agv._motor._left_speed, 100)
        self.assertEqual(self.agv._motor._right_speed, 25)

        self.agv.spin("LEFT", 100)
        self.assertEqual(self.agv._motor._left_speed, -100)
        self.assertEqual(self.agv._motor._right_speed, 100)

        self.agv.spin("RIGHT", 100)
        self.assertEqual(self.agv._motor._left_speed, 100)
        self.assertEqual(self.agv._motor._right_speed, -100)

        self.agv.steer(80, 120)
        self.assertEqual(self.agv._motor._left_speed, 80)
        self.assertEqual(self.agv._motor._right_speed, 120)
        self.agv.stop()

    def test_kinematics_and_coordinates(self):
        self.agv.reset_coordinates()
        pos = self.agv.get_position()
        self.assertEqual(pos["x"], 0.0)
        self.assertEqual(pos["y"], 0.0)
        self.assertEqual(pos["heading"], 0.0)

        self.agv.set_calibration_xy(100.0, 100.0)
        cal = self.agv.get_calibration()
        self.assertEqual(cal["scale_x"], 100.0)
        self.assertEqual(cal["scale_y"], 100.0)

    def test_sensors_and_telemetry(self):
        self.agv.set_radar_angle(45.0)
        self.assertEqual(self.agv.get_radar_angle(), 45.0)

        self.agv.set_mock_floor_color("MERAH", 255, 0, 0)
        self.assertEqual(self.agv.read_floor_color(), "MERAH")
        self.assertTrue(self.agv.is_floor_color("MERAH"))
        self.assertEqual(self.agv.get_color_rgb("R"), 255)
        self.assertEqual(self.agv.get_color_rgb("G"), 0)

        self.agv.set_mock_rfid_station("STATION_01")
        self.assertTrue(self.agv.is_rfid_present())
        self.assertEqual(self.agv.get_rfid_uid(), "STATION_01")

        telem = self.agv.get_telemetry()
        self.assertEqual(telem["mode"], "agv")
        self.assertIn("obstacle_distance", telem)
        self.assertIn("radar_angle", telem)
        self.assertIn("tcrt_state", telem)
        self.assertIn("timestamp", telem)


class TestRoboticArmHAL(unittest.TestCase):
    def setUp(self):
        self.arm = arm

    def test_singleton_aliases(self):
        self.assertIs(arm, robotic_arm)
        self.assertIsInstance(self.arm, RoboticArmHAL)

    def test_motor_drive_and_stop(self):
        self.arm.drive("M1", "open")
        self.arm.stop("M1")

        self.arm.drive("M2", "up")
        self.arm.stop("ALL")

    def test_light_control(self):
        self.arm.set_light(True)
        self.assertTrue(self.arm.is_light_on)
        self.arm.set_light(False)
        self.assertFalse(self.arm.is_light_on)

    def test_presets_execution(self):
        # Memastikan tidak ada exception saat preset dipanggil
        self.arm.inspection_pose()


if __name__ == "__main__":
    unittest.main()
