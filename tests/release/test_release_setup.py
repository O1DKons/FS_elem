"""Changed setup guards; no pip/model/NN invoked by these disk fixtures."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

scripts = Path(__file__).parents[2] / 'scripts'
sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location('release_setup', scripts / 'setup-release.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupGuards(unittest.TestCase):
    # Break: status ready bypasses wrong platform/fingerprint marker and adopts a foreign venv.
    def test_foreign_managed_marker_preserved_and_rejected_before_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / 'requirements.lock'
            lock.write_text('controlled fixture\n', encoding='utf-8')
            env = root / '.runtime' / 'venv-science'
            env.mkdir(parents=True)
            marker = env / '.release-environment.json'
            original = json.dumps({'status': 'complete', 'lockSha256': hashlib.sha256(lock.read_bytes()).hexdigest(), 'platformId': 'macos-arm64'})
            marker.write_text(original, encoding='utf-8')
            manifest = {'_platformId': 'windows-x64', '_profileSha256': 'a' * 64, 'environments': {'science': {'lock': 'requirements.lock', 'packages': {}}}}
            with self.assertRaisesRegex(setup.SetupError, 'changed managed'):
                setup.ensure_environment(root, 'science', 'missing-interpreter-never-invoked', manifest)
            self.assertEqual(marker.read_text(encoding='utf-8'), original)

    # Break: installer writes over an unrelated venv directory without an ownership marker.
    def test_unmanaged_environment_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = root / '.runtime' / 'venv-pose'
            env.mkdir(parents=True)
            sentinel = env / 'existing.txt'
            sentinel.write_text('preserve', encoding='utf-8')
            with self.assertRaisesRegex(setup.SetupError, 'unmanaged'):
                setup.ensure_environment(root, 'pose', 'missing-interpreter-never-invoked', {'_platformId': 'windows-x64'})
            self.assertEqual(sentinel.read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
