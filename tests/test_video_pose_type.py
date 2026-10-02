import sys, unittest, tempfile, json, inspect, hashlib
from unittest.mock import patch
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from video_pose_type import temporal_features, evaluate, predict_clip

class PoseTypeTests(unittest.TestCase):
    def sample(self):
        p=np.zeros((32,17,2));s=np.ones((32,17))
        for a,b in [(5,6),(11,12),(9,10),(15,16)]:
            p[:,a,0]=-10; p[:,b,0]=10
        p[:,11:13,1]=20
        return p,s
    def test_translation_scale_and_side_swap_invariance(self):
        p,s=self.sample(); f,c=temporal_features(p,s)
        q=p*2+100
        for a,b in [(5,6),(11,12),(9,10),(15,16)]: q[:,[a,b]]=q[:,[b,a]]
        g,d=temporal_features(q,s)
        np.testing.assert_allclose(f,g,atol=1e-10)
        self.assertEqual(f.shape,(40,))
    def test_missing_abstains(self):
        p,s=self.sample(); s[:9,15]=0
        f,c=temporal_features(p,s)
        self.assertIsNone(f)
        self.assertEqual(c[-1],23)
    def test_temporal_signal_changes_fft(self):
        p,s=self.sample();f,_=temporal_features(p,s)
        p[:,9,0]+=5*np.sin(np.arange(32)*2*np.pi*3/32)
        g,_=temporal_features(p,s)
        self.assertFalse(np.allclose(f,g))

    def test_abstentions_count_against_accuracy_and_recall(self):
        m=evaluate(['1A','other'],['abstain','other'])
        self.assertEqual(m['accuracy'],.5)
        self.assertEqual(m['coverage'],.5)
        self.assertEqual(m['axel_recall'],0)

    def test_predict_abstains_on_missing_pose(self):
        from video_type_model import fit_classifier
        model=fit_classifier(np.array([[0.]*40,[1.]*40]),np.array(['1A','other']))
        provenance={'test':True}
        with tempfile.TemporaryDirectory() as tmp:
            artifact=Path(tmp)/'classifier.npz'
            np.savez(artifact,**model,provenance=json.dumps({'provenance':provenance}),
                     feature_code_sha256=hashlib.sha256(inspect.getsource(temporal_features).encode()).hexdigest())
            p,s=self.sample();s[:]=0
            with patch('video_pose_type.extract_pose',return_value=(p,s,{'provenance':provenance,'source_sha256':'test'})):
                result=predict_clip('unused.mp4',artifact)
            self.assertEqual(result['predicted_label'],'abstain')
            self.assertEqual(result['raw_scores'],{})
