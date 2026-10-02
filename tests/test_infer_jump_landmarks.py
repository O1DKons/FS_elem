import sys,unittest,tempfile,json,hashlib
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from infer_jump_landmarks import sample_timeline,track_box,normalize_wholebody,augment_contact
class LandmarkTests(unittest.TestCase):
 def test_resampling_preserves_source(self):
  rows=sample_timeline([0,.04,.08],50)
  self.assertEqual([x['sourceFrameIndex'] for x in rows],[0,0,1,1,2])
  self.assertEqual(rows[-1]['sourceTime'],.08)
  with self.assertRaises(ValueError):sample_timeline([0,0,.04],50)
  with self.assertRaises(ValueError):sample_timeline([0,11],50)
 def test_tracks_prior_person(self):
  self.assertEqual(track_box([[1,1,11,31],[50,0,100,100]],[0,0,10,30]),[1.,1.,11.,31.])
  self.assertIsNone(track_box([],None))
 def test_feet_normalized(self):
  points=[[50,25]]*23;scores=[.8]*23
  result=normalize_wholebody(points,scores,100,50)
  self.assertEqual(len(result),23);self.assertEqual(result[-1]['name'],'right_heel');self.assertEqual(result[-1]['x'],.5)
 def test_augment_separate_output_preserves_pose_and_rejects_changed_frame(self):
  try:import cv2
  except ImportError:self.skipTest('cv2 optional in plain Python')
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory);source=p/'source.mp4';source.write_bytes(b'source');weights=p/'weights';weights.write_bytes(b'weights');frame=p/'frame.png';frame.write_bytes(b'not decoded because pose missing')
   digest=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
   data={'fps':50,'width':1280,'height':720,'videoId':'test','sourcePath':str(source),'sourceSha256':digest(source),'model':{'weightsSha256':digest(weights)},'frames':[{'frameIndex':i,'time':i/50,'sourceFrameIndex':i,'sourceTime':i/50,'image':'frame.png','sourceFrameSha256':digest(frame),'raw':{}} for i in range(13)]}
   pose=p/'pose.json';pose.write_text(json.dumps(data));before=pose.read_bytes()
   with patch('infer_jump_landmarks.POSE',weights),patch('infer_jump_landmarks.models',return_value=(None,None)):
    result=augment_contact(p,.04);self.assertEqual(result['items'][0]['firstContact'],2);self.assertEqual(pose.read_bytes(),before)
    with self.assertRaises(ValueError):augment_contact(p,.04)
    frame.write_bytes(b'changed')
    with self.assertRaises(ValueError):augment_contact(p,.04,p/'other.json')
if __name__=='__main__':unittest.main()
