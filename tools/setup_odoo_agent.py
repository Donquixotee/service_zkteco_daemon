import argparse
import getpass
import sys
import xmlrpc.client

ATTENDANCE_MANAGER = 'hr_attendance.group_hr_attendance_manager'
INTERNAL_USER = 'base.group_user'
AGENT_LOGIN = 'zkteco.agent'
AGENT_NAME = 'ZKTeco Agent'


class Odoo:

    def __init__(self, url, db, login, password):
        self.db = db
        self.password = password
        base = url.rstrip('/')
        self.common = xmlrpc.client.ServerProxy(base + '/xmlrpc/2/common', allow_none=True)
        self.models = xmlrpc.client.ServerProxy(base + '/xmlrpc/2/object', allow_none=True)
        self.uid = self.common.authenticate(db, login, password, {})
        if not self.uid:
            raise SystemExit('Authentication failed for %s on database %s' % (login, db))

    def call(self, model, method, *args, **kwargs):
        return self.models.execute_kw(self.db, self.uid, self.password,
                                      model, method, list(args), kwargs)

    def ref(self, xmlid):
        module, name = xmlid.split('.')
        found = self.call('ir.model.data', 'search_read',
                          [('module', '=', module), ('name', '=', name)], fields=['res_id'])
        if not found:
            raise SystemExit('Missing record %s on this database' % xmlid)
        return found[0]['res_id']


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Provision the ZKTeco agent user and raise the API key duration cap.')
    parser.add_argument('--url', required=True)
    parser.add_argument('--db', required=True)
    parser.add_argument('--login', required=True, help='An administrator login')
    parser.add_argument('--company', help="Company owning the devices (default: the administrator's company)")
    parser.add_argument('--key-days', type=int, default=3650)
    parser.add_argument('--dry-run', action='store_true',
                        help='Report what would change without writing anything')
    return parser.parse_args()


def resolve_company(odoo, requested_name):
    if requested_name:
        companies = odoo.call('res.company', 'search_read',
                              [('name', '=', requested_name)], fields=['name'])
        if not companies:
            raise SystemExit('No company named %r' % requested_name)
        return companies[0]['id'], companies[0]['name']
    company = odoo.call('res.users', 'read', [odoo.uid], fields=['company_id'])[0]['company_id']
    return company[0], company[1]


def main():
    arguments = parse_arguments()
    admin_password = getpass.getpass('Odoo password for %s: ' % arguments.login)
    odoo = Odoo(arguments.url, arguments.db, arguments.login, admin_password)
    print('Authenticated as uid=%s' % odoo.uid)

    installed = odoo.call('ir.module.module', 'search_read',
                          [('name', '=', 'dnd_hr_biometric_attendance')], fields=['state'])
    state = installed[0]['state'] if installed else 'not found'
    if state != 'installed':
        raise SystemExit('dnd_hr_biometric_attendance is %s on this database' % state)
    print('Module dnd_hr_biometric_attendance is installed')

    company_id, company_name = resolve_company(odoo, arguments.company)
    print('Company: %s (id=%s)' % (company_name, company_id))

    manager_group = odoo.ref(ATTENDANCE_MANAGER)
    internal_group = odoo.ref(INTERNAL_USER)

    existing = odoo.call('res.users', 'search_read', [('login', '=', AGENT_LOGIN)],
                         fields=['id', 'name'], context={'active_test': False})

    if arguments.dry_run:
        print('')
        print('DRY RUN, nothing written:')
        print('  %s the user %s' % ('update' if existing else 'create', AGENT_LOGIN))
        print('  grant Attendances/Administrator and allocate to %s' % company_name)
        current = odoo.call('res.groups', 'read', [manager_group], fields=['api_key_duration'])[0]
        print('  API key cap currently %s days, would become %s'
              % (current.get('api_key_duration') or 0, arguments.key_days))
        return 0

    agent_password = getpass.getpass('Password to set for %s: ' % AGENT_LOGIN)
    if not agent_password:
        raise SystemExit('A password is required so you can log in as the agent to mint its key')

    values = {
        'name': AGENT_NAME,
        'login': AGENT_LOGIN,
        'password': agent_password,
        'company_id': company_id,
        'company_ids': [(6, 0, [company_id])],
        'groups_id': [(4, internal_group), (4, manager_group)],
    }

    if existing:
        agent_id = existing[0]['id']
        odoo.call('res.users', 'write', [agent_id], values)
        print('Updated existing user %s (id=%s)' % (AGENT_LOGIN, agent_id))
    else:
        agent_id = odoo.call('res.users', 'create', values)
        print('Created user %s (id=%s)' % (AGENT_LOGIN, agent_id))

    current = odoo.call('res.groups', 'read', [manager_group], fields=['api_key_duration'])[0]
    if (current.get('api_key_duration') or 0) < arguments.key_days:
        odoo.call('res.groups', 'write', [manager_group], {'api_key_duration': arguments.key_days})
        print('Raised the API key duration cap to %s days' % arguments.key_days)
    else:
        print('API key duration cap already %s days' % current['api_key_duration'])

    base = arguments.url.rstrip('/')
    print('')
    print('The API key itself cannot be minted over RPC. Finish in the browser:')
    print('  1. Open %s in a private window' % base)
    print('  2. Log in as %s with the password you just set' % AGENT_LOGIN)
    print('  3. Avatar -> My Profile -> Account Security -> New API Key')
    print('  4. Choose a long duration and copy the key')
    print('')
    print('Then .env reads:')
    print('  ODOO_URL=%s' % base)
    print('  ODOO_DB=%s' % arguments.db)
    print('  ODOO_USER_LOGIN=%s' % AGENT_LOGIN)
    print('  ODOO_API_KEY=<the key from step 4>')
    return 0


if __name__ == '__main__':
    sys.exit(main())
