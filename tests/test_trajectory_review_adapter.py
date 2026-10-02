import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'work/flight-image-trajectory-v1/evaluate.py'
if path.exists():
    spec=importlib.util.spec_from_file_location('trajectory_review_adapter',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
else:module=None


class TrajectoryReviewAdapterTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(module,'Explicit sourceFps -> fps evaluation adapter absent')

    def test_actual_three_public_sources_validate_without_mutating_records(self):
        protocol=json.loads((ROOT/'work/flight-image-trajectory-v1/protocol.json').read_text())
        original=json.loads(json.dumps(protocol['sources']))
        copied=module.scoring_sources(protocol['sources'])
        found=0
        for source in copied:
            if source['videoId'] not in ('comp-20','comp-44','new12'):continue
            events=module.review_events(module.read(ROOT/source['reviewPath']),source)
            self.assertTrue(events)
            self.assertEqual(source['fps'],source['sourceFps']);found+=1
        self.assertEqual(found,3)
        self.assertEqual(protocol['sources'],original)

    def test_personal_pts_fps_is_preserved(self):
        result=module.scoring_sources([dict(videoId='personal',fps=59.81)])[0]
        self.assertEqual(result['fps'],59.81)

    def test_conflicting_metadata_is_rejected(self):
        with self.assertRaises(ValueError):module.scoring_sources([dict(fps=60.,sourceFps=50.)])


if __name__=='__main__':unittest.main()
