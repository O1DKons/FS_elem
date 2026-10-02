import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from axel_corpus import validate_corpus,validate_splits

def source(h,athlete,recording):
 return {'sourceSha256':h*64,'athleteId':athlete,'athleteIds':[athlete],'originalRecordingId':recording,
         'athleteIdentityVerified':True,'recordingGroupVerified':True}
def event():
 return {'eventId':'event1','sourceSha256':'a'*64,'family':'axel','nominal':'1A','labelScope':'full_review',
         'reviewComplete':True,'startSeconds':1.,'endSeconds':1.4,'provenance':[{'path':'review.json','sha256':'e'*64}]}
class CorpusTests(unittest.TestCase):
 def setUp(self):self.sources=[source('a','A','r1'),source('b','B','r2')]
 def test_valid(self):validate_corpus(self.sources,[event()])
 def test_unknown_source(self):
  e=event();e['sourceSha256']='c'*64
  with self.assertRaises(ValueError):validate_corpus(self.sources,[e])
 def test_protocol_not_expert_truth(self):
  e=event();e['labelScope']='protocol_only';e['reviewComplete']=False
  with self.assertRaises(ValueError):validate_corpus(self.sources,[e])
 def test_candidate_not_complete(self):
  e=event();e['labelScope']='candidate_family'
  with self.assertRaises(ValueError):validate_corpus(self.sources,[e])
 def test_bad_bounds(self):
  e=event();e['endSeconds']=.5
  with self.assertRaises(ValueError):validate_corpus(self.sources,[e])
 def test_duplicate_events_rejected(self):
  with self.assertRaises(ValueError):validate_corpus(self.sources,[event(),event()])
 def test_athlete_overlap(self):
  rows=copy.deepcopy(self.sources);rows[1]['athleteIds']=['A'];rows[1]['athleteId']='A'
  with self.assertRaises(ValueError):validate_splits(rows,{'development':['a'*64],'confirmation':['b'*64]})
 def test_recording_overlap(self):
  rows=copy.deepcopy(self.sources);rows[1]['originalRecordingId']='r1'
  with self.assertRaises(ValueError):validate_splits(rows,{'development':['a'*64],'confirmation':['b'*64]})
 def test_same_source_rejected(self):
  with self.assertRaises(ValueError):validate_splits(self.sources,{'development':['a'*64],'confirmation':['a'*64]})
 def test_unknown_identity_cannot_confirm(self):
  rows=copy.deepcopy(self.sources);rows[1]['athleteIdentityVerified']=False
  with self.assertRaises(ValueError):validate_splits(rows,{'development':['a'*64],'confirmation':['b'*64]},require_independence=True)
 def test_known_disjoint(self):validate_splits(self.sources,{'development':['a'*64],'confirmation':['b'*64]},require_independence=True)
 def test_alias_identity_overlap(self):
  rows=copy.deepcopy(self.sources);rows[1]['athleteIds'].append('A')
  with self.assertRaises(ValueError):validate_splits(rows,{'development':['a'*64],'confirmation':['b'*64]})
 def test_provenance_digest_required(self):
  e=event();e['provenance'][0]['sha256']='unknown'
  with self.assertRaises(ValueError):validate_corpus(self.sources,[e])
 def test_unknown_labels_not_training_examples(self):
  e=event();e.update(labelScope='protocol_only',reviewComplete=False,family=None,nominal=None,modelTrainingEligible=True)
  with self.assertRaises(ValueError):validate_corpus(self.sources,[e])
 def test_contact_indices_must_be_ordered(self):
  e=event();e.update(lastContactFrame=30,firstContactFrame=10)
  with self.assertRaises(ValueError):validate_corpus(self.sources,[e])
if __name__=='__main__':unittest.main()
