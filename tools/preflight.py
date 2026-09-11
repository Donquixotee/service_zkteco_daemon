import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src.device_client import DeviceUnreachable, device_connection
from src.main import build_odoo_client, load_configuration

RECEIVE_PUNCHES_MODEL = 'biometric.config'


def report(label, ok, detail=''):
    mark = 'PASS' if ok else 'FAIL'
    print('[%s] %s%s' % (mark, label, (' - ' + detail) if detail else ''))
    return ok


def check_device_handshake(device):
    label = 'Device %s answers at %s:%s' % (device['name'], device['ip'], device.get('port', 4370))
    probe = dict(device)
    probe['timeout'] = min(device.get('timeout', 10), 10)
    try:
        with device_connection(probe) as client:
            serial = client.get_serialnumber()
        if serial and serial != device['serial_number']:
            report(label, True, 'connected')
            return report('Serial matches daemon.yml', False,
                          'device reports %s, config says %s' % (serial, device['serial_number']))
        return report(label, True, 'serial %s' % serial)
    except DeviceUnreachable as error:
        return report(label, False, str(error))
    except Exception as error:
        return report(label, False,
                      '%s (check the IP, port 4370, a COMM key set on the device, '
                      'or try force_udp / ommit_ping)' % error)


def check_device_registered(odoo, device):
    found = odoo.call(RECEIVE_PUNCHES_MODEL, 'search_read',
                      args=[[('serialnumber', '=', device['serial_number'])]],
                      kwargs={'fields': ['name', 'connection_mode', 'time_zone']})
    if not found:
        return report('Serial %s exists in Odoo' % device['serial_number'], False,
                      'no biometric.config record carries this serial number')
    record = found[0]
    report('Serial %s exists in Odoo' % device['serial_number'], True, 'matches "%s"' % record['name'])
    report('Odoo device is in agent mode', record['connection_mode'] == 'agent',
           'currently %s' % record['connection_mode'])
    return report('Odoo device has a timezone', bool(record['time_zone']),
                  record['time_zone'] or 'not set, punches will be treated as GMT')


def main():
    load_dotenv()
    configuration = load_configuration(os.getenv('ZK_CONFIG_PATH', 'config/daemon.yml'))
    devices = configuration.get('devices', [])
    results = []

    try:
        odoo = build_odoo_client(configuration.get('odoo_rpc', {}))
        odoo.authenticate()
        results.append(report('Odoo authentication', True, os.getenv('ODOO_URL')))
    except Exception as error:
        report('Odoo authentication', False, str(error))
        print('\nFix authentication before checking anything else.')
        return 1

    for device in devices:
        print('')
        results.append(check_device_handshake(device))
        results.append(check_device_registered(odoo, device))

    print('')
    if all(results):
        print('All checks passed. Safe to start the service.')
        return 0
    print('Some checks failed. See the troubleshooting table in README.md.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
