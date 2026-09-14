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


def looks_like_clean_user_id(value):
    return value.isdigit() and len(value) <= 9


def scan_attendance(client):
    client.read_sizes()
    records_before = client.records
    payload, size = client.read_with_buffer(const.CMD_ATTLOG_RRQ)
    client.read_sizes()
    records_after = client.records
    total_size = unpack('I', payload[:4])[0]
    body = payload[4:]

    print('  records reported before read=%s after read=%s' % (records_before, records_after))
    print('  header total_size=%s body=%s  body%%40=%s' % (total_size, len(body), len(body) % 40))

    bad = []
    stamps = []
    for index in range(len(body) // 40):
        chunk = body[index * 40:(index + 1) * 40]
        uid, user_id, status, timestamp, punch, space = unpack('<H24sB4sB8s', chunk)
        text = user_id.split(b'\x00')[0].decode(errors='ignore')
        stamp = decode_time(timestamp)
        stamps.append(stamp)
        if not looks_like_clean_user_id(text) or not stamp.startswith('20'):
            bad.append((index, uid, text, stamp, codecs.encode(chunk, 'hex').decode()))

    total = len(body) // 40
    print('  attendance records=%s clean=%s corrupt=%s' % (total, total - len(bad), len(bad)))
    if stamps:
        print('  timestamp range %s -> %s' % (min(stamps), max(stamps)))
    if not bad:
        return
    indices = [entry[0] for entry in bad]
    print('  corrupt record indices: first=%s last=%s span=%s' % (indices[0], indices[-1], indices[-1] - indices[0] + 1))
    contiguous = indices == list(range(indices[0], indices[-1] + 1))
    print('  corrupt records contiguous: %s' % contiguous)
    for index, uid, text, stamp, hexdump in bad[:8]:
        print('    #%-5s uid=%-6s user_id=%-14r time=%s' % (index, uid, text, stamp))
        print('           %s' % hexdump)
    if bad[0][0] > 0:
        previous = body[(bad[0][0] - 1) * 40:bad[0][0] * 40]
        print('  record just before first corrupt one:')
        print('           %s' % codecs.encode(previous, 'hex').decode())


def scan_users(client):
    users = client.get_users() or []
    garbage = [user for user in users if not looks_like_clean_user_id(str(user.user_id))]
    named = [user for user in users if (user.name or '').strip()]
    print('  users=%s with_name=%s garbage_user_id=%s' % (len(users), len(named), len(garbage)))
    for user in users[:6]:
        print('    uid=%-5s user_id=%-10r name=%r card=%s' % (user.uid, user.user_id, user.name, user.card))
    for user in garbage[:6]:
        print('    GARBAGE uid=%-5s user_id=%r name=%r' % (user.uid, user.user_id, user.name))


def scan_everything(client, device):
    print('=== %s (%s) full scan ===' % (device['name'], device['ip']))
    print('  -- attendance --')
    scan_attendance(client)
    print('  -- users --')
    scan_users(client)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Read-only diagnosis of the attendance record layout.')
    parser.add_argument('--config', default=os.getenv('ZK_CONFIG_PATH', 'config/daemon.yml'))
    parser.add_argument('--device', help='Only diagnose the device with this name')
    parser.add_argument('--full', action='store_true',
                        help='Scan every record and every user for corruption instead of sampling four')
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
                if arguments.full:
                    scan_everything(client, device)
                else:
                    diagnose(client, device)
        except Exception as error:
            print('=== %s === FAILED: %s' % (device['name'], error))
        print('')
    return 0


if __name__ == '__main__':
    sys.exit(main())
