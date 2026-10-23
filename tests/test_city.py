import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
path = root / 'src/hal/city.py'
spec = importlib.util.spec_from_file_location('city_under_test', path)
city = importlib.util.module_from_spec(spec)
spec.loader.exec_module(city)


class CityTests(unittest.TestCase):
    def test_uart_hw_frame_and_invalid_jpeg(self):
        jpeg = b'\xff\xd8fake_jpeg_content\xff\xd9'
        packet = b'boot log\nFRAME ' + str(len(jpeg)).encode('ascii') + b'\n' + jpeg
        self.assertEqual(city.read_frame(io.BytesIO(packet)), jpeg)

        # Also support legacy tesuart_yolo.py header 'JPEG:<size>'
        legacy_packet = b'JPEG:' + str(len(jpeg)).encode('ascii') + b'\n' + jpeg
        self.assertEqual(city.read_frame(io.BytesIO(legacy_packet)), jpeg)

        # Corrupted JPEG end
        bad_jpeg = b'\xff\xd8fake_jpeg_content\xff\x00'
        bad_packet = b'FRAME ' + str(len(bad_jpeg)).encode('ascii') + b'\n' + bad_jpeg
        with self.assertRaises(ValueError):
            city.read_frame(io.BytesIO(bad_packet))

    def test_capture_sends_team_hw_command(self):
        jpeg = b'\xff\xd8valid_image\xff\xd9'
        packet = b'FRAME ' + str(len(jpeg)).encode('ascii') + b'\n' + jpeg

        class FakePort(io.BytesIO):
            def __init__(self):
                super().__init__(packet)
                self.command = None

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

            def reset_input_buffer(self):
                pass

            def write(self, value):
                self.command = value
                return len(value)

            def flush(self):
                pass

        port = FakePort()
        import sys
        from types import SimpleNamespace
        with patch.dict(sys.modules, {'serial': SimpleNamespace(Serial=lambda *a, **kw: port)}), \
                patch.object(city.time, 'sleep'), \
                patch.dict(city.os.environ, {'XPLORIA_MOCK_CAMERA': '0'}, clear=False), \
                patch('os.path.exists', return_value=True):
            service = city.CityCctvService()
            result_jpeg = service.capture()
            self.assertEqual(result_jpeg, jpeg)
            self.assertIn(port.command, (b'C', b'GET\n'))

    def test_ping_success(self):
        class FakePingPort(io.BytesIO):
            def __init__(self):
                super().__init__(b'PONG\n')
                self.command = None

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

            def reset_input_buffer(self):
                pass

            def write(self, value):
                self.command = value
                return len(value)

            def flush(self):
                pass

        import sys
        from types import SimpleNamespace
        port = FakePingPort()
        with patch.dict(sys.modules, {'serial': SimpleNamespace(Serial=lambda *a, **kw: port)}), \
                patch.dict(city.os.environ, {'XPLORIA_MOCK_CAMERA': '0'}, clear=False), \
                patch('os.path.exists', return_value=True):
            service = city.CityCctvService()
            self.assertTrue(service.ping())
            self.assertEqual(port.command, b'PING\n')

    def test_vehicle_counter_increments_on_car_detect(self):
        service = city.CityCctvService()
        self.assertEqual(service.vehicle_count, 0)

        # Mock detect car
        car_result = {'status': 'CAR', 'is_car': True, 'confidence': 0.85,
                      'label': 'Car', 'jpeg_bytes': b'\xff\xd8demo\xff\xd9'}
        with patch.object(service, 'capture', return_value=b'\xff\xd8demo\xff\xd9'), \
                patch.object(service, 'detect_vehicle', return_value=car_result):
            res = service.operate('cctv_scan')
            self.assertEqual(res['status'], 'CAR')
            self.assertTrue(res['is_car'])
            self.assertEqual(res['count'], 1)
            self.assertEqual(service.vehicle_count, 1)

            # Another car detected -> counter should be 2
            res2 = service.operate('cctv_scan')
            self.assertEqual(res2['count'], 2)
            self.assertEqual(service.vehicle_count, 2)

        # Mock detect empty road -> counter should NOT increment
        empty_result = {'status': 'EMPTY', 'is_car': False, 'confidence': 0.0,
                        'label': 'Empty', 'jpeg_bytes': b'\xff\xd8demo\xff\xd9'}
        with patch.object(service, 'capture', return_value=b'\xff\xd8demo\xff\xd9'), \
                patch.object(service, 'detect_vehicle', return_value=empty_result):
            res3 = service.operate('cctv_scan')
            self.assertEqual(res3['status'], 'EMPTY')
            self.assertFalse(res3['is_car'])
            self.assertEqual(res3['count'], 2)  # tetap 2!
            self.assertEqual(service.vehicle_count, 2)

        # Reset count
        reset_res = service.operate('vehicle_count_reset')
        self.assertEqual(reset_res['count'], 0)
        self.assertEqual(service.vehicle_count, 0)

    def test_public_functions_and_perform(self):
        city._service = city.CityCctvService()
        with patch.object(city._service, 'operate', return_value={'status': 'CAR', 'is_car': True, 'count': 5}):
            self.assertTrue(city.is_car_detected())

        with patch.object(city._service, 'operate', return_value={'count': 7}):
            self.assertEqual(city.vehicle_count(), 7)

        with patch.object(city._service, 'operate', return_value={'count': 0}):
            self.assertEqual(city.reset_vehicle_count(), 0)


if __name__ == '__main__':
    unittest.main()
