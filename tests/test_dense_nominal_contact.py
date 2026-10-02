import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
path=ROOT/'work/nominal-dense-flight-refinement-v1/contact.py'
module=None
if path.exists():
    spec=importlib.util.spec_from_file_location('nominal_contact_probe',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class DenseNominalContactTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module,'Dense contact helper missing')
        self.times=np.arange(16,dtype=float)/10

    def test_known_flight_refines_both_original_bounds(self):
        p=np.full(16,.05);p[5:11]=.95
        result=module.refine(self.times,p,np.ones(16,bool),.6,1.)
        self.assertEqual(result,(4,11))

    def test_no_ground_or_flight_evidence_abstains(self):
        for value in (.1,.5,.9):
            self.assertIsNone(module.refine(self.times,np.full(16,value),np.ones(16,bool),.6,1.))

    def test_missing_center_and_large_time_gap_never_bridged(self):
        p=np.full(16,.05);p[5:11]=.95;u=np.ones(16,bool);u[7]=False;p[7]=np.nan
        self.assertIsNone(module.refine(self.times,p,u,.6,1.))
        t=self.times.copy();t[8:] += 1
        self.assertIsNone(module.refine(t,np.nan_to_num(p,nan=.95),np.ones(16,bool),.6,2.))

    def test_inconsistent_or_invalid_observation_inputs_rejected(self):
        p=np.full(16,.5);p[3]=1.1
        with self.assertRaises(ValueError):module.refine(self.times,p,np.ones(16,bool),.6,1.)
        with self.assertRaises(ValueError):module.refine(np.zeros(16),np.full(16,.5),np.ones(16,bool),.6,1.)

    def test_complete_review_labels_all_jumps_and_grounded_context(self):
        events=[dict(id='a',eventClass='axel',start=.3,end=.6),dict(id='b',eventClass='other_jump',start=.9,end=1.2)]
        y=module.reviewed_labels(self.times,events,True)
        np.testing.assert_array_equal(y[[4,5,10,11]],1)
        np.testing.assert_array_equal(y[[0,1,2,7,8,13,14,15]],0)
        np.testing.assert_array_equal(y[[3,6,9,12]],-1)

    def test_partial_review_never_invents_grounded_context(self):
        events=[dict(id='a',eventClass='axel',start=.3,end=.6)]
        y=module.reviewed_labels(self.times,events,False)
        self.assertEqual(int((y==0).sum()),0)
        self.assertEqual(int((y==1).sum()),2)

    def test_uncertain_interval_remains_unknown(self):
        y=module.reviewed_labels(self.times,[dict(id='u',eventClass='uncertain',start=.3,end=.6)],True)
        np.testing.assert_array_equal(y[3:7],-1)

    def test_duplicate_or_overlapping_confirmed_events_rejected(self):
        a=dict(id='a',eventClass='axel',start=.3,end=.6)
        for events in ([a,dict(a)],[a,dict(id='b',eventClass='other_jump',start=.4,end=.7)]):
            with self.assertRaises(ValueError):module.reviewed_labels(self.times,events,True)

    def dense_example(self):
        times=[0.,.05,.15,.3];source=dict(timestampsSeconds=times,width=200,height=200,fps=20.)
        frames={}
        for i,t in enumerate(times):
            p=np.full((23,2),50.);p[5]=[40,20];p[6]=[60,20];p[11]=[40,60];p[12]=[60,60]
            p[9]=[40+40*t*t,40]
            frames[str(i)]=dict(time=t,points=p.tolist(),scores=np.ones(23).tolist())
        return dict(frames=frames),source

    def test_dense_features_use_actual_pts_derivative(self):
        document,source=self.dense_example();ix,x,u,t=module.dense_arrays(document,source)
        self.assertTrue(u.all());self.assertEqual(x.shape,(4,68))
        self.assertAlmostEqual(x[1,34+18],.1)
        self.assertAlmostEqual(x[2,34+18],.3)

    def test_out_of_image_shoulder_is_missing_not_clamped(self):
        document,source=self.dense_example();document['frames']['1']['points'][5]=[-10,20]
        ix,x,u,t=module.dense_arrays(document,source)
        self.assertFalse(u[1]);self.assertTrue(np.isnan(x[1]).all())

    def test_changed_dense_pts_or_missing_source_frame_rejected(self):
        document,source=self.dense_example();document['frames']['1']['time']+=.01
        with self.assertRaises(ValueError):module.dense_arrays(document,source)
        document,source=self.dense_example();del document['frames']['1']
        with self.assertRaises(ValueError):module.dense_arrays(document,source)


if __name__=='__main__':unittest.main()
