import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from jump_video_report import result_contract,render_report
class ReportTest(unittest.TestCase):
 def test_type_never_becomes_measured_rotation_or_clean_landing(self):
  r=result_contract({'predicted_label':'2A','raw_scores':{'2A':.7},'classes':['2A'],'extraction_status':'ok','video_sha256':'abc','scope':'short_single_element_clip'})
  self.assertEqual(r['elementProposal'],'2A');self.assertIsNone(r['measuredRevolutions']);self.assertIsNone(r['rotationAssessment']);self.assertEqual(r['nominalAxelRevolutions'],2.5)
 def test_abstention_has_no_nominal_rotation(self):
  r=result_contract({'predicted_label':None,'raw_scores':{},'classes':[],'extraction_status':'abstain','video_sha256':'abc'})
  self.assertIsNone(r['nominalAxelRevolutions']);self.assertIn('Недостаточно',render_report(r,'sample.mp4'))
 def test_report_escapes_content_and_does_not_call_score_probability(self):
  r=result_contract({'predicted_label':'<script>','raw_scores':{},'classes':[],'extraction_status':'ok','video_sha256':'abc'})
  page=render_report(r,'sample.mp4');self.assertNotIn('<script>',page);self.assertIn('&lt;script&gt;',page);self.assertNotIn('70%',page)
if __name__=='__main__':unittest.main()
