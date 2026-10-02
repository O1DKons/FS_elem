import sys,unittest,threading,urllib.request,urllib.error
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from serve_axel_prototype import Handler,valid_id
class UploadTest(unittest.TestCase):
 def test_invalid_requests_do_not_start_analysis(self):
  with ThreadingHTTPServer(('127.0.0.1',0),Handler) as server:
   threading.Thread(target=server.serve_forever,daemon=True).start();base='http://127.0.0.1:'+str(server.server_port)
   try:
    self.assertEqual(urllib.request.urlopen(base).status,200)
    for request,code in [(urllib.request.Request(base+'/analyze',data=b'',method='POST'),413),(urllib.request.Request(base+'/analyze',data=b'abc',headers={'Origin':'https://example.com'},method='POST'),403),(urllib.request.Request(base+'/confirm/not-a-run',data=b'{}',method='POST'),400)]:
     with self.assertRaises(urllib.error.HTTPError) as ctx:urllib.request.urlopen(request)
     self.assertEqual(ctx.exception.code,code)
   finally:server.shutdown()
 def test_run_id_is_canonical(self):
  self.assertFalse(valid_id('../hello'));self.assertFalse(valid_id(''));self.assertTrue(valid_id('00000000-0000-0000-0000-000000000000'))
if __name__=='__main__':unittest.main()
