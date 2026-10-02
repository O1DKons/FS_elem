import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "work/axel-skate-flight-v1"))
from axel_skate_flight import extract_flight_heading_features


def frame(index, left=None, right=None):
    candidates = []
    for side, heading in (("left", left), ("right", right)):
        candidates.append({
            "side": side,
            "status": "visible" if heading is not None else "uncertain",
            "imageHeadingDegrees": heading,
        })
    return {"frameIndex": index, "candidates": candidates}


class FlightHeadingTests(unittest.TestCase):
    def test_wraps_heading_and_discards_large_steps_without_bridging(self):
        pose = {"frames": [frame(1, 0, 0), frame(2, 170, 0), frame(3, -170, 130),
                            frame(4, None, 20), frame(5, 90, 130), frame(6, 0, 0)]}
        bounds = {"lastContact": {"frameIndex": 1}, "firstContact": {"frameIndex": 6}}
        values, quality = extract_flight_heading_features(pose, bounds)
        self.assertEqual(quality["flightFrames"], 4)
        # Per side: frame coverage, adjacent interval coverage, signed sum, absolute sum.
        self.assertAlmostEqual(values[0], 0.75)
        self.assertAlmostEqual(values[1], 1 / 3)
        self.assertAlmostEqual(values[2], 20.0)
        self.assertAlmostEqual(values[3], 20.0)
        self.assertAlmostEqual(values[4], 1.0)
        self.assertAlmostEqual(values[5], 0.0)
        self.assertEqual(values[6], 0.0)
        self.assertEqual(values[7], 0.0)

    def test_missing_flight_frames_are_not_interpolated(self):
        pose = {"frames": [frame(2, 0, 0), frame(4, 90, 0)]}
        bounds = {"lastContact": {"frameIndex": 1}, "firstContact": {"frameIndex": 5}}
        values, quality = extract_flight_heading_features(pose, bounds)
        self.assertEqual(quality["flightFrames"], 3)
        self.assertAlmostEqual(values[0], 2 / 3)
        self.assertEqual(values[1], 0.0)
        self.assertEqual(values[2], 0.0)


if __name__ == "__main__":
    unittest.main()
