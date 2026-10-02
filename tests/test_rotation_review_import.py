import importlib.util,unittest,copy,tempfile,json,subprocess
from pathlib import Path
spec=importlib.util.spec_from_file_location('review',Path(__file__).resolve().parents[1]/'scripts/import_rotation_review.py')
review=importlib.util.module_from_spec(spec)
if Path(spec.origin).exists():spec.loader.exec_module(review)
class ImportTests(unittest.TestCase):
 def setUp(self):
  self.item=dict(attemptId='a',videoId='v',sourceSha256='a'*64,lastContact=10,firstContact=32)
  self.manifest={'items':[self.item]}
  self.record={**self.item,'rotationAssessment':'apparently_short','visibility':{'takeoff':'clear','landing':'clear'},'notes':'','reviewedAt':'2026-09-22T00:00:00.000Z'}
  self.payload=dict(schemaVersion=1,kind='rotation-expert-review',assessments=[self.record])
 def test_preserves_expert_opinion_without_promoting_to_official(self):
  result=review.validate_review(self.payload,self.manifest)
  self.assertEqual(result['assessments'][0]['rotationAssessment'],'apparently_short')
  self.assertNotIn('protocolCode',result['assessments'][0])
 def test_rejects_source_and_boundary_mismatch(self):
  for key,value in [('sourceSha256','b'*64),('lastContact',11),('videoId','other')]:
   payload=copy.deepcopy(self.payload);payload['assessments'][0][key]=value
   with self.assertRaises(ValueError):review.validate_review(payload,self.manifest)
 def test_accepts_browser_maximum_notes_and_rejects_overflow(self):
  self.record['notes']='x'*5000
  self.assertEqual(len(review.validate_review(self.payload,self.manifest)['assessments'][0]['notes']),5000)
  self.record['notes']='x'*5001
  with self.assertRaises(ValueError):review.validate_review(self.payload,self.manifest)
 def test_javascript_export_roundtrip_without_writing_expert_records(self):
  root=Path(__file__).resolve().parents[1]
  module=(root/'scripts/rotation-review-assets/rotation-review-core.mjs').as_uri()
  source="import {exportAssessments} from "+json.dumps(module)+";let s='';for await (const chunk of process.stdin)s+=chunk;console.log(JSON.stringify(exportAssessments(JSON.parse(s))));"
  self.record['notes']='x'*5000
  output=subprocess.check_output([str(root/'.runtime/node'),'--input-type=module','-e',source],input=json.dumps([self.record]),text=True)
  result=review.validate_review(json.loads(output),self.manifest)
  self.assertEqual(result['assessments'],[self.record])
 def test_unknown_is_retained_and_not_clean(self):
  self.record['rotationAssessment']='unknown';self.record['visibility']['landing']='not_visible'
  self.assertEqual(review.validate_review(self.payload,self.manifest)['assessments'][0]['rotationAssessment'],'unknown')
 def test_rejects_duplicate_unknown_labels_and_extra_protocol(self):
  bad=copy.deepcopy(self.payload);bad['assessments'].append(self.record)
  with self.assertRaises(ValueError):review.validate_review(bad,self.manifest)
  for key,value in [('rotationAssessment','clean'),('protocolCode','2A'),('reviewedAt','not-a-date')]:
   bad=copy.deepcopy(self.payload);bad['assessments'][0][key]=value
   with self.assertRaises(ValueError):review.validate_review(bad,self.manifest)
if __name__=='__main__':unittest.main()
