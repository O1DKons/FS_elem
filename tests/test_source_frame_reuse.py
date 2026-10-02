import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from source_frame_reuse import SourceFrameCache,independent_intervals
class SourceReuseTests(unittest.TestCase):
 def test_same_identity_reuses_exact_output_and_deepcopies(self):
  cache=SourceFrameCache();calls=[];frame={'sourceFrameIndex':3,'sourceFrameSha256':'a'*64}
  def infer():calls.append(1);return {'raw':{'box':[0,0,3,4],'points':[[1,2]]},'nextBox':[1,1,5,6]}
  a,reused=cache.compute(frame,infer);self.assertFalse(reused);a['raw']['box'][0]=999
  b,reused=cache.compute(frame,infer);self.assertTrue(reused);self.assertEqual(b['raw']['box'][0],0);self.assertEqual(len(calls),1)
  cache.compute({**frame,'sourceFrameSha256':'b'*64},infer);self.assertEqual(len(calls),2)
 def test_missing_identity_not_cached(self):
  cache=SourceFrameCache();calls=[]
  for _ in range(2):cache.compute({'sourceFrameIndex':0},lambda:calls.append(1))
  self.assertEqual(len(calls),2)
 def test_gate_counts_only_new_observations_and_no_gap_bridge(self):
  def frame(n,source,hashchar,visible=True):return {'frameIndex':n,'sourceFrameIndex':source,'sourceFrameSha256':hashchar*64,'candidates':[{'side':'landing','status':'visible' if visible else 'uncertain','heel':[0,0],'toe':[10,0]}]}
  item={'firstContact':0,'frames':[frame(0,0,'a'),frame(1,0,'a'),frame(2,1,'b'),frame(3,1,'b'),frame(4,2,'c'),frame(5,3,'c'),frame(6,4,'d',False),frame(7,5,'e')]}
  r=independent_intervals(item);self.assertEqual(r['independentSourceIntervals'],2);self.assertEqual(r['standardizedIntervals'],5)
  item['frames'][2].pop('sourceFrameSha256');self.assertFalse(independent_intervals(item)['sourceProvenanceComplete'])
if __name__=='__main__':unittest.main()
