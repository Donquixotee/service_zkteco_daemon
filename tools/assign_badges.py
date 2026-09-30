import argparse
import csv
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src.odoo_client import OdooClient
from src.provisioning import propose_badge_numbers, usable_barcode

COLUMNS = ['employee_id', 'employee_name', 'current_barcode', 'proposed_barcode', 'status']


def all_taken_barcodes(odoo):
    rows = odoo.call('hr.employee', 'search_read',
                     args=[['|', ('active', '=', True), ('active', '=', False)]],
                     kwargs={'fields': ['barcode'], 'context': {'active_test': False}})
    return [row['barcode'] for row in rows if row.get('barcode')]


def write_report(proposals, path):
    with open(path, 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(proposals)


def apply_proposals(odoo, rows):
    planned = []
    seen = set()
    problems = []
    for row in rows:
        proposed = (row.get('proposed_barcode') or '').strip()
        if not proposed:
            continue
        if not usable_barcode(proposed):
            problems.append('%s: %r is not a usable badge number' % (row['employee_name'], proposed))
            continue
        if proposed in seen:
            problems.append('%s: badge %s is used twice in the file' % (row['employee_name'], proposed))
            continue
        seen.add(proposed)
        planned.append((int(row['employee_id']), proposed))
    if problems:
        return None, problems
    for employee_id, barcode in planned:
        odoo.call('hr.employee', 'write', args=[[employee_id], {'barcode': barcode}])
    return len(planned), []


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Propose badge numbers for employees without one, then write the reviewed file back.')
    parser.add_argument('--login', required=True, help='Odoo administrator login')
    parser.add_argument('--db', default=os.getenv('ODOO_DB'))
    parser.add_argument('--url', default=os.getenv('ODOO_URL'))
    parser.add_argument('--report', default='badge_numbers.csv')
    parser.add_argument('--start', type=int, help='First number to propose (default: highest existing + 1)')
    parser.add_argument('--from-csv', dest='from_csv', help='Write the reviewed file back to Odoo')
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    load_dotenv()
    password = getpass.getpass('Odoo password for %s: ' % arguments.login)
    odoo = OdooClient(url=arguments.url, db=arguments.db, login=arguments.login, password=password)
    odoo.authenticate()

    if arguments.from_csv:
        with open(arguments.from_csv, newline='', encoding='utf-8-sig') as handle:
            rows = list(csv.DictReader(handle))
        written, problems = apply_proposals(odoo, rows)
        if problems:
            print('Nothing was written. Fix these first:')
            for problem in problems:
                print('  ' + problem)
            return 1
        print('Badge numbers written for %s employee(s).' % written)
        return 0

    employees = odoo.call('hr.employee', 'search_read', args=[[('active', '=', True)]],
                          kwargs={'fields': ['id', 'name', 'barcode']})
    taken = all_taken_barcodes(odoo)
    numeric_taken = [int(value) for value in taken if str(value).isdigit()]
    start = arguments.start or (max(numeric_taken) + 1 if numeric_taken else 1)

    proposals = propose_badge_numbers(employees, taken, start)
    write_report(proposals, arguments.report)

    keeping = [item for item in proposals if not item['proposed_barcode']]
    assigning = [item for item in proposals if item['proposed_barcode']]
    print('Active employees: %s' % len(employees))
    print('Badge numbers already in use anywhere (incl. former staff): %s' % len(taken))
    print('Keeping their existing badge: %s' % len(keeping))
    print('Proposed a new badge: %s (from %s upward)' % (len(assigning), start))
    print('\nWrote %s' % arguments.report)
    print('\nGive this file to HR. They can overwrite proposed_barcode with the real')
    print('badge number where one exists, then write it back with:')
    print('  python tools\\assign_badges.py --login <admin> --from-csv %s' % arguments.report)
    return 0


if __name__ == '__main__':
    sys.exit(main())
