import unicodedata

DEVICE_NAME_LIMIT = 24
DEVICE_PIN_LIMIT = 9


class AssignmentError(Exception):
    pass


def device_name_for(employee_name):
    decomposed = unicodedata.normalize('NFKD', employee_name or '')
    ascii_only = ''.join(character for character in decomposed if not unicodedata.combining(character))
    cleaned = ''.join(character if character.isalnum() or character == ' ' else ' '
                      for character in ascii_only)
    collapsed = ' '.join(cleaned.upper().split())
    return collapsed[:DEVICE_NAME_LIMIT].strip()


def usable_barcode(value):
    text = (value or '').strip()
    if not text or not text.isdigit():
        return None
    trimmed = text.lstrip('0') or '0'
    return trimmed if len(trimmed) <= DEVICE_PIN_LIMIT else None


def assign_pins(employees, id_source='barcode'):
    if id_source not in ('barcode', 'employee'):
        raise AssignmentError('Unknown id source %r' % id_source)

    ordered = sorted(employees, key=lambda employee: employee['name'])
    assignments = []
    taken = set()
    fallbacks = []

    if id_source == 'barcode':
        counts = {}
        for employee in ordered:
            pin = usable_barcode(employee.get('barcode'))
            if pin:
                counts[pin] = counts.get(pin, 0) + 1
        duplicates = {pin for pin, count in counts.items() if count > 1}
    else:
        duplicates = set()

    for employee in ordered:
        pin = None
        if id_source == 'barcode':
            candidate = usable_barcode(employee.get('barcode'))
            if candidate and candidate not in duplicates:
                pin = candidate
        if pin is None:
            pin = str(employee['id'])
            fallbacks.append(employee['name'])
        if pin in taken:
            raise AssignmentError('Two employees would receive device id %s' % pin)
        taken.add(pin)
        assignments.append({'employee_id': employee['id'],
                            'employee_name': employee['name'],
                            'pin': pin,
                            'device_name': device_name_for(employee['name'])})

    clashing_names = _names_colliding_after_truncation(assignments)
    return assignments, fallbacks, clashing_names


def _names_colliding_after_truncation(assignments):
    seen = {}
    collisions = []
    for assignment in assignments:
        key = assignment['device_name']
        if key in seen:
            collisions.append((seen[key], assignment['employee_name'], key))
        else:
            seen[key] = assignment['employee_name']
    return collisions


def propose_badge_numbers(employees, taken_barcodes, start):
    reserved = {str(value).strip() for value in taken_barcodes if str(value).strip()}
    numeric_reserved = {int(value) for value in reserved if value.isdigit()}
    proposals = []
    candidate = start
    for employee in sorted(employees, key=lambda item: item['name']):
        current = (employee.get('barcode') or '').strip()
        if usable_barcode(current):
            proposals.append({'employee_id': employee['id'], 'employee_name': employee['name'],
                              'current_barcode': current, 'proposed_barcode': '',
                              'status': 'keeps existing badge'})
            continue
        while candidate in numeric_reserved:
            candidate += 1
        numeric_reserved.add(candidate)
        proposals.append({'employee_id': employee['id'], 'employee_name': employee['name'],
                          'current_barcode': current,
                          'proposed_barcode': str(candidate),
                          'status': 'unusable badge, replace' if current else 'no badge'})
        candidate += 1
    return proposals
