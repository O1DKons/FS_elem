"""Elapsed job metadata uses server time, terminal receipt time and read-only copies."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('elapsed_jobs', Path(__file__).with_name('jobs.py'))
jobs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jobs)


class ElapsedTests(unittest.TestCase):
    def job(self, state='queued'):
        return {'jobId': '668794a1-a96a-4a18-90d6-4cc7dc7f90a1', 'state': state,
                'createdAt': '2026-10-03T07:00:00+00:00', 'updatedAt': '2026-10-03T07:00:03+00:00'}

    def test_pending_and_running_include_queue_use_server_time(self):
        with patch.object(jobs, 'now', return_value='2026-10-03T07:00:12.5+00:00'):
            for state in ('queued', 'running'):
                self.assertEqual(jobs.job_elapsed_seconds(self.job(state)), 12.5)

    def test_all_terminal_states_stop_at_saved_end_and_are_poll_stable(self):
        for state in ('succeeded', 'failed', 'cancelled'):
            job = self.job(state)
            with patch.object(jobs, 'now', side_effect=AssertionError('Terminal must not sample current time')):
                self.assertEqual(jobs.job_elapsed_seconds(job), 3.0)
                self.assertEqual(jobs.job_elapsed_seconds(job), 3.0)

    def test_timezone_offsets_and_backwards_clock(self):
        job = self.job('succeeded')
        job['createdAt'] = '2026-10-03T12:00:00+05:00'
        self.assertEqual(jobs.job_elapsed_seconds(job), 3.0)
        job['updatedAt'] = '2026-10-03T06:59:59+00:00'
        self.assertEqual(jobs.job_elapsed_seconds(job), 0.0)

    def test_missing_invalid_naive_dates_and_unknown_states_return_null(self):
        for update in ({'createdAt': None}, {'updatedAt': 'bad'}, {'createdAt': '2026-10-03T07:00:00'},
                       {'updatedAt': '2026-10-03T07:00:03'}, {'state': 'not-a-job-state'}):
            job = self.job('succeeded')
            job.update(update)
            self.assertIsNone(jobs.job_elapsed_seconds(job))

    def test_get_does_not_write_elapsed_to_persisted_record(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manager = jobs.JobManager(root / 'jobs', root / 'missing.json', start_worker=False)
            job = self.job()
            manager.jobs[job['jobId']] = job
            directory = manager.directory / job['jobId']
            directory.mkdir()
            persisted = directory / 'job.json'
            persisted.write_text(json.dumps(job))
            before = persisted.read_bytes()
            with patch.object(jobs, 'now', return_value='2026-10-03T07:00:12.5+00:00'):
                first = manager.get(job['jobId'])
            with patch.object(jobs, 'now', return_value='2026-10-03T07:00:19+00:00'):
                second = manager.get(job['jobId'])
            self.assertEqual(first['elapsedSeconds'], 12.5)
            self.assertEqual(second['elapsedSeconds'], 19.0)
            self.assertEqual(first['updatedAt'], job['updatedAt'])
            self.assertNotIn('elapsedSeconds', manager.jobs[job['jobId']])
            self.assertEqual(persisted.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
