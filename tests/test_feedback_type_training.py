"""Guard expert eligibility, source separation, and label-free held-out scoring."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'work/new-programs-feedback-type-v1/run.py'


class FeedbackTrainingTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(RUNNER.is_file(), 'Feedback runner has not been implemented')
        spec = importlib.util.spec_from_file_location('feedback_type_training', RUNNER)
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)

    def test_pending_and_ineligible_labels_never_enter_training(self):
        rows = [dict(id='a', element='other', reviewStatus='confirmed', trainEligible=True),
                dict(id='b', element='2A', reviewStatus='pending_clip_mapping', trainEligible=True),
                dict(id='c', element='2A', reviewStatus='confirmed', trainEligible=False)]
        self.assertEqual([r['id'] for r in self.runner.select_feedback(rows)], ['a'])

    def test_downgrade_sign_preserves_attempted_double_axel(self):
        row = dict(id='a', element='2A', elementCode='2A<<', reviewStatus='confirmed', trainEligible=True)
        self.assertEqual(self.runner.select_feedback([row])[0]['truth'], '2A')
        row['element'] = '1A'
        with self.assertRaises(ValueError):
            self.runner.select_feedback([row])

    def test_same_source_reencoded_clip_cannot_be_a_holdout(self):
        with self.assertRaises(ValueError):
            self.runner.assert_disjoint([dict(sha256='clip-a', sourceSha256='source')],
                                        [dict(sha256='clip-b', sourceSha256='source')])
        with self.assertRaises(ValueError):
            self.runner.assert_disjoint([dict(sha256='same')], [dict(sha256='same')])

    def test_corrupt_or_incompatible_cache_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ('a' * 64 + '.npz')
            row = dict(sha256='a' * 64)
            provenance = dict(extractor='test')
            for changed in [dict(source_sha256='b' * 64),
                            dict(feature=np.full(512, np.nan)),
                            dict(feature=np.zeros(511)),
                            dict(provenance=json.dumps(dict(extractor='wrong')))]:
                payload = dict(source_sha256=row['sha256'], feature=np.ones(512),
                               provenance=json.dumps(provenance), extractor='test')
                payload.update(changed)
                np.savez_compressed(path, **payload)
                with self.assertRaises(ValueError):
                    self.runner.cached_feature(row, Path(folder), provenance)

    def test_both_clips_of_held_out_athlete_are_excluded_and_own_truth_is_inert(self):
        base = [dict(id='base1', sha256='b1', truth='2A'), dict(id='base2', sha256='b2', truth='other')]
        bx = np.array([[1., 0.], [0., 1.]])
        feedback = [dict(id='a1', sha256='a1', sourceSha256='pa', athleteGroup='a', truth='2A'),
                    dict(id='a2', sha256='a2', sourceSha256='pa', athleteGroup='a', truth='other'),
                    dict(id='c1', sha256='c1', sourceSha256='pc', athleteGroup='c', truth='other')]
        fx = np.array([[.8, .2], [.3, .7], [.1, .9]])
        first = self.runner.feedback_crossfit(base, bx, feedback, fx)
        fold = next(f for f in first['folds'] if f['heldOutAthlete'] == 'a')
        self.assertEqual(fold['trainingFeedbackIds'], ['c1'])
        self.assertEqual(fold['testFeedbackIds'], ['a1', 'a2'])
        changed = [dict(r) for r in feedback]
        changed[0]['truth'], changed[1]['truth'] = 'other', '2A'
        second = self.runner.feedback_crossfit(base, bx, changed, fx)
        for index in [0, 1]:
            self.assertEqual(first['records'][index]['rawScores'], second['records'][index]['rawScores'])


if __name__ == '__main__':
    unittest.main()
