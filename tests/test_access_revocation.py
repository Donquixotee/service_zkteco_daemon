import unittest

from src import device_client
from src.poller import DevicePoller


class StubUser:

    def __init__(self, uid, user_id, name, privilege=0, password='secret', group_id='1', card=4242):
        self.uid = uid
        self.user_id = user_id
        self.name = name
        self.privilege = privilege
        self.password = password
        self.group_id = group_id
        self.card = card


class StubTemplate:

    def __init__(self, uid, fid):
        self.uid = uid
        self.fid = fid


class StubZK:

    def __init__(self, users, templates, fail_on_uid=None):
        self.users = users
        self.templates = templates
        self.fail_on_uid = fail_on_uid
        self.deleted = []
        self.written = []
        self.disabled = False
        self.enabled = False
        self.refreshed = False

    def connect(self):
        return self

    def disconnect(self):
        return True

    def get_users(self):
        return self.users

    def get_templates(self):
        return self.templates

    def disable_device(self):
        self.disabled = True

    def enable_device(self):
        self.enabled = True

    def refresh_data(self):
        self.refreshed = True

    def delete_user_template(self, uid=0, temp_id=0, user_id=''):
        if uid == self.fail_on_uid:
            raise RuntimeError('device refused')
        self.deleted.append((uid, temp_id))
        return True

    def set_user(self, uid=None, name='', privilege=0, password='', group_id='', user_id='', card=0):
        self.written.append({'uid': uid, 'name': name, 'privilege': privilege, 'password': password,
                             'group_id': group_id, 'user_id': user_id, 'card': card})
        return True


class RevokeAccessTest(unittest.TestCase):

    def setUp(self):
        self.original_zk = device_client.ZK
        self.device = {'name': 'Entrance', 'ip': '192.168.1.201', 'port': 4370}

    def tearDown(self):
        device_client.ZK = self.original_zk

    def _install(self, stub):
        device_client.ZK = lambda *args, **kwargs: stub
        return stub

    def test_deletes_every_finger_of_that_user_only(self):
        stub = self._install(StubZK(
            users=[StubUser(uid=3, user_id='88', name='LEAVER')],
            templates=[StubTemplate(3, 0), StubTemplate(3, 1), StubTemplate(4, 0)]))
        device_client.revoke_access(self.device, [{'link_id': 1, 'pin': '88', 'name': 'LEAVER'}])
        self.assertEqual(sorted(stub.deleted), [(3, 0), (3, 1)])

    def test_clears_password_and_card_but_keeps_identity(self):
        stub = self._install(StubZK(
            users=[StubUser(uid=3, user_id='88', name='LEAVER', privilege=0, group_id='2')],
            templates=[StubTemplate(3, 0)]))
        device_client.revoke_access(self.device, [{'link_id': 1, 'pin': '88', 'name': 'LEAVER'}])
        written = stub.written[0]
        self.assertEqual(written['password'], '')
        self.assertEqual(written['card'], 0)
        self.assertEqual(written['uid'], 3)
        self.assertEqual(written['user_id'], '88')
        self.assertEqual(written['name'], 'LEAVER')
        self.assertEqual(written['group_id'], '2')

    def test_reports_the_number_of_fingerprints_removed(self):
        self._install(StubZK(users=[StubUser(uid=3, user_id='88', name='LEAVER')],
                             templates=[StubTemplate(3, 0), StubTemplate(3, 1)]))
        results = device_client.revoke_access(self.device, [{'link_id': 1, 'pin': '88', 'name': 'LEAVER'}])
        self.assertEqual(results, [{'link_id': 1, 'ok': True, 'fingerprints': 2}])

    def test_somebody_absent_from_the_reader_counts_as_done(self):
        self._install(StubZK(users=[], templates=[]))
        results = device_client.revoke_access(self.device, [{'link_id': 7, 'pin': '88', 'name': 'GONE'}])
        self.assertEqual(results, [{'link_id': 7, 'ok': True, 'fingerprints': 0}])

    def test_a_device_refusal_is_reported_not_raised(self):
        self._install(StubZK(users=[StubUser(uid=3, user_id='88', name='LEAVER')],
                             templates=[StubTemplate(3, 0)], fail_on_uid=3))
        results = device_client.revoke_access(self.device, [{'link_id': 1, 'pin': '88', 'name': 'LEAVER'}])
        self.assertFalse(results[0]['ok'])
        self.assertIn('refused', results[0]['error'])

    def test_one_failure_does_not_stop_the_others(self):
        self._install(StubZK(
            users=[StubUser(uid=3, user_id='88', name='LEAVER'), StubUser(uid=5, user_id='89', name='OTHER')],
            templates=[StubTemplate(3, 0), StubTemplate(5, 0)], fail_on_uid=3))
        results = device_client.revoke_access(self.device, [
            {'link_id': 1, 'pin': '88', 'name': 'LEAVER'},
            {'link_id': 2, 'pin': '89', 'name': 'OTHER'}])
        self.assertFalse(results[0]['ok'])
        self.assertTrue(results[1]['ok'])

    def test_the_reader_is_re_enabled_even_when_a_write_fails(self):
        stub = self._install(StubZK(users=[StubUser(uid=3, user_id='88', name='LEAVER')],
                                    templates=[StubTemplate(3, 0)], fail_on_uid=3))
        device_client.revoke_access(self.device, [{'link_id': 1, 'pin': '88', 'name': 'LEAVER'}])
        self.assertTrue(stub.disabled)
        self.assertTrue(stub.enabled)


class RecordingOdoo:

    def __init__(self, pending):
        self.pending = pending
        self.confirmed = None
        self.asked = []

    def pending_revocations(self, serial_number):
        self.asked.append(serial_number)
        return self.pending

    def confirm_revocations(self, serial_number, results):
        self.confirmed = results
        return {'revoked': len(results), 'failed': 0}


class PollerRevocationTest(unittest.TestCase):

    def setUp(self):
        self.original_revoke = device_client.revoke_access
        self.calls = []

    def tearDown(self):
        device_client.revoke_access = self.original_revoke

    def _poller(self, odoo):
        return DevicePoller(odoo, cursor_store=None)

    def test_a_device_without_the_flag_is_never_asked(self):
        odoo = RecordingOdoo({'enabled': True, 'pending': [{'link_id': 1, 'pin': '88'}]})
        self._poller(odoo).revoke_departed_employees(
            {'name': 'Entrance', 'serial_number': 'S1', 'allow_access_revocation': False})
        self.assertEqual(odoo.asked, [])

    def test_nothing_is_confirmed_when_nobody_is_pending(self):
        odoo = RecordingOdoo({'enabled': True, 'pending': []})
        self._poller(odoo).revoke_departed_employees(
            {'name': 'Entrance', 'serial_number': 'S1', 'allow_access_revocation': True})
        self.assertIsNone(odoo.confirmed)

    def test_an_odoo_error_stops_the_cycle_without_touching_the_reader(self):
        odoo = RecordingOdoo({'error': 'unknown_device'})
        poller = self._poller(odoo)
        poller.revoke_departed_employees(
            {'name': 'Entrance', 'serial_number': 'S1', 'allow_access_revocation': True})
        self.assertIsNone(odoo.confirmed)


if __name__ == '__main__':
    unittest.main()
