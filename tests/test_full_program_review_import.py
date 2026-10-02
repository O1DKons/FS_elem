import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    from import_full_program_review import import_review, validate_review
except ImportError:
    import_review = validate_review = None


def target():
    return dict(reviewId='pilot-program-test-full-program', sourceSha256='a'*64,
                sourceFrames=1000, fps=50.0, durationSeconds=20.0)


def event(identifier='first', kind='axel', code='2Aq', last=50, first=75):
    return dict(id=identifier, eventClass=kind, elementCode=code,
                lastContactFrame=last, firstContactFrame=first,
                rotationAssessment='apparently_short')


def review(events=None):
    return dict(schemaVersion=1, reviewId='pilot-program-test-full-program',
                sourceSha256='a'*64, durationSeconds=20.0, fps=50.0,
                coverageReviewed=True, reviewedAt='2026-10-01T08:00:00Z',
                events=[event()] if events is None else events)


class ReviewContractTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(validate_review, 'Generic full-program importer is not implemented')

    def test_keeps_nominal_separate_from_sign_and_physical_turns(self):
        document = review()
        before = copy.deepcopy(document)
        result = validate_review(document, target())
        row = result['events'][0]
        self.assertEqual((row['startSeconds'], row['endSeconds']), (1.0, 1.5))
        self.assertEqual(row['family'], 'axel')
        self.assertEqual(row['nominal'], '2A')
        self.assertEqual(row['reportedElementCode'], '2Aq')
        self.assertEqual(row['reportedRotationAssessment'], 'apparently_short')
        self.assertIsNone(row['physicalAirborneTurns'])
        self.assertIsNone(row['measuredUnderrotation'])
        self.assertIsNone(row['underrotation'])
        self.assertFalse(result['modelTrainingEligible'])
        self.assertEqual(document, before)

    def test_uncertain_does_not_become_a_negative_or_nominal_truth(self):
        document = review([event(kind='uncertain', code='1A')])
        row = validate_review(document, target())['events'][0]
        self.assertIsNone(row['family'])
        self.assertIsNone(row['nominal'])
        self.assertEqual(row['reportedElementCode'], '1A')

    def test_other_jumps_and_empty_fully_reviewed_programs_are_supported(self):
        row = validate_review(review([event(kind='other_jump', code='2Lz')]), target())['events'][0]
        self.assertEqual(row['family'], 'other')
        self.assertIsNone(row['nominal'])
        self.assertEqual(validate_review(review([]), target())['events'], [])

    def test_schema_and_complete_coverage_are_strict_not_truthy(self):
        for key, values in [('schemaVersion', [True, 1.0, '1', 2]),
                            ('coverageReviewed', [1, 'true', False, None])]:
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate_review({**review(), key:value}, target())

    def test_wrong_review_or_source_identity_is_rejected(self):
        for key, value in [('reviewId', 'some-other-program'), ('sourceSha256', 'b'*64)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_review({**review(), key:value}, target())

    def test_fps_and_duration_must_match_the_independent_manifest(self):
        for key, values in [('fps', [25, True, float('nan'), float('inf'), 50.01]),
                            ('durationSeconds', [0, True, float('nan'), 20.3])]:
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate_review({**review(), key:value}, target())

    def test_two_duration_tolerances_cannot_accumulate_against_frame_timebase(self):
        with self.assertRaises(ValueError):
            validate_review({**review(), 'durationSeconds':20.4},
                            {**target(), 'durationSeconds':20.2})

    def test_contacts_are_integers_ordered_and_inside_source(self):
        for last, first in [(True, 75), (50, 75.0), (-1, 75), (75, 75), (80, 75), (950, 1000)]:
            with self.subTest(last=last, first=first), self.assertRaises(ValueError):
                validate_review(review([event(last=last, first=first)]), target())

    def test_duplicate_ids_and_confirmed_overlap_are_rejected_but_combo_contact_is_valid(self):
        with self.assertRaises(ValueError):
            validate_review(review([event(), event()]), target())
        with self.assertRaises(ValueError):
            validate_review(review([event(), event('second', last=74, first=90)]), target())
        rows = validate_review(review([event(), event('second', last=75, first=90)]), target())['events']
        self.assertEqual(len(rows), 2)
        rows = validate_review(review([event(), event('unclear', 'uncertain', '', 55, 80)]), target())['events']
        self.assertIsNone(rows[1]['family'])

    def test_code_class_contradictions_are_rejected_and_higher_nominal_is_not_coerced(self):
        for kind, code in [('axel', '2Lz'), ('other_jump', '2a<<'), ('spin', '')]:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate_review(review([event(kind=kind, code=code)]), target())
        row = validate_review(review([event(code='3A<')]), target())['events'][0]
        self.assertEqual(row['nominal'], '3A')
        self.assertFalse(row['targetNominalSupported'])


class ReviewArchiveTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(import_review, 'Generic full-program importer is not implemented')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.media = self.base/'source.mp4'
        self.media.write_bytes(b'Controlled immutable source bytes')
        self.row = {**target(), 'sourceSha256':hashlib.sha256(self.media.read_bytes()).hexdigest(),
                    'sourcePath':str(self.media)}
        self.manifest = self.base/'manifest.json'
        self.manifest.write_text(json.dumps({'schemaVersion':1, 'items':[self.row]}))
        self.document = {**review(), 'sourceSha256':self.row['sourceSha256']}
        self.input = self.base/'review.json'
        self.input.write_bytes((json.dumps(self.document, ensure_ascii=False, indent=4)+'\n').encode())
        self.output = self.base/'imports'

    def test_preserves_bytes_is_idempotent_and_new_revision_never_replaces_original(self):
        raw = self.input.read_bytes()
        path = import_review(self.input, self.manifest, self.output)
        self.assertEqual((path/'review.json').read_bytes(), raw)
        self.assertEqual((path/'manifest.json').read_bytes(), self.manifest.read_bytes())
        receipt_raw = (path/'receipt.json').read_bytes()
        self.assertEqual(import_review(self.input, self.manifest, self.output), path)
        self.assertEqual((path/'receipt.json').read_bytes(), receipt_raw)
        validated = json.loads((path/'validated.json').read_text())
        self.assertFalse(validated['modelTrainingEligible'])
        self.document['events'][0]['elementCode'] = '1A'
        self.input.write_text(json.dumps(self.document))
        revision = import_review(self.input, self.manifest, self.output)
        self.assertNotEqual(path, revision)
        self.assertEqual((path/'review.json').read_bytes(), raw)

    def test_changed_source_leaves_no_archive(self):
        self.media.write_bytes(b'Changed source')
        with self.assertRaises(ValueError):
            import_review(self.input, self.manifest, self.output)
        self.assertFalse(self.output.exists())

    def test_nonfinite_json_leaves_no_archive(self):
        self.input.write_text('{"schemaVersion":NaN}')
        with self.assertRaises(ValueError):
            import_review(self.input, self.manifest, self.output)
        self.assertFalse(self.output.exists())

    def test_duplicate_json_keys_are_rejected_before_archiving(self):
        raw = self.input.read_text()
        self.input.write_text(raw.replace('"schemaVersion": 1,',
                             '"schemaVersion": 1, "schemaVersion": 1,'))
        with self.assertRaises(ValueError):
            import_review(self.input, self.manifest, self.output)
        self.assertFalse(self.output.exists())

    def test_ambiguous_manifest_target_is_rejected(self):
        self.manifest.write_text(json.dumps({'items':[self.row, self.row]}))
        with self.assertRaises(ValueError):
            import_review(self.input, self.manifest, self.output)
        self.assertFalse(self.output.exists())

    def test_corrupted_import_cannot_be_silently_repaired(self):
        path = import_review(self.input, self.manifest, self.output)
        (path/'validated.json').write_text('{}')
        with self.assertRaises(ValueError):
            import_review(self.input, self.manifest, self.output)
        self.assertEqual((path/'validated.json').read_text(), '{}')

    def test_qa_marker_is_rejected_unless_explicitly_isolated_and_scope_cannot_be_promoted(self):
        self.document['qaOnly'] = True
        self.input.write_text(json.dumps(self.document))
        with self.assertRaises(ValueError):
            import_review(self.input, self.manifest, self.output)
        path = import_review(self.input, self.manifest, self.output, qa_only=True)
        receipt = json.loads((path/'receipt.json').read_text())
        self.assertTrue(receipt['qaOnly'])
        self.assertFalse(receipt['modelTrainingEligible'])
        with self.assertRaises(ValueError):
            import_review(self.input, self.manifest, self.output)


if __name__ == '__main__':
    unittest.main()
