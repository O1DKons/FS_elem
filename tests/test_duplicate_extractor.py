"""Lightweight integration tests against the proposed extractor; no real models."""
import sys,unittest,tempfile,hashlib,json
from pathlib import Path
from unittest.mock import patch
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').is_file())
sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import infer_jump_landmarks as extract
from landing_rotation_model import predict_item
class DuplicateExtractorTests(unittest.TestCase):
 def test_real_loop_reuses_body_box_and_mirror_on_duplicate(self):
  import cv2,numpy as np
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory);source=p/'source.mp4';source.write_bytes(b'source');weights=p/'model';weights.write_bytes(b'fake weights');out=p/'out';out.mkdir()
   def decode(source,folder):
    rows=[]
    for n,k in enumerate([0,0,1,1]):
     im=np.full((720,1280,3),k,dtype=np.uint8);path=folder/f'{n}.png';cv2.imwrite(str(path),im)
     rows.append(dict(frameIndex=n,time=n/50,sourceFrameIndex=k,sourceTime=k/25,image=path.name,sourceFrameSha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return rows,{}
   class Detector:
    def __init__(self):self.calls=0
    def __call__(self,image):self.calls+=1;return [[100,100,500,650]]
   class Pose:
    def __init__(self):self.calls=0
    def __call__(self,image,bboxes):
     self.calls+=1;points=np.array([[[200+j*3+self.calls,150+j*10] for j in range(23)]],dtype=float)
     return points,np.full((1,23),.9)
   detector,pose=Detector(),Pose()
   with patch.object(extract,'decode',decode),patch.object(extract,'models',return_value=(detector,pose)),patch.object(extract,'POSE',weights),patch.object(extract,'DETECTOR',weights):
    result=extract.run(source,out,.02)
   frames=result['frames'];self.assertEqual(pose.calls,4);self.assertEqual(detector.calls,1)
   for a,b in [(0,1),(2,3)]:
    self.assertEqual(frames[a]['raw'],frames[b]['raw']);self.assertEqual(frames[a]['landmarks'],frames[b]['landmarks']);self.assertTrue(frames[b]['sourceObservationReused'])
   self.assertNotEqual(frames[0]['raw']['points'],frames[2]['raw']['points'])
   # Legacy duplicate inconsistency must not silently reuse an unrelated mirror crop.
   frames[1]['raw']['box'][0]+=1;(out/'pose.json').write_text(json.dumps(result))
   with patch.object(extract,'POSE',weights),patch.object(extract,'models') as loader:
    with self.assertRaisesRegex(ValueError,'Inconsistent duplicate'):extract.augment_contact(out,.02)
    loader.assert_not_called()
 def test_gate_missing_or_duplicate_provenance_abstains_before_model(self):
  def frame(n):return {'frameIndex':n,'sourceFrameIndex':0,'sourceFrameSha256':'a'*64,'candidates':[{'side':'landing','status':'visible','heel':[0,0],'toe':[10,0]}]}
  item={'firstContact':0,'frames':[frame(n) for n in range(11)]}
  result=predict_item(item,None,50);self.assertEqual(result['observedIntervals'],10);self.assertEqual(result['independentSourceIntervals'],0);self.assertEqual(result['status'],'insufficient_evidence')
  del item['frames'][0]['sourceFrameSha256'];result=predict_item(item,None,50);self.assertFalse(result['sourceProvenanceComplete'])
if __name__=='__main__':unittest.main()
