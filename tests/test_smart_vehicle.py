import unittest
import unittest.mock
import sys
import os

SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVER_ROOT)
sys.path.insert(0, os.path.join(SERVER_ROOT, "src"))

# Mock websockets jika environment test belum terinstall websockets daemon
if "websockets" not in sys.modules:
    sys.modules["websockets"] = unittest.mock.MagicMock()

from hal import agv, mobility, vehicle, robot, tello, drone, vision, cv_follower
from hal.agv import AGVHAL
from hal.tello import TelloHAL
from hal.cv_follower import VisionFollowerHAL

class TestSmartVehicleHAL(unittest.TestCase):
    def test_aliases_and_instances(self):
        # 1. Verifikasi Alias Singleton
        self.assertIs(agv, mobility)
        self.assertIs(agv, vehicle)
        self.assertIs(agv, robot)
        self.assertIs(tello, drone)
        self.assertIs(vision, cv_follower)

        self.assertIsInstance(mobility, AGVHAL)
        self.assertIsInstance(tello, TelloHAL)
        self.assertIsInstance(vision, VisionFollowerHAL)

    def test_agv_kinematics_and_differential_steering(self):
        # Gerakan dasar 4WD
        mobility.drive("FORWARD", 80)
        self.assertEqual(mobility._motor._left_speed, 80)
        self.assertEqual(mobility._motor._right_speed, 80)

        mobility.drive_for("FORWARD", 90, 0.01)
        self.assertEqual(mobility._motor._left_speed, 0)
        self.assertEqual(mobility._motor._right_speed, 0)

        mobility.turn("LEFT", 100)
        self.assertEqual(mobility._motor._left_speed, 25)
        self.assertEqual(mobility._motor._right_speed, 100)

        mobility.spin("RIGHT", 70)
        self.assertEqual(mobility._motor._left_speed, 70)
        self.assertEqual(mobility._motor._right_speed, -70)

        # Proportional Steering (STEM Closed-loop Control Loop)
        mobility.steer(60, 40)
        self.assertEqual(mobility._motor._left_speed, 60)
        self.assertEqual(mobility._motor._right_speed, 40)

        # Dead-reckoning & Navigasi Koordinat (jarak kecil untuk efisiensi tes)
        mobility.move_distance("FORWARD", 5, 100)
        mobility.rotate("LEFT", 15, 100)
        mobility.go(10, 10, 0, 100)
        mobility.curve(5, 5, 0, 10, 10, 0, 100)
        mobility.set_calibration_xy(105.0, 98.0)
        self.assertEqual(mobility._scale_x, 105.0)
        self.assertEqual(mobility._scale_y, 98.0)

        mobility.stop()
        self.assertEqual(mobility._motor._left_speed, 0)
        self.assertEqual(mobility._motor._right_speed, 0)

    def test_agv_sensors_and_telemetry(self):
        # TCRT5000 Line Tracker Primitives
        tcrt_l = mobility.read_tcrt("LEFT")
        tcrt_r = mobility.read_tcrt("RIGHT")
        self.assertIn(tcrt_l, [0, 1])
        self.assertIn(tcrt_r, [0, 1])
        self.assertIsInstance(mobility.is_on_line(), bool)
        self.assertIsInstance(mobility.is_on_line("LEFT"), bool)
        self.assertIsInstance(mobility.is_on_line("RIGHT"), bool)

        # Line Tracking Step
        res = mobility.line_track_step(50)
        self.assertIn(res, ["FORWARD", "LEFT", "RIGHT", "STOP", "SEARCH"])

        # Ultrasonic Radar & Wall Sensing
        mobility.set_radar_angle(90)
        dist = mobility.get_obstacle_distance()
        self.assertIsInstance(dist, (int, float))
        self.assertGreater(dist, 0)

        wall_dist = mobility.get_wall_distance()
        self.assertIsInstance(wall_dist, (int, float))
        self.assertIsInstance(mobility.is_wall_detected(20), bool)

        # IMU / Kompas
        angle = mobility.get_imu_angle()
        self.assertIsInstance(angle, (int, float))
        heading = mobility.get_heading()
        self.assertIsInstance(heading, (int, float))

        # RFID & Floor Color
        self.assertIsInstance(mobility.is_rfid_present(), bool)
        self.assertIsInstance(mobility.get_rfid_uid(), str)
        self.assertIsInstance(mobility.read_floor_color(), str)
        self.assertIsInstance(mobility.is_floor_color("RED"), bool)
        
        rgb_r = mobility.get_color_rgb("RED")
        self.assertIsInstance(rgb_r, int)
        self.assertGreaterEqual(rgb_r, 0)
        self.assertLessEqual(rgb_r, 255)

        # Buzzer & Telemetri
        mobility.beep(1000, 0.01)
        telem = mobility.get_telemetry()
        self.assertIsInstance(telem, dict)
        self.assertIn("speed_left", telem)
        self.assertIn("speed_right", telem)
        self.assertIn("obstacle_distance", telem)
        self.assertIn("heading", telem)

    def test_agv_vision_primitives(self):
        # Primitive Vision untuk Lane Tracking & Person Following
        offset = mobility.get_lane_offset()
        self.assertIsInstance(offset, (int, float))
        self.assertGreaterEqual(offset, -100)
        self.assertLessEqual(offset, 100)

        self.assertIsInstance(mobility.is_person_detected(), bool)
        person_offset = mobility.get_person_offset_x()
        self.assertIsInstance(person_offset, (int, float))
        person_dist = mobility.get_person_distance()
        self.assertIsInstance(person_dist, (int, float))

        # Module Vision Follower HAL
        self.assertIsInstance(vision.get_lane_offset(), (int, float))
        self.assertIsInstance(vision.is_person_detected(), bool)
        self.assertIsInstance(vision.get_person_offset_x(), (int, float))
        self.assertIsInstance(vision.get_person_distance(), (int, float))

    def test_drone_flight_and_kinematics(self):
        # Siklus Terbang Tello
        tello.takeoff()
        self.assertTrue(tello._is_flying)

        tello.set_speed(40)
        self.assertEqual(tello._speed, 40)

        tello.move_forward(30)
        tello.move_up(20)
        tello.move_down(10)
        tello.move_left(25)
        tello.move_right(25)
        tello.rotate_cw(90)
        tello.flip("f")

        # Vektor 3D, Kurva, dan Spiral
        tello.move_vector(10, 10, 10, 30)
        tello.go(50, 50, 80, 40)
        tello.curve(20, 20, 50, 40, 40, 60, 30)
        tello.shape_spiral(3, 1, 6, 30)
        d3 = tello.calculate_distance_3d(0, 0, 0, 30, 40, 0)
        self.assertAlmostEqual(d3, 50.0, places=1)

        tello.set_safety_guard(150, 20)
        tello.set_hover_delay(0.01)
        tello.stop()
        tello.land()
        self.assertFalse(tello._is_flying)

    def test_drone_sensors_and_vision(self):
        # Telemetri Drone
        self.assertGreaterEqual(tello.get_battery(), 0)
        self.assertGreaterEqual(tello.get_height(), 0)
        self.assertGreaterEqual(tello.get_temp(), 0)
        att = tello.get_attitude("pitch")
        self.assertIsInstance(att, int)
        self.assertGreaterEqual(tello.get_flight_time(), 0)
        self.assertGreaterEqual(tello.get_distance(), 0)

        # Kamera dan Vision
        tello.streamon()
        tello.take_photo()
        tello.start_recording()
        tello.stop_recording()
        tello.streamoff()

        # Pelacakan Warna Otonom
        tello.land_on_color("RED", 15)
        tello.follow_color("BLUE", 0.01)

    def test_blockly_execution_sandbox_compatibility(self):
        # Uji simulasi skrip Python hasil translasi Blockly Smart Vehicle & Drone
        import asyncio
        from ws_server import global_proxies

        sandbox = dict(global_proxies)
        sandbox["asyncio"] = asyncio

        # Skrip Proyek 1: Motion Shapes
        script_p1 = """
mobility.drive("FORWARD", 80)
mobility.rotate("LEFT", 15, 60)
mobility.stop()
"""
        exec(script_p1, sandbox)

        # Skrip Proyek 12: Smart Obstacle Avoidance (AEB)
        script_p12 = """
dist = mobility.get_obstacle_distance()
if dist < 25:
    mobility.stop()
    mobility.beep(2000, 0.01)
"""
        exec(script_p12, sandbox)

        # Skrip Proyek 17: Camera Lane Tracking (STEM Proportional Loop)
        script_p17 = """
offset = mobility.get_lane_offset()
base_spd = 50
kp = 0.5
corr = offset * kp
left_spd = max(0, min(100, int(base_spd + corr)))
right_spd = max(0, min(100, int(base_spd - corr)))
mobility.steer(left_spd, right_spd)
mobility.stop()
"""
        exec(script_p17, sandbox)

        # Skrip Proyek 7 & 14: Drone Explorer & Area Mapping
        script_drone = """
tello.takeoff()
tello.move_forward(30)
tello.take_photo()
d = tello.calculate_distance_3d(0, 0, 0, 30, 40, 0)
tello.land()
"""
        exec(script_drone, sandbox)

if __name__ == "__main__":
    unittest.main()
