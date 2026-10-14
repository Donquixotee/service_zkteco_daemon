import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src.device_client import device_connection
from src.main import load_configuration
from src.odoo_client import OdooClient


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Show which employees would lose their device credentials, without changing anything.')
    parser.add_argument('--config', default=os.getenv('ZK_CONFIG_PATH', 'config/daemon.yml'))
    parser.add_argument('--login', required=True, help='Odoo login')
    parser.add_argument('--db', default=os.getenv('ODOO_DB'))
    parser.add_argument('--url', default=os.getenv('ODOO_URL'))
    parser.add_argument('--device', help='Only look at the device with this name')
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    load_dotenv()
    devices = load_configuration(arguments.config).get('devices', [])
    if arguments.device:
        devices = [device for device in devices if device['name'] == arguments.device]
    if not devices:
        raise SystemExit('No matching devices in %s' % arguments.config)

    password = getpass.getpass('Odoo password for %s: ' % arguments.login)
    odoo = OdooClient(url=arguments.url, db=arguments.db, login=arguments.login, password=password)
    odoo.authenticate()

    total = 0
    for device in devices:
        print('\n=== %s ===' % device['name'])
        if not device.get('allow_access_revocation'):
            print('    allow_access_revocation is off in %s, this device would be skipped' % arguments.config)
        answer = odoo.pending_revocations(device['serial_number'])
        if not isinstance(answer, dict) or answer.get('error'):
            print('    Odoo answered: %s' % answer)
            continue
        if not answer.get('enabled'):
            print('    Remove Access When Archived is off on the Odoo device record')
            continue
        pending = answer.get('pending') or []
        if not pending:
            print('    nobody is waiting to lose access')
            continue
        held_back = answer.get('held_back') or 0

        with device_connection(device) as client:
            users = {str(user.user_id): user for user in client.get_users() or []}
            fingers = {}
            for template in client.get_templates() or []:
                fingers[template.uid] = fingers.get(template.uid, 0) + 1

        print('    %s employee(s) would have their fingerprint, password and card cleared:' % len(pending))
        for person in pending:
            user = users.get(str(person['pin']))
            if user is None:
                print('        %-8s %-28s not on this reader, nothing to clear'
                      % (person['pin'], person['name']))
                continue
            print('        %-8s %-28s uid=%-5s %s fingerprint(s) would be deleted'
                  % (person['pin'], person['name'], user.uid, fingers.get(user.uid, 0)))
        if held_back:
            print('    %s further employee(s) held back by the batch limit' % held_back)
        total += len(pending)

    print('\nDry run. Nothing was changed on any reader.')
    print('%s employee(s) would lose access in total.' % total)
    print('Fingerprints cannot be recovered. Anyone returning must enrol again in person.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
