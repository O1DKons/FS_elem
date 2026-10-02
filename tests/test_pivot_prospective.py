import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from pivot_prospective import validate_candidates


class ProspectivePivotTests(unittest.TestCase):
    def setUp(self):
        self.training = [
            dict(attemptId='train-1', athlete='Skater A', sourceSha256='a'),
            dict(attemptId='train-2', athlete='Skater B', sourceSha256='b'),
        ]

    def test_accepts_unlabelled_candidates_from_new_athletes_and_sources(self):
        candidates = [
            dict(attemptId='candidate-1', athlete='Skater C', sourceSha256='c'),
            dict(attemptId='candidate-2', athlete='Skater D', sourceSha256='d'),
        ]
        self.assertEqual(validate_candidates(candidates, self.training), candidates)

    def test_rejects_candidate_whose_athlete_was_in_training(self):
        candidates = [dict(attemptId='candidate-1', athlete='Skater A', sourceSha256='c')]
        with self.assertRaisesRegex(ValueError, 'athlete leakage'):
            validate_candidates(candidates, self.training)

    def test_rejects_candidate_whose_source_was_in_training(self):
        candidates = [dict(attemptId='candidate-1', athlete='Skater C', sourceSha256='a')]
        with self.assertRaisesRegex(ValueError, 'source leakage'):
            validate_candidates(candidates, self.training)

    def test_rejects_any_existing_expert_target(self):
        candidates = [dict(attemptId='train-1', athlete='Skater C', sourceSha256='c')]
        with self.assertRaisesRegex(ValueError, 'already appears'):
            validate_candidates(candidates, self.training)


if __name__ == '__main__':
    unittest.main()
