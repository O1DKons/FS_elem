"""Owned process lifecycle. Native Windows calls occur only during an admitted launch.

Windows JobObject ownership is established before the stdlib gate releases the
original command. POSIX retains the existing new-session process-group policy.
"""
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[2]
GATE=ROOT/'runtime/process_gate.py'
TOKEN='FS_ELEM_OWNED_START_V1\n'


class OwnershipError(RuntimeError):pass


class _WinJob:
    def __init__(self):
        if os.name!='nt':raise OwnershipError('Windows JobObject requires native Windows')
        import ctypes
        from ctypes import wintypes
        self.ctypes=ctypes
        if ctypes.sizeof(ctypes.c_void_p)!=8:raise OwnershipError('Windows x64 Python is required')
        size_t=ctypes.c_size_t
        class BasicLimits(ctypes.Structure):
            _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),
                ('flags',wintypes.DWORD),('min_working',size_t),('max_working',size_t),
                ('active_limit',wintypes.DWORD),('affinity',size_t),
                ('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
        class IOCounters(ctypes.Structure):
            _fields_=[(name,ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class ExtendedLimits(ctypes.Structure):
            _fields_=[('basic',BasicLimits),('io',IOCounters),('process_memory',size_t),
                ('job_memory',size_t),('peak_process',size_t),('peak_job',size_t)]
        class Accounting(ctypes.Structure):
            _fields_=[(name,ctypes.c_longlong) for name in ('user','kernel','period_user','period_kernel')]+[
                (name,wintypes.DWORD) for name in ('faults','total','active','terminated')]
        if ctypes.sizeof(ExtendedLimits)!=144 or ctypes.sizeof(Accounting)!=48:
            raise OwnershipError('Unexpected Windows x64 JobObject structure layout')
        self.accounting_type=Accounting
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);self.kernel=kernel
        signatures={
            'CreateJobObjectW':([ctypes.c_void_p,wintypes.LPCWSTR],wintypes.HANDLE),
            'SetHandleInformation':([wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD],wintypes.BOOL),
            'SetInformationJobObject':([wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD],wintypes.BOOL),
            'AssignProcessToJobObject':([wintypes.HANDLE,wintypes.HANDLE],wintypes.BOOL),
            'IsProcessInJob':([wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)],wintypes.BOOL),
            'TerminateJobObject':([wintypes.HANDLE,wintypes.UINT],wintypes.BOOL),
            'QueryInformationJobObject':([wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p],wintypes.BOOL),
            'CloseHandle':([wintypes.HANDLE],wintypes.BOOL)}
        for name,(args,result) in signatures.items():
            fn=getattr(kernel,name);fn.argtypes=args;fn.restype=result
        self.handle=kernel.CreateJobObjectW(None,None)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        try:
            # Explicitly non-inheritable: parent loss closes the last owning handle.
            self.require(kernel.SetHandleInformation(self.handle,1,0))
            limits=ExtendedLimits();limits.basic.flags=0x00002000 # KILL_ON_JOB_CLOSE; no breakaway.
            self.require(kernel.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)))
        except BaseException:
            self.close();raise
    def require(self,result):
        if not result:raise self.ctypes.WinError(self.ctypes.get_last_error())
    def assign(self,process):
        from ctypes import wintypes
        # CPython Windows Popen retains this native handle until its wait/reap completes.
        handle=wintypes.HANDLE(int(process._handle))
        self.require(self.kernel.AssignProcessToJobObject(self.handle,handle))
        assigned=wintypes.BOOL()
        self.require(self.kernel.IsProcessInJob(handle,self.handle,self.ctypes.byref(assigned)))
        if not assigned.value:raise OwnershipError('Windows child ownership was not established')
    def terminate(self):self.require(self.kernel.TerminateJobObject(self.handle,1))
    def active(self):
        value=self.accounting_type()
        self.require(self.kernel.QueryInformationJobObject(self.handle,1,self.ctypes.byref(value),self.ctypes.sizeof(value),None))
        return int(value.active)
    def close(self):
        if self.handle:
            handle=self.handle;self.handle=None
            self.require(self.kernel.CloseHandle(handle))


class OwnedProcess:
    def __init__(self,process,job=None):
        self.process=process;self.job=job;self._lock=threading.Lock();self._closed=False
    @property
    def pid(self):return self.process.pid
    @property
    def stdout(self):return self.process.stdout
    def poll(self):return self.process.poll()
    def wait(self,timeout=None):return self.process.wait(timeout=timeout)
    @classmethod
    def launch(cls,argv,cwd,env,windows_job_factory=None):
        # The injectable factory is for separately granted failure tests, never an unowned fallback.
        windows=os.name=='nt' or windows_job_factory is not None
        if not windows:
            process=subprocess.Popen(argv,cwd=cwd,env=env,stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',start_new_session=True)
            return cls(process)
        if not GATE.is_file():raise OwnershipError('Trusted Windows startup gate is missing')
        job=(windows_job_factory or _WinJob)();process=None
        try:
            # No sitecustomize/.pth/user imports may run before job assignment.
            process=subprocess.Popen([sys.executable,'-I','-S','-B','-X','utf8',str(GATE),*argv],cwd=cwd,env=env,
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',close_fds=True)
            job.assign(process) # All future descendants inherit this job; gate has not spawned any.
            process.stdin.write(TOKEN);process.stdin.flush();process.stdin.close()
            return cls(process,job)
        except BaseException as first:
            # Do not release the gate on assignment/nested-job failure.
            errors=[]
            try:job.close()
            except Exception as error:errors.append(error)
            if process is not None:
                try:
                    if process.stdin and not process.stdin.closed:process.stdin.close()
                except Exception as error:errors.append(error)
                try:
                    if process.poll() is None:process.kill()
                except OSError as error:errors.append(error)
                try:process.wait(timeout=3)
                except Exception as error:errors.append(error)
                try:
                    if process.stdout:process.stdout.close()
                except Exception as error:errors.append(error)
            for error in errors:
                if hasattr(first,'add_note'):first.add_note('Owned launch cleanup: '+str(error)[:256])
            raise
    def _group_alive(self):
        try:os.killpg(self.pid,0);return True
        except ProcessLookupError:return False
    def _group_signal(self,value):
        try:os.killpg(self.pid,value)
        except ProcessLookupError:pass
    def stop(self):
        with self._lock:
            if self._closed:return
            deadline=time.monotonic()+6
            def left():return max(.001,deadline-time.monotonic())
            if self.job is not None:
                error=None
                try:
                    try:self.job.terminate()
                    except Exception as exc:error=exc
                    try:self.process.wait(timeout=min(3,left()))
                    except subprocess.TimeoutExpired:
                        self.process.kill();self.process.wait(timeout=left())
                    while self.job.active():
                        if time.monotonic()>=deadline:raise OwnershipError('Owned Windows job did not drain')
                        time.sleep(min(.02,left()))
                    if error:raise error
                finally:
                    self.job.close() # Also kill-on-close on any failure; no handle inherits into producers.
            else:
                self._group_signal(signal.SIGTERM)
                try:self.process.wait(timeout=min(3,left()))
                except subprocess.TimeoutExpired:pass
                self._group_signal(signal.SIGKILL)
                self.process.wait(timeout=left())
                while self._group_alive():
                    if time.monotonic()>=deadline:raise OwnershipError('Owned POSIX group did not disappear')
                    time.sleep(min(.02,left()))
            self._closed=True
