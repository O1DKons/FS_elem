import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


class JobTests(unittest.TestCase):
    def test_persistent_job_cancel_and_restart(self):
        import jobs
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            manager = jobs.JobManager(base, base/'missing.json', start_worker=False)
            job = manager.upload(io.BytesIO(b'video'), 5, 'test.mp4', require_ready=False)
            self.assertEqual(job['state'], 'queued')
            self.assertEqual(manager.cancel(job['jobId'])['state'], 'cancelled')
            other = manager.upload(io.BytesIO(b'video'), 5, 'test.mp4', require_ready=False)
            restored = jobs.JobManager(base, base/'missing.json', start_worker=False)
            self.assertEqual(restored.get(other['jobId'])['state'], 'failed')
            self.assertEqual(restored.get(other['jobId'])['error']['code'], 'INTERRUPTED')
            self.assertEqual(restored.get(job['jobId'])['state'], 'cancelled')

    def test_upload_limits_and_identity(self):
        import jobs
        with tempfile.TemporaryDirectory() as td:
            manager = jobs.JobManager(Path(td), Path(td)/'config.json', start_worker=False, max_upload=8)
            with self.assertRaises(jobs.ApiError) as err:
                manager.upload(io.BytesIO(b'123456789'), 9, 'x.mp4', require_ready=False)
            self.assertEqual(err.exception.status, 413)
            with self.assertRaises(jobs.ApiError):
                manager.upload(io.BytesIO(b'ab'), 4, 'x.mp4', require_ready=False)
            with self.assertRaises(jobs.ApiError):
                manager.upload(io.BytesIO(b'x'), 1, '../../x.py', require_ready=False)
            with self.assertRaises(jobs.ApiError):
                manager.get('../../etc/passwd')
            job = manager.upload(io.BytesIO(b'123'), 3, 'спорт.MOV', require_ready=False)
            self.assertEqual(job['source']['sizeBytes'], 3)
            self.assertEqual(len(job['source']['sha256']), 64)
            self.assertNotIn(str(td), json.dumps(job))

    def test_successful_empty_result_and_owned_cancellation(self):
        import jobs
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            script = base/'fixture.py'
            script.write_text("import sys,json,time\nfrom pathlib import Path\np=Path(sys.argv[1])\nif sys.argv[2]=='sleep':\n print(json.dumps({'stage':'sparse','currentFrame':5,'totalFrames':10}),flush=True);time.sleep(30)\nelse:\n (p/'result.json').write_text(json.dumps({'events':[],'noEvents':True}));(p/'pose.json').write_text(json.dumps({'frames':[]}))\n")
            mode = ['empty']
            manager = jobs.JobManager(base/'jobs', base/'config.json', runner_command=lambda d:[sys.executable,str(script),str(d),mode[0]])
            self.addCleanup(manager.close)
            job = manager.upload(io.BytesIO(b'x'), 1, 'x.mp4', require_ready=False)
            self.wait_state(manager, job['jobId'], {'succeeded'})
            self.assertEqual(manager.artifact(job['jobId'], 'result')['events'], [])
            mode[0] = 'sleep'
            job = manager.upload(io.BytesIO(b'x'), 1, 'x.mp4', require_ready=False)
            self.wait_state(manager, job['jobId'], {'running'})
            manager.cancel(job['jobId'])
            self.wait_state(manager, job['jobId'], {'cancelled'})
            self.assertIsNone(manager.active_job_id)

    def wait_state(self, manager, jid, states):
        end = time.monotonic()+5
        while time.monotonic()<end:
            value=manager.get(jid)
            if value['state'] in states:return value
            if value['state']=='failed':self.fail(str(value))
            time.sleep(.02)
        self.fail('Job did not reach '+str(states))


if __name__=='__main__':unittest.main()
