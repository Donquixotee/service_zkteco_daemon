import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src.device_client import device_connection
from src.main import build_odoo_client, load_configuration
from src.matching import index_employees, match_device_user

LINK_MODEL = 'biometric.attendance.devices'
DEVICE_MODEL = 'biometric.config'
REPORT_COLUMNS = ['device', 'device_user_id', 'device_name', 'employee_id', 'employee_name', 'status']


def read_device_users(device):
    with device_connection(device) as client:
        return [{'user_id': str(user.user_id), 'name': user.name or ''}
                for user in client.get_users() or []]


def odoo_device_id(odoo, serial_number):
    found = odoo.call(DEVICE_MODEL, 'search_read',
                      args=[[('serialnumber', '=', serial_number)]], kwargs={'fields': ['name']})
    return found[0]['id'] if found else None


def existing_links(odoo, device_id):
    rows = odoo.call(LINK_MODEL, 'search_read', args=[[('device_id', '=', device_id)]],
                     kwargs={'fields': ['biometric_attendance_id', 'employee_id']})
    return {str(row['biometric_attendance_id']) for row in rows}


def build_rows(odoo, devices, employee_index):
    rows = []
    for device in devices:
        device_id = odoo_device_id(odoo, device['serial_number'])
        if not device_id:
            rows.append({'device': device['name'], 'device_user_id': '', 'device_name': '',
                         'employee_id': '', 'employee_name': '',
                         'status': 'device serial %s not found in Odoo' % device['serial_number']})
            continue
        linked = existing_links(odoo, device_id)
        for user in read_device_users(device):
            employee = match_device_user(user['name'], employee_index)
            if user['user_id'] in linked:
                status = 'already linked'
            elif employee:
                status = 'match'
            elif not user['name'].strip():
                status = 'device user has no name, map by hand'
            else:
                status = 'no match, map by hand'
            rows.append({'device': device['name'],
                         'device_user_id': user['user_id'],
                         'device_name': user['name'],
                         'employee_id': employee['id'] if employee else '',
                         'employee_name': employee['name'] if employee else '',
                         'status': status,
                         '_device_id': device_id})
    return rows


def write_report(rows, path):
    with open(path, 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def load_report(path, devices, odoo):
    device_ids = {device['name']: odoo_device_id(odoo, device['serial_number']) for device in devices}
    with open(path, newline='', encoding='utf-8-sig') as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row['_device_id'] = device_ids.get(row['device'])
    return rows


def apply_links(odoo, rows):
    creatable = [row for row in rows
                 if row.get('employee_id') and row.get('_device_id')
                 and row.get('status') != 'already linked']
    if not creatable:
        print('Nothing to create.')
        return 0
    payload = [{'employee_id': int(row['employee_id']),
                'biometric_attendance_id': str(row['device_user_id']),
                'device_id': int(row['_device_id'])} for row in creatable]
    odoo.call(LINK_MODEL, 'create', args=[payload])
    print('Created %s link(s).' % len(payload))
    return len(payload)


def summarise(rows):
    counts = {}
    for row in rows:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    for status, count in sorted(counts.items(), key=lambda item: -item[1]):
        print('  %-40s %s' % (status, count))


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Match device users to Odoo employees and create the link rows.')
    parser.add_argument('--config', default=os.getenv('ZK_CONFIG_PATH', 'config/daemon.yml'))
    parser.add_argument('--report', default='employee_links.csv')
    parser.add_argument('--apply', action='store_true',
                        help='Create the link rows. Without it, only the CSV report is written.')
    parser.add_argument('--from-csv', dest='from_csv',
                        help='Apply a hand-corrected CSV instead of probing the devices again.')
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    load_dotenv()
    configuration = load_configuration(arguments.config)
    devices = configuration.get('devices', [])
    odoo = build_odoo_client(configuration.get('odoo_rpc', {}))
    odoo.authenticate()

    if arguments.from_csv:
        rows = load_report(arguments.from_csv, devices, odoo)
        print('Loaded %s row(s) from %s' % (len(rows), arguments.from_csv))
        summarise(rows)
        return 0 if apply_links(odoo, rows) >= 0 else 1

    employees = odoo.call('hr.employee', 'search_read', args=[[('active', '=', True)]],
                          kwargs={'fields': ['id', 'name']})
    employee_index, ambiguous = index_employees(employees)
    print('Loaded %s active employees from Odoo' % len(employees))
    if ambiguous:
        print('WARNING: %s duplicated employee name(s) cannot be auto-matched' % len(ambiguous))

    rows = build_rows(odoo, devices, employee_index)
    write_report(rows, arguments.report)
    print('\nWrote %s\n' % arguments.report)
    summarise(rows)

    if arguments.apply:
        print('')
        apply_links(odoo, rows)
    else:
        print('\nReview the CSV, fill employee_id where status says "map by hand",')
        print('then apply it with:  python tools\\link_employees.py --from-csv %s' % arguments.report)
    return 0


if __name__ == '__main__':
    sys.exit(main())
