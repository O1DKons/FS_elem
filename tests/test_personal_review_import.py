import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from import_personal_video_review import validate_review

class PersonalImportTests(unittest.TestCase):
 def setUp(self):
  self.dataset={'datasetSha256':'a'*64,'items':[{'id':'b'*64,'sha256':'b'*64}]}
  self.row={'id':'b'*64,'sha256':'b'*64,'element':'2A','rotation':'short','athleteGroup':None}
 def doc(self,row=None):return dict(schemaVersion=1,datasetSha256='a'*64,labels=[self.row if row is None else row])
 def test_unknown_group_remains_unknown(self):
  rows=validate_review(self.doc(),self.dataset);self.assertIsNone(rows[0]['athleteGroup'])
 def test_wrong_dataset_and_hash_rejected(self):
  doc=self.doc();doc['datasetSha256']='c'*64
  with self.assertRaises(ValueError):validate_review(doc,self.dataset)
  with self.assertRaises(ValueError):validate_review(self.doc(dict(self.row,sha256='c'*64)),self.dataset)
 def test_duplicates_rejected(self):
  doc=self.doc();doc['labels']*=2
  with self.assertRaises(ValueError):validate_review(doc,self.dataset)
 def test_other_cannot_receive_underrotation(self):
  with self.assertRaises(ValueError):validate_review(self.doc(dict(self.row,element='other')),self.dataset)
  self.assertIsNone(validate_review(self.doc(dict(self.row,element='other',rotation=None)),self.dataset)[0]['rotation'])
 def test_axel_requires_explicit_assessment(self):
  with self.assertRaises(ValueError):validate_review(self.doc(dict(self.row,rotation=None)),self.dataset)
 def test_control_characters_in_group_rejected(self):
  with self.assertRaises(ValueError):validate_review(self.doc(dict(self.row,athleteGroup='a\nb')),self.dataset)
