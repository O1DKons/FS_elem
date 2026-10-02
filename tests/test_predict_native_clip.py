import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from predict_native_clip import predict_clip,load_model,ROOT,OUTPUT
class NativeClipTests(unittest.TestCase):
 def test_cached_challenge_parity_without_extraction(self):
  reference=json.loads((ROOT/'work/video-native-type-challenge/results.json').read_text())['records'][0]
  video=ROOT/'data/step3-candidates/clips'/(reference['attemptId']+'.mp4')
  with patch('extract_dense_pose_type.model_and_provenance',side_effect=AssertionError('Must not initialize extractor for cached test')):
   result=predict_clip(video,cache_dir=ROOT/'phase-cache/video-pose-dense-challenge-v2')
  expected=reference['prediction']
  self.assertEqual(result['predicted_label'],expected['predicted_label']);self.assertEqual(result['extraction_status'],expected['extraction_status'])
  self.assertEqual(result['raw_scores'],expected['raw_scores']);self.assertEqual(result['video_sha256'],expected['video_sha256'])
 def test_invalid_contract_fails_before_video_access(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'bad.npz'
   with np.load(OUTPUT/'classifier.npz',allow_pickle=False) as original:values={k:original[k] for k in original.files}
   provenance=json.loads(str(values['provenance']));provenance['contract']['confidence']=.9;values['provenance']=json.dumps(provenance);np.savez(path,**values)
   with self.assertRaisesRegex(ValueError,'contract mismatch'):predict_clip('nonexistent.mp4',path)
if __name__=='__main__':unittest.main()
