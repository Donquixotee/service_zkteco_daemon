import unittest

from src import poller as poller_module
from src.odoo_client import TimeoutSafeTransport, TimeoutTransport, transport_for
from src.poller import DevicePoller
from src.watchdog import Watchdog


class TransportTimeoutTest(unittest.TestCase):

    def test_https_gets_a_safe_transport_carrying_the_timeout(self):
        transport = transport_for('https://odoo.example.com', 30)
        self.assertIsInstance(transport, TimeoutSafeTransport)
        self.assertEqual(transport.timeout, 30)

    def test_http_gets_a_plain_transport_carrying_the_timeout(self):
        transport = transport_for('http://localhost:8069', 15)
        self.assertIsInstance(transport, TimeoutTransport)
        self.assertEqual(transport.timeout, 15)

    def test_the_timeout_reaches_the_connection(self):
        transport = transport_for('http://localhost:8069', 7)
        connection = transport.make_connection('localhost:8069')
        self.assertEqual(connection.timeout, 7)


class FakeClock:

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class WatchdogTest(unittest.TestCase):

    def build(self, limit=600):
        clock = FakeClock()
        fired = []
        watchdog = Watchdog(limit, on_hang=lambda: fired.append(True), clock=clock)
        return watchdog, clock, fired

    def test_quiet_while_progress_is_reported(self):
        watchdog, clock, fired = self.build()
        for _ in range(5):
            clock.advance(300)
            watchdog.progress()
            watchdog.check()
        self.assertEqual(fired, [])

    def test_fires_once_the_limit_is_exceeded(self):
        watchdog, clock, fired = self.build(limit=600)
        clock.advance(601)
        self.assertTrue(watchdog.check())
        self.assertEqual(len(fired), 1)

    def test_does_not_fire_exactly_at_the_limit(self):
        watchdog, clock, fired = self.build(limit=600)
        clock.advance(600)
        self.assertFalse(watchdog.check())

    def test_progress_resets_the_countdown(self):
        watchdog, clock, fired = self.build(limit=600)
        clock.advance(599)
        watchdog.progress()
        clock.advance(599)
        self.assertFalse(watchdog.check())


class StubOdoo:

    def __init__(self, failures=0):
        self.failures = failures
        self.sent = []

    def pending_users(self, serial_number):
        return {'pending': []}

    def send_punches(self, serial_number, punches):
        if self.failures:
            self.failures -= 1
            raise OSError('connection black holed')
        self.sent.append((serial_number, len(punches)))
        return {'created': len(punches), 'duplicates': 0, 'unmapped_user_ids': []}


class StubCursors:

    def __init__(self):
        self.cursor = {}

    def last_timestamp(self, serial_number):
        return self.cursor.get(serial_number)

    def advance(self, serial_number, timestamp):
        self.cursor[serial_number] = timestamp


class OdooOutageTest(unittest.TestCase):

    def setUp(self):
        self.original_read = poller_module.read_punches
        poller_module.read_punches = lambda device: [
            {'user_id': '7', 'timestamp': '2026-10-02 08:00:00'}]
        self.devices = [{'name': 'Entrance', 'serial_number': 'S1', 'ip': '192.168.1.201'}]

    def tearDown(self):
        poller_module.read_punches = self.original_read

    def test_an_outage_does_not_stop_the_agent(self):
        odoo = StubOdoo(failures=1)
        cursors = StubCursors()
        poller = DevicePoller(odoo, cursors)
        poller.poll_all(self.devices)
        self.assertEqual(odoo.sent, [])
        self.assertIsNone(cursors.last_timestamp('S1'))

    def test_it_catches_up_once_odoo_is_back(self):
        odoo = StubOdoo(failures=1)
        cursors = StubCursors()
        poller = DevicePoller(odoo, cursors)
        poller.poll_all(self.devices)
        poller.poll_all(self.devices)
        self.assertEqual(odoo.sent, [('S1', 1)])
        self.assertEqual(cursors.last_timestamp('S1'), '2026-10-02 08:00:00')

    def test_the_cursor_never_advances_past_a_failed_delivery(self):
        odoo = StubOdoo(failures=3)
        cursors = StubCursors()
        poller = DevicePoller(odoo, cursors)
        for _ in range(3):
            poller.poll_all(self.devices)
        self.assertIsNone(cursors.last_timestamp('S1'))

    def test_the_watchdog_sees_progress_during_an_outage(self):
        clock = FakeClock()
        watchdog = Watchdog(600, on_hang=lambda: None, clock=clock)
        poller = DevicePoller(StubOdoo(failures=1), StubCursors(), watchdog=watchdog)
        clock.advance(500)
        poller.poll_all(self.devices)
        self.assertEqual(watchdog.seconds_since_progress(), 0)


if __name__ == '__main__':
    unittest.main()
