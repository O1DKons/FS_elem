import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('rgb_replay',ROOT/'work/person-rgb-flight-v1/replay.py')
replay=importlib.util.module_from_spec(spec); spec.loader.exec_module(replay)


class PersonRgbReplayTests(unittest.TestCase):
    def test_readonly_comparison_preserves_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'verification.json'; p.write_text('{"count": 27}')
            before=p.read_bytes(); replay.compare_existing(p,{'count':27})
            self.assertEqual(p.read_bytes(),before)
            with self.assertRaises(ValueError): replay.compare_existing(p,{'count':28})
            self.assertEqual(p.read_bytes(),before)

    def test_replay_never_creates_missing_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'verification.json'
            with self.assertRaises(ValueError): replay.compare_existing(p,{'count':27})
            self.assertFalse(p.exists())


if __name__=='__main__': unittest.main()
