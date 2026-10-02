import importlib.util
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / 'work/full-program-temporal-flight-v1/temporal.py'
module = None
if MODULE_PATH.is_file():
    spec = importlib.util.spec_from_file_location('temporal_flight_features', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


class TemporalFlightFeatureTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'The temporal context feature has not been implemented')

    def test_context_preserves_past_to_future_order_and_coordinate_blocks(self):
        x = np.array([[10, 11], [20, 21], [30, 31], [40, 41], [50, 51]])
        result = module.context_features(x, np.array([0, .12, .24, .36, .48]), np.ones(5, bool))
        np.testing.assert_array_equal(result, [
            [np.nan, np.nan, np.nan, np.nan, 10, 11, 20, 21, 30, 31],
            [np.nan, np.nan, 10, 11, 20, 21, 30, 31, 40, 41],
            [10, 11, 20, 21, 30, 31, 40, 41, 50, 51],
            [20, 21, 30, 31, 40, 41, 50, 51, np.nan, np.nan],
            [30, 31, 40, 41, 50, 51, np.nan, np.nan, np.nan, np.nan],
        ])

    def test_real_pose_width_produces_340_features(self):
        x = np.arange(340, dtype=float).reshape(5, 68)
        result = module.context_features(x, np.array([0, .12, .24, .36, .48]), np.ones(5, bool))
        self.assertEqual(result.shape, (5, 340))
        np.testing.assert_array_equal(result[2], np.arange(340))

    def test_irregular_timestamps_choose_nearest_time_not_neighbor_index(self):
        result = module.context_features(np.arange(1, 8)[:, None],
            np.array([0, .05, .11, .22, .30, .40, .48]), np.ones(7, bool))
        np.testing.assert_array_equal(result[3], [np.nan, 3, 4, 5, 7])

    def test_equidistant_samples_choose_earlier_timestamp(self):
        result = module.context_features(np.array([[1], [2], [3], [4], [5]]),
            np.array([0, .06, .18, .24, .36]), np.ones(5, bool))
        self.assertEqual(result[3, 1], 2)

    def test_close_but_unequal_distances_do_not_count_as_tie(self):
        result = module.context_features(np.array([[1], [2], [3], [4], [5]]),
            np.array([0, .06, .17999999999, .24, .36]), np.ones(5, bool))
        self.assertEqual(result[3, 1], 3)

    def test_targets_outside_recording_stay_missing_without_endpoint_padding(self):
        result = module.context_features(np.array([[1], [2]]), np.array([0, .06]), np.ones(2, bool))
        np.testing.assert_array_equal(result, [
            [np.nan, np.nan, 1, np.nan, np.nan],
            [np.nan, np.nan, 2, np.nan, np.nan],
        ])

    def test_nearest_tolerance_is_inclusive_but_does_not_interpolate(self):
        x = np.array([[1], [2], [3], [4]])
        accepted = module.context_features(x, np.array([0, .055, .20, .30]), np.ones(4, bool))
        rejected = module.context_features(x, np.array([0, .054999, .20, .30]), np.ones(4, bool))
        self.assertEqual(accepted[0, 3], 2)
        self.assertTrue(np.isnan(rejected[0, 3]))

    def test_unusable_center_and_intermediate_rows_block_borrowing(self):
        result = module.context_features(np.arange(1, 6)[:, None],
            np.array([0, .12, .24, .36, .48]), np.array([True, False, True, True, True]))
        np.testing.assert_array_equal(result[0], [np.nan, np.nan, 1, np.nan, np.nan])
        self.assertTrue(np.isnan(result[1]).all())
        np.testing.assert_array_equal(result[2], [np.nan, np.nan, 3, 4, 5])

    def test_missing_time_span_blocks_context_even_when_target_has_a_close_sample(self):
        result = module.context_features(np.arange(1, 6)[:, None],
            np.array([0, .12, .301, .36, .48]), np.ones(5, bool))
        np.testing.assert_array_equal(result[1], [np.nan, 1, 2, np.nan, np.nan])
        self.assertTrue(np.isnan(result[2, 0]))

    def test_exact_maximum_adjacent_gap_remains_connected(self):
        result = module.context_features(np.arange(1, 7)[:, None],
            np.array([0, .06, .12, .30, .36, .48]), np.ones(6, bool))
        self.assertEqual(result[2, 3], 4)
        self.assertEqual(result[2, 4], 5)

    def test_missing_coordinates_are_preserved_and_inputs_are_unchanged(self):
        x = np.array([[1., np.nan], [2., 20.], [np.nan, 30.]])
        times = np.array([0, .12, .24])
        usable = np.array([True, True, True])
        originals = [a.copy() for a in (x, times, usable)]
        result = module.context_features(x, times, usable)
        np.testing.assert_array_equal(result[1], [np.nan, np.nan, 1, np.nan, 2, 20, np.nan, 30, np.nan, np.nan])
        for original, actual in zip(originals, (x, times, usable)):
            np.testing.assert_array_equal(actual, original)
        result[1, 4] = -100
        self.assertEqual(x[1, 0], 2)

    def test_separate_calls_do_not_share_recording_context(self):
        times = np.array([0, .12, .24])
        usable = np.ones(3, bool)
        first = module.context_features(np.array([[1], [2], [3]]), times, usable)
        second = module.context_features(np.array([[101], [102], [103]]), times, usable)
        np.testing.assert_array_equal(first[0], [np.nan, np.nan, 1, 2, 3])
        np.testing.assert_array_equal(second[0], [np.nan, np.nan, 101, 102, 103])

    def test_empty_recording_returns_empty_context_matrix(self):
        result = module.context_features(np.empty((0, 68)), np.empty(0), np.empty(0, bool))
        self.assertEqual(result.shape, (0, 340))

    def test_invalid_shapes_timebase_masks_and_infinity_are_rejected(self):
        cases = [
            (np.ones(3), np.array([0, .12, .24]), np.ones(3, bool)),
            (np.ones((3, 1)), np.array([[0, .12, .24]]), np.ones(3, bool)),
            (np.ones((3, 1)), np.array([0, .12]), np.ones(3, bool)),
            (np.ones((3, 1)), np.array([0, .12, .24]), np.ones(2, bool)),
            (np.ones((3, 1)), np.array([0, .12, .24]), np.ones((3, 1), bool)),
            (np.ones((3, 1)), np.array([0, .12, .24]), np.array([1, 1, 1])),
            (np.ones((3, 1)), np.array([0, .12, .12]), np.ones(3, bool)),
            (np.ones((3, 1)), np.array([0, .24, .12]), np.ones(3, bool)),
            (np.ones((3, 1)), np.array([0, np.nan, .24]), np.ones(3, bool)),
            (np.ones((3, 1)), np.array([0, .12, np.inf]), np.ones(3, bool)),
            (np.array([[1], [np.inf], [3]]), np.array([0, .12, .24]), np.ones(3, bool)),
            (np.array([[1], [-np.inf], [3]]), np.array([0, .12, .24]), np.ones(3, bool)),
        ]
        for x, times, usable in cases:
            with self.subTest(x=x, times=times, usable=usable):
                with self.assertRaises(ValueError):
                    module.context_features(x, times, usable)


if __name__ == '__main__':
    unittest.main()
