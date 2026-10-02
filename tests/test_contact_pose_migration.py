import sys,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from confirm_axel_contact import contact_pose_bundle
class MigrationTest(unittest.TestCase):
 def test_migration_preserves_original_and_requires_same_source_frame(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d);(out/'landmarks').mkdir();(out/'landmarks-v2').mkdir()
   old={'sourceSha256':'abc','sourcePath':'input.mp4','frames':[{'frameIndex':2,'sourceFrameIndex':1,'sourceFrameSha256':'def'}]}
   original=json.dumps(old);(out/'landmarks/pose.json').write_text(original)
   new={**old,'settings':{'sourceReuse':'v1'}};(out/'landmarks-v2/pose.json').write_text(json.dumps(new))
   result={}
   with patch('confirm_axel_contact.subprocess.run') as run:
    folder,pose=contact_pose_bundle(out,result,2);run.assert_not_called()
   self.assertEqual(folder.name,'landmarks-v2');self.assertEqual((out/'landmarks/pose.json').read_text(),original)
   self.assertEqual(result['landmarksDirectory'],'landmarks-v2')
   new['frames']=[{'frameIndex':2,'sourceFrameIndex':2,'sourceFrameSha256':'zzz'}];(out/'landmarks-v2/pose.json').write_text(json.dumps(new))
   with self.assertRaises(ValueError):contact_pose_bundle(out,{},2)
if __name__=='__main__':unittest.main()
