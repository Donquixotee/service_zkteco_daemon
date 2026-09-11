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
