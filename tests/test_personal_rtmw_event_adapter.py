import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'work/personal-rtmw-cascade-transfer-v1/evaluate.py'
if path.exists():
    spec=importlib.util.spec_from_file_location('personal_cascade_evaluator',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
else: module=None


class PersonalEventAdapterTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module,'Nested automatic interval adapter missing')
        self.source=[dict(videoId='p',duration=3.)]
        self.expert=[dict(videoId='p',eventId='true',startSeconds=1.,endSeconds=1.4,nominal='1A')]
        self.row=dict(candidateId='p-01',programId='p',interval=dict(start=1.05,end=1.45),family='axel',nominalConditional='1A')

    def test_nested_candidate_matches_same_flat_event_rule(self):
        result=module.calculate([self.row],self.source,self.expert)
        self.assertEqual({k:result['totals'][k] for k in ['N','D','C','FP']},dict(N=1,D=1,C=1,FP=0))

    def test_duplicate_keeps_false_positive_penalty(self):
        second=dict(self.row,candidateId='p-02')
        result=module.calculate([self.row,second],self.source,self.expert)
        self.assertEqual(result['totals']['FP'],1)
        self.assertEqual(result['totals']['C'],1)

    def test_wrong_nominal_and_no_proposal_remain_failures(self):
        wrong=module.calculate([dict(self.row,nominalConditional='2A')],self.source,self.expert)['totals']
        self.assertEqual(wrong['D'],1);self.assertEqual(wrong['C'],0)
        missing=module.calculate([],self.source,self.expert)['totals']
        self.assertEqual(missing['N'],1);self.assertEqual(missing['C'],0)

    def test_other_family_does_not_count_as_an_axel(self):
        result=module.calculate([dict(self.row,family='other')],self.source,self.expert)['totals']
        self.assertEqual(result['D'],0);self.assertEqual(result['C'],0)


if __name__=='__main__':unittest.main()
