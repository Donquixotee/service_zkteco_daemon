import argparse
import codecs
import os
import sys
from struct import unpack

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from zk import const

from src.device_client import device_connection
from src.main import load_configuration

SAMPLE_RECORDS = 4


def decode_time(raw):
    value = unpack('<I', raw)[0]
    second = value % 60
    value //= 60
    minute = value % 60
    value //= 60
    hour = value % 24
    value //= 24
    day = value % 31 + 1
    value //= 31
    month = value % 12 + 1
    value //= 12
    year = value + 2000
    return '%04d-%02d-%02d %02d:%02d:%02d' % (year, month, day, hour, minute, second)


def try_layout(payload, size, label, fmt, user_index, time_index):
    print('  --- as %s ---' % label)
    for index in range(min(SAMPLE_RECORDS, len(payload) // size)):
        chunk = payload[index * size:(index + 1) * size]
        try:
            fields = unpack(fmt, chunk.ljust(size, b'\x00'))
            user = fields[user_index]
            if isinstance(user, bytes):
                user = user.split(b'\x00')[0].decode(errors='ignore')
            stamp = decode_time(fields[time_index])
            print('    user_id=%-26r time=%s' % (user, stamp))
        except Exception as error:
            print('    unpack failed: %s' % error)


def diagnose(client, device):
    print('=== %s (%s) ===' % (device['name'], device['ip']))
    client.read_sizes()
    print('  reported users=%s records=%s' % (client.users, client.records))

    payload, size = client.read_with_buffer(const.CMD_ATTLOG_RRQ)
    print('  buffer bytes=%s' % size)
    if size < 4:
        print('  no attendance payload')
        return

    total_size = unpack('I', payload[:4])[0]
    body = payload[4:]
    print('  header total_size=%s body=%s' % (total_size, len(body)))

    if client.records:
        print('  total_size/records = %s' % (total_size / client.records))
        print('  body/records       = %s' % (len(body) / client.records))
    for candidate in (8, 16, 40):
        remainder = len(body) % candidate
        print('  body %% %-2s = %-6s  -> %s records' % (candidate, remainder, len(body) // candidate))

    print('  first %s bytes hex:' % min(120, len(body)))
    print('    %s' % codecs.encode(body[:120], 'hex').decode())

    try_layout(body, 16, '16-byte, user_id as int', '<I4sBB2sI', 0, 1)
    try_layout(body, 16, '16-byte, user_id as text', '<4s4sBB2sI', 0, 1)
    try_layout(body, 40, '40-byte, user_id as text', '<H24sB4sB8s', 1, 3)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Read-only diagnosis of the attendance record layout.')
    parser.add_argument('--config', default=os.getenv('ZK_CONFIG_PATH', 'config/daemon.yml'))
    parser.add_argument('--device', help='Only diagnose the device with this name')
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    load_dotenv()
    devices = load_configuration(arguments.config).get('devices', [])
    if arguments.device:
        devices = [device for device in devices if device['name'] == arguments.device]
    for device in devices:
        try:
            with device_connection(device) as client:
                diagnose(client, device)
        except Exception as error:
            print('=== %s === FAILED: %s' % (device['name'], error))
        print('')
    return 0


if __name__ == '__main__':
    sys.exit(main())
