"""Safeguards for the local native208 research experiment."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'work/native-feedback-crossfit-v1/run.py'


def module():
    assert RUNNER.exists(), 'Native feedback evaluation runner is missing'
    spec = importlib.util.spec_from_file_location('native_feedback_crossfit', RUNNER)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class NativeFeedbackSafetyTests(unittest.TestCase):
    def test_source_alias_and_athlete_links_are_transitive(self):
        rows = [dict(id='a', athleteGroup='A', sourceSha256='s1', sha256='a'),
                dict(id='b', athleteGroup='A', sourceSha256='s2', sha256='b'),
                dict(id='c', athleteGroup='alias', sourceSha256='s2', sha256='c'),
                dict(id='d', athleteGroup='B', sourceSha256='s3', sha256='d')]
        groups = module().feedback_groups(rows)
        self.assertEqual(groups, [[0, 1, 2], [3]])

    def test_sha_and_athlete_overlap_each_reject_a_fold(self):
        m = module()
        held = [dict(sha256='c2', sourceSha256='source', athleteGroup='A')]
        for train in [dict(sha256='source'), dict(sha256='z', athleteGroup='A')]:
            with self.subTest(train=train), self.assertRaises(ValueError):
                m.assert_disjoint([train], held)
        m.assert_disjoint([dict(sha256='safe', athleteGroup='B')], held)

    def test_abstain_never_counts_as_other_or_axel(self):
        result = module().summarize(['1A', '2A', 'other', 'other'], ['abstain', '3A', 'abstain', 'other'])
        self.assertEqual(result['nominalType']['correct'], 1)
        self.assertEqual(result['nominalType']['total'], 4)
        self.assertEqual(result['nominalType']['accuracy'], .25)
        self.assertEqual(result['axelDetection']['correct'], 2)
        self.assertEqual(result['axelDetection']['axelRecall'], .5)
        self.assertEqual(result['axelDetection']['otherRejection'], .5)
        self.assertEqual(result['axelDetection']['balancedAccuracy'], .5)
        self.assertEqual(result['coverage'], .5)

    def test_unknown_label_and_length_mismatch_rejected(self):
        m = module()
        for truth, predictions in [(['unknown'], ['other']), (['2A'], []), (['2A'], ['unknown'])]:
            with self.subTest(truth=truth, predictions=predictions), self.assertRaises(ValueError):
                m.summarize(truth, predictions)

    def test_grouping_requires_identity_and_forbids_duplicate_clips(self):
        m = module()
        for rows in [[dict(id='a', sha256='x', sourceSha256='s')],
                     [dict(id='a', sha256='x', sourceSha256='s', athleteGroup='A'),
                      dict(id='b', sha256='x', sourceSha256='s', athleteGroup='A')]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                m.feedback_groups(rows)

    def test_majority_is_selected_using_training_rows_only(self):
        result = module().training_majority(['1A', '2A', 'other', 'other'])
        self.assertEqual(result, {'nominal': 'other', 'binary': 'Axel'})


if __name__ == '__main__':
    unittest.main()
