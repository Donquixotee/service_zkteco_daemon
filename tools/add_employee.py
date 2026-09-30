import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src.device_client import device_connection
from src.main import load_configuration
from src.odoo_client import OdooClient
from src.provisioning import device_name_for, usable_barcode

LINK_MODEL = 'biometric.attendance.devices'
DEVICE_MODEL = 'biometric.config'


def find_employee(odoo, name, employee_id):
    domain = [('active', '=', True)]
    domain += [('id', '=', employee_id)] if employee_id else [('name', 'ilike', name)]
    found = odoo.call('hr.employee', 'search_read', args=[domain],
                      kwargs={'fields': ['id', 'name', 'barcode']})
    if not found:
        raise SystemExit('No active employee matches %r' % (employee_id or name))
    if len(found) > 1:
        print('Several employees match:')
        for employee in found:
            print('    id=%-6s %s' % (employee['id'], employee['name']))
        raise SystemExit('Narrow it down with --employee-id')
    return found[0]


def odoo_device_id(odoo, serial_number):
    found = odoo.call(DEVICE_MODEL, 'search_read',
                      args=[[('serialnumber', '=', serial_number)]], kwargs={'fields': ['name']})
    if not found:
        raise SystemExit('No Odoo device record carries serial %s' % serial_number)
    return found[0]['id']


def next_free_uid(users):
    return max((int(user.uid) for user in users), default=0) + 1


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Add one employee to the readers without disturbing anybody else.')
    parser.add_argument('--login', required=True, help='Odoo administrator login')
    parser.add_argument('--db', default=os.getenv('ODOO_DB'))
    parser.add_argument('--url', default=os.getenv('ODOO_URL'))
    parser.add_argument('--config', default=os.getenv('ZK_CONFIG_PATH', 'config/daemon.yml'))
    parser.add_argument('--name', help='Employee name, or part of it')
    parser.add_argument('--employee-id', type=int, dest='employee_id')
    parser.add_argument('--apply', action='store_true', help='Actually write to the readers')
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    if not arguments.name and not arguments.employee_id:
        raise SystemExit('Give --name or --employee-id')
    load_dotenv()
    devices = load_configuration(arguments.config).get('devices', [])
    password = getpass.getpass('Odoo password for %s: ' % arguments.login)
    odoo = OdooClient(url=arguments.url, db=arguments.db, login=arguments.login, password=password)
    odoo.authenticate()

    employee = find_employee(odoo, arguments.name, arguments.employee_id)
    pin = usable_barcode(employee.get('barcode'))
    if not pin:
        raise SystemExit('%s has no usable badge number in Odoo. Set one first with assign_badges.py'
                         % employee['name'])
    device_name = device_name_for(employee['name'])
    print('Employee : %s (id=%s)' % (employee['name'], employee['id']))
    print('Badge    : %s' % pin)
    print('On reader: %r' % device_name)

    for device in devices:
        print('\n=== %s ===' % device['name'])
        device_record_id = odoo_device_id(odoo, device['serial_number'])
        with device_connection(device) as client:
            users = client.get_users() or []
            clash = [user for user in users if str(user.user_id) == pin]
            if clash:
                existing = clash[0]
                print('    badge %s already belongs to uid=%s %r' % (pin, existing.uid, existing.name))
                if existing.name != device_name:
                    raise SystemExit('Badge %s is taken by someone else on %s' % (pin, device['name']))
                uid = existing.uid
                print('    already present, will refresh the name on uid=%s' % uid)
            else:
                uid = next_free_uid(users)
                print('    %s users on the reader, next free uid=%s' % (len(users), uid))

            if not arguments.apply:
                print('    dry run, nothing written')
                continue

            client.disable_device()
            try:
                client.set_user(uid=uid, name=device_name, privilege=0, password='',
                                group_id='', user_id=pin, card=0)
            finally:
                client.enable_device()
            print('    written to the reader as uid=%s' % uid)

        existing_link = odoo.call(LINK_MODEL, 'search',
                                  args=[[('device_id', '=', device_record_id),
                                         ('employee_id', '=', employee['id'])]])
        if existing_link:
            odoo.call(LINK_MODEL, 'write', args=[existing_link, {'biometric_attendance_id': pin}])
            print('    Odoo link updated')
        else:
            odoo.call(LINK_MODEL, 'create', args=[{'employee_id': employee['id'],
                                                   'biometric_attendance_id': pin,
                                                   'device_id': device_record_id}])
            print('    Odoo link created')

    if arguments.apply:
        print('\nDone. %s must now enrol a fingerprint at each reader.' % employee['name'])
    else:
        print('\nDry run. Re-run with --apply to write.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
