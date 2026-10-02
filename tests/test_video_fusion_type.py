import sys, unittest, tempfile, hashlib
from unittest.mock import patch
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from video_fusion_type import pose_descriptor, fit_preprocessing, preprocess, load_features, load_trusted_artifact

class FusionTests(unittest.TestCase):
    def test_body_coordinates_invariant_to_camera_similarity(self):
        p=np.zeros((32,17,2));p[:,5:7,1]=-20;p[:,9,0]=5
        s=np.ones((32,17));f,_=pose_descriptor(p,s)
        rot=np.array([[0.,-1.],[1.,0.]])
        q=p@rot.T*3+100
        g,_=pose_descriptor(q,s)
        np.testing.assert_allclose(f,g,atol=1e-10)
        self.assertEqual(f.shape,(2686,))
    def test_missing_pose_stays_nan_with_zero_masks(self):
        p=np.zeros((32,17,2));s=np.zeros((32,17))
        f,c=pose_descriptor(p,s)
        self.assertTrue(np.isnan(f[:2142]).all())
        self.assertTrue((f[2142:]==0).all())
        self.assertEqual(c,0)
    def test_preprocessing_train_only_and_all_missing_dimension(self):
        train=np.array([[1.,np.nan],[3.,np.nan]])
        params=fit_preprocessing(train)
        out=preprocess(np.array([[100.,np.nan]]),params)
        np.testing.assert_allclose(params['mean'],[2.,0.])
        self.assertEqual(out[0,1],0)
        self.assertEqual(out[0,0],98)

    def test_missing_cache_is_recorded_for_abstention(self):
        x,r=load_features([{'sha256':'missing-test-cache','file':'missing.mp4','truth':'1A','group':'x'}],{}, {})
        self.assertEqual(x.shape,(1,3198))
        self.assertFalse(r[0]['valid'])
        self.assertIsNotNone(r[0]['error'])

    def test_untrusted_artifact_rejected_before_deserialization(self):
        with tempfile.TemporaryDirectory() as tmp:
            trusted=Path(tmp)/'classifier.joblib';trusted.write_bytes(b'expected')
            trusted.with_suffix('.sha256').write_text(hashlib.sha256(b'expected').hexdigest())
            bad=Path(tmp)/'bad.joblib';bad.write_bytes(b'not trusted')
            with patch('video_fusion_type.TRUSTED_ARTIFACT',trusted),patch('joblib.load') as loader:
                with self.assertRaises(ValueError):load_trusted_artifact(bad)
                loader.assert_not_called()
