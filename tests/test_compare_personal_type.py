import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from compare_personal_type import compare
class CompareTests(unittest.TestCase):
 def setup_data(self):
  items=[dict(id=str(i),sha256=f'{i:064x}') for i in range(51)];dataset=dict(datasetSha256='d',items=items)
  review=dict(schemaVersion=1,datasetSha256='d',labels=[dict(**items[0],element='2A',rotation='short',athleteGroup=None),dict(**items[1],element='other',rotation=None,athleteGroup=None)])
  def pred():return dict(datasetSha256='d',complete=True,records=[dict(**r,typeProposal='abstain') for r in items])
  return dataset,review,pred(),pred()
 def test_refusal_stays_wrong_and_paired_changes(self):
  d,r,a,b=self.setup_data();a['records'][0]['typeProposal']='2A';b['records'][1]['typeProposal']='other'
  out=compare(r,a,b,d);self.assertEqual(out['native']['nominalType']['correct'],1);self.assertEqual(out['native']['axelDetection']['correct'],1)
  self.assertEqual(out['pairedNominal'],dict(corrected=1,regressed=1,bothCorrect=0,bothWrong=0))
 def test_incomplete_or_duplicate_rejected(self):
  for kind in ('incomplete','duplicate','hash'):
   d,r,a,b=self.setup_data()
   if kind=='incomplete':a['complete']=False
   elif kind=='duplicate':a['records'][1]=a['records'][0]
   else:a['records'][0]['sha256']='bad'
   with self.subTest(kind=kind),self.assertRaises(ValueError):compare(r,a,b,d)
if __name__=='__main__':unittest.main()
