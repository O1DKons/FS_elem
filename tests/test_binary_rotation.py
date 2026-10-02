import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from binary_rotation import nested_evaluate

class BinaryRotationTests(unittest.TestCase):
 def test_outer_labels_cannot_change_own_prediction_or_selection(self):
  x={'a':np.arange(16,dtype=float).reshape(8,2),'b':np.tile([1.,np.nan],(8,1))}
  y=np.array([0,1,0,1,0,1,0,1]);groups=np.array(list('aabbccdd'))
  first=nested_evaluate(x,y,groups);changed=y.copy();changed[:2]=1-changed[:2]
  second=nested_evaluate(x,changed,groups)
  self.assertEqual(first['predictions'][:2],second['predictions'][:2])
  self.assertEqual(first['folds'][0]['selected'],second['folds'][0]['selected'])
  for fold in first['folds']:
   train=set(fold['trainIndices']);test=set(fold['testIndices'])
   self.assertFalse(train & test)
   for inner in fold['innerFolds']:
    self.assertTrue(set(inner['trainIndices']) <= train)
    self.assertTrue(set(inner['testIndices']) <= train)
    self.assertFalse(set(groups[inner['trainIndices']]) & set(groups[inner['testIndices']]))
 def test_missing_values_and_imbalance(self):
  result=nested_evaluate({'constant':np.full((8,2),np.nan)},np.array([0,0,1,1,1,1,1,1]),np.array(list('abcdefgh')))
  self.assertEqual(result['majority']['metrics']['accuracy'],.75)
  self.assertEqual(result['majority']['metrics']['balancedAccuracy'],.5)
if __name__=='__main__':unittest.main()
