import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'work/family-personal-addition-v1/training.py'
if path.exists():
    spec = importlib.util.spec_from_file_location('personal_addition_training', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
else:
    module = None


def personal(source='b' * 64, identifier='jump-1', **updates):
    event = dict(eventId='personal-review:' + identifier, originalEventId=identifier,
        sourceSha256=source, family='axel', nominal='2A', elementCode='2A<<',
        startSeconds=2.0510255127563783, endSeconds=2.4679006169751543,
        labelScope='full_review', reviewComplete=True, modelTrainingEligible=True,
        videoId='personal-17', athleteId='personal:k', posePath='poses/17.json',
        provenance=[dict(path='review.json', sha256='c' * 64)],
        automaticUnderrotation=None, sourceFrameContactsVerified=False)
    event.update(updates)
    return event


def old(source='a' * 64, identifier='old-1', **updates):
    event = dict(id=identifier, sourceSha256=source, family='other', start=1., end=1.5)
    event.update(updates)
    return event


class PersonalAdditionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'Personal addition training adapter is missing')

    def test_review_seconds_remain_exact_without_inventing_contact_frames(self):
        source = personal()
        row = module.fold_events([], [source], set())[0]
        self.assertEqual(row['start'], source['startSeconds'])
        self.assertEqual(row['end'], source['endSeconds'])
        self.assertFalse(row['sourceFrameContactsVerified'])
        self.assertNotIn('lastContactFrame', row)
        self.assertNotIn('firstContactFrame', row)

    def test_known_target_alias_is_excluded_from_old_and_added_data(self):
        target, alias = 'd' * 64, 'e' * 64
        rows = module.fold_events([old(target), old()],
            [personal(alias), personal(identifier='retained')], {target, alias})
        self.assertEqual({r['sourceSha256'] for r in rows}, {'a' * 64, 'b' * 64})
        self.assertEqual(len(rows), 2)

    def test_expert_sign_is_preserved_separately_and_never_predicted(self):
        row = module.fold_events([], [personal()], set())[0]
        self.assertEqual(row['nominal'], '2A')
        self.assertEqual(row['elementCode'], '2A<<')
        self.assertIsNone(row['automaticUnderrotation'])

    def test_duplicate_review_or_renamed_same_interval_has_one_weight(self):
        first = personal()
        renamed = personal(identifier='renamed')
        rows = module.fold_events([], [first, copy.deepcopy(first), renamed], set())
        self.assertEqual(len(rows), 1)

    def test_same_source_event_with_changed_bounds_is_rejected(self):
        with self.assertRaises(ValueError):
            module.fold_events([], [personal(), personal(endSeconds=2.6)], set())

    def test_conflicting_label_on_same_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            module.fold_events([], [personal(), personal(identifier='other', nominal='1A', elementCode='1A')], set())

    def test_incomplete_unknown_or_model_label_is_rejected(self):
        for updates in [dict(reviewComplete=False), dict(modelTrainingEligible=False),
            dict(labelScope='candidate'), dict(family='unknown'), dict(nominal='3A'),
            dict(elementCode='1A'), dict(provenance=[]), dict(automaticUnderrotation='<')]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                module.fold_events([], [personal(**updates)], set())

    def test_invalid_seconds_do_not_enter_training(self):
        for updates in [dict(startSeconds=True), dict(startSeconds=-.01),
            dict(startSeconds=float('nan')), dict(endSeconds=float('inf')),
            dict(endSeconds=2.), dict(startSeconds='2.1')]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                module.fold_events([], [personal(**updates)], set())

    def test_existing_events_and_input_records_are_not_modified(self):
        a, b = old(), personal()
        before = copy.deepcopy([a, b])
        rows = module.fold_events([a], [b], set())
        self.assertEqual([a, b], before)
        self.assertEqual(rows[0], dict(a, featureBasis='old'))
        self.assertEqual(rows[1]['featureBasis'], 'personal-pose')


if __name__ == '__main__':
    unittest.main()
