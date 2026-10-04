"""Single-worker local inference jobs; persistent status and owned process cancellation."""
import hashlib
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT/'scripts') not in sys.path:sys.path.insert(0,str(ROOT/'scripts'))
from source_diagnostics import validate_diagnostics, public_source_error
TERMINAL={'succeeded','failed','cancelled'}


class ApiError(Exception):
    def __init__(self,status,code,message):
        super().__init__(message);self.status=status;self.code=code
    def payload(self):return {'error':{'code':self.code,'message':str(self)}}


def now():return datetime.now(timezone.utc).isoformat()


def job_elapsed_seconds(job):
    """Queue plus processing since accepted upload; terminal end never advances."""
    try:
        state=job['state']
        if state not in TERMINAL and state not in ('queued','running'):return None
        start=datetime.fromisoformat(job['createdAt'])
        end=datetime.fromisoformat(job['updatedAt'] if state in TERMINAL else now())
        if start.tzinfo is None or end.tzinfo is None:return None
        return max(0.0,(end-start).total_seconds())
    except (KeyError,TypeError,ValueError):return None


def write_atomic(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False));temp.replace(path)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def runtime_ready(config):
    """Metadata/checksum admission only; never load pickle or start a model session."""
    try:
        recipe=json.loads(config.read_text());base=config.parent
        for key in ['sciencePython','posePython']:
            p=base/recipe[key]
            if not p.is_file() or not os.access(p,os.X_OK):return False,['Run release setup: '+key+' missing']
        if not (ROOT/'runtime/pipeline/run.py').is_file():return False,['Release runtime missing']
        for row in [*recipe['models'].values(),*recipe['checkpoints'].values(),recipe['ffmpeg']]:
            p=base/row['path']
            if not p.is_file() or sha(p)!=row['sha256']:return False,['Run release setup: asset missing or checksum differs']
        for path,digest in recipe['inputSha256'].items():
            if sha(base/path)!=digest:return False,['Release code checksum differs; run setup after update']
        return True,[]
    except (OSError,ValueError,KeyError,TypeError):return False,['Release setup/configuration is incomplete']


class JobManager:
    def __init__(self,directory,config,start_worker=True,max_upload=512*1024*1024,runner_command=None,max_wall_seconds=5400):
        self.directory=Path(directory).resolve();self.directory.mkdir(parents=True,exist_ok=True)
        self.config=Path(config).resolve();self.max_upload=max_upload;self.runner_command=runner_command
        if type(max_wall_seconds) is not int or not 1<=max_wall_seconds<=5400:raise ValueError('Invalid job time limit')
        self.max_wall_seconds=max_wall_seconds
        self.lock=threading.RLock();self.jobs={};self.cancelled=set();self.queue=queue.Queue();self.stop=threading.Event()
        self.active_job_id=None;self.process=None;self.uploading=0
        self.ready,self.issues=runtime_ready(self.config)
        for path in self.directory.glob('*/job.json'):
            try:
                job=json.loads(path.read_text());jid=str(uuid.UUID(job['jobId']))
                if path.parent.name!=jid:continue
                if job['state'] not in TERMINAL:
                    job.update(state='failed',error={'code':'INTERRUPTED','message':'Service restarted; upload again to repeat analysis'},updatedAt=now())
                    job['progress']['stage']='failed';write_atomic(path,job)
                self.jobs[jid]=job
            except (OSError,ValueError,KeyError,TypeError):continue
        self.thread=None
        if start_worker:
            self.thread=threading.Thread(target=self._worker,name='analysis-single-worker',daemon=True);self.thread.start()

    def _id(self,jid):
        try:
            if str(uuid.UUID(jid))!=jid:raise ValueError()
        except (ValueError,AttributeError):raise ApiError(404,'NOT_FOUND','Job not found')
        if jid not in self.jobs:raise ApiError(404,'NOT_FOUND','Job not found')
        return jid

    def _update(self,jid,**changes):
        with self.lock:
            if changes.get('state') in TERMINAL and self.active_job_id==jid:self.active_job_id=None
            self.jobs[jid].update(changes,updatedAt=now());write_atomic(self.directory/jid/'job.json',self.jobs[jid])

    def get(self,jid):
        with self.lock:
            job=json.loads(json.dumps(self.jobs[self._id(jid)]))
            job['elapsedSeconds']=job_elapsed_seconds(job)
            return job

    def upload(self,stream,length,filename,require_ready=True):
        if length is not None and (type(length) is not int or length<=0):raise ApiError(400,'EMPTY_UPLOAD','Video bytes are required')
        if length is not None and length>self.max_upload:raise ApiError(413,'TOO_LARGE','Maximum video size is 512 MiB')
        filename=filename.replace('\\','/').split('/')[-1]
        if not filename or len(filename)>240 or any(ord(c)<32 for c in filename) or Path(filename).suffix.lower() not in ['.mp4','.mov','.m4v','.webm']:
            raise ApiError(415,'UNSUPPORTED_FORMAT','Use MP4, MOV, M4V or WebM')
        if require_ready and not self.ready:raise ApiError(503,'RUNTIME_UNAVAILABLE','Run release setup before analysis')
        with self.lock:
            pending=sum(j['state']=='queued' for j in self.jobs.values())+self.uploading
            if pending>=4:raise ApiError(429,'QUEUE_FULL','Wait for queued analyses to finish')
            self.uploading+=1
        jid=str(uuid.uuid4());directory=self.directory/jid;directory.mkdir();temp=directory/'upload.part'
        try:
            digest=hashlib.sha256();remaining=length;received=0
            with temp.open('xb') as output:
                while remaining is None or remaining:
                    block=stream.read(1024*1024 if remaining is None else min(1024*1024,remaining))
                    if not block:
                        if remaining:raise ApiError(400,'TRUNCATED_UPLOAD','Incomplete upload')
                        break
                    received+=len(block)
                    if received>self.max_upload:raise ApiError(413,'TOO_LARGE','Maximum video size is 512 MiB')
                    if remaining is not None:remaining-=len(block)
                    digest.update(block);output.write(block)
            if received==0:raise ApiError(400,'EMPTY_UPLOAD','Video bytes are required')
            temp.rename(directory/('video'+Path(filename).suffix.lower()))
            base='/api/analysis/jobs/'+jid
            job={'schemaVersion':1,'jobId':jid,'state':'queued','createdAt':now(),'updatedAt':now(),
                'source':{'filename':filename,'sizeBytes':received,'sha256':digest.hexdigest()},
                'progress':{'stage':'queued','currentFrame':None,'totalFrames':None,'percent':None},'error':None,
                'links':{'self':base,'result':base+'/result','pose':base+'/pose','media':base+'/media'}}
            with self.lock:self.jobs[jid]=job;write_atomic(directory/'job.json',job);self.queue.put(jid)
            return self.get(jid)
        finally:
            with self.lock:self.uploading-=1
            # An interrupted upload is not a job; preserve only its partial bytes for diagnostics.

    def artifact(self,jid,name):
        job=self.get(jid)
        if name not in ('result','pose'):raise ApiError(404,'NOT_FOUND','Artifact not found')
        if job['state']!='succeeded':raise ApiError(409,'NOT_READY','Analysis has not succeeded')
        return json.loads((self.directory/jid/(name+'.json')).read_text())

    def media(self,jid):
        self.get(jid)
        return next((self.directory/jid).glob('video.*'))

    def cancel(self,jid):
        with self.lock:
            self._id(jid);job=self.jobs[jid]
            if job['state'] in TERMINAL:return self.get(jid)
            self.cancelled.add(jid)
            if job['state']=='queued':self._update(jid,state='cancelled',progress={'stage':'cancelled','currentFrame':None,'totalFrames':None,'percent':None})
            else:self._update(jid,progress=dict(job['progress'],stage='cancelling'))
            return self.get(jid)

    def _command(self,directory):
        if self.runner_command:return self.runner_command(directory)
        recipe=json.loads(self.config.read_text());base=self.config.parent
        video=next(directory.glob('video.*'))
        return [str((base/recipe['sciencePython']).absolute()),str(ROOT/'runtime/analyze_job.py'),
                '--job',str(directory),'--video',str(video),'--config',str(self.config)]

    def _cleanup(self,process):
        """Every runtime descendant inherits this new session; terminate the entire group."""
        if os.name=='posix':
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
        elif process.poll() is None:process.terminate()
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:pass
        if os.name=='posix':
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        elif process.poll() is None:process.kill()
        process.wait(timeout=3)

    def _read_progress(self,process,directory,jid,diagnostics=None):
        size=0
        with (directory/'runtime.log').open('w') as log:
            for line in process.stdout:
                size+=len(line)
                if size<=2*1024*1024:log.write(line);log.flush()
                try:
                    data=json.loads(line)
                    if isinstance(data,dict) and data.get('kind')=='analysis_diagnostics':
                        value=validate_diagnostics(data.get('diagnostics'))
                        if diagnostics is not None:
                            if (value is None or diagnostics.get('invalid')
                                    or ('value' in diagnostics and diagnostics['value']!=value)):
                                diagnostics.clear();diagnostics['invalid']=True
                            else:diagnostics['value']=value
                        continue
                    stage=data.get('stage')
                    if stage not in ['probe','sparse','flight_family','dense','nominal','export']:continue
                    n,total=data.get('currentFrame'),data.get('totalFrames')
                    valid=type(n) is int and type(total) is int and 0<=n<=total and total>0
                    with self.lock:
                        if jid not in self.cancelled:
                            self._update(jid,progress={'stage':stage,'currentFrame':n if valid else None,
                                'totalFrames':total if type(total) is int and total>0 else None,
                                'percent':round(100*n/total,1) if valid else None})
                except (ValueError,TypeError,AttributeError):continue

    def _worker(self):
        while not self.stop.is_set():
            try:jid=self.queue.get(timeout=.1)
            except queue.Empty:continue
            process=None;reader=None;failure=None;diagnostics={}
            with self.lock:
                if jid in self.cancelled:continue
                self.active_job_id=jid
                self._update(jid,state='running',progress={'stage':'probe','currentFrame':None,'totalFrames':None,'percent':None})
            directory=self.directory/jid
            try:
                process=subprocess.Popen(self._command(directory),cwd=ROOT,stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True,
                    env={**os.environ,'OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2','MKL_NUM_THREADS':'2','NUMEXPR_NUM_THREADS':'2'})
                self.process=process
                reader=threading.Thread(target=self._read_progress,args=(process,directory,jid,diagnostics),daemon=True);reader.start()
                deadline=time.monotonic()+self.max_wall_seconds
                while process.poll() is None:
                    if jid in self.cancelled or self.stop.is_set():break
                    if time.monotonic()>deadline:failure=('TIME_LIMIT','Analysis exceeded the configured time limit');break
                    if sum(p.stat().st_size for p in directory.rglob('*') if p.is_file())>1024*1024*1024:
                        failure=('DISK_LIMIT','Analysis files exceeded 1 GiB');break
                    time.sleep(.1)
                cancelled=jid in self.cancelled or self.stop.is_set()
                returncode=process.poll()
                self._cleanup(process);reader.join(timeout=3)
                if cancelled:self._update(jid,state='cancelled',progress={'stage':'cancelled','currentFrame':None,'totalFrames':None,'percent':None})
                elif failure:self._fail(jid,*failure)
                elif returncode!=0:self._fail(jid,'ANALYSIS_FAILED','Video could not be analysed; inspect the local runtime log',diagnostics=diagnostics.get('value'))
                elif not all((directory/n).is_file() for n in ['result.json','pose.json']):self._fail(jid,'MISSING_RESULT','Runtime did not produce result and pose')
                else:self._update(jid,state='succeeded',progress={'stage':'completed','currentFrame':None,'totalFrames':None,'percent':100})
            except Exception:
                if process is not None:
                    try:self._cleanup(process)
                    except (OSError,subprocess.TimeoutExpired):pass
                self._fail(jid,'RUNTIME_ERROR','Analysis process could not finish safely; inspect local files')
            finally:
                if process and process.stdout:process.stdout.close()
                with self.lock:self.process=None;self.active_job_id=None

    def _fail(self,jid,code,message,diagnostics=None):
        error=public_source_error(diagnostics) or {'code':code,'message':message}
        self._update(jid,state='failed',error=error,progress={'stage':'failed','currentFrame':None,'totalFrames':None,'percent':None})

    def close(self):
        self.stop.set()
        with self.lock:
            for jid,job in list(self.jobs.items()):
                if job['state'] not in TERMINAL:self.cancel(jid)
        if self.thread:self.thread.join(timeout=10)
