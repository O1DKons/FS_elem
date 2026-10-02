"""Whole-video accounting, including failed sources, duplicates and domain gates."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
try:
    from evaluate_axel_pipeline import evaluate
except ImportError:
    evaluate = None
try:
    from evaluate_axel_pipeline import review_playback_audit
except ImportError:
    review_playback_audit = None
try:
    from evaluate_axel_pipeline import normalize_legacy_axel_codes
except ImportError:
    normalize_legacy_axel_codes = None


def event(identifier='a', start=1.0, end=1.4, nominal='1A', kind='axel'):
    return dict(id=identifier,start=start,end=end,nominal=nominal,eventClass=kind,
                boundaryStatus='expert_playback_evaluation')


def source(key='a', domain='personal', events=None, status='completed'):
    return dict(id='video-'+key,sourceSha256=key*64,domain=domain,durationSeconds=10.0,
                coverageReviewed=True,inferenceScope='whole_source',inferenceStatus=status,
                events=[event()] if events is None else events)


def prediction(identifier='p', key='a', start=1.0, end=1.4, nominal='1A', family='axel'):
    return dict(id=identifier,sourceSha256=key*64,start=start,end=end,nominal=nominal,family=family)


class WholeVideoScoringTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(evaluate,'Unified whole-source evaluator is not implemented')

    def test_failed_source_and_empty_output_are_misses_not_removed_denominators(self):
        result=evaluate([source('a'),source('b',status='failed')],[prediction()])
        metrics=result['domains']['personal']
        self.assertEqual((metrics['N'],metrics['D'],metrics['C'],metrics['FP']),(2,1,1,0))
        self.assertEqual(metrics['jointRecall'],.5)
        self.assertEqual(result['failedSourceIds'],['video-b'])
        self.assertEqual(result['sources'][1]['missedAxelIds'],['a'])

    def test_wrong_nominal_and_nominal_abstention_still_detect_but_fail_joint_success(self):
        rows=[event('one',1,1.4,'1A'),event('two',3,3.4,'2A')]
        result=evaluate([source(events=rows)],
            [prediction(nominal='2A'),prediction('q',start=3,end=3.4,nominal=None)])
        metrics=result['domains']['personal']
        self.assertEqual((metrics['N'],metrics['D'],metrics['C']),(2,2,0))
        self.assertEqual(metrics['nominalAbstentionsOnDetectedAxels'],1)
        self.assertEqual(metrics['byClass']['1A']['C'],0)
        self.assertEqual(metrics['byClass']['2A']['C'],0)

    def test_duplicate_other_jump_and_background_calls_are_false_axels(self):
        events=[event(),event('lutz',3,3.4,None,'other_jump')]
        calls=[prediction(),prediction('duplicate'),prediction('lutz',start=3,end=3.4),
               prediction('background',start=6,end=6.4)]
        metrics=evaluate([source(events=events)],calls)['domains']['personal']
        self.assertEqual((metrics['N'],metrics['D'],metrics['C'],metrics['FP']),(1,1,1,3))
        self.assertEqual(metrics['precision'],.25)
        self.assertEqual(metrics['falseCallsPerMinute'],18.0)

    def test_uncertain_exemption_cannot_hide_duplicate_known_event(self):
        events=[event(),event('uncertain',1,1.4,None,'uncertain')]
        result=evaluate([source(events=events)],[prediction(),prediction('duplicate')])
        self.assertEqual(result['domains']['personal']['FP'],1)
        self.assertEqual(result['domains']['personal']['unresolvedCalls'],0)

    def test_unrelated_uncertain_call_remains_unresolved_not_negative_truth(self):
        events=[event(),event('uncertain',3,3.4,None,'uncertain')]
        result=evaluate([source(events=events)],[prediction(),prediction('uncertain',start=3,end=3.4)])
        metrics=result['domains']['personal']
        self.assertEqual((metrics['N'],metrics['D'],metrics['FP'],metrics['unresolvedCalls']),(1,1,0,1))
        self.assertEqual(metrics['precision'],1.0)

    def test_matching_uses_intervals_without_optimizing_nominal_and_is_input_order_invariant(self):
        calls=[prediction('first',nominal='2A'),prediction('second',nominal='1A')]
        first=evaluate([source()],calls)
        second=evaluate([source()],calls[::-1])
        self.assertEqual(first,second)
        self.assertEqual(first['domains']['personal']['C'],0)
        self.assertEqual(first['domains']['personal']['FP'],1)

    def test_broad_window_containing_axel_midpoint_is_not_automatically_a_hit(self):
        result=evaluate([source()],[prediction(start=0,end=10)])
        self.assertEqual((result['domains']['personal']['D'],result['domains']['personal']['FP']),(0,1))

    def test_matching_reassigns_proposals_to_find_maximum_cardinality(self):
        events=[event('a',1,1.4,'1A'),event('b',1.5,1.9,'2A')]
        calls=[prediction('wide',start=1,end=1.9,nominal='2A'),
               prediction('narrow',start=1.01,end=1.41,nominal='1A')]
        metrics=evaluate([source(events=events)],calls)['domains']['personal']
        self.assertEqual((metrics['N'],metrics['D'],metrics['C'],metrics['FP']),(2,2,2,0))

    def test_non_axel_outputs_do_not_hide_a_missed_axel_or_count_as_false_axels(self):
        result=evaluate([source()],[prediction(family='other',nominal=None)])
        self.assertEqual((result['domains']['personal']['N'],result['domains']['personal']['D'],result['domains']['personal']['FP']),(1,0,0))

    def test_no_axel_source_penalizes_false_calls_and_zero_denominators_are_null(self):
        result=evaluate([source(events=[])],[prediction()])
        metrics=result['domains']['personal']
        self.assertEqual((metrics['N'],metrics['D'],metrics['FP']),(0,0,1))
        self.assertIsNone(metrics['jointRecall'])
        self.assertIsNone(metrics['conditionalNominalAccuracy'])
        self.assertEqual(metrics['precision'],0.0)

    def test_domains_do_not_pool_away_poor_personal_accuracy(self):
        full=source('a','full_program',[event('one',1,1.4,'1A'),event('two',3,3.4,'2A')])
        private=source('b','personal',[event('one',1,1.4,'1A'),event('two',3,3.4,'2A')])
        calls=[prediction(),prediction('double',start=3,end=3.4,nominal='2A')]
        result=evaluate([full,private],calls)
        self.assertEqual(result['domains']['full_program']['jointRecall'],1.0)
        self.assertEqual(result['domains']['personal']['jointRecall'],0.0)
        self.assertTrue(result['numericalGates']['full_program']['passed'])
        self.assertFalse(result['numericalGates']['personal']['passed'])
        self.assertFalse(result['allDomainsNumericalGatePassed'])
        self.assertFalse(result['goal70Verified'])

    def test_constant_majority_class_cannot_pass_per_class_gate(self):
        events=[event('single',1,1.4,'1A')]+[event(str(i),2+i*.6,2.4+i*.6,'2A') for i in range(10)]
        calls=[prediction(str(i),start=e['start'],end=e['end'],nominal='2A') for i,e in enumerate(events)]
        result=evaluate([source(events=events)],calls)
        self.assertGreater(result['domains']['personal']['jointRecall'],.7)
        self.assertFalse(result['numericalGates']['personal']['passed'])

    def test_validation_rejects_partial_or_candidate_only_review_and_quarantined_boundaries(self):
        for key,value in [('coverageReviewed',False),('inferenceScope','candidate_windows')]:
            row={**source(),key:value}
            with self.subTest(key=key),self.assertRaises(ValueError):evaluate([row],[])
        row=source();row['events'][0]['boundaryStatus']='navigation_anchors_physical_contacts_unverified'
        with self.assertRaises(ValueError):evaluate([row],[])

    def test_invalid_or_duplicate_sources_events_and_proposals_cannot_be_silently_dropped(self):
        cases=[([source(),source()],[]),([source()],[prediction(key='b')]),
               ([source()],[prediction(),prediction()]),([source(events=[event(),event()])],[]),
               ([source()],[prediction(start=True)]),([source()],[prediction(end=float('nan'))]),
               ([source()],[prediction(end=11)]),([source(events=[event(nominal='3A')])],[]),
               ([source('a',status='failed')],[prediction()])]
        for sources,calls in cases:
            with self.subTest(sources=sources,calls=calls),self.assertRaises(ValueError):evaluate(sources,calls)

    def test_perfect_development_metrics_are_not_independent_confirmation_or_physical_rotation(self):
        row=source(events=[event('one',1,1.4,'1A'),event('two',3,3.4,'2A')])
        calls=[prediction(),prediction('two',start=3,end=3.4,nominal='2A')]
        before=copy.deepcopy((row,calls))
        result=evaluate([row],calls)
        self.assertTrue(result['allDomainsNumericalGatePassed'])
        self.assertFalse(result['goal70Verified'])
        self.assertFalse(result['independentConfirmationVerified'])
        self.assertIsNone(result['underrotation'])
        self.assertIsNone(result['coldRuntimeSeconds'])
        self.assertEqual((row,calls),before)


class WholeVideoCliTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(evaluate,'Unified whole-source evaluator is not implemented')
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.input=Path(temporary.name)/'input.json';self.output=Path(temporary.name)/'result.json'
        self.document=dict(schemaVersion=1,sources=[source()],predictions=[prediction()])

    def run_cli(self):
        self.input.write_text(json.dumps(self.document))
        return subprocess.run([sys.executable,str(ROOT/'scripts/evaluate_axel_pipeline.py'),
            '--input',str(self.input),'--output',str(self.output)],capture_output=True,text=True)

    def test_cli_records_input_digest_and_refuses_to_overwrite_saved_score(self):
        result=self.run_cli();self.assertEqual(result.returncode,0,result.stderr)
        raw=self.output.read_bytes();saved=json.loads(raw)
        self.assertEqual(saved['inputSha256'],hashlib.sha256(self.input.read_bytes()).hexdigest())
        self.assertEqual(saved['domains']['personal']['C'],1)
        self.document['predictions']=[]
        self.assertNotEqual(self.run_cli().returncode,0)
        self.assertEqual(self.output.read_bytes(),raw)

    def test_qa_and_wrong_schema_leave_no_output(self):
        for key,value in [('qaOnly',True),('schemaVersion',True),('schemaVersion',2)]:
            self.document=dict(schemaVersion=1,sources=[source()],predictions=[prediction()],**{key:value}) if key!='schemaVersion' else dict(schemaVersion=value,sources=[source()],predictions=[prediction()])
            with self.subTest(key=key,value=value):
                self.assertNotEqual(self.run_cli().returncode,0)
                self.assertFalse(self.output.exists())


class LegacyPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(review_playback_audit,'Legacy review playback audit is not implemented')
        self.target=dict(sourceSha256='a'*64,fps=59.97102848865283,frameCount=200,
                         timestampsSeconds=[n/60 for n in range(200)],duration=200/60)
        self.review=dict(fps=59.97,sourceSha256='a'*64,
                         events=[dict(lastContactFrame=80,firstContactFrame=100)])

    def test_two_decimal_legacy_fps_is_accepted_without_modifying_raw_coordinates(self):
        before=copy.deepcopy(self.review)
        audit=review_playback_audit(self.review,self.target)
        self.assertEqual(audit['fpsCorrespondence'],'legacy_two_decimal_rounding')
        self.assertLess(audit['maxContactPlaybackDifferenceSeconds'],1/60)
        self.assertEqual(self.review,before)

    def test_matching_rounded_metadata_does_not_excuse_retimed_or_truncated_timestamps(self):
        for kind in ['retimed','truncated','wrongfps','wrongsource']:
            target=copy.deepcopy(self.target);review=copy.deepcopy(self.review)
            if kind=='retimed':target['timestampsSeconds']=[2*n/60 for n in range(200)]
            if kind=='truncated':target['timestampsSeconds'].pop()
            if kind=='wrongfps':review['fps']=30
            if kind=='wrongsource':review['sourceSha256']='b'*64
            with self.subTest(kind=kind),self.assertRaises(ValueError):review_playback_audit(review,target)


    def test_nonfinite_nonmonotonic_and_invalid_frame_indices_are_rejected(self):
        for kind in ['nan','reverse','boolframe','outside']:
            target=copy.deepcopy(self.target);review=copy.deepcopy(self.review)
            if kind=='nan':target['timestampsSeconds'][99]=float('nan')
            if kind=='reverse':target['timestampsSeconds'][99]=0
            if kind=='boolframe':review['events'][0]['lastContactFrame']=True
            if kind=='outside':review['events'][0]['firstContactFrame']=200
            with self.subTest(kind=kind),self.assertRaises(ValueError):review_playback_audit(review,target)


class LegacyCodeTests(unittest.TestCase):
    def test_cyrillic_axel_alias_is_normalized_in_copy_without_losing_reported_sign(self):
        self.assertIsNotNone(normalize_legacy_axel_codes,'Legacy code normalizer is not implemented')
        review=dict(events=[dict(elementCode='2А<'),dict(elementCode='1а'),dict(elementCode='2Lz'),
                            dict(elementCode='2С'),dict(elementCode='3А<<')])
        before=copy.deepcopy(review)
        normalized=normalize_legacy_axel_codes(review)
        self.assertEqual([r['elementCode'] for r in normalized['events']],['2A<','1A','2Lz','2С','3A<<'])
        self.assertEqual(review,before)


if __name__=='__main__':unittest.main()
