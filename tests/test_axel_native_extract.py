"""Coverage and atomic-write regressions for the supported native extractor."""
import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from axel_native_extract import extract

class Capture:
 def __init__(self,short=False):self.index=0;self.short=short
 def get(self,key):
  import cv2
  return 61 if key==cv2.CAP_PROP_FRAME_COUNT else 1
 def read(self):
  self.index+=1
  return (False,None) if self.short and self.index>30 else (True,np.zeros((20,20,3),np.uint8))
 def release(self):pass

class NativeExtractTests(unittest.TestCase):
 def run_case(self,short=False):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name);source=root/'source';source.write_bytes(b'fixture')
  with patch('cv2.VideoCapture',return_value=Capture(short)),patch('axel_native_extract.model_and_provenance',return_value=(SimpleNamespace(det_model=lambda image:[]),{'fixture':True})):
   output=extract(source,root/'cache')
  return output
 def test_complete_long_source(self):
  with np.load(self.run_case(),allow_pickle=False) as d:
   self.assertEqual(len(d['points']),61);np.testing.assert_array_equal(d['frame_indices'],np.arange(61))
 def test_incomplete_decode_rejected(self):
  with self.assertRaisesRegex(ValueError,'Incomplete'):self.run_case(True)
if __name__=='__main__':unittest.main()
