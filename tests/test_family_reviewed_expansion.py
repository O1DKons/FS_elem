import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'work/family-reviewed-expansion-v1/training.py'
if path.exists():
    spec=importlib.util.spec_from_file_location('reviewed_family_training',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
else:module=None

def event(identifier,source='a',family='axel'):
    return dict(id=identifier,sourceSha256=source,family=family,start=10,end=10.5)

def reviewed(identifier='n',source='b'):
    return dict(sourceSha256=source,programId='p',posePath='p.json',kept=[dict(
        interval=dict(start=20,end=20.5),family='other',reviewedNegativeIds=[identifier],
        labelScope='reviewed_candidate_family',exhaustiveSourceReview=False,physicalContactTruth=None)])

class TrainingSelectionTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(module,'Reviewed expansion training selection is missing')

    def test_target_and_alias_are_excluded_from_every_added_category(self):
        rows=module.fold_events([event('old','target'),event('ok','other')],
            [event('added','alias')],[reviewed(source='target'),reviewed(source='new')],{'target','alias'})
        self.assertEqual({r['sourceSha256'] for r in rows},{'other','new'})

    def test_each_new_negative_retains_review_scope_and_no_contact_truth(self):
        rows=module.fold_events([],[],[reviewed()],set())
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['family'],'other')
        self.assertEqual(rows[0]['reviewedNegativeIds'],['n'])
        self.assertIsNone(rows[0]['physicalContactTruth'])
        self.assertFalse(rows[0]['exhaustiveSourceReview'])

    def test_duplicate_interval_does_not_increase_event_weight(self):
        rows=module.fold_events([],[],[reviewed(),reviewed('second')],set())
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['reviewedNegativeIds'],['n','second'])

    def test_unknown_or_positive_review_cannot_be_added_as_negative(self):
        for changed in [{'family':'axel'},{'labelScope':'unknown'},{'reviewedNegativeIds':[]}]:
            row=reviewed();row['kept'][0].update(changed)
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                module.fold_events([],[],[row],set())

    def test_old_and_exact_positive_events_keep_their_bounds(self):
        old=event('old');positive={**event('positive','c'),'posePath':'c.json'}
        rows=module.fold_events([old],[positive],[],set())
        self.assertEqual(rows,[{**old,'featureBasis':'old'},{**positive,'featureBasis':'pose'}])

if __name__=='__main__':unittest.main()
