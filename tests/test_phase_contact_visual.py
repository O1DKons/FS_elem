import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase_contact_visual import combine_features,jitter_slice,predict_pose,normalize_cached_frame
class VisualContactTests(unittest.TestCase):
 def test_missing_cached_pose_is_not_fabricated(self):
  self.assertEqual(normalize_cached_frame({'missing':True}),[])
 def test_untrusted_pickle_is_rejected_before_loading(self):
  with self.assertRaisesRegex(ValueError,'trusted'):
   predict_pose({},'/tmp','/tmp/untrusted-contact-model.joblib')
 def test_missing_embeddings_preserved_not_dropped(self):
  pose=np.arange(12).reshape(3,4);images={10:np.ones(512),12:np.full(512,2)}
  out=combine_features(pose,[10,11,12],images)
  self.assertEqual(out.shape,(3,516));self.assertTrue(np.isnan(out[1,4:]).all());np.testing.assert_array_equal(out[:,:4],pose)
 def test_jitter_keeps_flight_and_ground_context(self):
  indices=np.arange(100,175);selection=jitter_slice('competition-20-01-01',indices,125,149)
  actual=indices[selection]
  self.assertLessEqual(actual[0],121);self.assertGreaterEqual(actual[-1],153)
  self.assertGreaterEqual(actual[0],100);self.assertLessEqual(actual[-1],174)
  self.assertEqual(selection,jitter_slice('competition-20-01-01',indices,125,149))
if __name__=='__main__':unittest.main()
