import sys,unittest,copy
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from binary_contact_validation import at_contact
class ContactValidationTests(unittest.TestCase):
 def test_recomputes_landing_without_manual_contact_or_old_landing(self):
  frames=[]
  for n in range(100,113):
   c=[dict(side=side,toe=[20,n-100+y],heel=[0,n-100+y],status='visible',score=1,reasons=[],projectedLength=20,imageHeadingDegrees=0) for side,y in [('left',100),('right',10)]]
   frames.append(dict(frameIndex=n,candidates=c+[dict(side='landing',status='visible',toe=[999,999],heel=[0,0])]))
  item=dict(firstContact=999,frames=frames);before=copy.deepcopy(item);a=at_contact(item,102);item['firstContact']=-999
  b=at_contact(item,102);np.testing.assert_allclose(a,b,equal_nan=True);self.assertEqual(item['frames'],before['frames'])
  self.assertEqual(a[0],1);self.assertEqual(a[1],1);self.assertEqual(a[2],0)
if __name__=='__main__':unittest.main()
