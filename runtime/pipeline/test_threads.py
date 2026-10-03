"""Session policy and provenance tests; no ORT/NN or video is loaded."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import pose_models

class ThreadPolicyTests(unittest.TestCase):
    def setUp(self):
        for name in ('ort_threads','runtime_sessions','validate_runtime_sessions'):
            self.assertTrue(hasattr(pose_models,name),'Recipe-bound runtime session verification is missing: '+name)

    def test_missing_policy_retains_legacy_fallback(self):
        self.assertEqual(pose_models.ort_threads({}),dict(intraOpNumThreads=2,interOpNumThreads=1))

    def test_explicit_two_and_four_supported(self):
        for n in (2,4):
            p=dict(intraOpNumThreads=n,interOpNumThreads=1)
            self.assertEqual(pose_models.ort_threads({'ortThreads':p}),p)

    def test_invalid_policy_fails_before_constructor(self):
        for p in (None,{},dict(intraOpNumThreads=8,interOpNumThreads=1),
                  dict(intraOpNumThreads=4,interOpNumThreads=True),
                  dict(intraOpNumThreads=4,interOpNumThreads=2),
                  dict(intraOpNumThreads=4,interOpNumThreads=1,provider='CoreML')):
            with self.assertRaises(ValueError):pose_models.ort_threads({'ortThreads':p})

    def build(self,n=4,effective=None,providers=None,fail=False):
        options=lambda:SimpleNamespace(intra_op_num_threads=0,inter_op_num_threads=0)
        def original(*args,**kw):
            if fail:raise RuntimeError('synthetic constructor failure')
            o=kw['sess_options']
            return SimpleNamespace(get_session_options=lambda:effective or o,
                                   get_providers=lambda:providers or ['CPUExecutionProvider'])
        ort=SimpleNamespace(SessionOptions=options,InferenceSession=original)
        def model(*args,**kw):return SimpleNamespace(session=ort.InferenceSession(args[0]))
        cv=SimpleNamespace(setNumThreads=lambda n:None)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'det').touch();(p/'pose').touch()
            recipe=dict(checkpoints=dict(detector=dict(path='det'),pose=dict(path='pose')),
                        ortThreads=dict(intraOpNumThreads=n,interOpNumThreads=1))
            with patch.dict('sys.modules',{'cv2':cv,'onnxruntime':ort,'rtmlib':SimpleNamespace(YOLOX=model,RTMPose=model)}):
                try:
                    d,s=pose_models.models(p/'config.json',recipe)
                    records=pose_models.runtime_sessions(d,s)
                    return records,recipe
                finally:self.assertIs(ort.InferenceSession,original)

    def test_both_sparse_and_dense_share_verified_detector_pose_factory(self):
        for stage in ('sparse','dense'):
            records,recipe=self.build()
            self.assertEqual([r['role'] for r in records],['detector','pose'])
            self.assertTrue(all(r['intraOpNumThreads']==4 and r['interOpNumThreads']==1 for r in records))
            pose_models.validate_runtime_sessions(records,recipe)

    def test_explicit_fallback_constructor(self):
        records,recipe=self.build(n=2)
        self.assertTrue(all(r['intraOpNumThreads']==2 for r in records))
        pose_models.validate_runtime_sessions(records,recipe)

    def test_reported_options_or_provider_mismatch_rejected(self):
        with self.assertRaises(ValueError):self.build(effective=SimpleNamespace(intra_op_num_threads=2,inter_op_num_threads=1))
        with self.assertRaises(ValueError):self.build(providers=['CoreMLExecutionProvider','CPUExecutionProvider'])

    def test_factory_restored_on_constructor_failure(self):
        with self.assertRaises(RuntimeError):self.build(fail=True)

    def test_saved_evidence_cannot_claim_wrong_threads_or_missing_role(self):
        records,recipe=self.build()
        records[0]['intraOpNumThreads']=2
        with self.assertRaises(ValueError):pose_models.validate_runtime_sessions(records,recipe)
        with self.assertRaises(ValueError):pose_models.validate_runtime_sessions([],recipe)
        pose_models.validate_runtime_sessions([],recipe,required=False)

if __name__=='__main__':unittest.main()
