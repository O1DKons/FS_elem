import sys,unittest,copy
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from contact_timebase import resample_native
class TimebaseTests(unittest.TestCase):
 def fixture(self):
  p=np.arange(6*17*2).reshape(6,17,2);s=np.ones((6,17))
  d={'fps':50,'timing':{'originalFrameCount':6},'frames':[{'frameIndex':i,'time':i/50,'sourceFrameIndex':k,'sourceTime':t} for i,(k,t) in enumerate([(0,.3),(1,.317),(2,.341),(4,.379),(5,.399)])]}
  return p,s,np.arange(6),d
 def test_uses_source_indices_with_varying_timestamps(self):
  p,s,i,d=self.fixture();a,b=resample_native(p,s,i,d)
  np.testing.assert_equal(a,p[[0,1,2,4,5]]);np.testing.assert_equal(b,s[[0,1,2,4,5]])
 def test_duplicates_preserved(self):
  p,s,i,d=self.fixture();d['frames'][1].update(sourceFrameIndex=0,sourceTime=.3)
  a,_=resample_native(p,s,i,d);np.testing.assert_equal(a[0],a[1])
 def test_rejects_misalignment(self):
  for kind in ('count','index','time','order','fps','duplicate_time'):
   p,s,i,d=self.fixture()
   if kind=='count':d['timing']['originalFrameCount']=7
   elif kind=='index':d['frames'][0]['sourceFrameIndex']=9
   elif kind=='time':d['frames'][1]['time']=.03
   elif kind=='order':d['frames'][2]['sourceFrameIndex']=0
   elif kind=='fps':d['fps']=60
   else:d['frames'][1]['sourceTime']=.3
   with self.subTest(kind=kind),self.assertRaises(ValueError):resample_native(p,s,i,d)
if __name__=='__main__':unittest.main()
