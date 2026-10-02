import importlib.util
import json
from pathlib import Path
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'work/personal-flight-domain-addition-v1/training.py'
if path.exists():
    spec = importlib.util.spec_from_file_location('mobile_flight_training', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
else:
    module = None


class PersonalFlightAdditionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'Real-PTS flight-label adapter absent')
        self.event = dict(startSeconds=.12, endSeconds=.37, reviewComplete=True,
                          labelScope='full_review', modelTrainingEligible=True)

    def test_irregular_pts_strict_interior_and_reviewed_background(self):
        times = np.array([0., .12, .183, .369, .37, .7])
        np.testing.assert_array_equal(module.seconds_labels(times, [self.event]), [0, 0, 1, 1, 0, 0])

    def test_partial_review_is_never_background(self):
        with self.assertRaises(ValueError):
            module.seconds_labels(np.array([0., .2, .5]), [dict(self.event, reviewComplete=False)])

    def test_overlap_is_not_silently_double_counted(self):
        with self.assertRaises(ValueError):
            module.seconds_labels(np.array([0., .2, .3, .5]),
                                 [self.event, dict(self.event, startSeconds=.25, endSeconds=.4)])

    def test_actual_linked_group_excludes_both_katya_sources(self):
        protocol = json.loads((ROOT/'work/personal-rtmw-cascade-transfer-v1/protocol.json').read_text())
        fold = next(f for f in protocol['folds'] if 'personal-06' in f['targetVideoIds'])
        records = protocol['sources']
        chosen = module.selected_sources(records, set(fold['excludedKnownSourceHashes']))
        self.assertNotIn('personal-06', [r['videoId'] for r in chosen])
        self.assertNotIn('personal-17', [r['videoId'] for r in chosen])
        self.assertEqual(len(chosen), 6)


if __name__ == '__main__':
    unittest.main()
