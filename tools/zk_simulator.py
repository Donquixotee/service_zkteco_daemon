import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src import poller as poller_module
from src.device_client import DEVICE_TIME_FORMAT
from src.main import build_odoo_client, configure_logging, load_configuration
from src.poller import DevicePoller
from src.state import CursorStore


def build_synthetic_punches(user_ids, days, first_punch_hour, second_punch_hour):
    punches = []
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for day_offset in range(days):
        day = midnight - timedelta(days=day_offset)
        for user_id in user_ids:
            for hour in (first_punch_hour, second_punch_hour):
                punches.append({'user_id': str(user_id),
                                'timestamp': day.replace(hour=hour).strftime(DEVICE_TIME_FORMAT)})
    return sorted(punches, key=lambda punch: punch['timestamp'])


def parse_arguments():
    parser = argparse.ArgumentParser(description='Feed synthetic punches through the agent pipeline.')
    parser.add_argument('--users', default='1', help='Comma separated device user ids')
    parser.add_argument('--days', type=int, default=1)
    parser.add_argument('--check-in-hour', type=int, default=8)
    parser.add_argument('--check-out-hour', type=int, default=17)
    parser.add_argument('--config', default=os.getenv('ZK_CONFIG_PATH', 'config/daemon.yml'))
    parser.add_argument('--dry-run', action='store_true', help='Print the punches without contacting Odoo')
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    load_dotenv()
    configure_logging(os.getenv('ZK_LOG_LEVEL', 'INFO'), None)

    user_ids = [value.strip() for value in arguments.users.split(',') if value.strip()]
    punches = build_synthetic_punches(user_ids, arguments.days,
                                      arguments.check_in_hour, arguments.check_out_hour)

    if arguments.dry_run:
        for punch in punches:
            print(punch)
        print('%s punches generated' % len(punches))
        return

    configuration = load_configuration(arguments.config)
    devices = configuration.get('devices', [])
    if not devices:
        raise SystemExit('No devices configured in %s' % arguments.config)

    poller_module.read_punches = lambda device: punches

    odoo = build_odoo_client(configuration.get('odoo_rpc', {}))
    odoo.authenticate()

    state_path = os.getenv('ZK_STATE_PATH') or configuration.get('daemon', {}).get('state_path', 'state.json')
    DevicePoller(odoo, CursorStore(state_path)).poll_device(devices[0])


if __name__ == '__main__':
    main()
