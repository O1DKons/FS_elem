"""Intake must not turn retimed camera copies into independent training truth."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from import_full_program_review import import_review, validate_review
try:
    from append_full_review_receipts import load_packet, merge_receipts, append_snapshot
except ImportError:
    load_packet = merge_receipts = append_snapshot = None


def packet(key='b', digest='d', code='1A', kind='axel', events=True):
    target = dict(reviewId='test-'+key, sourceSha256=key*64, sourceFrames=900,
                  fps=30.0, durationSeconds=30.0, sourcePath=key+'.mov')
    review = dict(schemaVersion=1, reviewId=target['reviewId'], sourceSha256=key*64,
                  fps=30, durationSeconds=30, coverageReviewed=True,
                  events=[dict(id='jump', eventClass=kind, elementCode=code,
                               lastContactFrame=300, firstContactFrame=360,
                               rotationAssessment='apparently_complete')] if events else [])
    valid = {**validate_review(review, target), 'qaOnly':False}
    return dict(target=target, validated=valid,
                receipt=dict(reviewSha256=digest*64, qaOnly=False),
                evidence=[dict(path=digest+'/review.json', sha256=digest*64)], mediaVerified=True)


def policy():
    return dict(schemaVersion=1, useScope='development_only_quarantined',
                physicalCaptureTimebaseVerified=False, physicalContactsVerified=False,
                globallyVerifiedAthleteIdentity=False, conservativeGroups=[], sameAttemptSourcePairs=[])


def source(key, groups=None, recording=None):
    return dict(sourceSha256=key*64, athleteIds=groups or ['old:'+key],
                originalRecordingId=recording or 'file:'+key, completeReviews=[],
                usedInDevelopment=False, provenance=[], mediaHashVerified=True,
                availablePaths=[key+'.mov'], athleteIdentityVerified=False, recordingGroupVerified=False)


class RegistryReceiptTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(merge_receipts, 'Full-review receipt adapter is not implemented')
        self.sources = [source('a')]
        self.events = []
        self.partitions = dict(development=['a'*64], confirmation=[], unassigned_needs_usage_audit=[])
        self.ref = dict(path='policy.json', sha256='f'*64)

    def merge(self, packets=None, settings=None):
        return merge_receipts(self.sources, self.events, self.partitions,
                              packets or [packet()], settings or policy(), self.ref)

    def test_playback_boundaries_do_not_become_physical_time_or_training_labels(self):
        original = copy.deepcopy((self.sources, self.events, self.partitions))
        sources, rows, splits = self.merge()
        row = rows[0]
        self.assertEqual((row['family'], row['nominal']), ('axel', '1A'))
        self.assertEqual((row['lastContactFrame'], row['firstContactFrame']), (300, 360))
        self.assertEqual((row['startSeconds'], row['endSeconds']), (10.0, 12.0))
        self.assertFalse(row['modelTrainingEligible'])
        self.assertEqual(row['eligibleTrainingTargets'], [])
        self.assertIsNone(row['physicalFlightSeconds'])
        self.assertIsNone(row['physicalAirborneTurns'])
        self.assertIsNone(row['underrotation'])
        self.assertEqual(row['reportedRotationAssessment'], 'apparently_complete')
        self.assertTrue(row['reviewComplete'])
        self.assertEqual(row['labelScope'], 'full_review')
        self.assertEqual(splits['development'], ['a'*64, 'b'*64])
        self.assertEqual(splits['confirmation'], [])
        self.assertEqual(sources[0], self.sources[0])
        self.assertEqual((self.sources, self.events, self.partitions), original)

    def test_repeated_receipt_is_idempotent_and_new_revision_keeps_both_observations(self):
        sources, rows, splits = self.merge()
        repeated = merge_receipts(sources, rows, splits, [packet()], policy(), self.ref)
        self.assertEqual(repeated, (sources, rows, splits))
        changed = merge_receipts(sources, rows, splits, [packet(digest='e', code='2A')], policy(), self.ref)
        self.assertEqual(len(changed[1]), 2)
        self.assertEqual([r['nominal'] for r in changed[1]], ['1A', '2A'])
        self.assertTrue(changed[0][1]['reviewRevisionsRequireSelection'])
        self.assertEqual(rows[0]['nominal'], '1A')

    def test_same_digest_with_conflicting_observation_is_rejected(self):
        sources, rows, splits = self.merge()
        with self.assertRaises(ValueError):
            merge_receipts(sources, rows, splits, [packet(code='2A')], policy(), self.ref)

    def test_full_review_with_no_events_records_coverage_without_fabricating_negative_events(self):
        sources, rows, splits = self.merge([packet(events=False)])
        self.assertEqual(rows, [])
        self.assertEqual(len(sources[1]['completeReviews']), 1)
        self.assertIn('b'*64, splits['development'])

    def test_uncertain_family_is_retained_without_negative_or_nominal_truth(self):
        _, rows, _ = self.merge([packet(kind='uncertain', code='1A')])
        self.assertIsNone(rows[0]['family'])
        self.assertIsNone(rows[0]['nominal'])
        self.assertEqual(rows[0]['availableLabelTargets'], [])

    def test_development_closure_follows_all_existing_group_and_recording_links(self):
        self.sources.extend([source('c', ['old:shared'], 'shared-recording'),
                             source('e', ['old:other'], 'shared-recording')])
        self.partitions['unassigned_needs_usage_audit'] = ['c'*64, 'e'*64]
        settings = policy()
        settings['conservativeGroups'] = [dict(exclusionGroup='old:shared', sourceHashes=['b'*64, 'c'*64])]
        sources, _, splits = self.merge(settings=settings)
        self.assertEqual(splits['development'], [c*64 for c in 'abce'])
        self.assertEqual(splits['unassigned_needs_usage_audit'], [])
        self.assertFalse(next(s for s in sources if s['sourceSha256']=='e'*64)['usedInDevelopment'])

    def test_camera_pairs_are_grouped_without_event_deduplication_or_identity_certification(self):
        settings = policy()
        settings['conservativeGroups'] = [dict(exclusionGroup='conservative-batch', sourceHashes=['b'*64, 'c'*64])]
        settings['sameAttemptSourcePairs'] = [dict(sourceHashes=['b'*64, 'c'*64],
            relation='human_confirmed_same_attempt_other_camera', eventCorrespondence='unresolved')]
        sources, rows, splits = self.merge([packet(), packet('c', 'e')], settings)
        self.assertEqual(len(rows), 2)
        self.assertEqual(splits['development'], ['a'*64, 'b'*64, 'c'*64])
        self.assertEqual(sources[1]['sameAttemptCameraPairs'][0]['eventCorrespondence'], 'unresolved')
        self.assertFalse(sources[1]['athleteIdentityVerified'])
        self.assertFalse(sources[1]['recordingGroupVerified'])

    def test_pair_without_shared_exclusion_group_or_with_unknown_source_is_rejected(self):
        for hashes in [['b'*64, 'c'*64], ['b'*64, 'f'*64]]:
            settings = policy()
            settings['sameAttemptSourcePairs'] = [dict(sourceHashes=hashes,
                relation='human_confirmed_same_attempt_other_camera', eventCorrespondence='unresolved')]
            with self.subTest(hashes=hashes), self.assertRaises(ValueError):
                self.merge([packet(), packet('c', 'e')], settings)

    def test_confirmation_partition_is_never_reassigned_silently(self):
        self.partitions = dict(development=[], confirmation=['a'*64], unassigned_needs_usage_audit=[])
        with self.assertRaises(ValueError):
            self.merge()

    def test_qa_partial_review_and_unverified_media_are_rejected(self):
        for kind in ['qa', 'partial', 'media']:
            item = packet()
            if kind == 'qa': item['receipt']['qaOnly'] = True
            if kind == 'partial': item['validated']['reviewComplete'] = False
            if kind == 'media': item['mediaVerified'] = False
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.merge([item])

    def test_intake_cannot_promote_physical_timing_or_global_identity(self):
        for flag in ['physicalCaptureTimebaseVerified', 'physicalContactsVerified', 'globallyVerifiedAthleteIdentity']:
            settings = policy(); settings[flag] = True
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                self.merge(settings=settings)


class PacketIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(load_packet, 'Full-review receipt loader is not implemented')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.media = self.base/'source.mov'; self.media.write_bytes(b'original-video-bytes')
        self.target = packet()['target']
        self.target.update(sourceSha256=hashlib.sha256(self.media.read_bytes()).hexdigest(), sourcePath=str(self.media))
        self.manifest = self.base/'manifest.json'
        self.manifest.write_text(json.dumps(dict(schemaVersion=1, items=[self.target])))
        self.review = self.base/'review-input.json'
        self.review.write_text(json.dumps(dict(schemaVersion=1, reviewId=self.target['reviewId'],
            sourceSha256=self.target['sourceSha256'], fps=30, durationSeconds=30,
            coverageReviewed=True, events=[dict(id='jump',eventClass='axel',elementCode='1A',
                lastContactFrame=300, firstContactFrame=360)])))
        self.archive = import_review(self.review, self.manifest, self.base/'imports')

    def test_actual_receipt_is_revalidated_and_original_bytes_retained(self):
        before = {p.name:p.read_bytes() for p in self.archive.iterdir()}
        item = load_packet(self.archive)
        self.assertEqual(item['validated']['events'][0]['nominal'], '1A')
        self.assertTrue(item['mediaVerified'])
        self.assertEqual(item['target']['sourceSha256'], self.target['sourceSha256'])
        self.assertEqual({p.name:p.read_bytes() for p in self.archive.iterdir()}, before)

    def test_changed_review_receipt_validated_output_and_media_are_rejected(self):
        before = {p:p.read_bytes() for p in self.archive.iterdir()}
        for name in ['review.json', 'manifest.json', 'validated.json', 'receipt.json', 'source.mov']:
            path = self.media if name == 'source.mov' else self.archive/name
            original = path.read_bytes()
            path.write_bytes(b'{}')
            with self.subTest(name=name), self.assertRaises(ValueError):
                load_packet(self.archive)
            path.write_bytes(original)
        self.assertEqual({p:p.read_bytes() for p in self.archive.iterdir()}, before)

    def test_rehashed_but_semantically_changed_validated_output_is_rejected(self):
        path = self.archive/'validated.json'
        doc = json.loads(path.read_text()); doc['events'][0]['nominal'] = '2A'
        path.write_text(json.dumps(doc))
        receipt = json.loads((self.archive/'receipt.json').read_text())
        receipt['fileSha256']['validated.json'] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.archive/'receipt.json').write_text(json.dumps(receipt))
        with self.assertRaises(ValueError):
            load_packet(self.archive)

    def test_qa_import_receipt_cannot_be_promoted_to_corpus(self):
        doc = json.loads(self.review.read_text()); doc['qaOnly'] = True
        self.review.write_text(json.dumps(doc))
        isolated = import_review(self.review, self.manifest, self.base/'qa-imports', qa_only=True)
        with self.assertRaises(ValueError):
            load_packet(isolated)

    def test_snapshot_creation_preserves_base_and_refuses_overwrite(self):
        # Minimal real corpus and real import; no trained model or production data.
        from pose_cache_contract import sha
        from verify_axel_corpus import verify
        temp = tempfile.TemporaryDirectory(dir=ROOT/'work')
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)/'base'; base.mkdir()
        old_source = source('a'); old_source['mediaHashVerified'] = False
        docs = {
            'sources.json':dict(schemaVersion=1, sources=[old_source]),
            'events.json':dict(schemaVersion=1, events=[]),
            'splits.json':dict(schemaVersion=1, status='not_frozen', independenceVerified=False,
                partitions=dict(development=['a'*64], confirmation=[], unassigned_needs_usage_audit=[]), limitations=[]),
            'database-snapshot.json':{},
            'intake-report.json':dict(summary={}, inputSha256={},
                builderSha256=sha(ROOT/'scripts/build_axel_corpus.py'), validatorSha256=sha(ROOT/'scripts/axel_corpus.py'))}
        for name, doc in docs.items():
            (base/name).write_text(json.dumps(doc))
        (base/'SHA256SUMS.json').write_text(json.dumps({name:sha(base/name) for name in docs}))
        original = {p.name:p.read_bytes() for p in base.iterdir()}
        settings = policy()
        settings.update(baseManifestSha256=sha(base/'SHA256SUMS.json'),
                        receipts=[str(self.archive)], inputSha256={})
        settings_path = Path(temp.name)/'policy.json'; settings_path.write_text(json.dumps(settings))
        output = Path(temp.name)/'new-corpus'
        result = append_snapshot(base, settings_path, output)
        self.assertEqual(result['verification']['sources'], 2)
        self.assertEqual(result['verification']['observations'], 1)
        self.assertEqual(result['extension']['observationsAdded'], 1)
        self.assertFalse(result['extension']['modelFittingPerformed'])
        self.assertEqual(verify(output)['sources'], 2)
        self.assertEqual({p.name:p.read_bytes() for p in base.iterdir()}, original)
        self.assertEqual((output/'database-snapshot.json').read_bytes(), original['database-snapshot.json'])
        saved = {p.name:p.read_bytes() for p in output.iterdir()}
        with self.assertRaises(ValueError):
            append_snapshot(base, settings_path, output)
        self.assertEqual({p.name:p.read_bytes() for p in output.iterdir()}, saved)


if __name__ == '__main__':
    unittest.main()
