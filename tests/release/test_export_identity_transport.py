"""Prepared export-race/provenance fixtures only; no execution in Source scope."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TRUSTED = "1" * 64


def entry_module(publish):
    # Isolate the external full result exporter; exercise the real entry gate
    # and real output files without importing inference libraries or raw poses.
    exporter = types.ModuleType("pose_export")
    exporter.publish = publish
    spec = importlib.util.spec_from_file_location("trusted_export_entry", ROOT / "runtime/analyze_job.py")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"pose_export": exporter}):
        spec.loader.exec_module(module)
    return module


class ExportIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="FS_elem export identity ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.job = self.base / "00000000-0000-4000-8000-000000000001"
        self.job.mkdir()
        self.video = self.job / "video.mp4"; self.video.write_bytes(b"synthetic source")
        self.config = self.base / "config.json"
        self.config.write_text(json.dumps({"posePython": "pose-python"}))
        self.mutable = self.job / "job.json"; self.mutable.write_text("locked mutable progress metadata")
        self.pipeline_sha = TRUSTED

    def pipeline(self, argv, check):
        self.assertIs(check, True)
        path = Path(argv[argv.index("--output") + 1])
        path.write_text(json.dumps({"sourceSha256": self.pipeline_sha}))
        return types.SimpleNamespace(returncode=0)

    def publish(self, job_id, raw, directory):
        # A narrow exporter boundary double publishes physical marker artifacts.
        # The assertions inspect the real entry's admitted/suppressed effects.
        for name in ("result.json", "pose.json"):
            (directory / name).write_text(json.dumps({"jobId": job_id, "sourceSha256": raw["sourceSha256"]}))

    def invoke(self, module):
        original = Path.read_text
        def guarded(path, *args, **kwargs):
            if path == self.mutable:
                raise PermissionError(13, "Progress metadata is concurrently replaced", str(path))
            return original(path, *args, **kwargs)
        argv = ["analyze_job.py", "--job", str(self.job), "--video", str(self.video),
                "--config", str(self.config), "--source-sha256", TRUSTED]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(module.subprocess, "run", side_effect=self.pipeline), \
                mock.patch.object(Path, "read_text", guarded):
            module.main()

    def test_locked_mutable_job_metadata_does_not_prevent_trusted_export(self):
        self.invoke(entry_module(self.publish))
        for name in ("result.json", "pose.json"):
            value = json.loads((self.job / name).read_text())
            self.assertEqual(value, {"jobId": self.job.name, "sourceSha256": TRUSTED})

    def test_pipeline_hash_mismatch_cannot_publish_result_or_pose(self):
        self.pipeline_sha = "2" * 64
        with self.assertRaisesRegex(ValueError, "source identity changed"):
            self.invoke(entry_module(self.publish))
        self.assertFalse((self.job / "result.json").exists())
        self.assertFalse((self.job / "pose.json").exists())


class CommandIdentityTests(unittest.TestCase):
    def test_parent_transports_memory_hash_without_reading_progress_file(self):
        owner = types.ModuleType("process_owner")
        owner.OwnedProcess = type("UnusedOwnedProcess", (), {})
        owner.OwnershipError = type("UnusedOwnershipError", (Exception,), {})
        diagnostics = types.ModuleType("source_diagnostics")
        diagnostics.validate_diagnostics = lambda value: value
        diagnostics.public_source_error = lambda value: None
        spec = importlib.util.spec_from_file_location("trusted_parent_jobs", ROOT / "services/analysis/jobs.py")
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"process_owner": owner, "source_diagnostics": diagnostics}):
            spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="FS_elem command identity ") as temp:
            directory = Path(temp) / "00000000-0000-4000-8000-000000000001"; directory.mkdir()
            (directory / "video.mp4").write_bytes(b"synthetic")
            config = Path(temp) / "config.json"; config.write_text(json.dumps({"sciencePython": "science-python"}))
            manager = object.__new__(module.JobManager)
            manager.runner_command = None; manager.config = config; manager.lock = threading.RLock()
            manager.jobs = {directory.name: {"source": {"sha256": TRUSTED}}}
            original = Path.read_text
            def guarded(path, *args, **kwargs):
                if path.name == "job.json":
                    raise PermissionError(13, "Mutable progress file must not be read")
                return original(path, *args, **kwargs)
            with mock.patch.object(Path, "read_text", guarded):
                command = manager._command(directory)
            self.assertEqual(command[command.index("--source-sha256") + 1], TRUSTED)
            self.assertEqual(command[command.index("--job") + 1], str(directory))
            self.assertEqual(command[command.index("--video") + 1], str(directory / "video.mp4"))


if __name__ == "__main__":
    unittest.main()
