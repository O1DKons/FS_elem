import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from pose_cache_contract import validate_pose_cache

class ContractTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.video=self.root/'video';self.video.write_bytes(b'video');self.cache=self.root/'pose.npz'
  self.contract={'pose_sha256':'a'*64,'detector_sha256':'b'*64,'native_extraction_sha256':'c'*64,'sampling':'native','recordingMode':'full-program-native-v1'}
  self.data=dict(points=np.ones((5,17,2)),scores=np.ones((5,17)),fps=50.,frame_indices=np.arange(5),times=np.arange(5)/50,source_sha256=hashlib.sha256(b'video').hexdigest(),provenance=json.dumps(self.contract))
  self.probe=patch('pose_cache_contract.probe_video_timeline',return_value={'fps':50.,'times':np.arange(5)/50});self.probe.start();self.addCleanup(self.probe.stop)
 def check(self):
  np.savez(self.cache,**self.data);return validate_pose_cache(self.video,self.cache,self.contract)
 def test_valid(self):self.assertEqual(self.check()['frameCount'],5)
 def test_wrong_provenance(self):
  for key in self.contract:
   with self.subTest(key=key):
    self.data['provenance']=json.dumps(dict(self.contract,**{key:'wrong'}))
    with self.assertRaises(ValueError):self.check()
 def test_truncated(self):
  for key in ['points','scores','frame_indices','times']:self.data[key]=self.data[key][:-1]
  with self.assertRaises(ValueError):self.check()
 def test_wrong_source(self):
  self.data['source_sha256']='d'*64
  with self.assertRaises(ValueError):self.check()
 def test_wrong_fps(self):
  self.data['fps']=25.;self.data['times']=np.arange(5)/25
  with self.assertRaises(ValueError):self.check()
 def test_vfr(self):
  with patch('pose_cache_contract.probe_video_timeline',return_value={'fps':50.,'times':np.array([0,.02,.04,.08,.1])}):
   with self.assertRaises(ValueError):self.check()
 def test_empty_contract(self):
  np.savez(self.cache,**self.data)
  with self.assertRaises(ValueError):validate_pose_cache(self.video,self.cache,{})
 def test_invalid_scores(self):
  self.data['scores'][0,0]=np.inf
  with self.assertRaises(ValueError):self.check()
if __name__=='__main__':unittest.main()
