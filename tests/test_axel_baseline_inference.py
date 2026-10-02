import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from axel_baseline_inference import gated_intervals,compatible_nominal_pose
class InferenceTests(unittest.TestCase):
 def test_gate_deduplicates(self):
  t=np.arange(10)/50
  a=np.array([0,1,1,1,0,0,1,0,0,0],float)
  self.assertEqual(gated_intervals(t,a,a),[(.02,.06)])
 def test_threshold_strict(self):
  self.assertEqual(gated_intervals(np.arange(4),np.ones(4)*.5,np.ones(4)),[])
 def test_incompatible_nominal(self):
  with self.assertRaises(ValueError):compatible_nominal_pose({'pose_sha256':'rtmpose'},{'pose_sha256':'rtmw'})
 def test_compatible(self):compatible_nominal_pose({'pose_sha256':'rtmw'},{'pose_sha256':'rtmw'})
if __name__=='__main__':unittest.main()
