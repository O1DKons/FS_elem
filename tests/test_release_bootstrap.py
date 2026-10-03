import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
import io
import zipfile
import subprocess
import shutil
import sys
import time
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/setup-release.py'
spec = importlib.util.spec_from_file_location('release_setup', SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.body = b'trusted fixture, never a model'
        self.asset = {'id': 'fixture', 'path': 'assets/models/fixture.bin',
                      'sha256': hashlib.sha256(self.body).hexdigest(),
                      'sizeBytes': len(self.body), 'url': None}

    def test_valid_bundled_asset_is_reused_without_network(self):
        p = self.root / self.asset['path']
        p.parent.mkdir(parents=True)
        p.write_bytes(self.body)
        self.assertEqual(setup.ensure_asset(self.root, self.asset), p)
        self.assertEqual(p.read_bytes(), self.body)

    def test_corrupt_existing_asset_is_never_replaced(self):
        p = self.root / self.asset['path']
        p.parent.mkdir(parents=True)
        p.write_bytes(b'local changes')
        with self.assertRaisesRegex(setup.SetupError, 'checksum'):
            setup.ensure_asset(self.root, self.asset)
        self.assertEqual(p.read_bytes(), b'local changes')

    def test_path_escape_is_rejected_before_download(self):
        with self.assertRaisesRegex(setup.SetupError, 'relative|outside'):
            setup.safe_path(self.root, '../outside.bin')
        with self.assertRaises(setup.SetupError):
            setup.safe_path(self.root, '/tmp/outside.bin')

    def test_symlink_escape_is_rejected(self):
        outside = self.root.parent / (self.root.name + '-outside')
        outside.mkdir()
        self.addCleanup(outside.rmdir)
        (self.root / 'assets').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(setup.SetupError, 'outside'):
            setup.safe_path(self.root, self.asset['path'])
        self.assertEqual(list(outside.iterdir()), [])

    def serve(self, body):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_port}/asset'

    def test_verified_download_is_published_atomically(self):
        asset = {**self.asset, 'url': self.serve(self.body)}
        path = setup.ensure_asset(self.root, asset)
        self.assertEqual(path.read_bytes(), self.body)
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ['fixture.bin'])

    def test_bad_download_leaves_no_asset_or_temporary_file(self):
        asset = {**self.asset, 'url': self.serve(b'x' * len(self.body))}
        with self.assertRaisesRegex(setup.SetupError, 'checksum'):
            setup.ensure_asset(self.root, asset)
        self.assertEqual(list((self.root / 'assets/models').iterdir()), [])

    def test_download_size_limit_aborts_and_cleans(self):
        asset = {**self.asset, 'url': self.serve(self.body + b'oversize')}
        with self.assertRaisesRegex(setup.SetupError, 'size'):
            setup.ensure_asset(self.root, asset)
        self.assertEqual(list((self.root / 'assets/models').iterdir()), [])

    def archive(self, entries):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
            for name, data in entries:
                z.writestr(name, data)
        return output.getvalue()

    def test_official_zip_extracts_only_verified_onnx_without_paths(self):
        data = self.archive([('../../outside.txt', b'never extract'), ('model/end2end.onnx', self.body)])
        asset = {**self.asset, 'url': self.serve(data), 'format': 'zip', 'downloadSizeBytes': len(data)}
        p = setup.ensure_asset(self.root, asset)
        self.assertEqual(p.read_bytes(), self.body)
        self.assertEqual(list(p.parent.iterdir()), [p])
        self.assertFalse((self.root / 'outside.txt').exists())

    def test_zip_with_multiple_onnx_members_is_rejected(self):
        data = self.archive([('a.onnx', self.body), ('b.onnx', self.body)])
        asset = {**self.asset, 'url': self.serve(data), 'format': 'zip', 'downloadSizeBytes': len(data)}
        with self.assertRaisesRegex(setup.SetupError, 'one ONNX'):
            setup.ensure_asset(self.root, asset)
        self.assertEqual(list((self.root / 'assets/models').iterdir()), [])

    def test_missing_bundled_asset_reports_packaging_failure(self):
        with self.assertRaisesRegex(setup.SetupError, 'bundled'):
            setup.ensure_asset(self.root, self.asset)
        self.assertFalse((self.root / self.asset['path']).exists())

    def test_unmanaged_environment_remains_untouched(self):
        p = self.root / '.runtime/venv-science'
        p.mkdir(parents=True)
        sentinel = p / 'keep.txt'
        sentinel.write_text('existing environment')
        with self.assertRaisesRegex(setup.SetupError, 'unmanaged'):
            setup.ensure_environment(self.root, 'science', 'not-an-interpreter', 'services/analysis/science.lock')
        self.assertEqual(sentinel.read_text(), 'existing environment')
        self.assertEqual(list(p.iterdir()), [sentinel])

    def test_manifest_cannot_use_external_model_destination(self):
        p = self.root / 'assets/models/manifest-release-v1.json'
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({'schemaVersion': 1, 'models': [{**self.asset, 'path': '../private'}]}))
        with self.assertRaises(setup.SetupError):
            setup.read_manifest(self.root)


class LauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = os.environ.get('FS_ELEM_TEST_NODE') or shutil.which('node')
        if not cls.node:
            raise unittest.SkipTest('Node required for launcher process fixtures')

    def test_setup_wrapper_preserves_interpreter_exit_status_and_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'fixture-python'
            fake.write_text('#!/usr/bin/env python3\nimport sys,json\nprint(json.dumps(sys.argv[1:]))\nsys.exit(17)\n')
            fake.chmod(0o755)
            result = subprocess.run([self.node, str(SCRIPT.with_suffix('.mjs')), '--install',
                                     '--science-python', str(fake), '--pose-python', 'pose path with spaces'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 17)
            self.assertEqual(json.loads(result.stdout), [str(SCRIPT), '--install', '--science-python', str(fake),
                                                       '--pose-python', 'pose path with spaces'])

    def launch_fixture(self, root):
        for relative in ('scripts', 'services/analysis', 'configs', 'apps/web', '.runtime/venv-science/bin'):
            (root / relative).mkdir(parents=True)
        shutil.copy2(SCRIPT.with_name('start-release.mjs'), root / 'scripts/start-release.mjs')
        shutil.copy2(SCRIPT.with_name('config.mjs'), root / 'scripts/config.mjs')
        (root / '.runtime/venv-science/bin/python').symlink_to(sys.executable)
        (root / 'scripts/setup-release.py').write_text('raise SystemExit(0)\n')
        (root / 'configs/axel-release-v1.json').write_text('{}\n')
        (root / 'services/analysis/server.py').write_text(
            "import json,sys,signal,time\nfrom pathlib import Path\n"
            "Path('api-args.json').write_text(json.dumps(sys.argv[1:]))\n"
            "def stop(*args):\n Path('api-stopped').write_text('yes');sys.exit(0)\n"
            "signal.signal(signal.SIGTERM,stop)\nprint(json.dumps({'port':5175}),flush=True)\n"
            "while True:time.sleep(0.05)\n")
        (root / 'scripts/web-worker.mjs').write_text(
            "import{writeFileSync}from'node:fs';\n"
            "writeFileSync('web-cwd',process.cwd());\n"
            "process.on('SIGTERM',()=>{writeFileSync('web-stopped','yes');process.exit(0)});\n"
            "process.send({ready:true});setInterval(()=>{},1000);\n")
        shutil.copy2(SCRIPT.with_suffix('.mjs'), root / 'scripts/setup-release.mjs')
        lock = root / 'apps/web/pnpm-lock.yaml'
        lock.write_text('inert fixture lock, no packages')
        (root / '.runtime/frontend-install.json').write_text(json.dumps({'lockSha256': hashlib.sha256(lock.read_bytes()).hexdigest(), 'nodeMajor': 24, 'pnpmVersion': '11.19.0'}))
        cli = root / 'apps/web/node_modules/vinext/dist/cli.js'
        cli.parent.mkdir(parents=True)
        cli.write_text('// inert fixture')

    def test_launcher_starts_release_api_and_stops_both_children(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.launch_fixture(root)
            p = subprocess.Popen([self.node, str(root / 'scripts/start-release.mjs')], cwd=root,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                lines = []
                for _ in range(6):
                    line = p.stdout.readline(); lines.append(line)
                    if '/analysis' in line or not line: break
                self.assertIn('http://127.0.0.1:5174/analysis', ''.join(lines))
                p.terminate()
                _, error = p.communicate(timeout=8)
                self.assertEqual(p.returncode, 0, error)
                argv = json.loads((root / 'api-args.json').read_text())
                self.assertEqual(argv, ['--port', '5175', '--config', str(root / 'configs/axel-release-v1.json'),
                                        '--jobs', str(root / '.runtime/jobs'), '--max-wall-seconds', '5400'])
                self.assertTrue((root / 'api-stopped').exists())
                self.assertEqual((root / 'apps/web/web-cwd').read_text(), str(root / 'apps/web'))
                self.assertTrue((root / 'apps/web/web-stopped').exists())
            finally:
                if p.poll() is None:
                    p.kill();p.communicate()

    def test_stale_frontend_lock_is_rejected_before_services_spawn(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.launch_fixture(root)
            (root / 'apps/web/pnpm-lock.yaml').write_text('changed dependency lock')
            p = subprocess.Popen([self.node, str(root / 'scripts/start-release.mjs')], cwd=root,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                out, error = p.communicate(timeout=4)
                self.assertEqual(p.returncode, 1)
                self.assertIn('Frontend does not match', error)
                self.assertFalse((root / 'api-args.json').exists())
            finally:
                if p.poll() is None:
                    p.terminate();p.communicate(timeout=8)



if __name__ == '__main__':
    unittest.main()
