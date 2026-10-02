"""Guard against assigning official labels to the wrong video or clip."""
import importlib.util
from pathlib import Path
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/match_program_scores.py'


class ProgramScoreMatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = None
        if SCRIPT.exists():
            spec = importlib.util.spec_from_file_location('match_program_scores', SCRIPT)
            cls.module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = cls.module
            spec.loader.exec_module(cls.module)

    def api(self):
        self.assertIsNotNone(self.module, 'Program matcher is not implemented')
        return self.module

    def program(self, **changes):
        p = {'id': 'p1', 'category': {'raw': 'Одиночное катание 1 Спортивный Девушки, девочки', 'segment': 'short'}, 'rank': 11, 'startNumber': 14,
             'athleteName': 'София ПОСЯГИНА', 'region': 'ЕКБ',
             'elements': [{'sequence': 1, 'code': '2A<', 'flagsInfo': ['F']}]}
        p.update(changes)
        return p

    def video(self, **changes):
        v = {'path': '/videos/source.mp4', 'categoryKey': '1-F', 'segment': 'short',
             'startNumber': 14, 'athleteName': 'София Александровна ПОСЯГИНА', 'region': 'ЕКБ'}
        v.update(changes)
        return v

    def test_mixed_alphabet_unicode_and_prefix_filename(self):
        # Losing normalization breaks legitimate exact matches; date prefix is not an ID.
        m = self.api()
        v = m.parse_video_filename(Path('2026-8-21 9-37-49 ММС Кубок федерации, 2 этап Одинoчнoe кaтaниe 1 Спopтивный Дeвушки, Короткая программа 14# София Александровна ПОСЯГИНА  (ЕКБ).mp4'))
        self.assertEqual((v['categoryKey'], v['segment'], v['startNumber']), ('1-F', 'short', 14))
        self.assertEqual(m.match_video(v, [self.program()])['status'], 'matched')

    def test_rank_does_not_substitute_for_start_number(self):
        m = self.api()
        self.assertEqual(m.match_video(self.video(startNumber=11), [self.program()])['status'], 'unmatched')
        self.assertEqual(m.match_video(self.video(), [self.program()])['programId'], 'p1')

    def test_wrong_name_region_segment_or_category_cannot_receive_label(self):
        m = self.api()
        for changes in ({'athleteName': 'Алина ПОСЯГИНА'}, {'region': 'КРГ'},
                        {'segment': 'free'}, {'categoryKey': '2-F'}):
            with self.subTest(changes=changes):
                self.assertNotEqual(m.match_video(self.video(**changes), [self.program()])['status'], 'matched')

    def test_duplicate_protocol_candidates_abstain(self):
        m = self.api()
        result = m.match_video(self.video(), [self.program(), self.program(id='p2')])
        self.assertEqual(result['status'], 'ambiguous')
        self.assertIsNone(result.get('programId'))

    def test_combination_components_preserve_mark_and_invalid_flag(self):
        m = self.api()
        result = m.axels_in_program(self.program(elements=[
            {'sequence': 1, 'code': '2Aq+1Eu+2S', 'flagsInfo': ['q']},
            {'sequence': 2, 'code': '2Lz+2A<<+SEQ', 'flagsInfo': ['<<']},
            {'sequence': 3, 'code': '1A*', 'flagsInfo': ['*']},
            {'sequence': 4, 'code': '2A', 'flagsInfo': []}]))
        self.assertEqual([(x['sequence'], x['componentCode'], x['rotationSign'], x['invalid']) for x in result],
                         [(1, '2Aq', 'q', False), (2, '2A<<', '<<', False), (3, '1A*', None, True), (4, '2A', None, False)])
        self.assertTrue(all(x['labelScope'] == 'program_element' and x['trainEligible'] is False for x in result))
        self.assertTrue(all(x['underrotationDegrees'] is None and x['measuredRevolutions'] is None for x in result))

    def test_unspecified_axel_does_not_invent_rotation_count(self):
        m = self.api()
        row = m.axels_in_program(self.program(elements=[{'sequence': 1, 'code': 'A', 'flagsInfo': []}]))[0]
        self.assertIsNone(row['nominalAxel'])
        self.assertFalse(row['trainEligible'])

    def test_reviewed_alias_is_scoped_to_exact_source_identity(self):
        m = self.api()
        video = self.video(athleteName='С. ПОСЯГИНА')
        program = self.program(sourceSha256='pdf-sha')
        alias = {'videoPath': video['path'], 'videoAthleteName': 'С. ПОСЯГИНА',
                 'programId': 'p1', 'programAthleteName': 'София ПОСЯГИНА',
                 'sourceSha256': 'pdf-sha', 'reason': 'reviewed_initial'}
        self.assertEqual(m.match_video(video, [program], [alias])['status'], 'matched')
        for wrong in (self.program(sourceSha256='changed'), self.program(sourceSha256='pdf-sha', region='КРГ'), self.program(sourceSha256='pdf-sha', athleteName='София ПЕТРОВА')):
            self.assertNotEqual(m.match_video(video, [wrong], [alias])['status'], 'matched')

    def test_fall_in_sequence_does_not_label_each_axel_as_fallen(self):
        m = self.api()
        rows = m.axels_in_program(self.program(elements=[
            {'sequence': 1, 'code': '3F!+A+2A+SEQ', 'flagsInfo': ['!', 'F'], 'fall': True}]))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['elementFall'] for row in rows))
        self.assertTrue(all(row['componentFall'] is None for row in rows))

    def test_full_program_duplicate_videos_abstain(self):
        m = self.api()
        result = m.match_all([self.video(), self.video(path='/videos/duplicate.mp4')], [self.program()])
        self.assertEqual([r['status'] for r in result], ['ambiguous', 'ambiguous'])


if __name__ == '__main__':
    unittest.main()
