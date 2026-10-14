import logging

from .device_client import read_punches, revoke_access, write_users

logger = logging.getLogger(__name__)


class DevicePoller:

    def __init__(self, odoo_client, cursor_store, watchdog=None):
        self.odoo = odoo_client
        self.cursors = cursor_store
        self.watchdog = watchdog

    def _progress(self):
        if self.watchdog:
            self.watchdog.progress()

    def poll_all(self, devices):
        for device in devices:
            self._progress()
            try:
                self.poll_device(device)
            except Exception as error:
                logger.error("Polling failed for device %s: %s", device.get('name'), error)
            self._progress()

    def poll_device(self, device):
        serial_number = device['serial_number']
        self.push_pending_users(device)
        punches = read_punches(device)
        pending = self._punches_after_cursor(serial_number, punches)
        if not pending:
            logger.info("Device %s has no new punches", device['name'])
            self.revoke_departed_employees(device)
            return
        response = self.odoo.send_punches(serial_number, pending)
        if not isinstance(response, dict) or response.get('error'):
            logger.error("Odoo rejected punches from %s: %s", device['name'], response)
            return
        logger.info("Device %s: sent %s, stored %s, already known %s",
                    device['name'], len(pending), response.get('created'), response.get('duplicates'))
        unmapped = response.get('unmapped_user_ids')
        if unmapped:
            logger.warning("Device %s has punches for users not linked to any employee: %s",
                           device['name'], unmapped)
        self.cursors.advance(serial_number, max(punch['timestamp'] for punch in pending))
        self.revoke_departed_employees(device)

    def revoke_departed_employees(self, device):
        if not device.get('allow_access_revocation'):
            return
        serial_number = device['serial_number']
        response = self.odoo.pending_revocations(serial_number)
        if not isinstance(response, dict) or response.get('error'):
            logger.error("Could not ask Odoo who should lose access on %s: %s", device['name'], response)
            return
        pending = response.get('pending') or []
        if not pending:
            return
        held_back = response.get('held_back') or 0
        if held_back:
            logger.warning("Device %s: Odoo held back %s further employee(s) this cycle",
                           device['name'], held_back)
        logger.info("Device %s: removing access for %s employee(s)", device['name'], len(pending))
        results = revoke_access(device, pending)
        confirmation = self.odoo.confirm_revocations(serial_number, results)
        logger.info("Device %s: Odoo recorded %s removed, %s failed",
                    device['name'], confirmation.get('revoked'), confirmation.get('failed'))

    def push_pending_users(self, device):
        serial_number = device['serial_number']
        response = self.odoo.pending_users(serial_number)
        if not isinstance(response, dict) or response.get('error'):
            logger.error("Could not ask Odoo for new users of %s: %s", device['name'], response)
            return
        pending = response.get('pending') or []
        if not pending:
            return
        logger.info("Device %s: %s employee(s) to add", device['name'], len(pending))
        results = write_users(device, pending)
        confirmation = self.odoo.confirm_users(serial_number, results)
        logger.info("Device %s: Odoo linked %s, refused %s",
                    device['name'], confirmation.get('created'), confirmation.get('failed'))

    def _punches_after_cursor(self, serial_number, punches):
        cursor = self.cursors.last_timestamp(serial_number)
        if not cursor:
            return punches
        return [punch for punch in punches if punch['timestamp'] > cursor]
