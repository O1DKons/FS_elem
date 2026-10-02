import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
try:
    from extend_axel_corpus import apply_identity_links
except ImportError:
    apply_identity_links = None


def fixture():
    sources = [dict(sourceSha256=key*64, athleteIds=athletes,
                    originalRecordingId=recording, athleteIdentityVerified=False,
                    usedInDevelopment=key=='a', provenance=[])
               for key, athletes, recording in [
                   ('a', ['old:anna'], 'recording1'),
                   ('b', ['new:anna'], 'recording2'),
                   ('c', ['new:anna'], 'recording3'),
                   ('d', ['new:other'], 'recording3'),
                   ('e', ['unresolved'], 'recording5')]]
    augmented = copy.deepcopy(sources)
    for row in augmented[:2]:
        row['athleteIds'].append('named:anna')
    overlay = dict(sources=augmented, addedSourceGroupLinks=2,
                   conservativeGroups=[dict(exclusionGroup='named:anna', sourceHashes=['a'*64,'b'*64])],
                   globallyVerifiedIdentity=False, replacesRegistry=False)
    partitions = dict(development=['a'*64], confirmation=[],
                      unassigned_needs_usage_audit=[key*64 for key in 'bcde'])
    return sources, partitions, overlay


class IdentitySnapshotTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(apply_identity_links, 'Immutable identity extension is not implemented')

    def test_transitive_athlete_and_recording_links_expand_exclusion_not_identity_certainty(self):
        sources, partitions, overlay = fixture()
        before = copy.deepcopy((sources, partitions, overlay))
        updated, split = apply_identity_links(sources, [], partitions, overlay,
                                              {'path':'links.json', 'sha256':'f'*64})
        self.assertEqual(split['development'], [key*64 for key in 'abcd'])
        self.assertEqual(split['unassigned_needs_usage_audit'], ['e'*64])
        self.assertEqual(split['confirmation'], [])
        self.assertFalse(updated[1]['athleteIdentityVerified'])
        self.assertFalse(updated[1]['usedInDevelopment'])
        self.assertEqual(updated[1]['athleteIds'], ['named:anna', 'new:anna'])
        self.assertEqual((sources, partitions, overlay), before)

    def test_old_labels_and_nonidentity_source_metadata_cannot_be_changed_by_overlay(self):
        sources, partitions, overlay = fixture()
        overlay['sources'][0]['usedInDevelopment'] = False
        with self.assertRaises(ValueError):
            apply_identity_links(sources, [], partitions, overlay, {'path':'links.json','sha256':'f'*64})

    def test_missing_source_or_removed_original_group_is_rejected(self):
        for kind in ['source', 'group']:
            sources, partitions, overlay = fixture()
            if kind=='source':overlay['sources'].pop()
            else:overlay['sources'][0]['athleteIds'].remove('old:anna')
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                apply_identity_links(sources, [], partitions, overlay, {'path':'links.json','sha256':'f'*64})

    def test_undeclared_new_group_and_incorrect_link_count_are_rejected(self):
        for kind in ['group', 'count']:
            sources, partitions, overlay = fixture()
            if kind=='group':overlay['sources'][2]['athleteIds'].append('named:unknown')
            else:overlay['addedSourceGroupLinks'] = 10
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                apply_identity_links(sources, [], partitions, overlay, {'path':'links.json','sha256':'f'*64})

    def test_overlay_must_not_claim_verified_identity_or_replacement(self):
        for flag in ['globallyVerifiedIdentity', 'replacesRegistry']:
            sources, partitions, overlay = fixture()
            overlay[flag] = True
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                apply_identity_links(sources, [], partitions, overlay, {'path':'links.json','sha256':'f'*64})

    def test_existing_confirmation_is_not_silently_repartitioned(self):
        sources, partitions, overlay = fixture()
        partitions['confirmation'] = ['b'*64]
        partitions['unassigned_needs_usage_audit'].remove('b'*64)
        with self.assertRaises(ValueError):
            apply_identity_links(sources, [], partitions, overlay, {'path':'links.json','sha256':'f'*64})

    def test_overlay_evidence_is_attached_only_to_changed_sources(self):
        sources, partitions, overlay = fixture()
        ref = {'path':'links.json','sha256':'f'*64}
        updated, _ = apply_identity_links(sources, [], partitions, overlay, ref)
        self.assertEqual(updated[0]['provenance'], [ref])
        self.assertEqual(updated[1]['provenance'], [ref])
        self.assertEqual(updated[2]['provenance'], [])


if __name__=='__main__':
    unittest.main()
