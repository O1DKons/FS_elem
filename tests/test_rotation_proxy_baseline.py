import importlib.util
from pathlib import Path
import unittest
import numpy as np

PATH = Path(__file__).resolve().parents[1] / 'scripts/run_rotation_proxy_baseline.py'
spec = importlib.util.spec_from_file_location('proxy', PATH)
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)

class RotationProxyTests(unittest.TestCase):
    def test_folds_keep_all_attempts_of_athlete_together(self):
        groups = ['a', 'a', 'b', 'c']
        for train, test in proxy.athlete_folds(groups):
            self.assertFalse(set(groups[i] for i in train) & set(groups[i] for i in test))
            self.assertEqual(set(train) | set(test), set(range(4)))
        self.assertEqual(len(list(proxy.athlete_folds(groups))), 3)

    def test_preprocessor_uses_training_only_handles_empty_and_constant(self):
        x = np.array([[1., np.nan, 7.], [3., np.nan, 7.]])
        state = proxy.fit_preprocessor(x)
        np.testing.assert_allclose(state['mean'], [2., 0., 7.])
        np.testing.assert_allclose(state['scale'], [1., 1., 1.])
        out = proxy.transform(np.array([[100., np.nan, 7.]]), state)
        np.testing.assert_allclose(out, [[98., 0., 0.]])
        np.testing.assert_allclose(state['mean'], [2., 0., 7.])

    def test_heldout_labels_do_not_change_prediction_or_training(self):
        x = np.array([[0.], [0.1], [1.], [1.1], [0.5]])
        groups = ['a', 'b', 'c', 'd', 'held']
        y = np.array([0, 0, 1, 1, 0])
        first = proxy.evaluate(x, y, groups)
        y[-1] = 1
        second = proxy.evaluate(x, y, groups)
        self.assertEqual(first['predictions'][-1], second['predictions'][-1])
        self.assertEqual(first['folds'][-1]['preprocessor'], second['folds'][-1]['preprocessor'])

    def test_features_ignore_metadata_and_outside_flight(self):
        pose = {'coordinateSpace': {'width': 100, 'height': 100}, 'frames': []}
        bounds = {'lastContact': {'frameIndex': 10, 'time': 1.}, 'firstContact': {'frameIndex': 20, 'time': 1.4}}
        a, _ = proxy.extract_features(pose, bounds)
        pose.update(protocolCode='2A<<', athlete='fake', reviewWindowSeconds=[0,999])
        pose['frames'] = [{'frameIndex': 9, 'landmarks': []}, {'frameIndex': 21, 'landmarks': []}]
        b, _ = proxy.extract_features(pose, bounds)
        np.testing.assert_allclose(a, b, equal_nan=True)
        self.assertAlmostEqual(a[0], .4)
        self.assertTrue(np.isnan(a[1:]).all())

    def test_known_geometry_respects_aspect_ratio_and_confidence(self):
        points = {'left_shoulder': (.2,.2), 'right_shoulder': (.4,.2),
                  'left_hip': (.2,.6), 'right_hip': (.4,.6),
                  'left_ankle': (.2,.8), 'right_ankle': (.4,.8),
                  'left_wrist': (.1,.4), 'right_wrist': (.5,.4)}
        frame = {'frameIndex': 15, 'landmarks': [dict(name=k,x=v[0],y=v[1],confidence=1.) for k,v in points.items()]}
        pose = {'coordinateSpace': {'width':200,'height':100}, 'frames':[frame]}
        bounds = {'lastContact': {'frameIndex':10,'time':1.}, 'firstContact': {'frameIndex':20,'time':1.4}}
        values, quality = proxy.extract_features(pose,bounds)
        np.testing.assert_allclose(values, [.4,1.,0.,1.,0.,1.,0.,2.,0.])
        frame['landmarks'][-1]['confidence'] = .1
        values, _ = proxy.extract_features(pose,bounds)
        self.assertTrue(np.isnan(values[-2:]).all())

    def test_heldout_extreme_values_do_not_change_training_state(self):
        x = np.array([[0.], [0.1], [1.], [1.1], [0.5]])
        groups = ['a', 'b', 'c', 'd', 'held']
        y = np.array([0, 0, 1, 1, 0])
        first = proxy.evaluate(x, y, groups)
        x[-1] = 1e12
        second = proxy.evaluate(x, y, groups)
        self.assertEqual(first['folds'][-1]['preprocessor'], second['folds'][-1]['preprocessor'])

    def test_majority_metrics_do_not_disguise_imbalance(self):
        result = proxy.metrics([0,0,1,1,1], [1]*5)
        self.assertEqual(result['accuracy'], .6)
        self.assertEqual(result['balancedAccuracy'], .5)
        self.assertEqual(result['confusionTrueRowsPredictedColumns'], [[0,2],[0,3]])

if __name__ == '__main__':
    unittest.main()
