import sys,unittest,io,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from skatingverse_download import select_members, safe_name, Remote, Budget
from unittest.mock import patch,MagicMock
class DownloadTests(unittest.TestCase):
 def test_paths(self):
  self.assertEqual(safe_name('train_videos/1_abcd.mp4'),'1_abcd.mp4')
  for name in ['../bad.mp4','train_videos/../bad.mp4','test_videos/1_a.mp4']:
   with self.assertRaises(ValueError):safe_name(name)
 def test_selection_deterministic_group_diversity(self):
  rows=[dict(name=f'train_videos/{g}_{j}.mp4',label=2,compressed=10,group=str(g)) for g in range(3) for j in range(4)]
  picked=select_members(rows,{2:3},100)
  self.assertEqual({x['group'] for x in picked},{'0','1','2'})
  self.assertEqual(picked,select_members(list(reversed(rows)),{2:3},100))
  with self.assertRaises(ValueError):select_members(rows,{2:3},20)
 def test_range_rejects_full_download(self):
  response=MagicMock();response.__enter__.return_value=response;response.status=200
  with patch('urllib.request.urlopen',return_value=response):
   with self.assertRaises(ValueError):Remote('https://example.test',100,Budget(100)).read(10)
  response.read.assert_not_called()
 def test_budget_and_exact_range(self):
  response=MagicMock();response.__enter__.return_value=response;response.status=206
  response.headers={'Content-Range':'bytes 2-4/100'};response.read.return_value=b'abc'
  b=Budget(3);r=Remote('https://example.test',100,b);r.seek(2)
  with patch('urllib.request.urlopen',return_value=response):self.assertEqual(r.read(3),b'abc')
  with self.assertRaises(ValueError):r.read(1)
if __name__=='__main__':unittest.main()
