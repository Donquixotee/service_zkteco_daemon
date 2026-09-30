import argparse
import base64
import getpass
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src.device_client import device_connection
from src.main import load_configuration
from src.odoo_client import OdooClient
from src.provisioning import assign_pins

LINK_MODEL = 'biometric.attendance.devices'
DEVICE_MODEL = 'biometric.config'
CONFIRMATION_WORD = 'WIPE'


def backup_device(client, device, directory):
    os.makedirs(directory, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    path = os.path.join(directory, '%s-%s.json' % (device['serial_number'], stamp))

    users = [{'uid': user.uid, 'user_id': str(user.user_id), 'name': user.name,
              'privilege': user.privilege, 'password': user.password,
              'group_id': user.group_id, 'card': user.card}
             for user in client.get_users() or []]
    templates = [{'uid': template.uid, 'fid': template.fid, 'valid': template.valid,
                  'template': base64.b64encode(template.template).decode()}
                 for template in client.get_templates() or []]
    punches = [{'user_id': str(punch.user_id), 'timestamp': punch.timestamp.isoformat(),
                'status': punch.status, 'punch': punch.punch}
               for punch in client.get_attendance() or []]

    with open(path, 'w', encoding='utf-8') as handle:
        json.dump({'device': device['name'], 'serial_number': device['serial_number'],
                   'taken_at': stamp, 'users': users, 'templates': templates,
                   'attendance': punches}, handle)
    print('    backup written: %s (%s users, %s fingerprints, %s punches)'
          % (path, len(users), len(templates), len(punches)))
    return path, len(users), len(templates), len(punches)


def network_snapshot(client):
    try:
        ip, mask, gateway = client.get_network_params()
        return {'ip': ip, 'netmask': mask, 'gateway': gateway}
    except Exception as error:
        return {'error': str(error)}


def describe_network(label, snapshot):
    if 'error' in snapshot:
        print('    %-16s unavailable (%s)' % (label, snapshot['error']))
    else:
        print('    %-16s ip=%s mask=%s gateway=%s'
              % (label, snapshot['ip'], snapshot['netmask'], snapshot['gateway']))


def push_assignments(client, assignments):
    written = 0
    for index, assignment in enumerate(assignments, start=1):
        client.set_user(uid=index, name=assignment['device_name'], privilege=0,
                        password='', group_id='', user_id=assignment['pin'], card=0)
        written += 1
        if written % 25 == 0:
            print('    written %s/%s' % (written, len(assignments)))
    return written


def relink_in_odoo(odoo, device_record_id, assignments):
    stale = odoo.call(LINK_MODEL, 'search', args=[[('device_id', '=', device_record_id)]])
    if stale:
        odoo.call(LINK_MODEL, 'unlink', args=[stale])
    payload = [{'employee_id': assignment['employee_id'],
                'biometric_attendance_id': assignment['pin'],
                'device_id': device_record_id} for assignment in assignments]
    odoo.call(LINK_MODEL, 'create', args=[payload])
    return len(stale), len(payload)


def odoo_device_id(odoo, serial_number):
    found = odoo.call(DEVICE_MODEL, 'search_read',
                      args=[[('serialnumber', '=', serial_number)]], kwargs={'fields': ['name']})
    if not found:
        raise SystemExit('No Odoo device record carries serial %s' % serial_number)
    return found[0]['id']


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Push Odoo employees onto the readers and link them, optionally wiping first.')
    parser.add_argument('--config', default=os.getenv('ZK_CONFIG_PATH', 'config/daemon.yml'))
    parser.add_argument('--login', required=True, help='Odoo administrator login')
    parser.add_argument('--db', default=os.getenv('ODOO_DB'))
    parser.add_argument('--url', default=os.getenv('ODOO_URL'))
    parser.add_argument('--device', help='Only provision the device with this name')
    parser.add_argument('--id-source', choices=('barcode', 'employee'), default='barcode')
    parser.add_argument('--backup-dir', default='backups')
    parser.add_argument('--wipe', action='store_true',
                        help='Erase all users, fingerprints and logs on the reader first')
    parser.add_argument('--apply', action='store_true',
                        help='Actually write to the readers. Without it nothing is changed.')
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    load_dotenv()
    configuration = load_configuration(arguments.config)
    devices = configuration.get('devices', [])
    if arguments.device:
        devices = [device for device in devices if device['name'] == arguments.device]
    if not devices:
        raise SystemExit('No matching devices in %s' % arguments.config)

    password = getpass.getpass('Odoo password for %s: ' % arguments.login)
    odoo = OdooClient(url=arguments.url, db=arguments.db, login=arguments.login, password=password)
    odoo.authenticate()

    employees = odoo.call('hr.employee', 'search_read', args=[[('active', '=', True)]],
                          kwargs={'fields': ['id', 'name', 'barcode']})
    assignments, fallbacks, collisions = assign_pins(employees, arguments.id_source)

    print('Active employees in Odoo: %s' % len(employees))
    print('Device ids taken from: %s' % arguments.id_source)
    if fallbacks:
        print('Using the Odoo record number for %s employee(s) with no usable barcode:' % len(fallbacks))
        for name in fallbacks[:10]:
            print('    %s' % name)
        if len(fallbacks) > 10:
            print('    ... and %s more' % (len(fallbacks) - 10))
    for first, second, truncated in collisions:
        print('WARNING: %r and %r both show as %r on the reader' % (first, second, truncated))

    print('\nDevices to provision:')
    for device in devices:
        print('    %s (%s) serial %s' % (device['name'], device['ip'], device['serial_number']))

    if not arguments.apply:
        print('\nDry run. Nothing was changed.')
        print('Sample of what would be written:')
        for assignment in assignments[:10]:
            print('    id=%-10s name=%r' % (assignment['pin'], assignment['device_name']))
        print('\nRe-run with --apply to write. Add --wipe to erase the readers first.')
        return 0

    if arguments.wipe:
        print('\nThis ERASES every user, fingerprint and attendance record on:')
        for device in devices:
            print('    %s (%s)' % (device['name'], device['ip']))
        print('Fingerprints cannot be recovered. Everyone must re-enrol in person.')
        if input('Type %s to continue: ' % CONFIRMATION_WORD).strip() != CONFIRMATION_WORD:
            print('Aborted.')
            return 1

    for device in devices:
        print('\n=== %s ===' % device['name'])
        device_record_id = odoo_device_id(odoo, device['serial_number'])
        with device_connection(device) as client:
            client.disable_device()
            try:
                before = network_snapshot(client)
                describe_network('network before', before)
                backup_device(client, device, arguments.backup_dir)
                if arguments.wipe:
                    client.clear_data()
                    print('    device erased')
                    after = network_snapshot(client)
                    describe_network('network after', after)
                    if before != after:
                        print('    WARNING: network settings changed, check the reader')
                written = push_assignments(client, assignments)
                print('    %s users written' % written)
                client.refresh_data()
                remaining = len(client.get_users() or [])
                print('    reader now reports %s users' % remaining)
            finally:
                client.enable_device()
        removed, created = relink_in_odoo(odoo, device_record_id, assignments)
        print('    Odoo links: %s removed, %s created' % (removed, created))

    print('\nDone. Employees must now enrol their fingerprints at each reader.')
    print('Attendance recorded before this point stays on the devices only if you did not wipe.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
