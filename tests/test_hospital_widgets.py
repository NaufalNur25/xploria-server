"""Exercise the real WebSocket handler without loading Raspberry Pi hardware."""
import asyncio
import importlib
import json
import pathlib
import sys
import types
import unittest
from unittest.mock import Mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.test-deps'))
sys.path.insert(0, str(ROOT / 'src'))

# Substitute hardware only; the WebSocket server and Hospital code are real.
hal = types.ModuleType('hal')
hal.__path__ = [str(ROOT / 'src/hal')]
for name in ('sensor', 'motor', 'led', 'rgb', 'ledstrip', 'power', 'rfid',
             'telemetry', 'pin', 'audio', 'display', 'motion', 'lan', 'ai'):
    setattr(hal, name, Mock())
sys.modules['hal'] = hal
sensor_module = types.ModuleType('hal.sensor')
sensor_module.stop_all_workers = Mock()
sys.modules['hal.sensor'] = sensor_module
hospital_module = importlib.import_module('hal.hospital')
hal.hospital = hospital_module.HospitalHAL()
server = importlib.import_module('ws_server')
import websockets


FORM_PROGRAM = '''import time
hospital.form('form-a', 'A', [
    {'label': 'nama', 'type': 'text'},
    {'label': 'usia', 'type': 'number'},
    {'label': 'keluhan', 'type': 'choice', 'options': ['Demam', 'Batuk']}])
hospital.form('form-b', 'B', [{'label': 'nama', 'type': 'text'}])
def a():
    hospital.report('result-a', 'display', hospital.answer('nama'))
def b():
    hospital.report('result-b', 'display', hospital.answer('nama'))
hospital.on_form('handler-a', 'A', a)
hospital.on_form('handler-b', 'B', b)
'''
SOURCES = ['form-a', 'form-b', 'handler-a', 'handler-b', 'result-a', 'result-b', 'scan', 'stock', 'button-a', 'button-b']


class NativeHospitalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ws_server = await websockets.serve(server.handler, '127.0.0.1', 0)
        self.port = self.ws_server.sockets[0].getsockname()[1]
        self.clients = []
        self.client = await self.connect()

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
        self.ws_server.close()
        await self.ws_server.wait_closed()
        await asyncio.sleep(.1)

    async def connect(self):
        client = await websockets.connect(f'ws://127.0.0.1:{self.port}')
        self.clients.append(client)
        return client

    async def send(self, data, client=None):
        await (client or self.client).send(json.dumps(data))

    async def receive(self, predicate, client=None):
        async def read():
            while True:
                packet = json.loads(await (client or self.client).recv())
                if predicate(packet):
                    return packet
        return await asyncio.wait_for(read(), 3)

    async def kind(self, kind, client=None):
        return (await self.receive(lambda p: p.get('telemetry', {}).get('kind') == kind, client))['telemetry']

    async def run_program(self, code=FORM_PROGRAM, session='s', project='p', client=None):
        await self.send({'type': 'run', 'code': code, 'widget_session': {
            'protocol_version': 1, 'project_id': project, 'session_id': session,
            'snapshot': {'obat': [{'barcode': 'A', 'stok': 5}]},
            'snapshot_version': 0, 'sources': SOURCES}}, client)
        return await self.kind('ready', client)

    def event(self, uid='form-a', event_id='e', session='s', **values):
        return {'type': 'hospital_widget_event', 'project_id': 'p', 'session_id': session,
                'source_uid': uid, 'event_id': event_id, 'topic': 'form',
                'answers': {'nama': 'Ayu', 'usia': 12, 'keluhan': 'Demam'}, **values}

    async def test_capabilities_and_legacy_python(self):
        await self.send({'type': 'capabilities', 'request_id': 'request'})
        packet = await self.receive(lambda p: p.get('type') == 'capabilities')
        self.assertEqual(packet, {'type': 'capabilities', 'request_id': 'request', 'hospital_widgets': 1})
        await self.send({'type': 'run', 'code': "print('legacy works')"})
        output = await self.receive(lambda p: p.get('type') == 'output')
        self.assertIn('legacy works', output['payload'])

    async def test_full_form_definitions_are_not_deltas(self):
        await self.send({'type': 'run', 'code': FORM_PROGRAM, 'widget_session': {
            'protocol_version': 1, 'project_id': 'p', 'session_id': 's', 'sources': SOURCES}})
        first, second = await self.kind('form'), await self.kind('form')
        for packet in (first, second):
            self.assertEqual(packet['action'], 'hospital_widget')
            self.assertEqual(packet['project_id'], 'p')
            self.assertEqual(packet['session_id'], 's')
            self.assertIn('name', packet)
            self.assertIn('fields', packet)
        self.assertEqual(len(first['fields']), 3)
        self.assertEqual(len(second['fields']), 1)
        await self.kind('ready')

    async def test_forms_are_isolated_and_replays_do_not_execute(self):
        await self.run_program()
        await self.send(self.event())
        # ACK and callback output may arrive in either order.
        packets = [json.loads(await asyncio.wait_for(self.client.recv(), 3)) for _ in range(2)]
        self.assertEqual({p['telemetry']['kind'] for p in packets}, {'event_ack', 'value'})
        value = next(p['telemetry'] for p in packets if p['telemetry']['kind'] == 'value')
        self.assertEqual((value['block_uid'], value['value']), ('result-a', 'Ayu'))
        await self.send(self.event())
        self.assertEqual((await self.kind('event_ack'))['status'], 'duplicate')
        await self.send(self.event(uid='form-b', event_id='b', answers={'nama': 'Budi'}))
        packets = [json.loads(await asyncio.wait_for(self.client.recv(), 3)) for _ in range(2)]
        value = next(p['telemetry'] for p in packets if p['telemetry']['kind'] == 'value')
        self.assertEqual((value['block_uid'], value['value']), ('result-b', 'Budi'))

    async def test_invalid_answers_and_inactive_sources_are_rejected(self):
        await self.run_program()
        for index, answers in enumerate(({}, {'nama': '', 'usia': 1, 'keluhan': 'Demam'},
                {'nama': 'A', 'usia': True, 'keluhan': 'Demam'},
                {'nama': 'A', 'usia': '12', 'keluhan': 'Demam'},
                {'nama': 'A', 'usia': 12, 'keluhan': 'Unknown'})):
            await self.send(self.event(event_id=str(index), answers=answers))
            self.assertEqual((await self.kind('event_ack'))['status'], 'rejected')
        await self.send(self.event(uid='deleted'))
        self.assertEqual((await self.kind('event_ack'))['status'], 'rejected')

    async def test_form_without_handler_cannot_submit(self):
        await self.run_program(code="hospital.form('form-a', 'A', [{'label':'nama','type':'text'}])")
        await self.send(self.event(answers={'nama': 'Ayu'}))
        self.assertEqual((await self.kind('event_ack'))['status'], 'rejected')

    def test_duplicate_form_error_message(self):
        session = server.HospitalWidgetSession('p', 's', {}, lambda **p: None, lambda _: None, ['f1', 'f2'], hal.hospital)
        session.form('f1', 'Pendaftaran', [{'label': 'Nama Pasien', 'type': 'text'}])
        with self.assertRaises(ValueError) as ctx:
            session.form('f2', 'Pendaftaran', [{'label': 'Keluhan', 'type': 'text'}])
        self.assertEqual(
            str(ctx.exception),
            "Formulir dengan nama 'Pendaftaran' sudah dibuat oleh blok lain. Gunakan hanya satu balok formulir untuk nama ini, atau gunakan nama yang berbeda."
        )

    async def test_buttons_dispatch_once_to_the_correct_handler(self):
        await self.run_program(code='''
def a(): hospital.report('result-a', 'display', 'A')
def b(): hospital.report('result-b', 'display', 'B')
hospital.on_button('button-a', a)
hospital.on_button('button-b', b)
''')
        await self.send(self.event(uid='button-a', topic='button'))
        self.assertEqual((await self.kind('value'))['value'], 'A')
        await self.send(self.event(uid='button-a', topic='button'))
        self.assertEqual((await self.kind('event_ack'))['status'], 'duplicate')
        await self.send(self.event(uid='button-b', topic='button', event_id='b'))
        self.assertEqual((await self.kind('value'))['block_uid'], 'result-b')

    async def test_widget_packets_are_not_broadcast_to_another_connection(self):
        await self.run_program()
        other = await self.connect()
        await self.send(self.event())
        await self.kind('value')
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(other.recv(), .1)

    async def test_connections_projects_and_replaced_sessions_are_isolated(self):
        await self.run_program()
        other = await self.connect()
        await self.send(self.event(), other)
        self.assertEqual((await self.kind('event_ack', other))['status'], 'rejected')
        await self.run_program(client=other, project='other')
        await self.send(self.event(), other)
        self.assertEqual((await self.kind('event_ack', other))['status'], 'rejected')
        await self.run_program(session='new')
        await self.send(self.event())
        self.assertEqual((await self.kind('event_ack'))['status'], 'rejected')
        await self.send({'type': 'stop', 'project_id': 'p', 'session_id': 's'})
        await self.receive(lambda p: p.get('type') == 'error')
        await self.send(self.event(event_id='new-event', session='new'))
        packets = [json.loads(await asyncio.wait_for(self.client.recv(), 3)) for _ in range(2)]
        self.assertTrue(any(p.get('telemetry', {}).get('value') == 'Ayu' for p in packets))

    async def test_stock_waits_for_json_ack_and_stop_wakes_waiter(self):
        program = '''import time
def scan():
    hospital.record_medicine_stock()
    hospital.report('stock', 'display', hospital.get_medicine_stock())
hospital.on_scan('scan', scan)
'''
        await self.run_program(code=program)
        event = self.event(uid='scan', topic='scan', barcode='A', mode='out', jumlah=2)
        await self.send(event)
        command = await self.kind('command')
        self.assertEqual(command['arguments'], {'barcode': 'A', 'mode': 'out', 'qty': 2})
        await self.send({'type': 'hospital_widget_result', 'project_id': 'p', 'session_id': 's',
                         'request_id': 'unknown', 'result': {'ok': True}})
        await self.receive(lambda p: p.get('type') == 'error')
        await self.send({'type': 'hospital_widget_result', 'project_id': 'p', 'session_id': 's',
                         'request_id': command['request_id'], 'result': {'ok': True,
                         'snapshot_version': 1, 'snapshot': {'obat': [{'barcode': 'A', 'stok': 3}]}}})
        self.assertEqual((await self.kind('value'))['value'], 3)
        await self.send({**event, 'event_id': 'wait-stop'})
        await self.kind('command')
        await self.send({'type': 'stop', 'project_id': 'p', 'session_id': 's'})
        await self.kind('closed')
        await self.send({**event, 'event_id': 'stopped'})
        self.assertEqual((await self.kind('event_ack'))['status'], 'rejected')

    async def test_disconnect_closes_runtime(self):
        await self.run_program()
        peer = next(iter(server.connected_clients))
        # Confirm a running execution is interrupted without a client stop packet.
        await self.client.close()
        for _ in range(30):
            if peer not in server.connected_clients:
                break
            await asyncio.sleep(.01)
        self.assertNotIn(peer, server.connected_clients)

    async def test_jitsi_delegation_is_preserved(self):
        hal.telemetry.send.reset_mock()
        session = server.HospitalWidgetSession('p', 's', {}, lambda **p: None, lambda _: None, [], hal.hospital)
        session.open_jitsi('room', 'Ayu', 'patient')
        hal.telemetry.send.assert_called_once_with(action='open_jitsi', roomName='room',
                                                   displayName='Ayu', role='patient', subject='')
        session.close_jitsi()
        hal.telemetry.send.assert_called_with(action='close_jitsi')


if __name__ == '__main__':
    unittest.main()
