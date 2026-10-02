import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase_duration_experiment import duration_bounds,decode_duration
class DurationTests(unittest.TestCase):
 def test_bounds_only_use_training_contacts(self):
  r=[dict(lastContact=10,firstContact=30),dict(lastContact=30,firstContact=53),dict(lastContact=10,firstContact=99)]
  expected=duration_bounds(r,[0,1]);r[2]['firstContact']=500
  self.assertEqual(duration_bounds(r,[0,1]),expected);self.assertEqual(expected['minAirborneFrames'],15);self.assertEqual(expected['maxAirborneFrames'],26)
 def test_decoder_matches_bruteforce_and_duration_constraint(self):
  rng=np.random.default_rng(7);p=rng.random((12,3));p/=p.sum(1,keepdims=True)
  a,b=decode_duration(p,3,5);self.assertGreaterEqual(b-a-1,3);self.assertLessEqual(b-a-1,5)
  lp=np.log(p);candidates=[(lp[:i+1,0].sum()+lp[i+1:j,1].sum()+lp[j:,2].sum(),i,j) for i in range(10) for j in range(i+2,12) if 3<=j-i-1<=5]
  best=max(candidates,key=lambda row:row[0]);self.assertEqual((a,b),best[1:])
 def test_short_and_invalid_sequence_abstains_by_error(self):
  with self.assertRaises(ValueError):decode_duration(np.ones((5,3))/3,4,6)
  with self.assertRaises(ValueError):decode_duration(np.full((10,3),np.nan),3,5)
if __name__=='__main__':unittest.main()
