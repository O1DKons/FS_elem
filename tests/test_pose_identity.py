import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('identity',Path(__file__).resolve().parents[1]/'scripts/pose_identity.py')
m=importlib.util.module_from_spec(spec)
if Path(spec.origin).exists():spec.loader.exec_module(m)

def sequence():
    return [dict(frameIndex=n,time=n*.02,landmarks=[dict(name=s+'_'+p,x=x+n*.005,y=y,confidence=.9)
        for s,x in [('left',.25),('right',.75)] for p,y in [('hip',.3),('knee',.5),('ankle',.7)]] ) for n in range(7)]

def swap(frame):
    for p in frame['landmarks']:
        p['name']=('right_' if p['name'].startswith('left_') else 'left_')+p['name'].split('_')[1]

class IdentityTests(unittest.TestCase):
    def test_short_swap_detected_without_moving_or_mutating_points(self):
        self.assertTrue(hasattr(m,'propose'), 'Temporal identity probe missing')
        f=sequence();swap(f[2]);swap(f[3])
        result=m.propose(f,1000,1000)
        lower=[r for r in result if r['region']=='legs']
        self.assertEqual([(r['startFrame'],r['endFrame']) for r in lower],[(2,3)])
        corrected=m.apply(f,result)
        self.assertEqual(next(p for p in corrected[2]['landmarks'] if p['name']=='left_knee')['x'],.26)
        self.assertEqual(next(p for p in f[2]['landmarks'] if p['name']=='left_knee')['x'],.76)
        self.assertEqual(sorted((p['x'],p['y'],p['confidence']) for p in f[2]['landmarks']),sorted((p['x'],p['y'],p['confidence']) for p in corrected[2]['landmarks']))

    def test_smooth_motion_and_ambiguous_overlap_are_not_corrected(self):
        self.assertTrue(hasattr(m,'propose'))
        self.assertEqual(m.propose(sequence(),1000,1000),[])
        f=sequence()
        for frame in f:
            for p in frame['landmarks']:p['x']=.5
        self.assertEqual(m.propose(f,1000,1000),[])

    def test_missing_low_confidence_or_noncontiguous_context_abstains(self):
        self.assertTrue(hasattr(m,'propose'))
        for kind in ('missing','confidence','gap'):
            f=sequence();swap(f[3])
            if kind=='missing':f[3]['landmarks'].pop()
            if kind=='confidence':
                for p in f[3]['landmarks']:p['confidence']=.01
            if kind=='gap':f[3]['frameIndex']=30
            self.assertEqual(m.propose(f,1000,1000),[],kind)

    def test_proposals_cannot_modify_each_others_context(self):
        self.assertTrue(hasattr(m,'select_nonconflicting'))
        candidates=[dict(region='legs',startFrame=2,endFrame=3,contextFrames=[1,4],gainPx=40),
                    dict(region='legs',startFrame=4,endFrame=4,contextFrames=[3,5],gainPx=20)]
        result=m.select_nonconflicting(candidates)
        self.assertEqual([(p['startFrame'],p['endFrame']) for p in result],[(2,3)])

    def test_collapsed_joint_in_second_context_frame_blocks_proposal(self):
        f=sequence();swap(f[2]);swap(f[3])
        for p in f[5]['landmarks']:
            if p['name'].endswith('_knee'):p['x']=.5
        self.assertEqual(m.propose(f,1000,1000),[],
            'Coincident knees in supporting context cannot establish side identity')

    def test_collapsed_joint_is_ambiguous_even_with_high_confidence(self):
        self.assertTrue(hasattr(m,'ambiguous_joints'))
        f=sequence()[0]
        for p in f['landmarks']:
            if p['name'].endswith('_knee'):p['x']=.5
        self.assertEqual(m.ambiguous_joints(f['landmarks'],'legs',1000,1000),['knee'])

    def test_persistent_wrong_side_cannot_be_claimed_as_resolved(self):
        self.assertTrue(hasattr(m,'propose'))
        f=sequence()
        for frame in f:swap(frame)
        self.assertEqual(m.propose(f,1000,1000),[])

if __name__=='__main__':unittest.main()
