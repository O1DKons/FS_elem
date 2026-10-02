import sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from import_personal_athletes import validate_mapping
class MappingTests(unittest.TestCase):
 def setUp(self):
  self.dataset={'datasetSha256':'d','items':[{'id':str(i),'sha256':f'{i:064x}','file':f'media/{i:02d}.mp4'} for i in range(1,52)]}
  self.mapping={'schemaVersion':1,'datasetSha256':'d','groups':[{'athleteId':'S01','videoNumbers':[1,3]},{'athleteId':'S02','videoNumbers':[2]}]}
 def test_maps_display_numbers_even_after_dataset_reorder(self):
  self.dataset['items'].reverse();r=validate_mapping(self.mapping,self.dataset)
  self.assertEqual([(x['videoNumber'],x['athleteId'],x['id']) for x in r['assignments']],[(1,'S01','1'),(2,'S02','2'),(3,'S01','3')]);self.assertEqual(len(r['unassignedVideoNumbers']),48)
  self.assertFalse(r['withinDatasetGroupingComplete']);self.assertFalse(r['athleteExclusionVerified'])
 def test_single_letter_anonymous_identity_is_allowed(self):
  self.mapping['groups'][0]['athleteId']='A';self.assertEqual(validate_mapping(self.mapping,self.dataset)['assignments'][0]['athleteId'],'A')
 def test_complete_grouping_is_not_cross_corpus_identity_proof(self):
  self.mapping['groups']=[{'athleteId':'S01','videoNumbers':list(range(1,52))}]
  r=validate_mapping(self.mapping,self.dataset);self.assertTrue(r['withinDatasetGroupingComplete']);self.assertFalse(r['athleteExclusionVerified'])
 def test_rejects_duplicates_jump_codes_wrong_dataset_and_bool_numbers(self):
  original=copy.deepcopy(self.mapping)
  for kind in ('duplicate_video','duplicate_athlete','unknown','bool','jump','dataset','empty'):
   m=copy.deepcopy(original)
   if kind=='duplicate_video':m['groups'][1]['videoNumbers']=[3]
   elif kind=='duplicate_athlete':m['groups'][1]['athleteId']='S01'
   elif kind=='unknown':m['groups'][0]['videoNumbers']=[52]
   elif kind=='bool':m['groups'][0]['videoNumbers']=[True]
   elif kind=='jump':m['groups'][0]['athleteId']='2А<<'
   elif kind=='dataset':m['datasetSha256']='different'
   else:m['groups'][0]['videoNumbers']=[]
   with self.subTest(kind=kind),self.assertRaises(ValueError):validate_mapping(m,self.dataset)
if __name__=='__main__':unittest.main()
