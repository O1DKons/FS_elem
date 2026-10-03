"""Real JobManager/HTTP lifecycle with one inert subprocess boundary, no video/NN."""
import hashlib
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

ROOT = Path(os.environ.get('FS_ELEM_RELEASE_ROOT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / 'services/analysis'))
from jobs import JobManager
from server import Handler


class ReleaseLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fs-release-lifecycle-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.config = self.base / 'synthetic-config.json'
        (self.base / 'stub-asset').write_bytes(b'synthetic-not-model')
        self.config.write_text(json.dumps({'sciencePython': sys.executable, 'posePython': sys.executable,
            'models': {}, 'checkpoints': {}, 'inputSha256': {},
            'ffmpeg': {'path': 'stub-asset', 'sha256': hashlib.sha256(b'synthetic-not-model').hexdigest()}}))

    def serve(self, worker=False, config=None, **manager_options):
        manager = JobManager(self.base / 'jobs', config or self.config, start_worker=worker,
            runner_command=lambda d: [sys.executable, str(Path(__file__).with_name('release-inert-pipeline.py')), str(d)],
            **manager_options)
        self.addCleanup(manager.close)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        server.manager = manager
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        thread.start()
        def close():
            server.shutdown(); server.server_close(); thread.join(timeout=2)
        self.addCleanup(close)
        return manager, server.server_port

    def request(self, port, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            data = response.read()
            return response.status, dict(response.getheaders()), data
        finally:
            connection.close()

    def upload(self, port, payload=b'fixture:empty', filename='синтетика.MOV'):
        status, _, raw = self.request(port, 'POST', '/jobs', payload,
            {'X-Filename': quote(filename), 'Content-Type': 'application/octet-stream'})
        self.assertEqual(status, 202, raw)
        return json.loads(raw)

    def wait(self, manager, jid, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = manager.get(jid)
            if predicate(job): return job
            time.sleep(.02)
        self.fail('Job did not reach expected state: ' + repr(manager.get(jid)))

    def test_queued_identity_range_not_ready_and_cancel(self):
        manager, port = self.serve()
        first = self.upload(port)
        second = self.upload(port, b'different source')
        self.assertNotEqual(first['jobId'], second['jobId'])
        self.assertEqual(first['source']['sha256'], hashlib.sha256(b'fixture:empty').hexdigest())
        self.assertNotEqual(first['source']['sha256'], second['source']['sha256'])
        self.assertEqual(first['source']['filename'], 'синтетика.MOV')
        path = '/jobs/' + first['jobId']
        for suffix in ['/result', '/pose']:
            status, _, raw = self.request(port, 'GET', path + suffix)
            self.assertEqual(status, 409)
            self.assertEqual(json.loads(raw)['error']['code'], 'NOT_READY')
        status, headers, data = self.request(port, 'GET', path + '/media', headers={'Range': 'bytes=2-5'})
        self.assertEqual((status, data, headers['Content-Range']), (206, b'xtur', 'bytes 2-5/13'))
        status, headers, data = self.request(port, 'HEAD', path + '/media')
        self.assertEqual((status, data, headers['Content-Length']), (200, b'', '13'))
        self.assertEqual(self.request(port, 'GET', '/jobs/00000000-0000-4000-8000-000000000099/result')[0], 404)
        status, _, raw = self.request(port, 'DELETE', path)
        self.assertEqual((status, json.loads(raw)['state']), (200, 'cancelled'))
        self.assertEqual(self.request(port, 'GET', path + '/result')[0], 409)

    def test_restart_interrupts_queued_job_and_keeps_cancelled_terminal(self):
        manager, port = self.serve()
        first, second = self.upload(port), self.upload(port, b'other')
        self.request(port, 'DELETE', '/jobs/' + first['jobId'])
        # No worker process is started; another real manager reads persisted records.
        restored = JobManager(self.base / 'jobs', self.config, start_worker=False)
        self.addCleanup(restored.close)
        self.assertEqual(restored.get(first['jobId'])['state'], 'cancelled')
        job = restored.get(second['jobId'])
        self.assertEqual((job['state'], job['error']['code']), ('failed', 'INTERRUPTED'))
        self.assertIsNone(restored.active_job_id)

    def test_empty_success_then_failed_partial_result(self):
        manager, port = self.serve(worker=True)
        first = self.upload(port)
        self.wait(manager, first['jobId'], lambda j: j['state'] == 'succeeded')
        path = '/jobs/' + first['jobId']
        status, _, raw = self.request(port, 'GET', path + '/result')
        result = json.loads(raw)
        self.assertEqual((status, result['noEvents'], result['events']), (200, True, []))
        self.assertEqual(result['source']['sha256'], first['source']['sha256'])
        self.assertEqual(self.request(port, 'DELETE', path)[0], 200)
        self.assertEqual(self.request(port, 'GET', path + '/result')[0], 200)
        failed = self.upload(port, b'fixture:fail')
        job = self.wait(manager, failed['jobId'], lambda j: j['state'] == 'failed')
        self.assertEqual(job['error']['code'], 'ANALYSIS_FAILED')
        self.assertEqual(self.request(port, 'GET', '/jobs/' + failed['jobId'] + '/result')[0], 409)

    @unittest.skipUnless(os.name == 'posix', 'process-group check is POSIX only')
    def test_running_cancel_cleans_own_descendant_and_next_job_works(self):
        manager, port = self.serve(worker=True)
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        def stop_unrelated():
            unrelated.terminate(); unrelated.wait(timeout=3)
        self.addCleanup(stop_unrelated)
        job = self.upload(port, b'fixture:hold')
        running = self.wait(manager, job['jobId'], lambda j: j['progress']['percent'] == 42.9)
        self.assertEqual(running['state'], 'running')
        ids = json.loads((self.base / 'jobs' / job['jobId'] / 'fixture-pids.json').read_text())
        status, _, raw = self.request(port, 'DELETE', '/jobs/' + job['jobId'])
        pending = json.loads(raw)
        self.assertEqual((status, pending['state'], pending['progress']['stage']), (202, 'running', 'cancelling'))
        self.wait(manager, job['jobId'], lambda j: j['state'] == 'cancelled' and manager.active_job_id is None)
        self.assertIsNone(unrelated.poll())
        for pid in ids:
            probe = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True, timeout=2)
            self.assertTrue(not probe.stdout.strip() or probe.stdout.strip().startswith('Z'),
                'owned process is still live: ' + str(pid))
        self.assertEqual(self.request(port, 'GET', '/jobs/' + job['jobId'] + '/pose')[0], 409)
        following = self.upload(port, b'next after cancellation')
        self.wait(manager, following['jobId'], lambda j: j['state'] == 'succeeded')

    def test_runtime_unavailable_refuses_valid_upload_with_reason(self):
        manager, port = self.serve(config=self.base / 'missing.json')
        status, _, raw = self.request(port, 'GET', '/health')
        health = json.loads(raw)
        self.assertEqual((status, health['inferenceAvailable'], health['activeJobId']), (200, False, None))
        self.assertTrue(health['issues'])
        status, _, raw = self.request(port, 'POST', '/jobs', b'fixture:empty', {'X-Filename': 'x.mp4'})
        self.assertEqual((status, json.loads(raw)['error']['code']), (503, 'RUNTIME_UNAVAILABLE'))
        self.assertEqual(manager.jobs, {})

    @unittest.skipUnless(os.name == 'posix', 'process-group check is POSIX only')
    def test_wall_limit_fails_cleans_owned_group_and_releases_next_job(self):
        manager, port = self.serve(worker=True, max_wall_seconds=1)
        first = self.upload(port, b'fixture:hold')
        self.wait(manager, first['jobId'], lambda j: j['progress']['percent'] == 42.9)
        ids = json.loads((self.base / 'jobs' / first['jobId'] / 'fixture-pids.json').read_text())
        following = self.upload(port, b'fixture:after-deadline')
        failed = self.wait(manager, first['jobId'], lambda j: j['state'] == 'failed')
        self.assertEqual(failed['error']['code'], 'TIME_LIMIT')
        self.assertEqual(failed['progress']['stage'], 'failed')
        self.assertNotEqual(manager.active_job_id, first['jobId'])
        for pid in ids:
            probe = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True, timeout=2)
            self.assertTrue(not probe.stdout.strip() or probe.stdout.strip().startswith('Z'),
                'time-limited owned process is still live: ' + str(pid))
        for suffix in ['result', 'pose']:
            status, _, raw = self.request(port, 'GET', '/jobs/' + first['jobId'] + '/' + suffix)
            self.assertEqual((status, json.loads(raw)['error']['code']), (409, 'NOT_READY'))
        self.wait(manager, following['jobId'], lambda j: j['state'] == 'succeeded')

    def test_invalid_wall_limit_is_rejected(self):
        for value in [0, -1, 5401, True, 1.5, '1800']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                JobManager(self.base / 'invalid', self.config, start_worker=False, max_wall_seconds=value)


if __name__ == '__main__':
    unittest.main()
