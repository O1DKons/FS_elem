"""Prior inference must exclude a source even when it was never a training row."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
try:
    from append_source_usage import apply_usage, load_usage_entries
except ImportError:
    apply_usage = load_usage_entries = None
from pose_cache_contract import sha


def source(key, athlete=None, recording=None):
    return dict(sourceSha256=key*64, athleteIds=[athlete or key],
        originalRecordingId=recording or 'recording-'+key, usedInDevelopment=key=='a',
        provenance=[], completeReviews=[], metadataObservations=[{'personalVideoNumber':4}],
        historicalField='preserved')


def entry(key='b'):
    return dict(sourceSha256=key*64, personalVideoId='personal-04',
        status='abstention', typeProposal='other', scope='short_single_element_clip',
        provenance=[dict(path='old/predictions.json',sha256='d'*64),
                    dict(path='old/result.json',sha256='e'*64)])


class PriorUsageTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(apply_usage, 'Source-specific historical usage intake is missing')
        self.sources=[source('a'),source('b'),source('c',athlete='b'),source('f',athlete='f',recording='recording-c')]
        self.partitions={'development':['a'*64], 'confirmation':[],
                         'unassigned_needs_usage_audit':['b'*64,'c'*64,'f'*64]}
        self.evidence=dict(path='work/overlay.json',sha256='a'*64)

    def test_abstention_marks_direct_use_and_transitive_links_but_not_training(self):
        original=copy.deepcopy(self.sources)
        updated,split=apply_usage(self.sources,[],self.partitions,[entry()],self.evidence)
        self.assertEqual(split['development'],sorted([s['sourceSha256'] for s in self.sources]))
        self.assertTrue(updated[1]['usedInDevelopment'])
        self.assertFalse(updated[2]['usedInDevelopment'])
        self.assertFalse(updated[3]['usedInDevelopment'])
        self.assertNotIn('trainingUses',updated[1])
        self.assertEqual(updated[1]['historicalInferenceUses'][0]['typeProposal'],'other')
        self.assertEqual(self.sources,original)
        for old,new in zip(original,updated):
            for key,value in old.items():
                if key not in ['usedInDevelopment','provenance']:
                    self.assertEqual(new[key],value)

    def test_existing_confirmation_cannot_be_repartitioned(self):
        partitions={'development':['a'*64], 'confirmation':['b'*64,'c'*64,'f'*64],
                    'unassigned_needs_usage_audit':[]}
        with self.assertRaises(ValueError):
            apply_usage(self.sources,[],partitions,[entry()],self.evidence)

    def test_unknown_duplicate_already_used_and_wrong_personal_source_rejected(self):
        for rows in [[entry('e')],[entry(),entry()],[entry('a')],[dict(entry(),personalVideoId='personal-43')]]:
            with self.subTest(rows=rows),self.assertRaises(ValueError):
                apply_usage(self.sources,[],self.partitions,rows,self.evidence)

    def test_incomplete_partition_rejected(self):
        partitions=copy.deepcopy(self.partitions);partitions['unassigned_needs_usage_audit'].pop()
        with self.assertRaises(ValueError):
            apply_usage(self.sources,[],partitions,[entry()],self.evidence)

    def test_historical_prediction_does_not_create_labels(self):
        events=[dict(eventId='known',sourceSha256='a'*64,labelScope='candidate_family',
            provenance=[self.evidence],family='axel',nominal='1A')]
        before=copy.deepcopy(events)
        apply_usage(self.sources,events,self.partitions,[entry()],self.evidence)
        self.assertEqual(events,before)


class EvidenceBindingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(load_usage_entries,'Historical prediction evidence loader is missing')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.h='b'*64
        self.result_path='old/result.json';self.prediction_path='old/predictions.json'
        self.result=dict(sourceSha256=self.h,scope='short_single_element_clip',
            typeProposal=dict(video_sha256=self.h,predicted_label='other',scope='short_single_element_clip'),
            modelSha256={'type':'a'*64})
        self.record=dict(id=self.h,sha256=self.h,status='abstention',typeProposal='other',resultPath=self.result_path)
        self.predictions=dict(complete=True,records=[self.record],modelSha256={'type':'a'*64})
        self.overlay=dict(schemaVersion=1,entries=[dict(sourceSha256=self.h,personalVideoId='personal-04',
            registryV5DirectUsedInDevelopment=False,provenance=[])])
        self.write_evidence()

    def write_evidence(self):
        for path,value in [(self.result_path,self.result),(self.prediction_path,self.predictions)]:
            p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))
        self.overlay['entries'][0]['provenance']=[dict(path=p,sha256=sha(self.root/p))
            for p in [self.prediction_path,self.result_path]]

    def test_source_specific_prediction_and_result_bound_by_hash_and_model(self):
        rows,inputs=load_usage_entries(self.overlay,self.root)
        self.assertEqual(rows[0]['sourceSha256'],self.h)
        self.assertEqual(rows[0]['status'],'abstention')
        self.assertEqual(set(inputs),{self.prediction_path,self.result_path})

    def test_evidence_tampering_rejected(self):
        (self.root/self.result_path).write_text('{}')
        with self.assertRaises(ValueError):load_usage_entries(self.overlay,self.root)

    def test_result_source_and_model_disagreement_rejected(self):
        original=copy.deepcopy(self.result)
        for changed in [dict(original,sourceSha256='c'*64),dict(original,modelSha256={'type':'c'*64})]:
            self.result=changed;self.write_evidence()
            with self.assertRaises(ValueError):load_usage_entries(self.overlay,self.root)

    def test_missing_duplicate_source_and_result_path_disagreement_rejected(self):
        for changed in [dict(self.predictions,records=[]),dict(self.predictions,records=[self.record,self.record]),
            dict(self.predictions,records=[dict(self.record,resultPath='unrelated.json')])]:
            self.predictions=changed;self.write_evidence()
            with self.assertRaises(ValueError):load_usage_entries(self.overlay,self.root)

    def test_path_escape_rejected(self):
        self.overlay['entries'][0]['provenance'][0]['path']='../outside.json'
        with self.assertRaises(ValueError):load_usage_entries(self.overlay,self.root)


if __name__=='__main__':unittest.main()
