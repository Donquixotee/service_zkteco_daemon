import re
import unicodedata

DEVICE_NAME_LIMIT = 24


def normalize(value):
    if not value:
        return ''
    decomposed = unicodedata.normalize('NFKD', str(value))
    without_accents = ''.join(char for char in decomposed if not unicodedata.combining(char))
    collapsed = re.sub(r'[^a-z0-9 ]+', ' ', without_accents.lower())
    return re.sub(r'\s+', ' ', collapsed).strip()


def name_keys(value):
    normalized = normalize(value)
    if not normalized:
        return set()
    tokens = normalized.split()
    return {
        normalized,
        normalized[:DEVICE_NAME_LIMIT].strip(),
        ' '.join(sorted(tokens)),
        ' '.join(sorted(tokens))[:DEVICE_NAME_LIMIT].strip(),
    }


def index_employees(employees):
    index = {}
    ambiguous = set()
    for employee in employees:
        for key in name_keys(employee['name']):
            if key in index and index[key]['id'] != employee['id']:
                ambiguous.add(key)
            index[key] = employee
    for key in ambiguous:
        index.pop(key, None)
    return index, ambiguous


def match_device_user(device_user_name, employee_index):
    for key in name_keys(device_user_name):
        if key in employee_index:
            return employee_index[key]
    return None
