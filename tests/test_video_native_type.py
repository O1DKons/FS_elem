import sys,unittest,tempfile
from unittest.mock import patch
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from video_native_type import native_features,FREQUENCIES,PAIR_NAMES,train,evaluate
from run_video_native_challenge import assert_disjoint

class NativeTemporalTests(unittest.TestCase):
    def sample(self,fps,seconds=4,frequency=3):
        t=np.arange(round(fps*seconds))/fps
        p=np.zeros((len(t),17,2));s=np.ones((len(t),17))
        width=20*(1+.3*np.sin(2*np.pi*frequency*t))
        for a,b in [(5,6),(11,12),(9,10),(15,16)]:
            p[:,a,0]=width/2;p[:,b,0]=-width/2
        p[:,11:13,1]=20;p[:,9:11,1]=10;p[:,15:17,1]=40
        return p,s
    def test_physical_frequency_stable_at_25_and_50_fps(self):
        peaks=[];power=[]
        for fps in [25,50]:
            p,s=self.sample(fps,seconds=1);f,details=native_features(p,s,fps)
            self.assertEqual(f.shape,(208,))
            row=f.reshape(8,26)[0]
            peaks.append(float(FREQUENCIES[np.argmax(row[2:])]))
            power.append(row[2:])
        self.assertEqual(peaks,[3.,3.])
        np.testing.assert_allclose(power[0],power[1],rtol=.04,atol=.0001)
    def test_reflection_flips_signed_mean_not_spectrum(self):
        p,s=self.sample(25);f,_=native_features(p,s,25)
        q=p.copy();q[:,:,0]*=-1;g,_=native_features(q,s,25)
        f=f.reshape(8,26);g=g.reshape(8,26)
        np.testing.assert_allclose(f[:4,0],-g[:4,0])
        np.testing.assert_allclose(f[:4,1:],g[:4,1:],atol=1e-12)
        np.testing.assert_allclose(f[4:],g[4:],atol=1e-12)
    def test_low_confidence_and_too_few_distinct_frames_abstain(self):
        p,s=self.sample(25);s[:26,9]=0
        f,d=native_features(p,s,25)
        self.assertIsNone(f);self.assertEqual(d['reason'],'insufficient_confident_samples')
        p,s=self.sample(25);indices=np.zeros(len(p),dtype=int)
        f,d=native_features(p,s,25,indices)
        self.assertIsNone(f);self.assertEqual(d['reason'],'insufficient_distinct_frames')
    def test_seven_valid_of_nine_still_abstains(self):
        p,s=self.sample(25);p=p[:9];s=s[:9];s[:2,15]=0
        f,d=native_features(p,s,25)
        self.assertIsNone(f)
    def test_sub_nyquist_abstains(self):
        p,s=self.sample(20);f,d=native_features(p,s,20)
        self.assertIsNone(f);self.assertEqual(d['reason'],'frequency_grid_above_nyquist')

    def test_incomplete_native_cache_prevents_any_model_fit(self):
        items=[{'sha256':str(i)} for i in range(190)]
        with tempfile.TemporaryDirectory() as tmp:
            with patch('video_native_type.pilot_items',return_value=(items,{})),patch('video_native_type.fit_classifier') as fit:
                with self.assertRaisesRegex(ValueError,'incomplete: 0/190'):
                    train('unused-manifest',cache=Path(tmp))
                fit.assert_not_called()

    def test_repeated_25fps_frames_at_50fps_preserve_physical_peak(self):
        p,s=self.sample(25,seconds=1)
        original,_=native_features(p,s,25)
        repeated,_=native_features(np.repeat(p,2,axis=0),np.repeat(s,2,axis=0),50)
        a=original.reshape(8,26)[0,2:];b=repeated.reshape(8,26)[0,2:]
        self.assertEqual(float(FREQUENCIES[np.argmax(a)]),3.)
        self.assertEqual(float(FREQUENCIES[np.argmax(b)]),3.)

    def test_abstentions_are_not_predicted_axels(self):
        result=evaluate(['1A','other'],['abstain','abstain'])
        self.assertEqual(result['accuracy'],0)
        self.assertEqual(result['coverage'],0)
        self.assertEqual(result['axel_recall'],0)
        self.assertIsNone(result['axel_precision'])
    def test_challenge_rejects_training_source_sha(self):
        with self.assertRaises(ValueError):assert_disjoint([{'sha256':'same'}],{'same'})
        assert_disjoint([{'sha256':'new'}],{'same'})
