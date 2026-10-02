import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
try:
    from build_axel_competition_links import competition_links
except ImportError:
    competition_links = None


class CompetitionLinksTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(competition_links, 'Cross-event conservative links are missing')
        self.sources = [
            dict(sourceSha256='old', athleteIds=['old:A'], athleteLabels=['Алиса БАЛУЕВА'],
                 metadataObservations=[dict(videoId='comp-44')], athleteIdentityVerified=False),
            dict(sourceSha256='new', athleteIds=['new:A'], athleteLabels=['Алиса Васильевна БАЛУЕВА'],
                 metadataObservations=[], athleteIdentityVerified=False),
            dict(sourceSha256='other', athleteIds=['other:A'], athleteLabels=['Елена БАЛУЕВА'],
                 metadataObservations=[], athleteIdentityVerified=False)]
        self.library = [dict(programId='p1', sourceSha256='new', matchStatus='matched'),
                        dict(programId='p2', sourceSha256='other', matchStatus='matched')]
        self.overlaps = [dict(normalizedFullName='алиса балуева',
                             conservativeExclusionGroup='named:алиса балуева',
                             oldCompetitionStartNumbers=[44], newPrograms=[dict(programId='p1')])]

    def test_exact_audit_links_old_and_new_sources_without_claiming_verified_identity(self):
        sources, groups = competition_links(self.sources, self.library, self.overlaps)
        group = 'named:алиса балуева'
        self.assertIn(group, sources[0]['athleteIds'])
        self.assertIn(group, sources[1]['athleteIds'])
        self.assertNotIn(group, sources[2]['athleteIds'])
        self.assertFalse(sources[1]['athleteIdentityVerified'])
        self.assertEqual(groups[0]['sourceHashes'], ['new','old'])

    def test_input_registry_is_not_mutated(self):
        competition_links(self.sources, self.library, self.overlaps)
        self.assertEqual(self.sources[0]['athleteIds'], ['old:A'])

    def test_ambiguous_program_file_match_does_not_create_identity_link(self):
        library = [dict(programId='p1', sourceSha256='new', matchStatus='ambiguous')]
        sources, _ = competition_links(self.sources, library, self.overlaps)
        self.assertEqual(sources[1]['athleteIds'], ['new:A'])


if __name__=='__main__':
    unittest.main()
