"""Loopback upload/job service; stdlib only. Inference lives in owned subprocesses."""
import argparse
import json
import mimetypes
import re
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
from jobs import ApiError, JobManager, ROOT


class ChunkedReader:
    def __init__(self,stream):self.stream=stream;self.remaining=0;self.done=False
    def read(self,size):
        if self.done:return b''
        if self.remaining==0:
            line=self.stream.readline(256)
            try:
                if not line.endswith(b'\r\n'):raise ValueError()
                token=line.split(b';',1)[0].strip()
                if not re.fullmatch(b'[0-9a-fA-F]+',token):raise ValueError()
                self.remaining=int(token,16)
            except ValueError:raise ApiError(400,'INVALID_UPLOAD','Malformed chunked upload')
            if self.remaining==0:
                total=0
                while True:
                    trailer=self.stream.readline(1024);total+=len(trailer)
                    if not trailer or total>4096:raise ApiError(400,'INVALID_UPLOAD','Malformed upload trailers')
                    if trailer==b'\r\n':break
                self.done=True;return b''
        data=self.stream.read(min(size,self.remaining))
        if not data:raise ApiError(400,'TRUNCATED_UPLOAD','Incomplete upload')
        self.remaining-=len(data)
        if self.remaining==0 and self.stream.read(2)!=b'\r\n':raise ApiError(400,'INVALID_UPLOAD','Malformed upload chunk')
        return data


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def send_json(self,status,value):
        data=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
        if self.close_connection:self.send_header('Connection','close')
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(data)

    def handle_api(self):
        port=self.server.server_port
        if self.headers.get('Host') not in ['127.0.0.1:'+str(port),'localhost:'+str(port)]:
            raise ApiError(403,'LOCAL_ONLY','Local access only')
        origin=self.headers.get('Origin')
        if (origin and origin!='http://'+self.headers['Host']) or self.headers.get('Sec-Fetch-Site')=='cross-site':
            raise ApiError(403,'ORIGIN_REJECTED','Origin rejected')
        manager=self.server.manager;path=urlsplit(self.path).path
        if self.command=='GET' and path=='/health':
            return self.send_json(200,{'service':'fs-elem-analysis','status':'ready',
                'inferenceAvailable':manager.ready,'issues':manager.issues,'activeJobId':manager.active_job_id,'python':sys.version.split()[0]})
        if self.command=='POST' and path=='/jobs':
            length=self.headers.get('Content-Length');transfer=self.headers.get('Transfer-Encoding')
            if length is not None and transfer is not None:raise ApiError(400,'INVALID_UPLOAD','Ambiguous body framing')
            if transfer:
                if transfer.lower()!='chunked':raise ApiError(400,'INVALID_UPLOAD','Unsupported transfer encoding')
                stream=ChunkedReader(self.rfile);length=None
            else:
                try:length=int(length)
                except (TypeError,ValueError):raise ApiError(411,'LENGTH_REQUIRED','Content-Length or chunked body required')
                stream=self.rfile
            job=manager.upload(stream,length,unquote(self.headers.get('X-Filename','')))
            return self.send_json(202,job)
        match=re.fullmatch(r'/jobs/([a-z0-9-]+)(?:/(state|result|pose|media))?',path)
        if not match:raise ApiError(404,'NOT_FOUND','Not found')
        jid,part=match.groups()
        if self.command=='GET' and part in (None,'state'):return self.send_json(200,manager.get(jid))
        if self.command=='GET' and part in ('result','pose'):return self.send_json(200,manager.artifact(jid,part))
        if self.command=='DELETE' and part is None:
            job=manager.cancel(jid);return self.send_json(202 if job['state']=='running' else 200,job)
        if self.command in ('GET','HEAD') and part=='media':return self.send_media(manager.media(jid))
        raise ApiError(405,'METHOD_NOT_ALLOWED','Method not allowed')

    def send_media(self,path):
        size=path.stat().st_size;start=0;end=size-1;status=200
        header=self.headers.get('Range')
        if header:
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',header)
            try:
                if not match or not any(match.groups()):raise ValueError()
                a,b=match.groups()
                if a:start=int(a);end=min(int(b),size-1) if b else size-1
                else:
                    if int(b)<=0:raise ValueError()
                    start=max(0,size-int(b))
                if start>end or start>=size:raise ValueError()
            except ValueError:
                self.send_response(416);self.send_header('Content-Range','bytes */'+str(size));self.send_header('Content-Length','0');self.end_headers();return
            status=206
        self.send_response(status);self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
        if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command=='HEAD':return
        with path.open('rb') as stream:
            stream.seek(start);remaining=end-start+1
            while remaining:
                data=stream.read(min(1024*1024,remaining))
                if not data:break
                self.wfile.write(data);remaining-=len(data)

    def dispatch(self):
        try:self.handle_api()
        except ApiError as error:
            if self.command=='POST':self.close_connection=True
            self.send_json(error.status,error.payload())
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:
            self.close_connection=True;self.send_json(500,{'error':{'code':'SERVICE_ERROR','message':'Local service error'}})
    do_GET=do_HEAD=do_POST=do_DELETE=dispatch
    def log_message(self,*args):pass


def main():
    if sys.version_info<(3,12):raise SystemExit('FS_elem requires Python 3.12 or later. Run setup first.')
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=5175)
    parser.add_argument('--config',type=Path,default=ROOT/'configs/axel-release-v1.json')
    parser.add_argument('--jobs',type=Path,default=ROOT/'.runtime/jobs')
    parser.add_argument('--max-wall-seconds',type=int,default=5400);args=parser.parse_args()
    manager=JobManager(args.jobs,args.config,max_wall_seconds=args.max_wall_seconds)
    with ThreadingHTTPServer(('127.0.0.1',args.port),Handler) as server:
        server.daemon_threads=True;server.manager=manager
        signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))
        print(json.dumps({'port':server.server_port}),flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:manager.close()


if __name__=='__main__':main()
