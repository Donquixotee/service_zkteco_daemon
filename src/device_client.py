import logging
from contextlib import contextmanager

from zk import ZK, const

logger = logging.getLogger(__name__)

DEVICE_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'


class DeviceUnreachable(Exception):
    pass


class DeviceWipeFailed(Exception):
    pass


def clear_all_data(client):
    response = client._ZK__send_command(const.CMD_CLEAR_DATA, b'')
    if not response.get('status'):
        raise DeviceWipeFailed('Device refused to clear its data: %s' % response)
    client.next_uid = 1
    return True


@contextmanager
def device_connection(device):
    client = ZK(device['ip'],
                port=device.get('port', 4370),
                password=device.get('password', 0),
                timeout=device.get('timeout', 30),
                force_udp=device.get('force_udp', False),
                ommit_ping=device.get('ommit_ping', False))
    connection = None
    try:
        connection = client.connect()
        if not connection:
            raise DeviceUnreachable("Device %s refused the connection" % device['name'])
        yield client
    finally:
        if connection:
            try:
                client.disconnect()
            except Exception as error:
                logger.debug("Unclean disconnect from %s: %s", device['name'], error)


def next_free_uid(users):
    return max((int(user.uid) for user in users), default=0) + 1


def write_users(device, people):
    written = []
    with device_connection(device) as client:
        existing = client.get_users() or []
        uid_by_pin = {str(user.user_id): int(user.uid) for user in existing}
        candidate_uid = next_free_uid(existing)
        client.disable_device()
        try:
            for person in people:
                pin = str(person['pin'])
                uid = uid_by_pin.get(pin, candidate_uid)
                try:
                    client.set_user(uid=uid, name=person['name'], privilege=0,
                                    password='', group_id='', user_id=pin, card=0)
                except Exception as error:
                    logger.error("Could not write %s to %s: %s", person['name'], device['name'], error)
                    written.append({'employee_id': person['employee_id'], 'pin': pin,
                                    'ok': False, 'error': str(error)})
                    continue
                if pin not in uid_by_pin:
                    uid_by_pin[pin] = uid
                    candidate_uid += 1
                written.append({'employee_id': person['employee_id'], 'pin': pin,
                                'uid': uid, 'ok': True})
        finally:
            client.enable_device()
    return written


def read_punches(device):
    with device_connection(device) as client:
        raw_punches = client.get_attendance() or []
        punches = []
        for punch in raw_punches:
            if not hasattr(punch, 'user_id') or not hasattr(punch, 'timestamp'):
                logger.warning("Skipping malformed punch on %s", device['name'])
                continue
            punches.append({'user_id': str(punch.user_id),
                            'timestamp': punch.timestamp.strftime(DEVICE_TIME_FORMAT)})
        logger.info("Read %s punches from %s", len(punches), device['name'])
        return punches
