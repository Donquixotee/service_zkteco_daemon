import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src.device_client import device_connection
from src.main import load_configuration

READ_ONLY_ATTRIBUTES = (
    ('Serial number', 'get_serialnumber'),
    ('Model', 'get_device_name'),
    ('Firmware', 'get_firmware_version'),
    ('Platform', 'get_platform'),
    ('Device clock', 'get_time'),
)


def describe(client, device):
    print('--- %s (%s:%s) ---' % (device['name'], device['ip'], device.get('port', 4370)))
    for label, method in READ_ONLY_ATTRIBUTES:
        try:
            print('  %-14s %s' % (label + ':', getattr(client, method)()))
        except Exception as error:
            print('  %-14s unavailable (%s)' % (label + ':', error))

    users = client.get_users() or []
    print('  %-14s %s' % ('Users:', len(users)))
    for user in users[:10]:
        print('      uid=%s user_id=%s name=%r card=%s privilege=%s'
              % (user.uid, user.user_id, user.name, user.card, user.privilege))
    if len(users) > 10:
        print('      ... %s more' % (len(users) - 10))

    punches = client.get_attendance() or []
    print('  %-14s %s' % ('Punches:', len(punches)))
    if punches:
        stamps = [punch.timestamp for punch in punches]
        print('      oldest %s' % min(stamps))
        print('      newest %s' % max(stamps))
        for punch in sorted(punches, key=lambda item: item.timestamp)[-5:]:
            print('      user_id=%s %s status=%s punch=%s'
                  % (punch.user_id, punch.timestamp, punch.status, punch.punch))


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Read-only inspection of the configured devices. Writes nothing.')
    parser.add_argument('--config', default=os.getenv('ZK_CONFIG_PATH', 'config/daemon.yml'))
    parser.add_argument('--device', help='Only probe the device with this name')
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    load_dotenv()
    devices = load_configuration(arguments.config).get('devices', [])
    if arguments.device:
        devices = [device for device in devices if device['name'] == arguments.device]
    if not devices:
        raise SystemExit('No matching devices in %s' % arguments.config)

    failures = 0
    for device in devices:
        try:
            with device_connection(device) as client:
                describe(client, device)
        except Exception as error:
            failures += 1
            print('--- %s (%s) ---' % (device['name'], device['ip']))
            print('  FAILED: %s' % error)
        print('')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
