import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src.device_client import device_connection
from src.main import build_odoo_client, load_configuration
from src.matching import differs_only_by_gendered_ending, index_employees, match_device_user, suggest_device_users

LINK_MODEL = 'biometric.attendance.devices'
DEVICE_MODEL = 'biometric.config'


def read_device_users(device):
    with device_connection(device) as client:
        return [{'user_id': str(user.user_id), 'name': user.name or ''}
                for user in client.get_users() or []]


def odoo_device_id(odoo, serial_number):
    found = odoo.call(DEVICE_MODEL, 'search_read',
                      args=[[('serialnumber', '=', serial_number)]], kwargs={'fields': ['name']})
    if not found:
        raise SystemExit('No Odoo device record carries serial %s' % serial_number)
    return found[0]['id']


def existing_links_by_employee(odoo, device_id):
    rows = odoo.call(LINK_MODEL, 'search_read', args=[[('device_id', '=', device_id)]],
                     kwargs={'fields': ['biometric_attendance_id', 'employee_id']})
    return {row['employee_id'][0]: str(row['biometric_attendance_id'])
            for row in rows if row['employee_id']}


def report_cross_device_consistency(users_by_device):
    names = list(users_by_device)
    if len(names) < 2:
        return
    maps = {name: {user['user_id']: user['name'] for user in users} for name, users in users_by_device.items()}
    first, second = names[0], names[1]
    shared = set(maps[first]) & set(maps[second])
    identical = sum(1 for user_id in shared if maps[first][user_id] == maps[second][user_id])
    print('User ids shared by %s and %s: %s, with identical names: %s'
          % (first, second, len(shared), identical))


def column(device_name, suffix):
    return '%s_%s' % (device_name.lower(), suffix)


def build_report(employees, devices, users_by_device, links_by_device):
    rows = []
    for employee in sorted(employees, key=lambda item: item['name']):
        row = {'employee_id': employee['id'], 'employee_name': employee['name']}
        for device in devices:
            name = device['name']
            users = users_by_device[name]
            index, _ = index_employees([{'id': user['user_id'], 'name': user['name']} for user in users])
            linked = links_by_device[name].get(employee['id'])
            if linked:
                row[column(name, 'user_id')] = linked
                row[column(name, 'status')] = 'already linked'
                row[column(name, 'suggestions')] = ''
                continue
            exact = match_device_user(employee['name'], index)
            if exact:
                row[column(name, 'user_id')] = exact['id']
                row[column(name, 'status')] = 'match'
                row[column(name, 'suggestions')] = ''
                continue
            suggestions = suggest_device_users(employee['name'], users)
            row[column(name, 'user_id')] = ''
            row[column(name, 'status')] = 'suggestions' if suggestions else 'not found on device'
            row[column(name, 'suggestions')] = ' | '.join(
                '%s:%s (%.0f%%)%s' % (user['user_id'], user['name'], score * 100,
                                     ' [CHECK: male/female form, may be a different person]'
                                     if differs_only_by_gendered_ending(employee['name'], user['name']) else '')
                for score, user in suggestions)
        rows.append(row)
    return rows


def fieldnames(devices):
    names = ['employee_id', 'employee_name']
    for device in devices:
        names += [column(device['name'], 'user_id'), column(device['name'], 'status'),
                  column(device['name'], 'suggestions')]
    return names


def write_report(rows, devices, path):
    with open(path, 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames(devices))
        writer.writeheader()
        writer.writerows(rows)


def summarise(rows, devices):
    for device in devices:
        counts = {}
        for row in rows:
            status = row.get(column(device['name'], 'status')) or 'filled by hand'
            counts[status] = counts.get(status, 0) + 1
        print('  %s:' % device['name'])
        for status, count in sorted(counts.items(), key=lambda item: -item[1]):
            print('    %-24s %s' % (status, count))


def collect_links(rows, devices, device_ids, copy_across):
    planned = []
    problems = []
    for device in devices:
        name = device['name']
        claimed = {}
        for row in rows:
            user_id = (row.get(column(name, 'user_id')) or '').strip()
            if not user_id and copy_across:
                user_id = next((
                    (row.get(column(other['name'], 'user_id')) or '').strip()
                    for other in devices
                    if (row.get(column(other['name'], 'user_id')) or '').strip()), '')
            if not user_id or row.get(column(name, 'status')) == 'already linked':
                continue
            if user_id in claimed:
                problems.append('%s: device user %s claimed by both %r and %r'
                                % (name, user_id, claimed[user_id], row['employee_name']))
                continue
            claimed[user_id] = row['employee_name']
            planned.append({'employee_id': int(row['employee_id']),
                            'biometric_attendance_id': user_id,
                            'device_id': device_ids[name]})
    return planned, problems


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Link Odoo employees to their device user ids, one row per employee.')
    parser.add_argument('--config', default=os.getenv('ZK_CONFIG_PATH', 'config/daemon.yml'))
    parser.add_argument('--report', default='employee_links.csv')
    parser.add_argument('--from-csv', dest='from_csv',
                        help='Create links from a reviewed report instead of building a new one')
    parser.add_argument('--copy-across-devices', action='store_true',
                        help='When a user id is filled for one device only, use it for every device')
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    load_dotenv()
    configuration = load_configuration(arguments.config)
    devices = configuration.get('devices', [])
    odoo = build_odoo_client(configuration.get('odoo_rpc', {}))
    odoo.authenticate()
    device_ids = {device['name']: odoo_device_id(odoo, device['serial_number']) for device in devices}

    if arguments.from_csv:
        with open(arguments.from_csv, newline='', encoding='utf-8-sig') as handle:
            rows = list(csv.DictReader(handle))
        planned, problems = collect_links(rows, devices, device_ids, arguments.copy_across_devices)
        if problems:
            print('Refusing to apply, fix these in the CSV first:')
            for problem in problems:
                print('  ' + problem)
            return 1
        if planned:
            odoo.call(LINK_MODEL, 'create', args=[planned])
        print('Created %s link(s).' % len(planned))
        return 0

    employees = odoo.call('hr.employee', 'search_read', args=[[('active', '=', True)]],
                          kwargs={'fields': ['id', 'name']})
    users_by_device = {device['name']: read_device_users(device) for device in devices}
    links_by_device = {device['name']: existing_links_by_employee(odoo, device_ids[device['name']])
                       for device in devices}

    print('Active employees in Odoo: %s' % len(employees))
    for device in devices:
        print('Users on %s: %s' % (device['name'], len(users_by_device[device['name']])))
    report_cross_device_consistency(users_by_device)

    rows = build_report(employees, devices, users_by_device, links_by_device)
    write_report(rows, devices, arguments.report)
    print('\nWrote %s (%s employees)\n' % (arguments.report, len(rows)))
    summarise(rows, devices)
    print('\nOpen the CSV. For each employee without a user id, copy the right id from the')
    print('suggestions column, or type it if you know it. Then apply with:')
    print('  python tools\\link_employees.py --from-csv %s' % arguments.report)
    return 0


if __name__ == '__main__':
    sys.exit(main())
