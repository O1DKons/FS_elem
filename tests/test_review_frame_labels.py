import importlib.util
from pathlib import Path
import unittest
import numpy as np

PATH=Path(__file__).resolve().parents[1]/'scripts/review_frame_labels.py'


class ReviewFrameLabelsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('review_frame_labels',PATH)
        cls.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.module)

    def events(self):
        return [dict(id='a',eventClass='axel',lastContactFrame=3,firstContactFrame=6)]

    def labels(self,events=None,complete=True,indices=None,review_sha='a'*64):
        return self.module.review_frame_labels(np.arange(10) if indices is None else indices,
            self.events() if events is None else events,complete,'a'*64,review_sha,10)

    def test_exact_contact_frames_stay_unknown_without_fps_conversion(self):
        np.testing.assert_array_equal(self.labels(),[0,0,0,-1,1,1,-1,0,0,0])

    def test_incomplete_review_does_not_invent_ground(self):
        np.testing.assert_array_equal(self.labels(complete=False),[-1,-1,-1,-1,1,1,-1,-1,-1,-1])

    def test_confirmed_other_jump_has_airborne_labels(self):
        e=self.events();e[0]['eventClass']='other_jump'
        np.testing.assert_array_equal(self.labels(events=e),self.labels())

    def test_uncertain_interval_masks_air_and_ground(self):
        e=self.events()+[dict(id='u',eventClass='uncertain',lastContactFrame=5,firstContactFrame=8)]
        self.assertTrue(np.all(self.labels(events=e)[5:9]==-1))

    def test_source_mismatch_rejected(self):
        with self.assertRaises(ValueError):self.labels(review_sha='b'*64)

    def test_noninteger_outside_or_reversed_contacts_rejected(self):
        for last,first in [(3.0,6),(3,10),(6,3),(True,6)]:
            e=self.events();e[0].update(lastContactFrame=last,firstContactFrame=first)
            with self.subTest(last=last,first=first):
                with self.assertRaises(ValueError):self.labels(events=e)

    def test_overlapping_confirmed_events_and_duplicate_ids_rejected(self):
        for e in [self.events()*2,self.events()+[dict(id='b',eventClass='other_jump',lastContactFrame=5,firstContactFrame=8)]]:
            with self.assertRaises(ValueError):self.labels(events=e)

    def test_sparse_indices_preserved_and_duplicate_indices_rejected(self):
        np.testing.assert_array_equal(self.labels(indices=[0,3,4,6,9]),[0,-1,1,-1,0])
        with self.assertRaises(ValueError):self.labels(indices=[0,3,3,6])


if __name__=='__main__':unittest.main()
