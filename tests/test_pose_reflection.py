import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from pose_reflection import restore_heatmaps

class ReflectionTests(unittest.TestCase):
    def test_reflection_reverses_pixels_and_anatomical_channels(self):
        heatmaps=np.zeros((1,17,4,6),dtype=np.float32)
        heatmaps[0,5,1,4]=.9
        heatmaps[0,6,2,0]=.7
        fixed=restore_heatmaps(heatmaps)
        self.assertAlmostEqual(float(fixed[0,6,1,1]),.9,places=6)
        self.assertAlmostEqual(float(fixed[0,5,2,5]),.7,places=6)
        np.testing.assert_array_equal(restore_heatmaps(fixed),heatmaps)
        self.assertFalse(np.shares_memory(heatmaps,fixed))

if __name__=='__main__':unittest.main()
