import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "work/full-program-pose-flight-18-v1/run_pose_cache.py"
SPEC = importlib.util.spec_from_file_location("run_pose_cache", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PoseCachePathTests(unittest.TestCase):
    def test_reuses_verified_extensionless_flat_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            source = output / "comp-24"
            target = output / "comp-24.json"
            source.write_text(json.dumps({"source": {"sha256": "abc"}, "frames": []}))

            resolved = MODULE.ensure_pose_cache("comp-24", "abc", output=output,
                                                external_cache=output / "missing.json")

            self.assertEqual(resolved, target)
            self.assertEqual(json.loads(target.read_text())["source"]["sha256"], "abc")
            self.assertTrue(source.exists())

    def test_reuses_nested_pose_json_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            nested = output / "comp-24" / "pose.json"
            nested.parent.mkdir()
            nested.write_text(json.dumps({"source": {"sha256": "abc"}, "frames": []}))

            resolved = MODULE.ensure_pose_cache("comp-24", "abc", output=output,
                                                external_cache=output / "missing.json")

            self.assertEqual(resolved, output / "comp-24.json")
            self.assertTrue(resolved.is_file())

    def test_rejects_cached_artifact_for_different_source(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output / "comp-24").write_text(json.dumps({"source": {"sha256": "wrong"}}))

            with self.assertRaisesRegex(ValueError, "source mismatch"):
                MODULE.ensure_pose_cache("comp-24", "abc", output=output,
                                         external_cache=output / "missing.json")


if __name__ == "__main__":
    unittest.main()
