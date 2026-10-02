import importlib.util
from pathlib import Path
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'work/flight-image-trajectory-v1/verify.py'
if path.exists():
    spec=importlib.util.spec_from_file_location('flight_roundoff_verifier',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
else:module=None


class FlightProbabilityRoundoffTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(module,'Explicit float64 replay tolerance missing')

    def test_one_ulp_parallel_tree_sum_is_roundoff(self):
        expected=np.array([.05801948302212517,np.nan,.31])
        actual=expected.copy();actual[0]=np.nextafter(expected[0],0.)
        module.compare_probabilities(actual,expected)

    def test_real_prediction_change_is_rejected(self):
        with self.assertRaises(AssertionError):module.compare_probabilities(np.array([.310001]),np.array([.31]))

    def test_nan_coverage_change_is_rejected(self):
        with self.assertRaises(AssertionError):module.compare_probabilities(np.array([.3]),np.array([np.nan]))


if __name__=='__main__':unittest.main()
