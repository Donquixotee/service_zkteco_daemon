import logging
import logging.handlers
import os
import signal
import sys
import time

import yaml
from dotenv import load_dotenv

from .odoo_client import OdooClient
from .poller import DevicePoller
from .state import CursorStore
from .watchdog import Watchdog

logger = logging.getLogger('zkteco_agent')

DEFAULT_POLL_INTERVAL = 300
MINIMUM_STALL_LIMIT = 600
STALL_LIMIT_MULTIPLIER = 4
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5


class ShutdownSignal:

    def __init__(self):
        self.requested = False
        signal.signal(signal.SIGINT, self._request)
        signal.signal(signal.SIGTERM, self._request)

    def _request(self, signum, frame):
        logger.info("Shutdown requested (signal %s)", signum)
        self.requested = True


def configure_logging(level_name, log_file):
    level = getattr(logging, (level_name or 'INFO').upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s')

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        rotating = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
        rotating.setFormatter(formatter)
        root.addHandler(rotating)


def load_configuration(path):
    with open(path, 'r', encoding='utf-8') as handle:
        return yaml.safe_load(handle) or {}


def require_environment(name):
    value = os.getenv(name)
    if not value:
        raise SystemExit("Missing required environment variable %s" % name)
    return value


def build_odoo_client(rpc_settings):
    return OdooClient(url=require_environment('ODOO_URL'),
                      db=require_environment('ODOO_DB'),
                      login=require_environment('ODOO_USER_LOGIN'),
                      api_key=os.getenv('ODOO_API_KEY'),
                      password=os.getenv('ODOO_PASSWORD'),
                      max_retries=rpc_settings.get('max_retries', 3),
                      retry_delay=rpc_settings.get('retry_delay', 2),
                      timeout=rpc_settings.get('timeout', 30))


def validate_devices(devices):
    for device in devices:
        for key in ('name', 'serial_number', 'ip'):
            if not device.get(key):
                raise SystemExit("Device entry is missing '%s': %r" % (key, device))
    return devices


def main():
    load_dotenv()
    configure_logging(os.getenv('ZK_LOG_LEVEL'), os.getenv('ZK_LOG_FILE'))

    configuration = load_configuration(os.getenv('ZK_CONFIG_PATH', 'config/daemon.yml'))
    daemon_settings = configuration.get('daemon', {})
    devices = validate_devices(configuration.get('devices', []))
    if not devices:
        raise SystemExit("No devices configured in daemon.yml")

    poll_interval = daemon_settings.get('poll_interval', DEFAULT_POLL_INTERVAL)
    state_path = os.getenv('ZK_STATE_PATH') or daemon_settings.get('state_path', 'state.json')

    odoo = build_odoo_client(configuration.get('odoo_rpc', {}))
    try:
        odoo.authenticate()
    except Exception as error:
        logger.error("Could not reach Odoo at startup, will keep retrying: %s", error)

    poller = DevicePoller(odoo, CursorStore(state_path))
    shutdown = ShutdownSignal()

    stall_limit = max(MINIMUM_STALL_LIMIT, poll_interval * STALL_LIMIT_MULTIPLIER)
    watchdog = Watchdog(stall_limit)
    poller.watchdog = watchdog
    watchdog.start()

    logger.info("Agent started for %s device(s), polling every %ss, restarting if stalled for %ss",
                len(devices), poll_interval, stall_limit)
    while not shutdown.requested:
        watchdog.progress()
        try:
            poller.poll_all(devices)
        except Exception as error:
            logger.exception("Polling cycle failed, continuing: %s", error)
        watchdog.progress()
        for _ in range(poll_interval):
            if shutdown.requested:
                break
            time.sleep(1)
    watchdog.stop()
    logger.info("Agent stopped")


if __name__ == '__main__':
    main()
