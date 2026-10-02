import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np,cv2
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import extract_dense_pose_type as module
class DenseTest(unittest.TestCase):
 def test_native_frames_preserved_and_identical_pixels_do_not_move(self):
  class Cap:
   n=0
   def get(self,key):return 3 if key==cv2.CAP_PROP_FRAME_COUNT else 25
   def read(self):
    image=np.full((50,50,3),0 if self.n<2 else 255,dtype=np.uint8);self.n+=1;return True,image
   def release(self):pass
  class Body:
   calls=0
   def det_model(self,image):return [[0,0,40,40]]
   def pose_model(self,image,bboxes):self.calls+=1;return np.full((1,17,2),self.calls,dtype=float),np.ones((1,17))
  body=Body()
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'input.mp4';source.write_bytes(b'test')
   with patch.object(cv2,'VideoCapture',return_value=Cap()),patch.object(module,'model_and_provenance',return_value=(body,{})):
    result=module.extract(source,Path(d)/'cache')
   with np.load(result,allow_pickle=False) as data:
    self.assertEqual(data['frame_indices'].tolist(),[0,1,2]);np.testing.assert_allclose(data['times'],[0,.04,.08]);np.testing.assert_array_equal(data['points'][0],data['points'][1]);self.assertFalse(np.array_equal(data['points'][1],data['points'][2]))
   self.assertEqual(body.calls,2)
if __name__=='__main__':unittest.main()
