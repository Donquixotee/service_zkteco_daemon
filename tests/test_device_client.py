import unittest
from datetime import datetime

from zk.attendance import Attendance

from src import device_client


class StubZK:

    def __init__(self, punches, refuse=False):
        self.punches = punches
        self.refuse = refuse
        self.disconnected = False

    def connect(self):
        return None if self.refuse else self

    def disconnect(self):
        self.disconnected = True

    def get_attendance(self):
        return self.punches


class PunchWithoutTimestamp:
    user_id = 5


class DeviceClientTest(unittest.TestCase):

    def setUp(self):
        self.original_zk = device_client.ZK
        self.device = {'name': 'Bench', 'ip': '192.168.1.201', 'port': 4370}

    def tearDown(self):
        device_client.ZK = self.original_zk

    def _install(self, stub):
        device_client.ZK = lambda *args, **kwargs: stub
        return stub

    def test_converts_device_objects_to_plain_punches(self):
        self._install(StubZK([
            Attendance(user_id=7, timestamp=datetime(2026, 9, 12, 8, 0, 0), status=0),
            Attendance(user_id='8', timestamp=datetime(2026, 9, 12, 17, 30, 45), status=1),
        ]))
        self.assertEqual(device_client.read_punches(self.device), [
            {'user_id': '7', 'timestamp': '2026-09-12 08:00:00'},
            {'user_id': '8', 'timestamp': '2026-09-12 17:30:45'},
        ])

    def test_numeric_user_id_becomes_string(self):
        self._install(StubZK([Attendance(user_id=7, timestamp=datetime(2026, 9, 12, 8, 0), status=0)]))
        self.assertIsInstance(device_client.read_punches(self.device)[0]['user_id'], str)

    def test_malformed_punch_is_skipped(self):
        self._install(StubZK([
            PunchWithoutTimestamp(),
            Attendance(user_id=7, timestamp=datetime(2026, 9, 12, 8, 0), status=0),
        ]))
        self.assertEqual(len(device_client.read_punches(self.device)), 1)

    def test_empty_device_log_returns_nothing(self):
        self._install(StubZK([]))
        self.assertEqual(device_client.read_punches(self.device), [])

    def test_disconnects_after_reading(self):
        stub = self._install(StubZK([Attendance(user_id=7, timestamp=datetime(2026, 9, 12, 8, 0), status=0)]))
        device_client.read_punches(self.device)
        self.assertTrue(stub.disconnected)

    def test_refused_connection_raises_device_unreachable(self):
        self._install(StubZK([], refuse=True))
        with self.assertRaises(device_client.DeviceUnreachable):
            device_client.read_punches(self.device)

    def test_no_disconnect_attempted_when_never_connected(self):
        stub = self._install(StubZK([], refuse=True))
        with self.assertRaises(device_client.DeviceUnreachable):
            device_client.read_punches(self.device)
        self.assertFalse(stub.disconnected)


if __name__ == '__main__':
    unittest.main()


class ClearAllDataTest(unittest.TestCase):

    def test_sends_bytes_so_the_packet_can_be_built(self):
        from struct import pack
        from src.device_client import clear_all_data
        sent = {}

        class Stub:
            next_uid = 99

            def _ZK__send_command(self, command, command_string):
                sent['command'] = command
                sent['payload'] = command_string
                pack('<4H', command, 0, 1, 2) + command_string
                return {'status': True}

        clear_all_data(Stub())
        self.assertIsInstance(sent['payload'], bytes)
        self.assertEqual(sent['command'], 14)

    def test_resets_the_next_uid_so_users_start_at_one(self):
        from src.device_client import clear_all_data

        class Stub:
            next_uid = 801

            def _ZK__send_command(self, command, command_string):
                return {'status': True}

        stub = Stub()
        clear_all_data(stub)
        self.assertEqual(stub.next_uid, 1)

    def test_refusal_raises_instead_of_reporting_success(self):
        from src.device_client import DeviceWipeFailed, clear_all_data

        class Stub:
            next_uid = 5

            def _ZK__send_command(self, command, command_string):
                return {'status': False, 'code': 0}

        with self.assertRaises(DeviceWipeFailed):
            clear_all_data(Stub())

    def test_pyzk_clear_data_is_still_broken_so_we_keep_our_own(self):
        import zk.base
        import inspect
        source = inspect.getsource(zk.base.ZK.clear_data)
        self.assertIn("command_string = ''", source)


class WriteUsersTest(unittest.TestCase):

    def setUp(self):
        self.original_zk = device_client.ZK
        self.device = {'name': 'Entrance', 'ip': '192.168.1.201', 'port': 4370}

    def tearDown(self):
        device_client.ZK = self.original_zk

    def install(self, existing, failing_pins=()):
        written = []

        class User:
            def __init__(self, uid, user_id):
                self.uid = uid
                self.user_id = user_id

        class Stub:
            disabled = False
            enabled = False

            def connect(self_inner):
                return self_inner

            def disconnect(self_inner):
                pass

            def get_users(self_inner):
                return [User(uid, pin) for uid, pin in existing]

            def disable_device(self_inner):
                self_inner.disabled = True

            def enable_device(self_inner):
                self_inner.enabled = True

            def set_user(self_inner, uid, name, privilege, password, group_id, user_id, card):
                if user_id in failing_pins:
                    raise RuntimeError('device refused')
                written.append({'uid': uid, 'name': name, 'pin': user_id})

        stub = Stub()
        device_client.ZK = lambda *args, **kwargs: stub
        return stub, written

    def test_new_people_get_uids_after_the_highest_existing(self):
        _, written = self.install(existing=[(1, '21'), (2, '105'), (3, '1457')])
        device_client.write_users(self.device, [
            {'employee_id': 7, 'pin': '1458', 'name': 'NEW ONE'},
            {'employee_id': 8, 'pin': '1459', 'name': 'NEW TWO'},
        ])
        self.assertEqual([entry['uid'] for entry in written], [4, 5])

    def test_existing_badge_keeps_its_uid_so_fingerprints_survive(self):
        _, written = self.install(existing=[(1, '21'), (2, '105')])
        device_client.write_users(self.device, [{'employee_id': 7, 'pin': '105', 'name': 'RENAMED'}])
        self.assertEqual(written[0]['uid'], 2)

    def test_nobody_elses_uid_is_touched(self):
        _, written = self.install(existing=[(1, '21'), (2, '105')])
        device_client.write_users(self.device, [{'employee_id': 7, 'pin': '999', 'name': 'NEW'}])
        self.assertEqual([entry['pin'] for entry in written], ['999'])

    def test_a_refused_write_is_reported_and_does_not_stop_the_rest(self):
        _, written = self.install(existing=[], failing_pins={'111'})
        results = device_client.write_users(self.device, [
            {'employee_id': 1, 'pin': '111', 'name': 'BAD'},
            {'employee_id': 2, 'pin': '222', 'name': 'GOOD'},
        ])
        self.assertFalse(results[0]['ok'])
        self.assertTrue(results[1]['ok'])
        self.assertEqual([entry['pin'] for entry in written], ['222'])

    def test_device_is_locked_during_the_write_and_released_after(self):
        stub, _ = self.install(existing=[])
        device_client.write_users(self.device, [{'employee_id': 1, 'pin': '1', 'name': 'X'}])
        self.assertTrue(stub.disabled)
        self.assertTrue(stub.enabled)

    def test_empty_list_writes_nothing(self):
        _, written = self.install(existing=[(1, '21')])
        self.assertEqual(device_client.write_users(self.device, []), [])
        self.assertEqual(written, [])
