import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'work/nominal-boundary-robust-v1'))
import common


class ExperimentSafetyTests(unittest.TestCase):
    def test_explicit_missing_pose_is_preserved(self):
        frames={'100':{'missing':True,'sourceFrameSha256':'a'*64}}
        self.assertEqual(common.validate_pose({'weightsSha256':common.WEIGHTS,'frames':frames}),frames)

    def test_malformed_unmarked_pose_is_rejected(self):
        with self.assertRaises(ValueError):
            common.validate_pose({'weightsSha256':common.WEIGHTS,'frames':{'100':{}}})

    def test_aliases_and_recordings_are_excluded_transitively(self):
        rows=[{'sourceSha256':'a','athleteIds':['one'],'originalRecordingId':'r1'},
              {'sourceSha256':'b','athleteIds':['one','two'],'originalRecordingId':'r2'},
              {'sourceSha256':'c','athleteIds':['two'],'originalRecordingId':'r3'},
              {'sourceSha256':'d','athleteIds':['three'],'originalRecordingId':'r3'},
              {'sourceSha256':'e','athleteIds':['four'],'originalRecordingId':'r4'}]
        self.assertEqual(common.known_group(rows,'a'),{'a','b','c','d'})

    def test_unknown_source_cannot_claim_exclusion(self):
        with self.assertRaises(ValueError):common.known_group([], 'unknown')

    def test_missing_and_abstained_axels_remain_in_denominator(self):
        events=[{'id':'a','eventClass':'axel','start':1.,'end':1.5,'nominal':'1A'},
                {'id':'b','eventClass':'axel','start':3.,'end':3.5,'nominal':'2A'}]
        proposals=[{'candidateId':'p','start':1.,'end':1.5,'family':'axel','nominal':None}]
        result=common.score_program(proposals,events,10.)
        self.assertEqual((result['N'],result['D'],result['C'],result['FP']),(2,1,0,0))
        self.assertEqual(result['byClass']['2A']['N'],1)
        self.assertEqual(result['byClass']['2A']['D'],0)
        self.assertEqual(result['nominalAbstentionsOnDetectedAxels'],1)

    def test_duplicate_and_other_jump_are_false_axel_calls(self):
        events=[{'id':'a','eventClass':'axel','start':1.,'end':1.5,'nominal':'1A'},
                {'id':'b','eventClass':'other_jump','start':3.,'end':3.5,'nominal':None}]
        proposals=[{'candidateId':'p','start':1.,'end':1.5,'family':'axel','nominal':'1A'},
                   {'candidateId':'duplicate','start':1.,'end':1.5,'family':'axel','nominal':'1A'},
                   {'candidateId':'lutz','start':3.,'end':3.5,'family':'axel','nominal':'2A'}]
        result=common.score_program(proposals,events,10.)
        self.assertEqual((result['N'],result['D'],result['C'],result['FP']),(1,1,1,2))

    def test_uncertain_expert_answer_is_separate(self):
        events=[{'id':'u','eventClass':'uncertain','start':1.,'end':1.5,'nominal':None}]
        proposals=[{'candidateId':'p','start':1.,'end':1.5,'family':'axel','nominal':'2A'}]
        result=common.score_program(proposals,events,10.)
        self.assertEqual(result['FP'],0)
        self.assertEqual(result['unresolvedCalls'],1)
        self.assertIsNone(result['jointRecall'])


if __name__=='__main__':unittest.main()
