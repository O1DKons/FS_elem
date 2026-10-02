import copy
import importlib.util
from pathlib import Path
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT/'work/family-negative-separation-v1/labels.py'
if MODULE.exists():
    spec = importlib.util.spec_from_file_location('family_negative_labels', MODULE)
    labels = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(labels)
else:
    labels = None


def sources():
    return [dict(exhaustive=True, sourceSha256='a'*64,
                 events=[dict(id='a',eventClass='axel'),dict(id='b',eventClass='other_jump'),
                         dict(id='u',eventClass='uncertain')])]


def event(identity='a', family='axel', background=False):
    return dict(sourceIndex=0, sourceSha256='a'*64, id=identity, family=family,
                syntheticBackground=background)


class NegativeSeparationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(labels, 'Three-class label adapter is not implemented')

    def test_existing_positive_other_jump_and_fixed_background_remain_distinct(self):
        self.assertEqual(labels.training_class(event(), sources()), 'axel')
        self.assertEqual(labels.training_class(event('b','other'), sources()), 'other_jump')
        self.assertEqual(labels.training_class(event('background-1','other',True), sources()), 'background')

    def test_unknown_and_contradictory_event_cannot_be_used_as_negative(self):
        for row in [event('u','other'),event('missing','other'),event('a','other'),
                    event('b','axel'),event('background-1','axel',True)]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                labels.training_class(row, sources())

    def test_background_requires_complete_review_and_exact_source_binding(self):
        with self.assertRaises(ValueError):
            labels.training_class(event('background-1','other',True),
                                  [{**sources()[0],'exhaustive':False}])
        with self.assertRaises(ValueError):
            labels.training_class({**event(),'sourceSha256':'b'*64}, sources())
        with self.assertRaises(ValueError):
            labels.training_class({**event(),'sourceIndex':True}, sources())

    def test_classification_is_argmax_and_both_negative_categories_produce_no_axel(self):
        scores = np.array([[0.8,0.1,0.1],[0.2,0.7,0.1],[0.1,0.2,0.7]])
        family, category = labels.family_calls(scores, ['axel','background','other_jump'])
        self.assertEqual(family, ['axel','other','other'])
        self.assertEqual(category, ['axel','background','other_jump'])
        before=copy.deepcopy(scores)
        labels.family_calls(scores, ['axel','background','other_jump'])
        np.testing.assert_array_equal(scores, before)

    def test_nonfinite_scores_or_missing_category_fail_without_silent_prediction(self):
        for scores, classes in [(np.array([[np.nan,0,1]]),['axel','background','other_jump']),
                                (np.ones((2,2)),['axel','other_jump']),
                                (np.ones((2,3)),['axel','axel','background'])]:
            with self.subTest(classes=classes), self.assertRaises(ValueError):
                labels.family_calls(scores, classes)


if __name__=='__main__':
    unittest.main()
