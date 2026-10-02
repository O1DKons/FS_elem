import importlib.util
import math
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('adapter', Path(__file__).resolve().parents[1] / 'scripts/rtmpose_adapter.py')
adapter = importlib.util.module_from_spec(spec)
# Loading is guarded so missing implementation reports a failing assertion.
if Path(spec.origin).exists():
    spec.loader.exec_module(adapter)

class AdapterTests(unittest.TestCase):
    def test_anatomical_mapping_and_source_pixel_normalization(self):
        self.assertTrue(hasattr(adapter, 'normalize_coco'), 'COCO adapter is not implemented')
        pts = [[100, 100] for _ in range(17)]
        pts[13] = [960, 180]  # anatomical left knee remains left even at screen right
        pts[14] = [320, 540]
        out = {p['name']: p for p in adapter.normalize_coco(pts, [.9]*17, 1280, 720)}
        self.assertEqual((out['left_knee']['x'], out['left_knee']['y']), (.75, .25))
        self.assertEqual((out['right_knee']['x'], out['right_knee']['y']), (.25, .75))
        self.assertEqual(len(out), 17)

    def test_invalid_points_omitted_without_clamping_or_confidence_filter(self):
        self.assertTrue(hasattr(adapter, 'normalize_coco'))
        pts = [[100, 100] for _ in range(17)]
        pts[13] = [-1, 0]
        pts[14] = [math.nan, 0]
        scores = [.01]*17
        out = {p['name']: p for p in adapter.normalize_coco(pts, scores, 1280, 720)}
        self.assertNotIn('left_knee', out)
        self.assertNotIn('right_knee', out)
        self.assertEqual(out['left_ankle']['confidence'], .01)
        with self.assertRaises(ValueError):
            adapter.normalize_coco(pts[:12], scores, 1280, 720)

    def test_heatmap_peak_above_one_preserves_joint(self):
        points = [[100, 200] for _ in range(17)]
        scores = [.8]*17
        scores[14] = 1.03
        out = {p['name']: p for p in adapter.normalize_coco(points, scores, 1280, 720, score_kind='heatmap_peak')}
        self.assertEqual(out['right_knee']['confidence'], 1.0)
        self.assertEqual(out['right_knee']['y'], 200/720)
        self.assertEqual(scores[14], 1.03)
        strict = {p['name']: p for p in adapter.normalize_coco(points, scores, 1280, 720)}
        self.assertNotIn('right_knee', strict)

    def test_no_detection_stays_missing_and_largest_box_selection(self):
        self.assertTrue(hasattr(adapter, 'select_bbox'))
        self.assertIsNone(adapter.select_bbox([]))
        self.assertEqual(adapter.select_bbox([[0,0,20,20],[100,100,300,400]]), [100,100,300,400])
        self.assertIsNone(adapter.select_bbox([[3,3,1,1],[0,0,math.nan,1]]))

    def test_evaluation_counts_missing_and_does_not_swap_sides(self):
        self.assertTrue(hasattr(adapter, 'evaluate'))
        refs = [{'id':'x','frameIndex':1,'width':100,'height':100,'joints':{
            'left_knee':{'status':'located','x':.1,'y':.2},
            'right_knee':{'status':'located','x':.9,'y':.2},
            'left_ankle':{'status':'located','x':.1,'y':.9},
            'right_ankle':{'status':'unassessable'}}}]
        prediction = {('x',1):[{'name':'left_knee','x':.9,'y':.2}, {'name':'right_knee','x':.1,'y':.2}]}
        result = adapter.evaluate(refs, {'A':prediction})
        self.assertEqual(result['models']['A']['meanPx'], 80)
        self.assertEqual(result['models']['A']['missing'], 1)
        self.assertEqual(result['located'], 3)
        self.assertEqual(result['unassessable'], 1)

class IntegrationTests(unittest.TestCase):
    def test_join_preserves_baselines_and_rejects_misaligned_source(self):
        self.assertTrue(hasattr(adapter, 'integrate'))
        demo = {'width':100,'height':100,'clips':[{'id':'a','sourceSha256':'hash',
            'frames':[{'frameIndex':4,'time':.08,'pose':{'Lite':[], 'Full':[]},
                       'flags':{'Lite':{}, 'Full':{}},'manual':{'left_knee':'reference'}}]}]}
        proposal = {'sourceSha256':'hash','coordinateSpace':{'width':100,'height':100},
                    'frames':[{'frameIndex':4,'time':.08,'landmarks':[
                        {'name':'left_knee','x':.75,'y':.25,'confidence':.8}]}]}
        out = adapter.integrate(demo, {'a':proposal})
        frame = out['clips'][0]['frames'][0]
        self.assertEqual(frame['pose']['RTMPose'][0]['x'], .75)
        self.assertEqual(frame['manual'], {'left_knee':'reference'})
        self.assertEqual(frame['flags']['RTMPose']['right_knee'], ['missing'])
        self.assertNotIn('RTMPose', demo['clips'][0]['frames'][0]['pose'])
        proposal['frames'][0]['time'] = .09
        with self.assertRaises(ValueError):
            adapter.integrate(demo, {'a':proposal})
        proposal['frames'][0]['time'] = .08
        proposal['sourceSha256'] = 'wrong'
        with self.assertRaises(ValueError):
            adapter.integrate(demo, {'a':proposal})

class ModelIsolationTests(unittest.TestCase):
    def test_new_model_does_not_overwrite_existing_rtmpose(self):
        old=[dict(name='left_knee',x=.1,y=.2,confidence=.8)]
        demo={'width':100,'height':100,'clips':[{'id':'a','sourceSha256':'h','frames':[
            {'frameIndex':1,'time':.02,'pose':{'Full':[],'RTMPose':old},'flags':{'RTMPose':{'left_knee':[]}}}]}]}
        new=[dict(name='left_knee',x=.3,y=.4,confidence=.9)]
        proposals={'a':{'sourceSha256':'h','coordinateSpace':{'width':100,'height':100},'frames':[
            {'frameIndex':1,'time':.02,'landmarks':new}]}}
        result=adapter.integrate(demo,proposals,label='RTMPose-X')
        self.assertEqual(result['clips'][0]['frames'][0]['pose']['RTMPose'],old)
        self.assertEqual(result['clips'][0]['frames'][0]['pose']['RTMPose-X'],new)
        self.assertNotIn('RTMPose-X',demo['clips'][0]['frames'][0]['pose'])

if __name__ == '__main__':
    unittest.main()
