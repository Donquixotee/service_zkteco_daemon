import unittest

from src.matching import index_employees, match_device_user, normalize


class NormalizeTest(unittest.TestCase):

    def test_strips_accents_and_case(self):
        self.assertEqual(normalize('Amraoui Sofiane'), normalize('AMRAOUI SOFIANE'))
        self.assertEqual(normalize('Benaïssa Réda'), 'benaissa reda')

    def test_collapses_punctuation_and_spacing(self):
        self.assertEqual(normalize('  EL-HADJ   Ali '), 'el hadj ali')

    def test_empty_input(self):
        self.assertEqual(normalize(None), '')
        self.assertEqual(normalize(''), '')


class MatchTest(unittest.TestCase):

    def setUp(self):
        self.employees = [
            {'id': 1, 'name': 'Amraoui Sofiane'},
            {'id': 2, 'name': 'Benaïssa Réda'},
            {'id': 3, 'name': 'Abdelkader Bensalem Mohammed Lamine'},
        ]
        self.index, self.ambiguous = index_employees(self.employees)

    def test_exact_match(self):
        self.assertEqual(match_device_user('Amraoui Sofiane', self.index)['id'], 1)

    def test_case_and_accent_insensitive(self):
        self.assertEqual(match_device_user('BENAISSA REDA', self.index)['id'], 2)

    def test_reversed_name_order(self):
        self.assertEqual(match_device_user('Sofiane Amraoui', self.index)['id'], 1)

    def test_device_truncation_to_24_characters(self):
        truncated = 'Abdelkader Bensalem Moha'
        self.assertEqual(match_device_user(truncated, self.index)['id'], 3)

    def test_unknown_name_returns_nothing(self):
        self.assertIsNone(match_device_user('Nobody Here', self.index))

    def test_blank_device_name_returns_nothing(self):
        self.assertIsNone(match_device_user('', self.index))

    def test_duplicate_employee_names_are_not_matched(self):
        index, ambiguous = index_employees([
            {'id': 10, 'name': 'Mohamed Ali'},
            {'id': 11, 'name': 'Mohamed Ali'},
        ])
        self.assertIsNone(match_device_user('Mohamed Ali', index))
        self.assertTrue(ambiguous)


if __name__ == '__main__':
    unittest.main()
