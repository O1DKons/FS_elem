import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_protocol_rotation_crossfit import protocol_target, protocol_2a_by_attempt


class ProtocolRotationTests(unittest.TestCase):
    def test_maps_official_2a_calls_to_binary_protocol_target(self):
        self.assertEqual(protocol_target('2A'), 0)
        self.assertEqual(protocol_target('2Aq'), 1)
        self.assertEqual(protocol_target('2A<'), 1)
        self.assertEqual(protocol_target('2A<<'), 1)
        self.assertIsNone(protocol_target('2A*'))
        self.assertIsNone(protocol_target('2Lz<'))

    def test_extracts_axel_components_and_keeps_athlete_and_element_identity(self):
        doc = {'programs': [
            {'startNumber': 7, 'athlete': 'Skater A', 'elements': [
                {'sequence': 2, 'code': '2A<+2T', 'jumpComponents': ['2A<', '2T'], 'fall': False},
                {'sequence': 4, 'code': '2F', 'jumpComponents': ['2F'], 'fall': False},
            ]}
        ]}
        rows = protocol_2a_by_attempt(doc)
        self.assertEqual(list(rows), ['competition-07-02-01'])
        self.assertEqual(rows['competition-07-02-01']['athlete'], 'Skater A')
        self.assertEqual(rows['competition-07-02-01']['target'], 1)
        self.assertEqual(rows['competition-07-02-01']['code'], '2A<')

    def test_rejects_duplicate_axel_identity_in_protocol(self):
        doc = {'programs': [
            {'startNumber': 7, 'athlete': 'Skater A', 'elements': [
                {'sequence': 2, 'jumpComponents': ['2A'], 'fall': False},
                {'sequence': 2, 'jumpComponents': ['2A<'], 'fall': False},
            ]}
        ]}
        with self.assertRaises(ValueError):
            protocol_2a_by_attempt(doc)


if __name__ == '__main__':
    unittest.main()
