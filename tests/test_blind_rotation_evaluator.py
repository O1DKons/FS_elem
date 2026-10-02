import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from blind_rotation_evaluator import evaluate,strict_loads
class BlindEvaluationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);items=[]
  for i in range(4):
   data=f'video{i}'.encode();(self.root/f'{i}.mp4').write_bytes(data);items.append(dict(id=str(i),sha256=hashlib.sha256(data).hexdigest(),file=f'{i}.mp4'))
  digest=hashlib.sha256(json.dumps(items,sort_keys=True).encode()).hexdigest()
  self.dataset=dict(schemaVersion=1,datasetSha256=digest,items=items)
  self.labels=dict(schemaVersion=1,datasetSha256=digest,labels=[dict(id=str(i),sha256=items[i]['sha256'],assessment=a) for i,a in enumerate(('complete','short','unclear'))])
  self.pred=dict(schemaVersion=1,datasetSha256=digest,modelSha256={'pivot':'a'*64},complete=True,records=[dict(id=str(i),sha256=items[i]['sha256'],rotationAssessment=a,status='ready' if a else 'abstain') for i,a in enumerate(('apparently_complete',None,'apparently_short','apparently_complete'))])
 def tearDown(self):self.tmp.cleanup()
 def test_abstention_counts_wrong_partial_labels_explicit(self):
  labels=copy.deepcopy(self.labels);r=evaluate(self.dataset,self.labels,self.pred,self.root)
  self.assertEqual(self.labels,labels);self.assertEqual(r['counts']['missingLabels'],1);self.assertEqual(r['counts']['unclearLabels'],1)
  self.assertEqual(r['metrics']['correct'],1);self.assertEqual(r['metrics']['total'],2);self.assertEqual(r['metrics']['accuracy'],.5)
  self.assertEqual(r['metrics']['balancedAccuracy'],.5);self.assertEqual(r['metrics']['predictionCoverage'],.5);self.assertEqual(r['metrics']['abstentions'],1)
  self.assertEqual(r['metrics']['perClass']['short']['recall'],0)
 def test_stale_dataset_or_video_hash_rejected(self):
  bad=copy.deepcopy(self.labels);bad['datasetSha256']='b'*64
  with self.assertRaises(ValueError):evaluate(self.dataset,bad,self.pred,self.root)
  (self.root/'0.mp4').write_bytes(b'changed')
  with self.assertRaises(ValueError):evaluate(self.dataset,self.labels,self.pred,self.root)
 def test_duplicate_unknown_and_incomplete_predictions_rejected(self):
  for mutation in ('duplicate','unknown','missing','incomplete'):
   pred=copy.deepcopy(self.pred)
   if mutation=='duplicate':pred['records'].append(pred['records'][0])
   elif mutation=='unknown':pred['records'][0]['id']='unknown'
   elif mutation=='missing':pred['records'].pop()
   else:pred['complete']=False
   with self.assertRaises(ValueError,msg=mutation):evaluate(self.dataset,self.labels,pred,self.root)
 def test_duplicate_labels_and_json_keys_rejected(self):
  self.labels['labels'].append(copy.deepcopy(self.labels['labels'][0]))
  with self.assertRaises(ValueError):evaluate(self.dataset,self.labels,self.pred,self.root)
  with self.assertRaises(ValueError):strict_loads('{"schemaVersion":1,"schemaVersion":1}')
 def test_single_or_no_clear_class_cannot_claim_balanced_accuracy(self):
  self.labels['labels']=self.labels['labels'][:1];r=evaluate(self.dataset,self.labels,self.pred,self.root)
  self.assertIsNone(r['metrics']['balancedAccuracy'])
  self.labels['labels']=[];r=evaluate(self.dataset,self.labels,self.pred,self.root)
  self.assertIsNone(r['metrics']['accuracy']);self.assertIsNone(r['majorityBaseline']['accuracy'])
if __name__=='__main__':unittest.main()
