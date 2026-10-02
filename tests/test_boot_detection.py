import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import boot_detection as b
class BootDetectionTests(unittest.TestCase):
 def fixture(self):
  p=[[0.,0.] for _ in range(23)];s=[.9]*23
  for start,x in [(17,200),(20,400)]:p[start]=[x+40,500];p[start+1]=[x+40,502];p[start+2]=[x,500]
  mirror=[v[:] for v in p]
  for a,c in [(17,20),(18,21),(19,22)]:
   mirror[a]=[1279-p[c][0],p[c][1]];mirror[c]=[1279-p[a][0],p[a][1]]
  return p,s,mirror,s[:]
 def test_mirror_restores_semantic_sides_and_geometry(self):
  r=b.candidates(*self.fixture(),1280,720,500)
  self.assertEqual([x['status'] for x in r],['visible','visible']);self.assertEqual(r[0]['heel'],[200.,500.]);self.assertEqual(r[0]['toe'],[240.,501.])
 def test_confident_mirror_disagreement_is_not_trusted(self):
  p,s,m,t=self.fixture();m[22][0]-=40
  r=b.candidates(p,s,m,t,1280,720,500);self.assertEqual(r[0]['status'],'uncertain');self.assertIn('mirror_disagreement',r[0]['reasons'])
 def test_end_on_short_foot_does_not_get_angle(self):
  p,s,m,t=self.fixture();p[17]=p[18]=[204,500];m[20]=m[21]=[1075,500]
  r=b.candidates(p,s,m,t,1280,720,500);self.assertIn('foreshortened',r[0]['reasons']);self.assertIsNone(r[0]['imageHeadingDegrees'])
 def test_outside_and_nonfinite_do_not_leak_geometry(self):
  p,s,m,t=self.fixture();p[19]=[float('nan'),500]
  r=b.candidates(p,s,m,t,1280,720,500);self.assertIsNone(r[0]['heel']);self.assertIsNone(r[0]['toe'])
 def test_confidence_failure_and_recovery_are_frame_local(self):
  p,s,m,t=self.fixture();s[17]=.1
  self.assertEqual(b.candidates(p,s,m,t,1280,720,500)[0]['status'],'uncertain')
  self.assertEqual(b.candidates(*self.fixture(),1280,720,500)[0]['status'],'visible')
 def test_near_identical_feet_are_ambiguous(self):
  p,s,m,t=self.fixture()
  for a,c in [(17,20),(18,21),(19,22)]:p[c]=p[a][:];m[a]=m[c][:]
  r=b.candidates(p,s,m,t,1280,720,500);self.assertTrue(all('feet_overlap' in x['reasons'] for x in r))
 def test_missing_keypoints_rejected(self):
  with self.assertRaises(ValueError):b.candidates([],[],[],[],1280,720,500)

class TemporalTests(unittest.TestCase):
 def foot(self,side,x,reverse=False):
  return dict(side=side,heel=[x,100],toe=[x+(-30 if reverse else 30),100],status='visible',reasons=[],imageHeadingDegrees=180 if reverse else 0,projectedLength=30)
 def test_identity_exchange_flagged_without_relabeling(self):
  frames=[dict(frameIndex=1,candidates=[self.foot('left',100),self.foot('right',300)]),dict(frameIndex=2,candidates=[self.foot('left',300),self.foot('right',100)])]
  result=b.temporal_checks(frames)
  self.assertEqual(result[1]['candidates'][0]['heel'],[300,100]);self.assertIn('side_identity_change',result[1]['candidates'][0]['reasons'])
  self.assertEqual(frames[1]['candidates'][0]['status'],'visible')
 def test_heading_flip_flagged_then_independent_detection_recovers(self):
  frames=[dict(frameIndex=i,candidates=[self.foot('left',100,i>1)]) for i in (1,2,3)]
  result=b.temporal_checks(frames)
  self.assertEqual(result[1]['candidates'][0]['status'],'uncertain');self.assertEqual(result[2]['candidates'][0]['status'],'visible')
 def test_gaps_not_treated_as_adjacent_frames(self):
  frames=[dict(frameIndex=1,candidates=[self.foot('left',100)]),dict(frameIndex=8,candidates=[self.foot('left',100,True)])]
  self.assertEqual(b.temporal_checks(frames)[1]['candidates'][0]['status'],'visible')



class LandingCandidateTests(unittest.TestCase):
 def foot(self,side,x,y,status='visible'):
  return dict(side=side,toe=[x+30,y],heel=[x,y],score=.8,status=status,reasons=[],projectedLength=30,imageHeadingDegrees=0)
 def test_lower_foot_keeps_role_when_model_side_changes(self):
  f=[dict(frameIndex=10,candidates=[self.foot('right',100,500),self.foot('left',200,400)]),dict(frameIndex=11,candidates=[self.foot('left',102,500),self.foot('right',202,400)])]
  r=b.landing_candidates(f,10)
  self.assertEqual(r[0]['candidates'][-1]['heel'],[100,500]);self.assertEqual(r[1]['candidates'][-1]['heel'],[102,500]);self.assertEqual(r[1]['candidates'][-1]['side'],'landing')
 def test_do_not_replace_uncertain_lower_foot_with_clear_free_foot(self):
  f=[dict(frameIndex=10,candidates=[self.foot('right',100,500,'uncertain'),self.foot('left',200,400)])]
  self.assertEqual(b.landing_candidates(f,10)[0]['candidates'][-1]['status'],'uncertain')
 def test_equal_height_and_before_window_are_unresolved(self):
  f=[dict(frameIndex=n,candidates=[self.foot('right',100,500),self.foot('left',200,501)]) for n in [3,10]]
  r=b.landing_candidates(f,10)
  self.assertIn('outside_landing_window',r[0]['candidates'][-1]['reasons']);self.assertIn('landing_choice_ambiguous',r[1]['candidates'][-1]['reasons'])
if __name__=='__main__':unittest.main()
