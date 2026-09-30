import unittest

from src.provisioning import AssignmentError, assign_pins, device_name_for, usable_barcode


class DeviceNameTest(unittest.TestCase):

    def test_uppercases_and_strips_accents(self):
        self.assertEqual(device_name_for('Benaïssa Réda'), 'BENAISSA REDA')

    def test_truncates_to_the_device_limit(self):
        self.assertEqual(len(device_name_for('ABDELKADER BENSALEM MOHAMMED LAMINE')), 24)

    def test_collapses_punctuation_and_spacing(self):
        self.assertEqual(device_name_for('  EL-HADJ   Ali '), 'EL HADJ ALI')

    def test_handles_missing_name(self):
        self.assertEqual(device_name_for(None), '')


class BarcodeTest(unittest.TestCase):

    def test_strips_leading_zeros(self):
        self.assertEqual(usable_barcode('021'), '21')

    def test_rejects_blank_and_non_numeric(self):
        for value in (None, '', '   ', 'A12', '12-3'):
            self.assertIsNone(usable_barcode(value))

    def test_rejects_values_longer_than_the_device_allows(self):
        self.assertIsNone(usable_barcode('1234567890'))


class AssignPinsTest(unittest.TestCase):

    def employees(self):
        return [
            {'id': 7, 'name': 'BRINA MOHAMED', 'barcode': '150'},
            {'id': 3, 'name': 'AICHOUR YASSINE', 'barcode': '175'},
            {'id': 9, 'name': 'AZOUG GHILES', 'barcode': ''},
        ]

    def test_uses_barcode_when_available(self):
        assignments, fallbacks, _ = assign_pins(self.employees())
        by_name = {item['employee_name']: item['pin'] for item in assignments}
        self.assertEqual(by_name['AICHOUR YASSINE'], '175')
        self.assertEqual(by_name['BRINA MOHAMED'], '150')

    def test_falls_back_to_employee_id_without_a_barcode(self):
        assignments, fallbacks, _ = assign_pins(self.employees())
        by_name = {item['employee_name']: item['pin'] for item in assignments}
        self.assertEqual(by_name['AZOUG GHILES'], '9')
        self.assertEqual(fallbacks, ['AZOUG GHILES'])

    def test_duplicate_barcodes_fall_back_for_both_employees(self):
        employees = [{'id': 1, 'name': 'A ONE', 'barcode': '50'},
                     {'id': 2, 'name': 'B TWO', 'barcode': '50'}]
        assignments, fallbacks, _ = assign_pins(employees)
        self.assertEqual(sorted(item['pin'] for item in assignments), ['1', '2'])
        self.assertEqual(len(fallbacks), 2)

    def test_employee_id_source_ignores_barcodes(self):
        assignments, _, _ = assign_pins(self.employees(), id_source='employee')
        self.assertEqual(sorted(item['pin'] for item in assignments), ['3', '7', '9'])

    def test_every_pin_is_unique(self):
        assignments, _, _ = assign_pins(self.employees())
        pins = [item['pin'] for item in assignments]
        self.assertEqual(len(pins), len(set(pins)))

    def test_barcode_colliding_with_a_fallback_id_is_refused(self):
        employees = [{'id': 5, 'name': 'A ONE', 'barcode': ''},
                     {'id': 2, 'name': 'B TWO', 'barcode': '5'}]
        with self.assertRaises(AssignmentError):
            assign_pins(employees)

    def test_names_truncating_to_the_same_value_are_reported(self):
        employees = [{'id': 1, 'name': 'ABDELKADER BENSALEM MOHAMMED LAMINE', 'barcode': '1'},
                     {'id': 2, 'name': 'ABDELKADER BENSALEM MOHAMMED KARIM', 'barcode': '2'}]
        _, _, collisions = assign_pins(employees)
        self.assertEqual(len(collisions), 1)


if __name__ == '__main__':
    unittest.main()


class ProposeBadgeNumbersTest(unittest.TestCase):

    def employees(self):
        return [
            {'id': 1, 'name': 'A ONE', 'barcode': '105'},
            {'id': 2, 'name': 'B TWO', 'barcode': ''},
            {'id': 3, 'name': 'C THREE', 'barcode': None},
            {'id': 4, 'name': 'D FOUR', 'barcode': 'ABC'},
        ]

    def proposals(self, taken=('105', '1323')):
        from src.provisioning import propose_badge_numbers
        return {item['employee_name']: item for item in
                propose_badge_numbers(self.employees(), taken, start=1323)}

    def test_employees_with_a_usable_badge_are_untouched(self):
        self.assertEqual(self.proposals()['A ONE']['proposed_barcode'], '')

    def test_missing_badges_get_a_number(self):
        self.assertEqual(self.proposals()['B TWO']['proposed_barcode'], '1324')

    def test_reserved_numbers_are_skipped(self):
        self.assertNotIn('1323', [item['proposed_barcode'] for item in self.proposals().values()])

    def test_non_numeric_badge_is_flagged_and_replaced(self):
        proposal = self.proposals()['D FOUR']
        self.assertEqual(proposal['status'], 'unusable badge, replace')
        self.assertTrue(proposal['proposed_barcode'])

    def test_every_proposal_is_unique(self):
        proposed = [item['proposed_barcode'] for item in self.proposals().values() if item['proposed_barcode']]
        self.assertEqual(len(proposed), len(set(proposed)))

    def test_inactive_employee_barcodes_are_respected(self):
        from src.provisioning import propose_badge_numbers
        proposals = propose_badge_numbers(self.employees(), ['1323', '1324', '1325'], start=1323)
        assigned = [item['proposed_barcode'] for item in proposals if item['proposed_barcode']]
        self.assertNotIn('1324', assigned)
        self.assertNotIn('1325', assigned)
