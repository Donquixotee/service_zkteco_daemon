import logging

from .device_client import read_punches

logger = logging.getLogger(__name__)


class DevicePoller:

    def __init__(self, odoo_client, cursor_store):
        self.odoo = odoo_client
        self.cursors = cursor_store

    def poll_all(self, devices):
        for device in devices:
            try:
                self.poll_device(device)
            except Exception as error:
                logger.error("Polling failed for device %s: %s", device.get('name'), error)

    def poll_device(self, device):
        serial_number = device['serial_number']
        punches = read_punches(device)
        pending = self._punches_after_cursor(serial_number, punches)
        if not pending:
            logger.info("Device %s has no new punches", device['name'])
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

    def _punches_after_cursor(self, serial_number, punches):
        cursor = self.cursors.last_timestamp(serial_number)
        if not cursor:
            return punches
        return [punch for punch in punches if punch['timestamp'] > cursor]
