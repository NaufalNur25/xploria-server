"""Real WebSocket routing with hardware/model operations stubbed."""
import unittest
from unittest.mock import patch
import test_hospital_widgets as hospital_tests
server = hospital_tests.server


class CameraSocketTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = hospital_tests.NativeHospitalTests.asyncSetUp
    asyncTearDown = hospital_tests.NativeHospitalTests.asyncTearDown
    connect = hospital_tests.NativeHospitalTests.connect
    send = hospital_tests.NativeHospitalTests.send
    receive = hospital_tests.NativeHospitalTests.receive

    async def test_legacy_widget_control(self):
        with patch.object(server.face.FaceService, 'operate', return_value={'message': 'Foto OK'}):
            await self.send({'type': 'control', 'hw_type': 'esp32_cam',
                             'block_uid': 'old-uid', 'block_type': 'sh_camera_capture',
                             'channel': 'camera_capture', 'command': 'camera_capture',
                             'request_id': 'camera-1'})
            result = await self.receive(lambda p: p.get('type') == 'camera_result')
            self.assertEqual(result['request_id'], 'camera-1')
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['block_uid'], 'old-uid')

    async def test_blockly_import_and_error(self):
        with patch.object(server.face.FaceService, 'operate', side_effect=ValueError('No face')):
            await self.send({'type': 'run', 'code': 'from xploria_hal import face\nface.is_recognized()'})
            result = await self.receive(lambda p: p.get('type') == 'camera_result')
            self.assertEqual(result['source'], 'blockly')
            self.assertEqual(result['status'], 'error')
            self.assertEqual(result['message'], 'No face')

    async def test_blockly_threshold_and_last_score_share_one_camera_result(self):
        result = {'recognized': True, 'name': 'Andi', 'similarity': 0.72,
                  'threshold': 0.7, 'message': 'Dikenali: Andi'}
        with patch.object(server.face.FaceService, 'operate', return_value=result) as camera:
            await self.send({'type': 'run', 'code':
                'from xploria_hal import face\n'
                'if face.is_recognized_at_least(70):\n'
                '    print(face.get_recognized_name())\n'
                '    print(face.get_last_similarity_percent())'})
            packet = await self.receive(lambda p: p.get('type') == 'camera_result')
            self.assertEqual(packet['threshold'], 0.7)
            self.assertEqual(packet['similarity'], 0.72)
            camera.assert_called_once_with('face_recognized', 0.7)

    async def test_unsupported_command(self):
        await self.send({'type': 'control', 'hw_type': 'esp32_cam',
                         'command': 'unknown', 'request_id': 'bad'})
        result = await self.receive(lambda p: p.get('type') == 'camera_result')
        self.assertEqual(result['status'], 'error')

    async def test_cctv_widget_control(self):
        cctv_data = {'status': 'CAR', 'is_car': True, 'confidence': 0.9, 'count': 1, 'message': 'Mobil Terdeteksi!'}
        with patch.object(server.city.CityCctvService, 'operate', return_value=cctv_data):
            await self.send({'type': 'control', 'hw_type': 'cctv_cam',
                             'block_uid': 'cctv-123', 'block_type': 'sc_cctv_scan',
                             'channel': 'cctv_scan', 'command': 'cctv_scan',
                             'request_id': 'cctv-req-1'})
            result = await self.receive(lambda p: p.get('type') == 'cctv_result')
            self.assertEqual(result['request_id'], 'cctv-req-1')
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['is_car'], True)
            self.assertEqual(result['count'], 1)
            self.assertEqual(result['block_uid'], 'cctv-123')

    async def test_blockly_cctv_run(self):
        cctv_data = {'status': 'CAR', 'is_car': True, 'count': 3, 'confidence': 0.88, 'message': 'Mobil OK'}
        with patch.object(server.city.CityCctvService, 'operate', return_value=cctv_data):
            await self.send({'type': 'run', 'code': 'from xploria_hal import city\nif city.is_car_detected():\n    print(city.vehicle_count())'})
            packet = await self.receive(lambda p: p.get('type') == 'cctv_result')
            self.assertEqual(packet['source'], 'blockly')
            self.assertEqual(packet['status'], 'ok')
            self.assertEqual(packet['is_car'], True)

