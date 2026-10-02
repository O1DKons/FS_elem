import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from element_sign_sequence import sequence_features
class Tests(unittest.TestCase):
 def test_missing_not_interpolated(self):
  p=dict(coordinateSpace=dict(width=100,height=100),frames=[])
  self.assertTrue(np.isnan(sequence_features(p,dict(firstContact=20))).all())
 def test_order_and_swap(self):
  def frame(n,vertical):
   pts=[dict(name='left_'+part,x=.3,y=.3,confidence=1) for part in ['shoulder','hip']]
   pts += [dict(name='right_'+part,x=.3 if vertical else .6,y=.6 if vertical else .3,confidence=1) for part in ['shoulder','hip']]
   return dict(frameIndex=n,landmarks=pts)
  p=dict(coordinateSpace=dict(width=100,height=100),frames=[frame(8,False),frame(12,True)])
  a=sequence_features(p,dict(firstContact=20))
  self.assertEqual(len(a),28);self.assertAlmostEqual(a[0],1);self.assertAlmostEqual(a[4],-1)
  for f in p['frames']:
   for pt in f['landmarks']:pt['name']=pt['name'].replace('left','TMP').replace('right','left').replace('TMP','right')
  np.testing.assert_allclose(a,sequence_features(p,dict(firstContact=20)),equal_nan=True)
