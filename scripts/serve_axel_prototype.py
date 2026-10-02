"""Loopback-only single-job research upload UI. No remote service or automatic judging claim."""
import argparse,json,subprocess,sys,threading,uuid
from pathlib import Path
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/local-axel-prototype'
JOBS={};BUSY=threading.Lock();LIMIT=60*1024*1024
for previous in (WORK/'runs').glob('*'):
 if previous.is_dir():JOBS[previous.name]={'status':'done'} if (previous/'output/index.html').is_file() else {'status':'error','error':'Предыдущий запуск был прерван; загрузите видео заново.'}

def valid_id(value):
 try:return str(uuid.UUID(value))==value
 except (ValueError,AttributeError):return False

def run_job(run_id,folder,frame=None):
 try:
  with (folder/'process.log').open('a') as log:
   command=[sys.executable,str(ROOT/'scripts/analyze_axel_clip.py'),'--input',str(folder/'input.mp4'),'--output',str(folder/'output')] if frame is None else [sys.executable,str(ROOT/'scripts/confirm_axel_contact.py'),'--output',str(folder/'output'),'--frame',str(frame)]
   run=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
  JOBS[run_id]={'status':'done'} if run.returncode==0 else {'status':'error','error':'Обработчик остановился. Подробности сохранены в process.log.'}
 except Exception as exc:JOBS[run_id]={'status':'error','error':str(exc)}
 finally:BUSY.release()

class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(WORK),**kwargs)
 def allowed(self):
  port=self.server.server_port
  return self.headers.get('Host') in (f'127.0.0.1:{port}',f'localhost:{port}') and self.headers.get('Origin') in (None,f'http://127.0.0.1:{port}',f'http://localhost:{port}')
 def send_json(self,status,data):
  raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  if not self.allowed():self.send_json(403,{'error':'Local origin required'});return
  path=urlsplit(self.path).path
  if path=='/':
   raw=(ROOT/'scripts/axel-upload-assets/index.html').read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  elif path.startswith('/status/'):
   run_id=path.removeprefix('/status/')
   if not valid_id(run_id) or run_id not in JOBS:self.send_json(404,{'error':'Unknown run'});return
   self.send_json(200,JOBS[run_id])
  elif path.startswith('/runs/'):super().do_GET()
  else:self.send_json(404,{'error':'Not found'})
 def do_POST(self):
  if not self.allowed():self.send_json(403,{'error':'Local origin required'});return
  if self.path.startswith('/confirm/'):
   run_id=self.path.removeprefix('/confirm/')
   if not valid_id(run_id) or run_id not in JOBS or JOBS[run_id]['status']!='done':self.send_json(400,{'error':'Analysis is not ready'});return
   try:
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<=256:raise ValueError('Invalid request')
    frame=json.loads(self.rfile.read(length))['frame'];folder=WORK/'runs'/run_id
    if type(frame) is not int or not 0<=frame<=500:raise ValueError('Invalid frame')
    result=json.loads((folder/'output/result.json').read_text())
    pose=json.loads((folder/'output'/result.get('landmarksDirectory','landmarks')/'pose.json').read_text())
    if frame not in {r['frameIndex'] for r in pose['frames']}:raise ValueError('Unknown frame')
   except (ValueError,KeyError,FileNotFoundError):self.send_json(400,{'error':'Invalid frame'});return
   if not BUSY.acquire(blocking=False):self.send_json(409,{'error':'Already processing'});return
   JOBS[run_id]={'status':'processing'};threading.Thread(target=run_job,args=(run_id,folder,frame),daemon=True).start();self.send_json(202,{'id':run_id});return
  if self.path!='/analyze':self.send_json(404,{'error':'Not found'});return
  try:length=int(self.headers.get('Content-Length','0'))
  except ValueError:length=0
  if not 0<length<=LIMIT:self.send_json(413,{'error':'Нужен файл размером до60МБ'});return
  if not BUSY.acquire(blocking=False):self.send_json(409,{'error':'Уже выполняется другой анализ. Дождитесь результата.'});return
  run_id=str(uuid.uuid4());folder=WORK/'runs'/run_id;folder.mkdir(parents=True)
  started=False
  try:
   self.connection.settimeout(30)
   with (folder/'input.mp4').open('wb') as target:
    remaining=length
    while remaining:
     block=self.rfile.read(min(1024*1024,remaining))
     if not block:raise ValueError('Incomplete upload')
     target.write(block);remaining-=len(block)
   JOBS[run_id]={'status':'processing'}
   threading.Thread(target=run_job,args=(run_id,folder),daemon=True).start();started=True
   self.send_json(202,{'id':run_id})
  except Exception as exc:
   if not started:BUSY.release()
   self.send_json(400,{'error':str(exc)})
 def list_directory(self,path):self.send_json(403,{'error':'Directory listing disabled'})
 def log_message(self,*args):pass

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=5196);args=parser.parse_args();WORK.mkdir(parents=True,exist_ok=True)
 with ThreadingHTTPServer(('127.0.0.1',args.port),Handler) as server:
  print(f'http://127.0.0.1:{server.server_port}',flush=True);server.serve_forever()
