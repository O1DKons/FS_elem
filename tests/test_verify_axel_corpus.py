import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import verify_axel_corpus as verifier
from pose_cache_contract import sha


class RegistryChecksumTests(unittest.TestCase):
    def test_changed_event_file_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            events = root / 'events.json'
            events.write_text('{"events":[]}')
            (root / 'SHA256SUMS.json').write_text(json.dumps({'events.json': sha(events)}))
            events.write_text('{"events":["changed"]}')
            with self.assertRaises(ValueError):
                verifier.verify_files(root)

    def test_manifest_cannot_escape_registry_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'SHA256SUMS.json').write_text(json.dumps({'../outside.json': 'a' * 64}))
            with self.assertRaises(ValueError):
                verifier.verify_files(root)


if __name__ == '__main__':
    unittest.main()
