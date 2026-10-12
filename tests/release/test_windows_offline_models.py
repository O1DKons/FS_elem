import hashlib
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('offline_assembler', ROOT / 'scripts/prepare-windows-bundle.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class OfflineModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.body = b'public model fixture'
        self.asset = {'id': 'yolox', 'path': 'assets/models/yolox.onnx',
                      'sizeBytes': len(self.body), 'sha256': hashlib.sha256(self.body).hexdigest(),
                      'url': 'https://download.openmmlab.com/fixture.zip', 'format': 'zip',
                      'licenseEvidence': 'docs/release/third-party.md',
                      'checkpointLicenseStatus': 'not explicitly verified'}

    def method(self, name):
        value = getattr(MODULE, name, None)
        self.assertTrue(callable(value), name + ' offline behavior missing')
        return value

    def archive(self, members):
        path = self.root / 'model.zip'
        with zipfile.ZipFile(path, 'w') as stream:
            for name, body in members:
                stream.writestr(name, body)
        return path

    def test_exact_single_member_bytes_are_extracted_and_recorded(self):
        archive = self.archive([('sdk/end2end.onnx', self.body), ('ignored.txt', b'not a model')])
        target = self.root / 'yolox.onnx'
        member = self.method('extract_model')(archive, self.asset, target)
        self.assertEqual(member, 'sdk/end2end.onnx')
        self.assertEqual(target.read_bytes(), b'public model fixture')
        self.assertFalse((self.root / 'ignored.txt').exists())

    def test_ambiguous_archive_cannot_publish_any_model(self):
        archive = self.archive([('one.onnx', self.body), ('two.onnx', self.body)])
        target = self.root / 'yolox.onnx'
        with self.assertRaises(ValueError):
            self.method('extract_model')(archive, self.asset, target)
        self.assertFalse(target.exists())

    def test_traversal_member_never_escapes_staging(self):
        archive = self.archive([('../escape.onnx', self.body)])
        target = self.root / 'yolox.onnx'
        with self.assertRaises(ValueError):
            self.method('extract_model')(archive, self.asset, target)
        self.assertFalse(target.exists())
        self.assertFalse((self.root.parent / 'escape.onnx').exists())

    def test_same_size_corrupt_member_is_rejected_without_final_file(self):
        archive = self.archive([('model.onnx', b'x' * len(self.body))])
        target = self.root / 'yolox.onnx'
        with self.assertRaises(ValueError):
            self.method('extract_model')(archive, self.asset, target)
        self.assertFalse(target.exists())

    def staged(self):
        models = self.root / 'models'
        assets = [self.asset, dict(self.asset, id='rtmw', path='assets/models/rtmw.onnx')]
        records = []
        for asset in assets:
            path = models / asset['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.body)
            records.append(dict(asset, archiveMember='sdk/model.onnx', archiveBytes=100,
                                archiveSha256='a' * 64))
        (models / 'offline-models.json').write_text(json.dumps({'schemaVersion': 1, 'models': records}))
        app = self.root / 'app'
        evidence = app / 'docs/release/third-party.md'
        evidence.parent.mkdir(parents=True)
        evidence.write_text('Checkpoint terms not verified; preserve qualification.')
        return {'models': assets}, models, app

    def test_both_upstream_models_are_in_payload_inventory_without_network(self):
        manifest, models, app = self.staged()
        self.method('stage_offline_models')(manifest, models, app)
        files = {x['path']: x for x in MODULE.inventory(app)}
        for name in ('yolox', 'rtmw'):
            self.assertEqual((app / ('assets/models/' + name + '.onnx')).read_bytes(), self.body)
            self.assertEqual(files['assets/models/' + name + '.onnx']['bytes'], len(self.body))

    def test_corrupt_second_model_fails_before_copying_first(self):
        manifest, models, app = self.staged()
        (models / 'assets/models/rtmw.onnx').write_bytes(b'x' * len(self.body))
        with self.assertRaises(ValueError):
            self.method('stage_offline_models')(manifest, models, app)
        self.assertFalse((app / 'assets/models/yolox.onnx').exists())

    def test_missing_license_evidence_cannot_produce_offline_payload(self):
        manifest, models, app = self.staged()
        (app / 'docs/release/third-party.md').unlink()
        with self.assertRaises(ValueError):
            self.method('stage_offline_models')(manifest, models, app)
        self.assertFalse((app / 'assets/models/yolox.onnx').exists())

    def test_member_receipt_cannot_substitute_a_different_model(self):
        manifest, models, app = self.staged()
        receipt = json.loads((models / 'offline-models.json').read_text())
        receipt['models'][0]['sha256'] = '0' * 64
        (models / 'offline-models.json').write_text(json.dumps(receipt))
        with self.assertRaises(ValueError):
            self.method('stage_offline_models')(manifest, models, app)
        self.assertFalse((app / 'assets/models/yolox.onnx').exists())

    def test_build_host_acquisition_records_exact_archive_and_member_without_live_network(self):
        archive = self.archive([('official/end2end.onnx', self.body)])
        raw = archive.read_bytes()
        source = self.root / 'source'
        folder = source / 'assets/models'
        folder.mkdir(parents=True)
        assets = [dict(self.asset, downloadSizeBytes=len(raw), downloadSha256=None),
                  dict(self.asset, id='rtmw', path='assets/models/rtmw.onnx', downloadSizeBytes=len(raw), downloadSha256=None)]
        (folder / 'manifest-release-v1.json').write_text(json.dumps({'models': assets}))
        class Response(io.BytesIO):
            def geturl(self):
                return 'https://download.openmmlab.com/fixture.zip'
        with mock.patch.object(MODULE.urllib.request, 'urlopen', side_effect=lambda *a, **k: Response(raw)):
            MODULE.acquire_models(source, self.root / 'downloaded')
        receipt = json.loads((self.root / 'downloaded/offline-models.json').read_text())
        self.assertEqual(len(receipt['models']), 2)
        self.assertEqual(receipt['models'][0]['archiveMember'], 'official/end2end.onnx')
        self.assertEqual(receipt['models'][0]['archiveSha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual((self.root / 'downloaded/assets/models/rtmw.onnx').read_bytes(), b'public model fixture')
        self.assertFalse(list((self.root / 'downloaded').glob('*.part')))

    def test_short_download_cannot_publish_complete_receipt(self):
        archive = self.archive([('model.onnx', self.body)])
        raw = archive.read_bytes()
        source = self.root / 'source'
        folder = source / 'assets/models'
        folder.mkdir(parents=True)
        assets = [dict(self.asset, downloadSizeBytes=len(raw) + 1),
                  dict(self.asset, id='rtmw', path='assets/models/rtmw.onnx', downloadSizeBytes=len(raw) + 1)]
        (folder / 'manifest-release-v1.json').write_text(json.dumps({'models': assets}))
        class Response(io.BytesIO):
            def geturl(self):
                return 'https://download.openmmlab.com/fixture.zip'
        with mock.patch.object(MODULE.urllib.request, 'urlopen', side_effect=lambda *a, **k: Response(raw)):
            with self.assertRaises(ValueError):
                MODULE.acquire_models(source, self.root / 'downloaded')
        self.assertFalse((self.root / 'downloaded/offline-models.json').exists())
        self.assertFalse((self.root / 'downloaded/assets/models/yolox.onnx').exists())

    def test_symlink_app_destination_cannot_receive_offline_models(self):
        manifest, models, app = self.staged()
        alias = self.root / 'app-alias'
        alias.symlink_to(app, target_is_directory=True)
        with self.assertRaises(ValueError):
            MODULE.stage_offline_models(manifest, models, alias)
        self.assertFalse((app / 'assets/models/yolox.onnx').exists())

    def test_declared_exact_member_cannot_be_renamed_with_identical_contents(self):
        archive = self.archive([('renamed.onnx', self.body)])
        target = self.root / 'yolox.onnx'
        with self.assertRaises(ValueError):
            MODULE.extract_model(archive, dict(self.asset, archiveMember='official.onnx'), target)
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
