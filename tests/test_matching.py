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


class SuggestionTest(unittest.TestCase):

    def test_close_spelling_is_suggested(self):
        from src.matching import suggest_device_users
        users = [{'user_id': '203', 'name': 'AICHOUR YACINE'}, {'user_id': '9', 'name': 'BRINA MOHAMED'}]
        best = suggest_device_users('AICHOUR YASSINE', users)
        self.assertEqual(best[0][1]['user_id'], '203')

    def test_numeric_and_no_name_users_are_never_suggested(self):
        from src.matching import has_real_name
        self.assertFalse(has_real_name({'name': '14'}))
        self.assertFalse(has_real_name({'name': 'NN-1092632900'}))
        self.assertFalse(has_real_name({'name': ''}))
        self.assertTrue(has_real_name({'name': 'BELARBI YAMINA'}))

    def test_unrelated_names_fall_below_threshold(self):
        from src.matching import suggest_device_users
        users = [{'user_id': '1', 'name': 'ZOUBIR KHALED'}]
        self.assertEqual(suggest_device_users('AICHOUR YASSINE', users), [])
