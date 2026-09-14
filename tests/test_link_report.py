import unittest

from tools.link_employees import build_report, collect_links, column

DEVICES = [{'name': 'Entrance'}, {'name': 'Exit'}]
DEVICE_IDS = {'Entrance': 1, 'Exit': 2}

DEVICE_USERS = [
    {'user_id': '203', 'name': 'AICHOUR YASSINE'},
    {'user_id': '144', 'name': 'AIT TAHAR YOUCEF'},
    {'user_id': '21', 'name': 'BELARBI YAMINA'},
    {'user_id': '14', 'name': '14'},
    {'user_id': '1092632900', 'name': 'NN-1092632900'},
    {'user_id': '88', 'name': 'BOUCHAMA MOHAMED AIMEN'},
]

EMPLOYEES = [
    {'id': 1, 'name': 'AICHOUR YASSINE', 'barcode': '175'},
    {'id': 2, 'name': 'AIT TAHAR YOUCEF', 'barcode': '105'},
    {'id': 3, 'name': 'BOUCHAMA MOHAMED AYMEN', 'barcode': '121'},
    {'id': 4, 'name': 'NOBODY ON DEVICE', 'barcode': ''},
]


def report(links=None):
    users = {'Entrance': DEVICE_USERS, 'Exit': DEVICE_USERS}
    existing = links or {'Entrance': {}, 'Exit': {}}
    return {row['employee_id']: row for row in build_report(EMPLOYEES, DEVICES, users, existing)}


class BuildReportTest(unittest.TestCase):

    def test_one_row_per_employee_not_per_device_user(self):
        self.assertEqual(len(report()), len(EMPLOYEES))

    def test_exact_name_is_matched_on_every_device(self):
        row = report()[1]
        self.assertEqual(row[column('Entrance', 'user_id')], '203')
        self.assertEqual(row[column('Exit', 'user_id')], '203')
        self.assertEqual(row[column('Entrance', 'status')], 'match')

    def test_barcode_is_never_used_as_the_device_id(self):
        self.assertNotEqual(report()[1][column('Entrance', 'user_id')], '175')

    def test_close_spelling_is_left_blank_with_a_suggestion(self):
        row = report()[3]
        self.assertEqual(row[column('Entrance', 'user_id')], '')
        self.assertEqual(row[column('Entrance', 'status')], 'suggestions')
        self.assertIn('88:BOUCHAMA MOHAMED AIMEN', row[column('Entrance', 'suggestions')])

    def test_absent_employee_is_reported_not_found(self):
        self.assertEqual(report()[4][column('Entrance', 'status')], 'not found on device')

    def test_existing_link_is_preserved(self):
        row = report({'Entrance': {2: '999'}, 'Exit': {}})[2]
        self.assertEqual(row[column('Entrance', 'user_id')], '999')
        self.assertEqual(row[column('Entrance', 'status')], 'already linked')


def csv_rows():
    return [
        {'employee_id': '1', 'employee_name': 'AICHOUR YASSINE',
         'entrance_user_id': '203', 'entrance_status': 'match',
         'exit_user_id': '203', 'exit_status': 'match'},
        {'employee_id': '3', 'employee_name': 'BOUCHAMA MOHAMED AYMEN',
         'entrance_user_id': '88', 'entrance_status': 'suggestions',
         'exit_user_id': '', 'exit_status': 'suggestions'},
        {'employee_id': '2', 'employee_name': 'AIT TAHAR YOUCEF',
         'entrance_user_id': '144', 'entrance_status': 'already linked',
         'exit_user_id': '144', 'exit_status': 'match'},
    ]


class CollectLinksTest(unittest.TestCase):

    def test_filled_ids_become_links_and_already_linked_are_skipped(self):
        planned, problems = collect_links(csv_rows(), DEVICES, DEVICE_IDS, copy_across=False)
        self.assertEqual(problems, [])
        pairs = sorted((link['device_id'], link['employee_id'], link['biometric_attendance_id']) for link in planned)
        self.assertEqual(pairs, [(1, 1, '203'), (1, 3, '88'), (2, 1, '203'), (2, 2, '144')])

    def test_copy_across_fills_the_missing_device(self):
        planned, _ = collect_links(csv_rows(), DEVICES, DEVICE_IDS, copy_across=True)
        self.assertIn((2, 3, '88'), [(link['device_id'], link['employee_id'], link['biometric_attendance_id'])
                                     for link in planned])

    def test_same_device_user_claimed_twice_is_refused(self):
        rows = csv_rows()
        rows[1]['entrance_user_id'] = '203'
        planned, problems = collect_links(rows, DEVICES, DEVICE_IDS, copy_across=False)
        self.assertTrue(any('203' in problem for problem in problems))


if __name__ == '__main__':
    unittest.main()


class GenderedSuggestionWarningTest(unittest.TestCase):

    def test_gender_variant_suggestion_carries_a_warning_and_is_not_filled(self):
        users = [{'user_id': '41', 'name': 'SAIDI KARIMA'}]
        rows = build_report([{'id': 1, 'name': 'SAIDI KARIM'}], DEVICES,
                            {'Entrance': users, 'Exit': users}, {'Entrance': {}, 'Exit': {}})
        self.assertEqual(rows[0][column('Entrance', 'user_id')], '')
        self.assertIn('CHECK: male/female form', rows[0][column('Entrance', 'suggestions')])

    def test_spelling_variant_suggestion_carries_no_warning(self):
        users = [{'user_id': '203', 'name': 'AICHOUR YACINE'}]
        rows = build_report([{'id': 1, 'name': 'AICHOUR YASSINE'}], DEVICES,
                            {'Entrance': users, 'Exit': users}, {'Entrance': {}, 'Exit': {}})
        self.assertNotIn('CHECK', rows[0][column('Entrance', 'suggestions')])
