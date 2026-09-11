import logging
from contextlib import contextmanager

from zk import ZK

logger = logging.getLogger(__name__)

DEVICE_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'


class DeviceUnreachable(Exception):
    pass


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
