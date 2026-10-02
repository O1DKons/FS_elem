"""Consumer contracts and missing-observation handling, without model downloads."""
import copy
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from axel_nominal import hip_features, nominal_prediction
from axel_rtmw_windows import window_specs,validate_window

class NominalRuntimeTests(unittest.TestCase):
 def test_strict_flight_and_missing(self):
  frames={str(i):{'points':np.ones((23,2)).tolist(),'scores':np.ones(23).tolist()} for i in range(12)}
  frames['2']={};frames['9']={}
  x,qa=hip_features(frames,2,9)
  self.assertEqual(qa['flightFrames'],6)
  self.assertEqual(qa['usableHipFrames'],6)
  self.assertEqual(x.shape,(40,))
  frames['3']={};x,qa=hip_features(frames,2,9)
  self.assertTrue(np.isnan(x).all())
 def test_all_missing_abstains(self):
  pred=nominal_prediction({'frames':{}},0,8,{}, {'pose_sha256':'a'}, {'pose_sha256':'a'})
  self.assertIsNone(pred['nominal'])
  self.assertEqual(pred['reason'],'insufficient_hip_observations')
 def test_wrong_weights_rejected_before_model(self):
  with self.assertRaises(ValueError):nominal_prediction({'frames':{}},0,8,{}, {'pose_sha256':'a'}, {'pose_sha256':'b'})
 def test_window_selection(self):
  rows=window_specs([{'startSeconds':.2,'endSeconds':.6,'family':'axel'},{'startSeconds':.8,'endSeconds':1,'family':'other'}],50,100)
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['startFrame'],10);self.assertEqual(rows[0]['endFrame'],30)
  self.assertEqual(rows[0]['cropStartFrame'],0);self.assertEqual(rows[0]['cropEndFrame'],50)
 def test_off_grid_event_rejected(self):
  with self.assertRaises(ValueError):window_specs([{'startSeconds':.201,'endSeconds':.6,'family':'axel'}],50,100)
 def test_immutable_contract(self):
  w=window_specs([{'startSeconds':.2,'endSeconds':.6,'family':'axel'}],50,100)[0]
  contract={'pose_sha256':'a','detector_sha256':'b','extractor_sha256':'c','geometry':'RTMW23_source_pixels'}
  d={'schemaVersion':1,'sourceSha256':'source','fps':50,'frameCount':100,'window':w,'provenance':contract,'frames':{str(i):{'points':[],'scores':[],'frameIndex':i,'time':i/50} for i in range(51)}}
  validate_window(d,'source',50,100,w,contract)
  for key in contract:
   x=copy.deepcopy(d);x['provenance'][key]='wrong'
   with self.subTest(key=key),self.assertRaises(ValueError):validate_window(x,'source',50,100,w,contract)
  x=copy.deepcopy(d);del x['frames']['20']
  with self.assertRaises(ValueError):validate_window(x,'source',50,100,w,contract)
class ConfigBindingTests(unittest.TestCase):
 def test_nominal_weights_bound_to_training(self):
  from run_axel_baseline import verify_nominal_contract
  training={'models':{'nominal':{'trainingPoseSha256':'rtmw'}}}
  verify_nominal_contract({'nominalPoseContract':{'pose_sha256':'rtmw'}},training)
  with self.assertRaises(ValueError):verify_nominal_contract({'nominalPoseContract':{'pose_sha256':'rtmpose'}},training)

if __name__=="__main__":unittest.main()
