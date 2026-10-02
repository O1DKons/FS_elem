import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_pivot_runtime_crossfit import attach_verified_source_indices


class PivotRuntimeMappingTests(unittest.TestCase):
    def test_adds_source_indices_only_after_hash_and_time_provenance_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = b'frame-png-bytes'
            (root / 'frame.png').write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            item = dict(firstContact=11, frames=[
                dict(frameIndex=10, image='frame.png', sourceFrameSha256=digest, candidates=[]),
                dict(frameIndex=11, image='frame.png', sourceFrameSha256=digest, candidates=[]),
            ])
            review = dict(frames=[
                dict(frameIndex=10, time=.2, image='frame.png', sourceFrameSha256=digest),
                dict(frameIndex=11, time=.22, image='frame.png', sourceFrameSha256=digest),
            ])
            mapped, audit = attach_verified_source_indices(
                item, review, {10: (10, .2), 11: (11, .221)}, root, time_tolerance=.002)
            self.assertEqual([x['sourceFrameIndex'] for x in mapped['frames']], [10, 11])
            self.assertEqual(audit['verifiedFrames'], 2)
            self.assertNotIn('sourceFrameIndex', item['frames'][0])

    def test_refuses_source_index_when_frame_image_hash_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'frame.png').write_bytes(b'wrong-image')
            expected = hashlib.sha256(b'expected-image').hexdigest()
            item = dict(firstContact=10, frames=[dict(frameIndex=10, sourceFrameSha256=expected, candidates=[])])
            review = dict(frames=[dict(frameIndex=10, time=.2, image='frame.png', sourceFrameSha256=expected)])
            with self.assertRaises(ValueError):
                attach_verified_source_indices(item, review, {10: (10, .2)}, root)

    def test_refuses_time_mapping_outside_tolerance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = b'image'
            (root / 'frame.png').write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            item = dict(firstContact=10, frames=[dict(frameIndex=10, sourceFrameSha256=digest, candidates=[])])
            review = dict(frames=[dict(frameIndex=10, time=.2, image='frame.png', sourceFrameSha256=digest)])
            with self.assertRaises(ValueError):
                attach_verified_source_indices(item, review, {10: (10, .23)}, root, time_tolerance=.002)


if __name__ == '__main__':
    unittest.main()
