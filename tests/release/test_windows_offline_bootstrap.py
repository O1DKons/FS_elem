"""Installed-bundle behavior with real files and all network/install paths denied."""
import json
from unittest import mock
import unittest
import test_windows_first_run as fixture

first = fixture.first


class OfflineBootstrapTests(unittest.TestCase):
    def setUp(self):
        fixture.FirstRunTests.setUp(self)
        self.model['url'] = 'https://example.invalid/model.bin'
        self.bundle['offline'] = True
        self.rebind()
        def forbidden(*args, **kwargs):
            raise first.setup.SetupError('NETWORK_OR_INSTALL_FORBIDDEN')
        for target, name in [(first.setup, 'urlopen'),
                             (first.setup.subprocess, 'run'),
                             (first.setup.subprocess, 'Popen'),
                             (first.setup, 'ensure_environment')]:
            denial = mock.patch.object(target, name, side_effect=forbidden)
            denial.start();self.addCleanup(denial.stop)

    def rebind(self, include_model=True):
        self.put('assets/models/manifest-release-v1.json', json.dumps({
            'schemaVersion': 1, 'models': [self.model],
            'platforms': {'windows-x64': self.native}}))
        self.bundle['files'] = [dict(path=p, bytes=len(b), sha256=fixture.digest(b))
            for p, b in self.files.items() if p != first.BUNDLE
            and (include_model or p != self.model['path'])]
        self.put(first.BUNDLE, json.dumps(self.bundle))

    def test_present_bundled_url_model_is_verified_without_network_or_install(self):
        self.assertEqual(first.bootstrap(self.root, self.events.append), {'cached': False})
        self.assertEqual((self.root / self.model['path']).read_bytes(), b'verified model')
        state = json.loads((self.root / first.RECEIPT).read_text())
        self.assertEqual(state['status'], 'complete')
        self.assertTrue(first.cached_ready(self.root))
        self.assertEqual(first.bootstrap(self.root, self.events.append), {'cached': True})
        self.assertFalse(any(e.get('stage') == 'download' for e in self.events))

    def test_model_outside_bundle_inventory_is_rejected_even_if_present(self):
        self.rebind(include_model=False)
        with self.assertRaisesRegex(first.setup.SetupError, 'неполон|offline|inventory'):
            first.bootstrap(self.root, self.events.append)
        self.assertFalse((self.root / first.RECEIPT).exists())

    def test_missing_url_model_fails_locally_without_fetch_or_partial_files(self):
        (self.root / self.model['path']).unlink()
        self.rebind(include_model=False)
        with self.assertRaisesRegex(first.setup.SetupError, 'неполон|Переустановите|offline'):
            first.bootstrap(self.root, self.events.append)
        self.assertFalse((self.root / self.model['path']).exists())
        self.assertFalse((self.root / first.RECEIPT).exists())
        self.assertFalse(list((self.root / 'assets/models').glob('*.part')))

    def test_missing_inventory_model_has_readable_reinstall_error(self):
        (self.root / self.model['path']).unlink()
        try:
            first.bootstrap(self.root, self.events.append)
        except (OSError, first.setup.SetupError) as error:
            self.assertIn(self.model['path'], str(error))
            self.assertIn('Переустановите', str(error))
        else:
            self.fail('Missing bundled model was accepted')
        self.assertFalse((self.root / first.RECEIPT).exists())

    def test_corrupt_model_is_preserved_and_cannot_publish_readiness(self):
        corrupted = b'corrupt data!!'
        (self.root / self.model['path']).write_bytes(corrupted)
        with self.assertRaisesRegex(first.setup.SetupError, 'Поврежд|checksum'):
            first.bootstrap(self.root, self.events.append)
        self.assertEqual((self.root / self.model['path']).read_bytes(), corrupted)
        self.assertFalse((self.root / first.RECEIPT).exists())
        self.assertFalse(first.cached_ready(self.root))

    def test_offline_release_025_writes_explicit_receipt_lineage(self):
        self.bundle['packageVersion'] = '0.2.5'
        self.rebind()
        try:
            first.bootstrap(self.root, self.events.append)
        except first.setup.SetupError as error:
            self.fail('Valid offline 0.2.5 bundle rejected: ' + str(error))
        state = json.loads((self.root / first.RECEIPT).read_text())
        self.assertEqual(state.get('packageVersion'), '0.2.5')
        self.assertIs(state.get('offline'), True)

    def test_receipt_without_offline_lineage_cannot_be_reused(self):
        first.bootstrap(self.root, self.events.append)
        state = json.loads((self.root / first.RECEIPT).read_text())
        state.pop('offline', None)
        (self.root / first.RECEIPT).write_text(json.dumps(state))
        self.assertFalse(first.cached_ready(self.root))

    def test_bundle_without_offline_policy_is_not_admitted(self):
        self.bundle['offline'] = False
        self.rebind()
        with self.assertRaisesRegex(first.setup.SetupError, 'offline|Офлайн|офлайн'):
            first.bootstrap(self.root, self.events.append)


if __name__ == '__main__':
    unittest.main()
