"""Leakage and denominator guards for the ordered personal-pose experiment."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

RUNNER = Path(__file__).resolve().parents[1] / 'work/personal-ordered-pose-v1/run.py'


class PersonalOrderedTrainingTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(RUNNER.exists(), 'Ordered personal-pose runner is not implemented')
        spec = importlib.util.spec_from_file_location('personal_ordered_training', RUNNER)
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)

    def test_shared_original_source_across_athletes_is_rejected(self):
        rows = [dict(id='one', sha256='clip1', sourceSha256='same-source', athlete='a', truth='1A'),
                dict(id='two', sha256='clip2', sourceSha256='same-source', athlete='b', truth='other')]
        with self.assertRaises(ValueError):
            self.runner.crossfit(rows, [np.array([1., 0.]), np.array([0., 1.])])

    def test_held_out_truth_never_changes_its_scores_or_training_majority(self):
        rows = [dict(id='one', sha256='clip1', athlete='a', truth='1A'),
                dict(id='two', sha256='clip2', athlete='a', truth='other'),
                dict(id='three', sha256='clip3', athlete='b', truth='1A'),
                dict(id='four', sha256='clip4', athlete='c', truth='other')]
        features = [np.array([.9, .1]), np.array([.2, .8]), np.array([1., 0.]), np.array([0., 1.])]
        first = self.runner.crossfit(rows, features)
        changed = [dict(r) for r in rows]
        changed[0]['truth'], changed[1]['truth'] = 'other', '2A'
        second = self.runner.crossfit(changed, features)
        fold = next(f for f in first['folds'] if f['heldOutAthlete'] == 'a')
        self.assertEqual(fold['trainIndices'], [2, 3])
        self.assertEqual(fold['testIndices'], [0, 1])
        for index in [0, 1]:
            self.assertEqual(first['records'][index]['rawScores'], second['records'][index]['rawScores'])
            self.assertEqual(first['records'][index]['trainingMajority'], second['records'][index]['trainingMajority'])

    def test_missing_pose_stays_in_evaluation_denominator(self):
        rows = [dict(id='one', sha256='clip1', athlete='a', truth='1A'),
                dict(id='two', sha256='clip2', athlete='b', truth='1A'),
                dict(id='three', sha256='clip3', athlete='c', truth='other')]
        result = self.runner.crossfit(rows, [None, np.array([1., 0.]), np.array([0., 1.])])
        self.assertEqual(result['records'][0]['prediction'], 'abstain')
        summary = self.runner.summarize(rows, result['records'])
        self.assertEqual(summary['nominalType']['total'], 3)
        self.assertEqual(summary['nominalType']['answered'], 2)
        self.assertEqual(summary['axelDetection']['total'], 3)
        self.assertEqual(summary['axelDetection']['answered'], 2)


if __name__ == '__main__':
    unittest.main()
