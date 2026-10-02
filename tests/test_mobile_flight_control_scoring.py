import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'work/full-program-mobile-flight-control-v1/finish.py'
if path.exists():
    spec=importlib.util.spec_from_file_location('full_mobile_control_scoring',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
else:module=None


class MobileControlScoringTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(module,'Whole-program control evaluator absent')

    def test_all_three_real_reviews_retain_six_axels_and_other_jumps(self):
        parent=json.loads((ROOT/'work/flight-image-trajectory-v1/protocol.json').read_text())
        sources=[dict(s,fps=s['sourceFps']) for s in parent['sources'] if s['videoId'] in ('comp-20','comp-44','new12')]
        result=module.calculate([],dict(sources=sources))
        self.assertEqual(result['totals']['N'],6)
        self.assertEqual(result['totals']['C'],0)
        self.assertEqual(result['totals']['byClass']['1A']['N'],3)
        self.assertEqual(result['totals']['byClass']['2A']['N'],3)

    def test_actual_first_axel_wrong_nominal_remains_detection_but_not_joint_success(self):
        parent=json.loads((ROOT/'work/flight-image-trajectory-v1/protocol.json').read_text())
        source=next(dict(s,fps=s['sourceFps']) for s in parent['sources'] if s['videoId']=='comp-20')
        event=next(e for e in module.review_events(module.read(ROOT/source['reviewPath']),source) if e['eventClass']=='axel')
        row=dict(programId='comp-20',candidateId='test',family='axel',start=event['start'],end=event['end'],nominal='1A' if event['nominal']=='2A' else '2A')
        result=module.calculate([row],dict(sources=[source]))['totals']
        self.assertEqual(result['D'],1);self.assertEqual(result['C'],0)


if __name__=='__main__':unittest.main()
