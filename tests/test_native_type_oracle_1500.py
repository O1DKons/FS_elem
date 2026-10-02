import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "work/native-type-1500ms-oracle-v1"))
from run import oracle_window, validate_clip_mapping


class OracleWindowTests(unittest.TestCase):
    def test_window_has_exact_length_and_contains_contact_midpoint(self):
        start, end = oracle_window(175.5, frame_count=350, length=75)
        self.assertEqual(end - start, 75)
        self.assertLessEqual(start, 175.5)
        self.assertGreater(end, 175.5)

    def test_window_clamps_to_clip_bounds_without_shortening(self):
        self.assertEqual(oracle_window(1.0, frame_count=100, length=75), (0, 75))
        self.assertEqual(oracle_window(99.0, frame_count=100, length=75), (25, 100))

    def test_window_rejects_impossible_inputs(self):
        with self.assertRaises(ValueError):
            oracle_window(5.0, frame_count=30, length=75)

    def test_one_frame_tail_shortfall_is_explicit_and_contacts_stay_inside(self):
        self.assertEqual(validate_clip_mapping(399, 1701, 2100, 1867, 1891), -1)
        with self.assertRaises(ValueError):
            validate_clip_mapping(399, 1701, 2100, 2100, 2101)
        with self.assertRaises(ValueError):
            validate_clip_mapping(398, 1701, 2100, 1867, 1891)


if __name__ == "__main__":
    unittest.main()
