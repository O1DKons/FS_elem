"""Prospective tests; no target execution authorized in Source phase."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).parents[2] / 'scripts' / 'release_platform.py'
spec = importlib.util.spec_from_file_location('release_platform', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PlatformTests(unittest.TestCase):
    # Break: ignoring Windows AMD64 spelling or choosing Unix venv executable.
    def test_native_venv_paths(self):
        self.assertEqual(module.platform_id('Windows', 'AMD64', '10'), 'windows-x64')
        self.assertEqual(module.venv_python(Path('runtime/venv'), 'windows-x64'), Path('runtime/venv/Scripts/python.exe'))
        self.assertEqual(module.venv_python(Path('runtime/venv'), 'macos-arm64'), Path('runtime/venv/bin/python'))

    # Break: unsupported host quietly falls back to Mac locks.
    def test_reject_unsupported_hosts(self):
        for system, arch, version in [('Windows', 'ARM64', '11'), ('Darwin', 'x86_64', '14'), ('Linux', 'x86_64', '6'), ('Darwin', 'arm64', '12')]:
            with self.subTest(system=system, arch=arch):
                with self.assertRaises(ValueError):
                    module.platform_id(system, arch, version)

    # Break: placeholder Windows hashes interpreted as a usable native runtime.
    def test_pending_profile_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'pending'):
            module.require_ready_profile({'status': 'pending-metadata', 'ffmpeg': {'sha256': None}})

    # Break: a missing lock/FFmpeg identity silently permits an unpinned setup.
    def test_ready_label_does_not_bypass_integrity_fields(self):
        with self.assertRaisesRegex(ValueError, 'lock'):
            module.require_ready_profile({'status': 'ready', 'environments': {'science': {'lock': 'x', 'lockSha256': 'g' * 64}}})

    # Break: a 32-bit Python on an x64 host reaches pip with incompatible wheel tags.
    def test_reject_wrong_interpreter_bitness_or_version(self):
        good = {'system': 'Windows', 'machine': 'AMD64', 'version': [3, 12, 1], 'bits': 64}
        module.require_interpreter(good, 'windows-x64', (3, 12))
        for changed in ({'bits': 32}, {'machine': 'ARM64'}, {'version': [3, 9, 1]}, {'system': 'Darwin'}):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    module.require_interpreter(dict(good, **changed), 'windows-x64', (3, 12))


if __name__ == '__main__':
    unittest.main()
