import copy,json,sys,unittest,tempfile,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from evaluate_personal_blind import evaluate,digest
class EvaluationTests(unittest.TestCase):
 def setUp(self):
  self.items=[dict(id=f'{i:064x}',sha256=f'{i:064x}') for i in range(51)]
  self.dataset=dict(datasetSha256='dataset',items=self.items)
  self.ds=digest(json.dumps(self.dataset).encode())
  self.protocol=dict(schemaVersion=1,frozenAt='frozen',datasetSha256='dataset',datasetFileSha256=self.ds,modelSha256={'a':'frozen'},codeSha256={'a':'frozen'},expectedCount=51,scope='scope',evaluationPolicy='policy')
  self.pred=dict(**self.protocol,complete=True,records=[dict(**r,typeProposal=None,rotationAssessment=None,status='abstention') for r in self.items])
  self.review=dict(schemaVersion=1,datasetSha256='dataset',labels=[])
 def label(self,i,element,rotation=None,group=None):self.review['labels'].append(dict(**self.items[i],element=element,rotation=rotation,athleteGroup=group))
 def run_eval(self):return evaluate(self.review,self.pred,self.dataset,self.protocol,self.ds)
 def test_refusals_unsupported_and_unknown_denominators(self):
  self.label(0,'2A','complete','S1');self.label(1,'2A','short','S2');self.label(2,'1A','complete');self.label(3,'other');self.label(4,'unclear')
  self.pred['records'][0].update(typeProposal='2A',rotationAssessment='apparently_complete',status='proposal')
  self.pred['records'][2].update(typeProposal='2A',rotationAssessment='apparently_complete',status='proposal')
  r=self.run_eval();self.assertEqual(r['rotation']['total'],3);self.assertEqual(r['rotation']['correct'],1);self.assertAlmostEqual(r['rotation']['balancedRecall'],.25);self.assertAlmostEqual(r['rotation']['majorityBaseline'],2/3)
  self.assertEqual(r['axelDetection']['total'],4);self.assertEqual(r['axelDetection']['correct'],2);self.assertEqual(r['nominalType']['correct'],1);self.assertFalse(r['athleteExclusionVerified']);self.assertFalse(r['goal70Verified']);self.assertEqual(r['grouping']['missing'],3)
 def test_complete_exact_prediction_set_required(self):
  self.label(0,'other')
  original=copy.deepcopy(self.pred)
  for mutation in ('partial','duplicate','foreign','hash','incomplete','protocol','dataset'):
   self.pred=copy.deepcopy(original)
   if mutation=='partial':self.pred['records'].pop()
   elif mutation=='duplicate':self.pred['records'][1]=self.pred['records'][0]
   elif mutation=='foreign':self.pred['records'][0]['id']='foreign'
   elif mutation=='hash':self.pred['records'][0]['sha256']='bad'
   elif mutation=='incomplete':self.pred['complete']=False
   elif mutation=='protocol':self.pred['modelSha256']={}
   else:self.pred['datasetSha256']='bad'
   with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.run_eval()
 def test_no_labels_rejected_unknown_only_has_no_accuracy(self):
  with self.assertRaises(ValueError):self.run_eval()
  self.label(0,'unclear');r=self.run_eval();self.assertIsNone(r['rotation']['accuracy']);self.assertIsNone(r['axelDetection']['accuracy'])
 def test_refusal_does_not_become_negative(self):
  self.label(0,'other');r=self.run_eval();self.assertEqual(r['axelDetection']['correct'],0);self.assertEqual(r['axelDetection']['coverage'],0)
 def test_cli_hash_provenance_and_immutable_output(self):
  self.label(0,'other')
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);paths={}
   for name,document in [('review',self.review),('predictions',self.pred),('dataset',self.dataset),('protocol',self.protocol)]:
    paths[name]=root/(name+'.json');paths[name].write_text(json.dumps(document))
   output=root/'result.json';command=[sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/evaluate_personal_blind.py')]
   for name,path in paths.items():command+=['--'+name,str(path)]
   command+=['--output',str(output)]
   subprocess.run(command,check=True,capture_output=True)
   result=json.loads(output.read_text());self.assertTrue(result['provenance']['frozenProtocolMatched']);self.assertEqual(result['provenance']['reviewFileSha256'],digest(paths['review'].read_bytes()))
   output.write_text('existing immutable artifact')
   self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
   self.assertEqual(output.read_text(),'existing immutable artifact')
 def test_reuses_crossfield_review_validator(self):
  self.label(0,'other','short')
  with self.assertRaises(ValueError):self.run_eval()
 def test_per_type_rotation_keeps_unsupported_and_refused_cases(self):
  self.label(0,'1A','complete');self.label(1,'2A','short');self.label(2,'2A','complete')
  self.pred['records'][1].update(typeProposal='2A',rotationAssessment='apparently_short',status='diagnostic_prediction')
  r=self.run_eval()['rotationByNominalType']
  self.assertEqual(r['1A']['total'],1);self.assertEqual(r['1A']['answered'],0)
  self.assertEqual(r['2A']['total'],2);self.assertEqual(r['2A']['accuracy'],.5)
  self.assertEqual(r['2A']['recall'],{'complete':0.0,'short':1.0})
  self.assertIsNone(r['3A']['accuracy'])
if __name__=='__main__':unittest.main()
