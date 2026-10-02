import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'work/all-stage-excluded-family-v1/helpers.py'
module = None
if PATH.exists():
    spec = importlib.util.spec_from_file_location('cascade_exclusion_helpers', PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


class AllStageExclusionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'All-stage exclusion checks are not implemented')
        self.registry = [
            {'sourceSha256': 'target', 'athleteIds': ['A'], 'originalRecordingId': 'r1'},
            {'sourceSha256': 'alias', 'athleteIds': ['A', 'B'], 'originalRecordingId': 'r2'},
            {'sourceSha256': 'crop', 'athleteIds': ['C'], 'originalRecordingId': 'r2'},
            {'sourceSha256': 'other', 'athleteIds': ['D'], 'originalRecordingId': 'r3'}]

    def test_transitive_athlete_and_recording_links_are_excluded(self):
        self.assertEqual(module.known_group(self.registry, 'target'), {'target', 'alias', 'crop'})

    def test_unknown_target_is_rejected(self):
        with self.assertRaises(ValueError):
            module.known_group(self.registry, 'unknown')

    def test_inner_threshold_fit_cannot_contain_target_alias(self):
        with self.assertRaisesRegex(ValueError, 'threshold_inner'):
            module.assert_excluded({'target', 'alias'}, ['other', 'alias'], 'threshold_inner')

    def test_inner_threshold_validation_cannot_contain_target(self):
        with self.assertRaisesRegex(ValueError, 'threshold_validation'):
            module.assert_excluded({'target'}, ['target'], 'threshold_validation')

    def test_disjoint_stage_returns_auditable_source_list(self):
        self.assertEqual(module.assert_excluded({'target'}, ['other', 'other'], 'family'), ['other'])

    def test_receipt_can_supply_nominal_missing_from_older_family_review(self):
        row = dict(id='event', sourceSha256='other', nominal='1A')
        older = dict(candidateId='event', sourceSha256='other', family='axel', nominal=None)
        module.validate_family_receipt(row, older)

    def test_receipt_cannot_override_known_contradictory_family_or_nominal(self):
        row = dict(id='event', sourceSha256='other', nominal='1A')
        older = dict(candidateId='event', sourceSha256='other', family='axel', nominal=None)
        for patch in [dict(family='other'), dict(nominal='2A'), dict(sourceSha256='wrong')]:
            with self.assertRaises(ValueError):
                module.validate_family_receipt(row, dict(older, **patch))

    def test_expert_training_contacts_keep_exact_native_time(self):
        row = dict(id='event', sourceSha256='other', lastContactFrame=699,
                   firstContactFrame=717, fps=50., nominal='1A', readyForContactTraining=True)
        event = module.expert_training_event(row, dict(sha256='other', fps=50., frameCount=1000))
        self.assertEqual((event['start'], event['end']), (13.98, 14.34))
        self.assertEqual(event['windowBasis'], 'user_exact_contacts')

    def test_expert_contacts_cannot_change_source_or_timebase(self):
        row = dict(id='event', sourceSha256='other', lastContactFrame=10,
                   firstContactFrame=30, fps=50., nominal='2A', readyForContactTraining=True)
        for source in [dict(sha256='wrong', fps=50., frameCount=1000),
                       dict(sha256='other', fps=25., frameCount=1000)]:
            with self.assertRaises(ValueError):
                module.expert_training_event(row, source)

    def test_invalid_or_incomplete_contacts_do_not_become_training(self):
        row = dict(id='event', sourceSha256='other', lastContactFrame=10,
                   firstContactFrame=30, fps=50., nominal='1A', readyForContactTraining=True)
        source = dict(sha256='other', fps=50., frameCount=1000)
        for patch in [dict(lastContactFrame=True), dict(firstContactFrame=10),
                      dict(firstContactFrame=1000), dict(readyForContactTraining=False),
                      dict(nominal=None)]:
            with self.assertRaises(ValueError):
                module.expert_training_event(dict(row, **patch), source)


if __name__ == '__main__':
    unittest.main()
