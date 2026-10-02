import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from candidate_family_labels import training_label
class Tests(unittest.TestCase):
 def setUp(self):
  self.events=[dict(id='a',eventClass='axel',start=10,end=10.5),dict(id='b',eventClass='other_jump',start=11,end=11.4)]
 def test_fragment_of_axel_unknown(self):self.assertIsNone(training_label(dict(start=10.48,end=10.6),self.events,None,True))
 def test_matched_axel(self):self.assertEqual(training_label(dict(start=10,end=10.5),self.events,'a',True),'axel')
 def test_other_jump(self):self.assertEqual(training_label(dict(start=11,end=11.4),self.events,'b',True),'other')
 def test_partial_background_unknown(self):self.assertIsNone(training_label(dict(start=12,end=12.5),self.events,None,False))
 def test_full_background(self):self.assertEqual(training_label(dict(start=12,end=12.5),self.events,None,True),'other')
 def test_mixed_window_unknown(self):self.assertIsNone(training_label(dict(start=10.4,end=11.2),self.events,'b',True))
 def test_invalid_match_rejected(self):
  with self.assertRaises(ValueError):training_label(dict(start=12,end=13),self.events,'a',True)
 def test_touching_boundary_is_not_overlap(self):self.assertEqual(training_label(dict(start=10.5,end=10.8),self.events,None,True),'other')
if __name__=='__main__':unittest.main()
