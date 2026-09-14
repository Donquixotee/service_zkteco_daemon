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


def similarity(first, second):
    from difflib import SequenceMatcher
    left = ' '.join(sorted(normalize(first).split()))
    right = ' '.join(sorted(normalize(second).split()))
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def has_real_name(device_user):
    name = normalize(device_user.get('name'))
    return bool(name) and not name.replace(' ', '').isdigit() and not name.startswith('nn ')


def suggest_device_users(employee_name, device_users, limit=3, threshold=0.6):
    scored = [(similarity(employee_name, user['name']), user)
              for user in device_users if has_real_name(user)]
    scored = [entry for entry in scored if entry[0] >= threshold]
    scored.sort(key=lambda entry: -entry[0])
    return scored[:limit]


def _feminine_form(masculine, feminine):
    if masculine + 'a' == feminine:
        return True
    return masculine.endswith('e') and masculine[:-1] + 'a' == feminine


def differs_only_by_gendered_ending(first, second):
    left = sorted(normalize(first).split())
    right = sorted(normalize(second).split())
    if len(left) != len(right):
        return False
    differences = [(a, b) for a, b in zip(left, right) if a != b]
    if len(differences) != 1:
        return False
    a, b = differences[0]
    return _feminine_form(a, b) or _feminine_form(b, a)
