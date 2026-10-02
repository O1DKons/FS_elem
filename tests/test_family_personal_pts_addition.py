import importlib.util
from pathlib import Path
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'work/family-personal-pts-addition-v1/run.py'
if path.exists():
    spec = importlib.util.spec_from_file_location('family_personal_pts_addition', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
else:
    module = None


class PersonalPtsAdditionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'Fixed eight-personal experiment is missing')
        self.registry = module.read(ROOT / 'data/axel-corpus-v4/sources.json')['sources']

    def test_records_are_original_complete_user_reviews_and_groups_remain_linked(self):
        events = module.personal_events(self.registry)
        self.assertEqual(len(events), 8)
        self.assertEqual(sum(e['nominal'] == '1A' for e in events), 5)
        by_video = {e['videoId']: e for e in events}
        self.assertEqual(by_video['personal-06']['athleteId'], by_video['personal-17']['athleteId'])
        self.assertEqual(by_video['personal-07']['athleteId'], by_video['personal-16']['athleteId'])
        self.assertEqual(len({e['athleteId'] for e in events}), 6)
        self.assertTrue(all(e['reviewComplete'] and e['automaticUnderrotation'] is None for e in events))

    def test_real_known_athlete_closure_excludes_related_personal_sources(self):
        events = module.personal_events(self.registry)
        by_video = {e['videoId']: e for e in events}
        for a, b in [('personal-06', 'personal-17'), ('personal-07', 'personal-16')]:
            excluded = module.known_group(self.registry, by_video[a]['sourceSha256'])
            selected = module.fold_events([], events, excluded)
            self.assertNotIn(by_video[b]['sourceSha256'], {e['sourceSha256'] for e in selected})
            self.assertNotIn(by_video[a]['sourceSha256'], {e['sourceSha256'] for e in selected})

    def test_original_target_automatic_features_and_five_compatible_vectors_are_unchanged(self):
        parent = module.read(module.PARENT / 'protocol.json')
        folds = module.rebuilt_folds(parent, self.registry)
        arrays = module.feature_arrays(parent, folds, self.registry)
        _, target = module.separation.arrays(parent)
        np.testing.assert_allclose(arrays['prediction'], target, rtol=0, atol=0, equal_nan=True)
        with np.load(ROOT / 'work/personal-review-rtmw-intake-v1/family-features.npz') as old:
            np.testing.assert_allclose(arrays['personal'][:5], old['x'], rtol=0, atol=0, equal_nan=True)
        self.assertEqual(arrays['personal'].shape, (8, 545))
        self.assertTrue(np.isnan(arrays['personal'][1]).any(), 'Cropped torso must retain missing channels')

    def test_each_target_uses_only_original_pool_and_allowed_personal_reviews(self):
        parent = module.read(module.PARENT / 'protocol.json')
        folds = module.rebuilt_folds(parent, self.registry)
        for fold in folds:
            excluded = set(fold['excludedKnownSourceHashes'])
            self.assertFalse(excluded.intersection(fold['trainingSourceHashes']))
            self.assertEqual(sum(e['featureBasis'] == 'personal-pose' for e in fold['events']), 8)
            expected_old = [e for e in parent['oldEvents'] if e['sourceSha256'] not in excluded]
            selected_old = [e for e in fold['events'] if e['featureBasis'] == 'old']
            self.assertEqual(len(selected_old), len(expected_old))
            self.assertEqual({e['featureBasis'] for e in fold['events']}, {'old', 'personal-pose'})


if __name__ == '__main__':
    unittest.main()
