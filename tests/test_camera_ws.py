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

    async def test_unsupported_command(self):
        await self.send({'type': 'control', 'hw_type': 'esp32_cam',
                         'command': 'unknown', 'request_id': 'bad'})
        result = await self.receive(lambda p: p.get('type') == 'camera_result')
        self.assertEqual(result['status'], 'error')
