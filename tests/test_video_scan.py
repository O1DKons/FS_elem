import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from video_scan import windows,select_candidates
class ScanTest(unittest.TestCase):
 def test_windows_cover_end_without_duplicate_or_outside(self):
  self.assertEqual(windows(1),[(0.,1.)])
  x=windows(3.2);self.assertEqual(x[-1],(1.7,3.2));self.assertEqual(len(x),len(set(x)));self.assertTrue(all(0<=a<b<=3.2 for a,b in x))
 def test_other_is_not_a_candidate_and_overlaps_are_suppressed(self):
  rows=[dict(start=0,end=1.5,prediction={'raw_scores':{'2A':.9,'other':.1}}),dict(start=.5,end=2,prediction={'raw_scores':{'2A':.7,'other':.2}}),dict(start=3,end=4.5,prediction={'raw_scores':{'2A':.1,'other':.8}})]
  x=select_candidates(rows);self.assertEqual(len(x),1);self.assertEqual(x[0]['start'],0);self.assertEqual(x[0]['elementProposal'],'2A')
if __name__=='__main__':unittest.main()
