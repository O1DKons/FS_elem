import importlib.util
import json
from pathlib import Path
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'work/nominal-personal-pts-addition-v1/training.py'
if path.exists():
    spec=importlib.util.spec_from_file_location('personal_nominal_training',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
else:module=None


class NominalPersonalTrainingTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(module,'Group-excluded nominal data selection missing')

    def test_actual_linked_katya_sources_both_removed(self):
        parent=json.loads((ROOT/'work/personal-rtmw-cascade-transfer-v1/protocol.json').read_text())
        rows=[dict(eventId=e['eventId'],sourceSha256=e['sourceSha256'],truth=e['nominal']) for e in parent['expertEvents']]
        fold=next(f for f in parent['folds'] if 'personal-17' in f['targetVideoIds'])
        chosen=module.training_indices(rows,set(fold['excludedKnownSourceHashes']))
        self.assertEqual(len(chosen),6)
        selected={rows[i]['sourceSha256'] for i in chosen}
        for vid in ('personal-06','personal-17'):
            self.assertNotIn(next(s['sourceSha256'] for s in parent['sources'] if s['videoId']==vid),selected)

    def test_no_nominal_sign_is_used_as_class(self):
        with self.assertRaises(ValueError):module.training_indices([dict(eventId='a',sourceSha256='s',truth='2A<<')],set())

    def test_duplicate_event_cannot_gain_training_weight(self):
        row=dict(eventId='a',sourceSha256='s',truth='1A')
        with self.assertRaises(ValueError):module.training_indices([row,dict(row)],set())


if __name__=='__main__':unittest.main()
