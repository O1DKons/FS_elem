import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_axel_corpus as builder


def legacy_contact_observation(*args):
    return builder.legacy_contact_observation(*args)


class LegacyContactIntakeTests(unittest.TestCase):
    def test_original_schema_has_no_element_code(self):
        record = {'id': 'competition-32-01-01', 'eventClass': 'axel',
                  'lastContactFrame': 912, 'firstContactFrame': 933}
        observation = legacy_contact_observation(record, 'a' * 64, 50., [])
        self.assertIsNone(observation['protocolCode'])
        self.assertIsNone(observation.get('family'))
        self.assertFalse(observation['modelTrainingEligible'])
        self.assertAlmostEqual(observation['startSeconds'], 18.24)
        self.assertAlmostEqual(observation['endSeconds'], 18.66)

    def test_supplied_code_is_only_a_hint(self):
        record = {'id': 'old1', 'elementCode': '2A<<',
                  'lastContactFrame': 10, 'firstContactFrame': 30}
        observation = legacy_contact_observation(record, 'a' * 64, 50., [])
        self.assertEqual(observation['protocolNominalHint'], '2A')
        self.assertIsNone(observation.get('nominal'))

    def test_invalid_contacts_rejected(self):
        record = {'id': 'old1', 'lastContactFrame': 30, 'firstContactFrame': 10}
        with self.assertRaises(ValueError):
            legacy_contact_observation(record, 'a' * 64, 50., [])


class ReportCardIntakeTests(unittest.TestCase):
    def test_confirmed_card_does_not_invent_contacts_or_measure_underrotation(self):
        component = {'code': '2A<', 'jumpFamily': 'A'}
        row = {'id': 'card1', 'confirmedReportComponent': component}
        card = {'id': 'card1', 'kind': 'jump', 'protocolComponent': component,
                'review': {'start': 1., 'end': 1.5}}
        observation = builder.confirmed_report_observation(row, card, 'a' * 64, [])
        self.assertEqual(observation['nominal'], '2A')
        self.assertEqual(observation['family'], 'axel')
        self.assertFalse(observation['reviewComplete'])
        self.assertIsNone(observation.get('lastContactFrame'))
        self.assertIsNone(observation['measuredUnderrotation'])
        self.assertEqual(observation['boundaryStatus'], 'report_display_approximation')

    def test_card_identity_mismatch_rejected(self):
        row = {'id': 'card1', 'confirmedReportComponent': {'code': '1A'}}
        card = {'id': 'card2', 'kind': 'jump', 'protocolComponent': {'code': '1A'}}
        with self.assertRaises(ValueError):
            builder.confirmed_report_observation(row, card, 'a' * 64, [])

    def test_contact_conflicts_preserve_both_observations(self):
        events = [{'eventId': 'editor1', 'sourceSha256': 'a'*64,
                   'lastContactFrame': 1717, 'firstContactFrame': 1741},
                  {'eventId': 'full1', 'sourceSha256': 'a'*64,
                   'lastContactFrame': 1717, 'firstContactFrame': 1740}]
        issues = builder.contact_conflicts(events)
        self.assertEqual(len(issues), 1)
        self.assertEqual(set(issues[0]['eventIds']), {'editor1', 'full1'})
        self.assertEqual(events[0]['firstContactFrame'], 1741)


if __name__ == '__main__':
    unittest.main()
