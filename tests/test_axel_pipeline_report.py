import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from axel_pipeline_report import render
class ReportTest(unittest.TestCase):
 def test_automatic_proposal_is_not_displayed_as_verdict(self):
  result={'typeProposal':{'predicted_label':'2A'},'rotationAssessment':None,'rotationProposal':{'rotationAssessment':'apparently_complete'}}
  page=render(result,[])
  self.assertNotIn('<h2>Предположительно докручен</h2>',page)
  self.assertIn('Фактическое число оборотов',page)
 def test_confirmed_frame_survives_reload(self):
  result={'typeProposal':{'predicted_label':'2A'},'contactProposal':{'predictedFirstContact':1},'userConfirmedContactFrame':2}
  frames=[{'frameIndex':i,'image':f'{i}.png','time':i/50} for i in range(4)]
  self.assertIn('value="2"',render(result,frames))
 def test_non_double_axel_has_no_contact_confirmation(self):
  self.assertNotIn('id="confirm"',render({'typeProposal':{'predicted_label':'3A'}},[{'frameIndex':0,'image':'0.png','time':0}]))
if __name__=='__main__':unittest.main()
