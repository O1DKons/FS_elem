"""Prepared lifecycle tests. No execution is authorized by inclusion of this file.

Run only against a complete isolated package with the overlay applied, after an exact
Root grant, FS_ELEM_RUN_PROCESS_TESTS=1 and FS_ELEM_TEST_PACKAGE_ROOT set.
"""
import ctypes
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

PACKAGE=Path(os.environ.get('FS_ELEM_TEST_PACKAGE_ROOT','.')).resolve()
sys.path.insert(0,str(PACKAGE/'services/analysis'))
FIXTURE=Path(__file__).with_name('lifecycle_fixture.py')
GRANTED=os.environ.get('FS_ELEM_RUN_PROCESS_TESTS')=='1'


def wait_until(callback,timeout=8):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=callback()
        if value:return value
        time.sleep(.02)
    raise AssertionError('bounded fixture condition was not reached')


def fixture_pid(directory,name):
    try:return json.loads((directory/(name+'.json')).read_text())['pid']
    except (OSError,ValueError,KeyError):return None


def alive(pid):
    if os.name=='nt':
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        kernel.WaitForSingleObject.restype=wintypes.DWORD
        kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
        handle=kernel.OpenProcess(0x00100000,False,pid)
        if not handle:
            code=ctypes.get_last_error()
            if code==87:return False
            raise ctypes.WinError(code)
        try:
            result=kernel.WaitForSingleObject(handle,0)
            if result==258:return True
            if result==0:return False
            raise ctypes.WinError(ctypes.get_last_error())
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False


def cleanup_fixture(owner,sentinel,temporary):
    """Always clean every retained fixture, keeping the first cleanup failure."""
    first=None
    def remember(error):
        nonlocal first
        if first is None:first=(error,error.__traceback__)
        elif hasattr(first[0],'add_note'):
            first[0].add_note('Additional fixture cleanup failure: '+str(error)[:256])
    try:
        if owner:owner.stop()
    except BaseException as error:remember(error)
    finally:
        try:
            stream=getattr(owner,'stdout',None)
            if stream is not None:stream.close()
        except BaseException as error:remember(error)
        try:
            if sentinel.poll() is None:sentinel.terminate()
        except BaseException as error:remember(error)
        finally:
            try:
                try:sentinel.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:sentinel.kill()
                    except BaseException as error:remember(error)
                    finally:
                        try:sentinel.wait(timeout=3)
                        except BaseException as error:remember(error)
            except BaseException as error:remember(error)
            finally:
                try:temporary.cleanup()
                except BaseException as error:remember(error)
    if first is not None:raise first[0].with_traceback(first[1])


@unittest.skipUnless(GRANTED,'separate lifecycle execution grant required')
class OwnedLifecycle(unittest.TestCase):
    def setUp(self):
        from process_owner import OwnedProcess
        self.Owner=OwnedProcess;self.temp=tempfile.TemporaryDirectory()
        self.directory=Path(self.temp.name);self.owner=None
        self.sentinel=subprocess.Popen([sys.executable,str(FIXTURE),'sentinel',str(self.directory)])
    def tearDown(self):
        cleanup_fixture(self.owner,self.sentinel,self.temp)
    def start_tree(self):
        self.owner=self.Owner.launch([sys.executable,str(FIXTURE),'tree',str(self.directory)],cwd=self.directory,env=os.environ.copy())
        return [wait_until(lambda n=n:fixture_pid(self.directory,n)) for n in ('tree','child','leaf')]
    def test_cancel_kills_owned_grandchild_and_keeps_sentinel(self):
        pids=self.start_tree();self.owner.stop();self.owner.wait(timeout=1)
        wait_until(lambda:not any(alive(pid) for pid in pids))
        self.assertIsNone(self.sentinel.poll())
    def test_assignment_failure_never_releases_producer(self):
        class RefuseAssignment:
            def assign(self,process):raise OSError('injected assignment refusal')
            def close(self):pass
        with self.assertRaises(OSError):
            self.Owner.launch([sys.executable,str(FIXTURE),'tree',str(self.directory)],cwd=self.directory,env=os.environ.copy(),windows_job_factory=RefuseAssignment)
        self.assertFalse((self.directory/'tree.json').exists())
        self.assertIsNone(self.sentinel.poll())
    @unittest.skipUnless(os.name=='nt','native Windows JobObject parent-loss proof only')
    def test_parent_loss_kills_job_and_keeps_unrelated_sentinel(self):
        host=subprocess.Popen([sys.executable,str(FIXTURE),'owner_host',str(self.directory),'--services',str(PACKAGE/'services/analysis')])
        try:
            pids=[wait_until(lambda n=n:fixture_pid(self.directory,n)) for n in ('gate','tree','child','leaf')]
            host.kill();host.wait(timeout=3)
            wait_until(lambda:not any(alive(pid) for pid in pids))
            self.assertIsNone(self.sentinel.poll())
        finally:
            if host.poll() is None:host.kill()
            host.wait(timeout=3)
    def test_timeout_cancel_and_restart_restore(self):
        from jobs import JobManager
        command=lambda d:[sys.executable,str(FIXTURE),'tree',str(d)]
        manager=JobManager(self.directory/'jobs',self.directory/'missing-config.json',runner_command=command,max_wall_seconds=1)
        try:
            job=manager.upload(io.BytesIO(b'fixture'),7,'fixture.mp4',require_ready=False)
            jid=job['jobId'];wait_until(lambda:manager.get(jid)['state']=='failed')
            self.assertEqual(manager.get(jid)['error']['code'],'TIME_LIMIT')
        finally:manager.close()
        restored=JobManager(self.directory/'jobs',self.directory/'missing-config.json',start_worker=False)
        try:self.assertEqual(restored.get(jid)['state'],'failed')
        finally:restored.close()
        self.assertIsNone(self.sentinel.poll())
    def test_manager_cancel_releases_active_tree_and_queued_job(self):
        from jobs import JobManager
        manager=JobManager(self.directory/'cancel',self.directory/'missing-config.json',
            runner_command=lambda d:[sys.executable,str(FIXTURE),'tree',str(d)])
        try:
            jid=manager.upload(io.BytesIO(b'fixture'),7,'fixture.mp4',require_ready=False)['jobId']
            path=manager.directory/jid
            pids=[wait_until(lambda n=n:fixture_pid(path,n)) for n in ('tree','child','leaf')]
            queued=manager.upload(io.BytesIO(b'fixture'),7,'queued.mp4',require_ready=False)['jobId']
            self.assertEqual(manager.cancel(queued)['state'],'cancelled')
            manager.cancel(jid)
            wait_until(lambda:manager.get(jid)['state']=='cancelled')
            wait_until(lambda:not any(alive(pid) for pid in pids))
            self.assertIsNone(self.sentinel.poll())
        finally:manager.close()
    def test_manager_close_releases_running_tree(self):
        from jobs import JobManager
        manager=JobManager(self.directory/'closing',self.directory/'missing-config.json',
            runner_command=lambda d:[sys.executable,str(FIXTURE),'tree',str(d)])
        try:
            jid=manager.upload(io.BytesIO(b'fixture'),7,'fixture.mp4',require_ready=False)['jobId']
            pids=[wait_until(lambda n=n:fixture_pid(manager.directory/jid,n)) for n in ('tree','child','leaf')]
        finally:manager.close()
        self.assertEqual(manager.get(jid)['state'],'cancelled')
        wait_until(lambda:not any(alive(pid) for pid in pids))
        self.assertIsNone(self.sentinel.poll())
    def test_completed_result_survives_restart(self):
        from jobs import JobManager
        command=lambda d:[sys.executable,str(FIXTURE),'complete',str(d)]
        manager=JobManager(self.directory/'results',self.directory/'missing-config.json',runner_command=command)
        try:
            jid=manager.upload(io.BytesIO(b'fixture'),7,'fixture.mp4',require_ready=False)['jobId']
            wait_until(lambda:manager.get(jid)['state']=='succeeded')
        finally:manager.close()
        restored=JobManager(self.directory/'results',self.directory/'missing-config.json',start_worker=False)
        try:self.assertEqual(restored.artifact(jid,'result'),{})
        finally:restored.close()


@unittest.skipUnless(GRANTED,'separate lifecycle execution grant required')
class CooperativeControl(unittest.TestCase):

    def test_cleanup_preserves_first_failure_and_attempts_all_retained_resources(self):
        for has_stdout in (False,True):
            with self.subTest(has_stdout=has_stdout):
                calls=[];first=RuntimeError('forced owner.stop failure')
                class Pipe:
                    def close(self):calls.append('owner.stdout.close');raise OSError('later stdout close failure')
                class Owner:
                    def stop(self):calls.append('owner.stop');raise first
                class Sentinel:
                    def poll(self):calls.append('sentinel.poll');return None
                    def terminate(self):calls.append('sentinel.terminate');raise OSError('later terminate failure')
                    def wait(self,timeout):calls.append('sentinel.wait');return 0
                class Temporary:
                    def cleanup(self):calls.append('temporary.cleanup');raise ValueError('later temp failure')
                owner=Owner()
                if has_stdout:owner.stdout=Pipe()
                with self.assertRaises(RuntimeError) as caught:
                    cleanup_fixture(owner,Sentinel(),Temporary())
                self.assertIs(caught.exception,first)
                expected=['owner.stop']+(['owner.stdout.close'] if has_stdout else [])+['sentinel.poll','sentinel.terminate','sentinel.wait','temporary.cleanup']
                self.assertEqual(calls,expected)

    def test_shutdown_and_eof_and_invalid_bounded_input(self):
        from server import read_control_stdin
        for raw in (b'{"type":"shutdown"}\n',b'',b'x'*257,b'{"type":"unknown"}\n'):
            seen=[];read_control_stdin(io.BytesIO(raw),lambda:seen.append(True))
            self.assertEqual(seen,[True])
    def test_idle_api_stdin_close_terminates_retained_handle(self):
        with tempfile.TemporaryDirectory() as temporary:
            p=subprocess.Popen([sys.executable,str(PACKAGE/'services/analysis/server.py'),'--port','0','--config',str(Path(temporary)/'none.json'),'--jobs',str(Path(temporary)/'jobs')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={**os.environ,'FS_ELEM_CONTROL_STDIN':'1'})
            try:
                # Dedicated scoped harness must additionally impose an external start deadline.
                startup=p.stdout.readline()
                (PACKAGE.parent/'idle-api-startup.bin').write_bytes(startup[:4097])
                if not startup:
                    code=p.wait(timeout=3)
                    diagnostic=p.stderr.read(4097)
                    (PACKAGE.parent/'idle-api-failure-stderr.bin').write_bytes(diagnostic)
                    message=('API startup EOF; exit '+str(code)+'; stderr: '+diagnostic.decode('utf-8',errors='replace')).encode('utf-8')[:4096].decode('utf-8',errors='replace')
                    self.fail(message)
                self.assertIn('port',json.loads(startup))
                p.stdin.write(b'{"type":"shutdown"}\n');p.stdin.flush();p.stdin.close()
                self.assertEqual(p.wait(timeout=12),0)
            finally:
                active=sys.exception();later=[]
                try:
                    if p.poll() is None:p.kill()
                except BaseException as error:later.append(error)
                try:p.wait(timeout=3)
                except BaseException as error:later.append(error)
                for stream in (p.stdin,p.stdout,p.stderr):
                    try:stream.close()
                    except BaseException as error:later.append(error)
                if later:
                    if active is None:raise later[0]
                    for error in later:active.add_note('API cleanup failure: '+str(error)[:256])


if __name__=='__main__':unittest.main()
