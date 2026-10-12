"""One migration regression using actual receipt IO; no installs/downloads/inference."""
import copy
import json
import unittest
from unittest import mock
import test_windows_first_run as fixture

first = fixture.first


class OfflineReceiptUpgradeTest(unittest.TestCase):
    setUp = fixture.FirstRunTests.setUp

    def test_v024_ready_is_rejected_and_regenerated_as_exact_offline025(self):
        def forbidden(*args, **kwargs):
            raise AssertionError('No network or dependency installation during upgrade')
        with mock.patch.object(first.setup, 'urlopen', side_effect=forbidden), \
                mock.patch.object(first.setup.subprocess, 'run', side_effect=forbidden), \
                mock.patch.object(first.setup.subprocess, 'Popen', side_effect=forbidden):
            first.bootstrap(self.root, self.events.append)
            receipt_path = self.root / first.RECEIPT
            old = json.loads(receipt_path.read_text())
            # v0.2.4 did not write explicit packageVersion/offline receipt fields.
            old.pop('packageVersion');old.pop('offline')
            old_bundle = copy.deepcopy(self.bundle)
            old_bundle['packageVersion'] = '0.2.4'
            old_bundle.pop('offline')
            old['bundleSha256'] = fixture.digest(json.dumps(old_bundle).encode())
            old_body = (json.dumps(old) + '\n').encode()
            receipt_path.write_bytes(old_body)

            self.assertFalse(first.cached_ready(self.root))
            self.assertEqual(first.bootstrap(self.root, self.events.append), {'cached': False})
            current = json.loads(receipt_path.read_text())
            self.assertNotEqual(receipt_path.read_bytes(), old_body)
            self.assertEqual(current['packageVersion'], '0.2.5')
            self.assertIs(current['offline'], True)
            self.assertEqual(current['status'], 'complete')
            self.assertEqual(current['bundleSha256'], fixture.digest((self.root / first.BUNDLE).read_bytes()))
            expected = {row['path']: row['sha256'] for row in self.bundle['files']}
            self.assertEqual({row['path']: row['sha256'] for row in current['files']}, expected)
            self.assertEqual(len(current['files']), len(expected))
            self.assertTrue(first.cached_ready(self.root))


if __name__ == '__main__':
    unittest.main()
