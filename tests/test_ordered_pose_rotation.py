"""Behavioral guards for single-type rotation evaluation, not feature outcomes."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np

RUNNER = Path(__file__).resolve().parents[1] / 'work/ordered-pose-rotation-v1/run.py'


class OrderedRotationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(RUNNER.exists(), 'Rotation runner has not been implemented')
        spec = importlib.util.spec_from_file_location('ordered_rotation', RUNNER)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def rows(self):
        return [dict(id='a', sha256='a', sourceSha256='pa', athleteKey='a', truth='complete'),
                dict(id='b', sha256='b', sourceSha256='pb', athleteKey='b', truth='short'),
                dict(id='c', sha256='c', sourceSha256='pc', athleteKey='c', truth='complete')]

    def test_whole_athlete_and_shared_source_cannot_cross_fold(self):
        for field, value in [('athleteKey', 'a'), ('sourceSha256', 'pa')]:
            rows = self.rows(); rows[2][field] = value
            with self.assertRaises(ValueError):
                self.m.evaluate_fold(rows, [np.array([1., 0.]), np.array([0., 1.]), np.array([.8, .2])], [0, 1], [2])

    def test_own_held_out_truth_cannot_change_scores(self):
        rows = self.rows(); x = [np.array([1., 0.]), np.array([0., 1.]), np.array([.8, .2])]
        first = self.m.evaluate_fold(rows, x, [0, 1], [2])
        rows[2]['truth'] = 'short'
        second = self.m.evaluate_fold(rows, x, [0, 1], [2])
        self.assertEqual(first['records'][0]['rawScores'], second['records'][0]['rawScores'])
        self.assertEqual(first['records'][0]['prediction'], second['records'][0]['prediction'])

    def test_unknown_is_excluded_not_a_complete_negative(self):
        self.assertIsNone(self.m.rotation_truth('unknown'))
        self.assertIsNone(self.m.rotation_truth('unclear'))
        self.assertEqual(self.m.rotation_truth('apparently_short'), 'short')
        with self.assertRaises(ValueError):
            self.m.rotation_truth('2A<<')

    def test_abstentions_remain_wrong_in_class_denominators(self):
        result = self.m.summarize([dict(truth='complete', prediction='abstain'), dict(truth='short', prediction='short')])
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['correct'], 1)
        self.assertEqual(result['coverage'], .5)
        self.assertEqual(result['recall']['complete'], 0.)
        self.assertEqual(result['balancedAccuracy'], .5)

    def test_one_class_fold_does_not_claim_learned_rotation(self):
        rows = self.rows(); rows[0]['truth'] = 'short'
        result = self.m.evaluate_fold(rows, [np.array([1., 0.]), np.array([0., 1.]), np.array([.8, .2])], [0, 1], [2])
        self.assertFalse(result['learnedModelAvailable'])
        self.assertEqual(result['records'][0]['prediction'], 'abstain')
        self.assertEqual(result['records'][0]['trainingMajority'], 'short')

    def test_changed_frozen_features_or_inventory_fail_before_training(self):
        validator = getattr(self.m, 'validate_frozen_protocol', None)
        self.assertTrue(callable(validator), 'Frozen input guard is missing')
        protocol = dict(features=dict(sha256='a' * 64), inventorySha256='b' * 64)
        validator(protocol, 'a' * 64, 'b' * 64)
        for feature_hash, inventory_hash in [('c' * 64, 'b' * 64), ('a' * 64, 'c' * 64)]:
            with self.assertRaises(ValueError):
                validator(protocol, feature_hash, inventory_hash)


if __name__ == '__main__':
    unittest.main()
