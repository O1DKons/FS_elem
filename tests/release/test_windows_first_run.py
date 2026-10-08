"""Offline packaging checks: synthetic bytes, no dependency install or inference."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).parents[2] / 'scripts'
sys.path.insert(0, str(SCRIPTS))


def load(name, filename):
    path = SCRIPTS / filename
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup = load('desktop_setup', 'setup-release.py')
first = load('windows_first_run', 'windows-first-run.py')


def digest(body):
    return hashlib.sha256(body).hexdigest()


class FirstRunTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(first, 'Windows first-run bootstrap is not implemented')
        self.temp = tempfile.TemporaryDirectory(prefix='FS_elem & Кириллица ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.events = []
        self.files = {}

        def put(path, body):
            body = body.encode() if isinstance(body, str) else body
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            self.files[path] = body

        self.put = put
        for name in ('science', 'pose'):
            put(f'{name}.lock', 'synthetic lock ' + name)
            put(f'.runtime/venv-{name}/Scripts/python.exe', 'synthetic executable')
        put('.runtime/node/node.exe', 'synthetic node')
        put('.runtime/bin/ffmpeg.exe', 'synthetic ffmpeg')
        put('.runtime/frontend-install.json', '{}')
        put('apps/web/dist/server/index.js', 'synthetic compiled UI')
        put('apps/web/dist/client/index.html', 'synthetic compiled client')
        put('assets/models/model.bin', 'verified model')
        self.native = {
            'status': 'ready', 'platform': {'system': 'Windows', 'architecture': 'x64'},
            'environments': {n: {'lock': n + '.lock', 'lockSha256': digest(self.files[n + '.lock']),
                                'packages': {}} for n in ('science', 'pose')},
            'ffmpeg': {'id': 'ffmpeg', 'path': '.runtime/bin/ffmpeg.exe',
                       'sizeBytes': len(self.files['.runtime/bin/ffmpeg.exe']),
                       'sha256': digest(self.files['.runtime/bin/ffmpeg.exe'])}}
        self.profile_sha = digest(json.dumps(self.native, sort_keys=True, separators=(',', ':')).encode())
        for name, minor in (('science', [3, 12]), ('pose', [3, 9])):
            put(f'.runtime/venv-{name}/.release-environment.json', json.dumps({
                'schemaVersion': 2, 'status': 'complete', 'pythonMinor': minor,
                'lockSha256': digest(self.files[name + '.lock']), 'platformId': 'windows-x64',
                'profileSha256': self.profile_sha}))
        self.model = {'id': 'synthetic', 'path': 'assets/models/model.bin',
                      'sizeBytes': len(self.files['assets/models/model.bin']),
                      'sha256': digest(self.files['assets/models/model.bin']), 'url': None}
        put('assets/models/manifest-release-v1.json', json.dumps({
            'schemaVersion': 1, 'models': [self.model], 'platforms': {'windows-x64': self.native}}))
        self.bundle = {'schemaVersion': 1, 'packageVersion': '0.2.2', 'platformId': 'windows-x64',
                       'nativeProfileSha256': self.profile_sha,
                       'node': {'path': '.runtime/node/node.exe', 'version': '24.15.0'},
                       'interpreters': {n: f'.runtime/venv-{n}/Scripts/python.exe' for n in ('science', 'pose')},
                       'files': [{'path': p, 'bytes': len(b), 'sha256': digest(b)} for p, b in self.files.items()]}
        put('windows-bundle.json', json.dumps(self.bundle))
        self.platform = mock.patch.object(first.setup, 'platform_id', return_value='windows-x64')
        self.platform.start()
        self.addCleanup(self.platform.stop)
        self.validation = mock.patch.object(first.setup, 'validate_environment', return_value=None)
        self.validate = self.validation.start()
        self.addCleanup(self.validation.stop)
        self.no_install = mock.patch.object(first.setup, 'ensure_environment', side_effect=AssertionError('no install on user'))
        self.no_install.start()
        self.addCleanup(self.no_install.stop)

    def test_windows_volume_serial_matches_native_node_without_truncating_other_fields(self):
        import stat
        # Observed native Python3.12/Node24 mismatch: only volume serial width differs.
        source = mock.Mock()
        source.is_file.return_value = True
        source.is_symlink.return_value = False
        source.stat.side_effect = AssertionError('Use the fresh lstat snapshot without another stat query')
        source.lstat.return_value = mock.Mock(st_mode=stat.S_IFREG | 0o600,
            st_size=17, st_dev=10116456482831564288,
            st_ino=79228162514264337593543950433, st_mtime_ns=1729000000123456700,
            st_ctime_ns=1728000000123456700)
        expected = dict(sizeBytes=17, dev='1692368384', ino='79228162514264337593543950433',
            mtimeNs='1729000000123456700', ctimeNs='1728000000123456700')
        with mock.patch.object(first.os, 'name', 'nt'):
            self.assertEqual(first.fingerprint(source), expected)
        expected['dev'] = '10116456482831564288'
        with mock.patch.object(first.os, 'name', 'posix'):
            self.assertEqual(first.fingerprint(source), expected)
        self.assertEqual(source.lstat.call_count, 2)
        source.stat.assert_not_called()

    def test_fingerprint_rejects_actual_directory(self):
        directory = self.root / 'not-a-regular-file'
        directory.mkdir()
        with self.assertRaises(first.setup.SetupError):
            first.fingerprint(directory)

    def test_fingerprint_rejects_actual_final_symlink(self):
        target = self.root / 'regular-target'
        target.write_bytes(b'verified regular bytes')
        link = self.root / 'linked-file'
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as error:
            self.skipTest('Host does not permit creating a symlink: ' + str(error))
        with self.assertRaises(first.setup.SetupError):
            first.fingerprint(link)

    def test_json_progress_preserves_unicode_and_first_error_on_cp1252_stdout(self):
        import io
        message = 'Проверка файлов: ' + str(self.root)
        first_error = 'Исходная ошибка: ' + str(self.root)
        def progress_then_error(root, emit):
            self.assertEqual(root, self.root)
            emit(dict(type='progress', stage='verify', message=message))
            raise first.setup.SetupError(first_error)
        raw = io.BytesIO()
        output = io.TextIOWrapper(raw, encoding='cp1252', newline='\n')
        with mock.patch.object(first.sys, 'stdout', output), \
                mock.patch.object(first, 'bootstrap', side_effect=progress_then_error):
            self.assertEqual(first.main(['--root', str(self.root)]), 1)
        output.flush()
        events = [json.loads(line) for line in raw.getvalue().decode('utf-8').splitlines()]
        self.assertEqual(events, [dict(type='progress', stage='verify', message=message),
            dict(type='error', stage='verify', message=first_error)])

    # Removing receipt bindings or metadata checks would accept a changed file.
    def test_verified_receipt_reused_then_model_mutation_invalidates_it(self):
        self.assertFalse(first.bootstrap(self.root, self.events.append)['cached'])
        self.assertEqual(self.validate.call_count, 2)
        self.assertTrue(first.bootstrap(self.root, self.events.append)['cached'])
        self.assertEqual(self.validate.call_count, 2)
        (self.root / self.model['path']).write_bytes(b'corrupt!')
        with self.assertRaises(first.setup.SetupError):
            first.bootstrap(self.root, self.events.append)
        self.assertFalse(first.cached_ready(self.root))

    # Publishing ready before full verification would leave a usable corrupt payload.
    def test_corrupt_bundle_file_never_publishes_ready(self):
        (self.root / '.runtime/node/node.exe').write_bytes(b'corrupt!')
        with self.assertRaises(first.setup.SetupError):
            first.bootstrap(self.root, self.events.append)
        self.assertFalse((self.root / '.runtime/windows-ready.json').exists())

    def test_external_path_in_bundle_rejected(self):
        self.bundle['files'][0]['path'] = '../outside'
        self.put('windows-bundle.json', json.dumps(self.bundle))
        with self.assertRaises(first.setup.SetupError):
            first.bootstrap(self.root, self.events.append)

    def test_windows_case_aliases_are_rejected_before_reading_files(self):
        self.bundle['files'].append(dict(self.bundle['files'][0], path=self.bundle['files'][0]['path'].upper()))
        self.put('windows-bundle.json', json.dumps(self.bundle))
        # Bind before IO; no host-specific case-sensitive fallback can hide this collision.
        with self.assertRaisesRegex(first.setup.SetupError, 'Duplicate'):
            first.binding(self.root)

    def test_full_check_failure_has_no_ready_receipt(self):
        self.validate.side_effect = first.setup.SetupError('DLL check failed')
        with self.assertRaisesRegex(first.setup.SetupError, 'DLL check failed'):
            first.bootstrap(self.root, self.events.append)
        self.assertFalse((self.root / '.runtime/windows-ready.json').exists())

    def test_progress_finishes_only_after_full_verification(self):
        first.bootstrap(self.root, self.events.append)
        self.assertEqual(self.events[-1]['type'], 'ready')
        self.assertEqual(self.events[-1]['stage'], 'complete')
        self.assertTrue(any(e.get('stage') == 'verify-model' for e in self.events))
        receipt = json.loads((self.root / '.runtime/windows-ready.json').read_text())
        self.assertEqual(receipt['status'], 'complete')
        self.assertEqual(receipt['bundleSha256'], digest((self.root / 'windows-bundle.json').read_bytes()))

    def downloadable(self, bodies):
        calls = {name: 0 for name in bodies}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(handler):
                calls[handler.path] += 1
                good = bodies[handler.path]
                body = b'bad' if handler.path == '/second' and calls[handler.path] == 1 else good
                handler.send_response(200)
                handler.end_headers()
                handler.wfile.write(body)

            def log_message(handler, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        assets = [dict(id=p[1:], path='assets/models/' + p[1:] + '.bin',
                       sizeBytes=len(body), sha256=digest(body),
                       url=f'http://127.0.0.1:{server.server_port}{p}') for p, body in bodies.items()]
        self.put('assets/models/manifest-release-v1.json', json.dumps({
            'schemaVersion': 1, 'models': [self.model] + assets,
            'platforms': {'windows-x64': self.native}}))
        self.bundle['files'] = [{'path': p, 'bytes': len(b), 'sha256': digest(b)}
                                for p, b in self.files.items() if p != 'windows-bundle.json']
        self.put('windows-bundle.json', json.dumps(self.bundle))
        return assets, calls

    # Break: failed download publishes corrupt model, or retry discards a verified model.
    def test_retry_preserves_verified_download_and_reports_actual_bytes(self):
        assets, calls = self.downloadable({'/first': b'one', '/second': b'two'})
        with self.assertRaisesRegex(first.setup.SetupError, 'checksum'):
            first.bootstrap(self.root, self.events.append)
        self.assertEqual((self.root / assets[0]['path']).read_bytes(), b'one')
        self.assertFalse((self.root / assets[1]['path']).exists())
        self.assertFalse((self.root / '.runtime/windows-ready.json').exists())
        first.bootstrap(self.root, self.events.append)
        self.assertEqual(calls, {'/first': 1, '/second': 2})
        self.assertTrue(any(e.get('stage') == 'download' and e.get('bytes') == 3
                            and e.get('total') == 3 for e in self.events))
        self.assertFalse(list((self.root / 'assets/models').glob('*.part')))

    # Break: an interrupted callback leaves a falsely ready state or a temporary model.
    def test_interrupted_download_never_publishes_ready(self):
        assets, calls = self.downloadable({'/first': b'one'})
        def interrupted(event):
            if event.get('stage') == 'download' and event.get('bytes', 0):
                raise InterruptedError('controlled interruption')
        with self.assertRaises(InterruptedError):
            first.bootstrap(self.root, interrupted)
        self.assertFalse((self.root / assets[0]['path']).exists())
        self.assertFalse((self.root / '.runtime/windows-ready.json').exists())
        self.assertFalse(list((self.root / 'assets/models').glob('*.part')))

    def test_node_accepts_python_receipt_then_rejects_mutation(self):
        import os
        import re
        import shutil
        import subprocess
        node = os.environ.get('FS_ELEM_TEST_NODE') or shutil.which('node')
        if not node:
            self.skipTest('Explicit Node test executable unavailable')
        first.bootstrap(self.root, self.events.append)
        checker = (SCRIPTS / 'windows-bundle.mjs').as_uri()
        command = [node, '--input-type=module', '-e',
                   f'import {{requireDesktopReady}} from {json.dumps(checker)};requireDesktopReady(process.argv[1]);',
                   str(self.root)]
        result = subprocess.run(command, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.root / self.model['path']).write_bytes(b'corrupt')
        result = subprocess.run(command, text=True, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        mismatch = re.search(r'fingerprintMismatch=(\{[^\r\n]*\})', result.stderr)
        self.assertIsNotNone(mismatch, result.stderr)
        diagnostic = json.loads(mismatch.group(1))
        self.assertTrue(diagnostic['isFile'])
        self.assertIn('sizeBytes', diagnostic['fields'])
        self.assertEqual(diagnostic['expected']['sizeBytes'], str(self.model['sizeBytes']))
        self.assertEqual(diagnostic['actual']['sizeBytes'], '7')
        self.assertLess(len(mismatch.group(0)), 1500)


if __name__ == '__main__':
    unittest.main()
