import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from import_program_score_pdfs import ImportFailure, parse_element, parse_pages, import_manifest


# Hand-checked against the first athlete's original PDF table. The extractor
# places the first element above the athlete row because of rotated headings.
FIRST_BLOCK = '''ММС Кубок федерации, 2 этап (20.09.2026-22.09.2026) -- Одинoчнoe кaтaниe 1 Спopтивный Дeвушки, дeвoчки (Короткая программа)
Регион
# GOE J1 J2 J3 Реф.
1 3F 5.30 -0.35 -2 0 0 4.95
ofnI
1 Арина ДУДАРЕВА КУР 16 50.57 29.05 21.52 0.00
г. Каменск-Уральский, МАУ СШ
2 2A 3.30 0.11 1 0 0 3.41
3 CCoSp4 4.20 0.14 1 0 0 4.34
4 StSq2 2.70 0.09 1 0 0 2.79
5 FCSp2 2.80 0.37 1 2 1 3.17
6 3Lo+2T 6.82 x -0.16 -1 0 0 6.66
7 LSp4 3.20 0.53 1 2 2 3.73
28.32 29.05
Компоненты программы Фактор
Композиция 1.50 5,25 4,50 4,50 4.75
Представление 1.50 5,50 4,75 4,50 4.92
Мастерство катания 1.50 5,00 4,50 4,50 4.67
Сумма за компоненты программы (умноженная) 21.52
Снижения 0.00'''


class ProgramScorePdfTests(unittest.TestCase):
    def parse(self, text=FIRST_BLOCK):
        return parse_pages([{'page': 1, 'text': text}], 'sample.pdf', 'a' * 64)

    def test_first_element_stays_with_athlete_and_start_number_is_not_rank(self):
        row = self.parse()[0]
        self.assertEqual((row['athleteName'], row['startNumber'], row['rank']),
                         ('Арина ДУДАРЕВА', 16, 1))
        self.assertEqual(row['category']['level'], '1')
        self.assertEqual(row['category']['gender'], 'F')
        self.assertEqual(row['category']['segment'], 'short')
        self.assertEqual([e['code'] for e in row['elements']],
                         ['3F', '2A', 'CCoSp4', 'StSq2', 'FCSp2', '3Lo+2T', 'LSp4'])
        self.assertEqual(row['scores'], {'TSS': 50.57, 'TES': 29.05, 'PCS': 21.52,
                                         'deductions': 0.0, 'baseValue': 28.32})
        self.assertEqual(row['sourcePage'], 1)
        self.assertEqual(row['sourceSha256'], 'a' * 64)

    def test_component_marks_and_info_flags_are_lossless_without_duplication(self):
        row = parse_element('4 3F!+2Aq+2A<+SЕQ ! 11.24 -1.94 -4 -4 -3 9.30')
        self.assertEqual(row['code'], '3F!+2Aq+2A<+SЕQ')
        self.assertEqual(row['modifiers'], ['SEQ'])
        self.assertEqual([(c['nominalType'], c['rotationSign']) for c in row['components']],
                         [('3F', None), ('2A', 'q'), ('2A', '<')])
        downgrade = parse_element('1 2A<<+2T << 2.40 -0.39 -3 -3 -3 -4 -3 2.01')
        self.assertEqual(len(downgrade['components']), 2)
        self.assertEqual(downgrade['components'][0]['rotationSign'], '<<')
        self.assertEqual(downgrade['flagsInfo'], ['<<'])

    def test_unmarked_and_invalid_axels_remain_distinct(self):
        clean = parse_element('2 2A 3.30 0.11 1 0 0 3.41')
        invalid = parse_element('5 1A* * 0.00 x 0.00 - - - 0.00')
        fall = parse_element('1 2A< F 2.64 -1.32 -5 -5 -5 1.32')
        self.assertIsNone(clean['components'][0]['rotationSign'])
        self.assertTrue(invalid['components'][0]['invalid'])
        self.assertEqual(invalid['components'][0]['nominalType'], '1A')
        self.assertTrue(fall['fall'])
        self.assertEqual(fall['components'][0]['rotationSign'], '<')

    def test_refuses_lost_element_duplicate_athlete_and_incorrect_totals(self):
        bad_inputs = [FIRST_BLOCK.replace('2 2A 3.30 0.11 1 0 0 3.41\n', ''),
                      FIRST_BLOCK + '\n1 Арина ДУДАРЕВА КУР 16 50.57 29.05 21.52 0.00',
                      FIRST_BLOCK.replace('28.32 29.05', '28.31 29.05'),
                      FIRST_BLOCK.replace('5 FCSp2', '5 ???')]
        for text in bad_inputs:
            with self.subTest(text=text[-100:]), self.assertRaises(ImportFailure):
                self.parse(text)

    def test_euler_and_unspecified_axel_are_not_silently_relabelled(self):
        row = parse_element('2 3F!+A+2A+SЕQ F 8.60 -2.65 -5 -5 -5 5.95')
        self.assertEqual([c['nominalType'] for c in row['components']], ['3F', 'A', '2A'])
        self.assertIsNone(row['components'][1]['nominalRevolutions'])
        row = parse_element('1 2A+1Eu+2S 5.10 0.00 0 0 0 5.10')
        self.assertEqual([c['nominalType'] for c in row['components']], ['2A', '1Eu', '2S'])

    def test_basic_level_is_not_swallowed_into_the_element_family(self):
        row = parse_element('4 CCoSpBV nU 1.28 -0.13 -1 0 -2 1.15')
        self.assertEqual(row['components'][0]['nominalType'], 'CCoSpB')
        self.assertEqual(row['components'][0]['flagsCode'], ['V'])
        self.assertEqual(row['flagsInfo'], ['nU'])

    def test_imports_real_source_counts_and_key_official_calls(self):
        result = import_manifest(ROOT / 'data/new-programs-protocols-v1/manifest.json', ROOT)
        self.assertEqual(len(result['programs']), 144)
        self.assertEqual(result['summary']['sourcePdfCount'], 13)
        self.assertEqual(result['summary']['sourcePageCount'], 62)
        expected = {'Элина ДЬЯКОВА': (10, 6, '2A', '<<'),
                    'Виктория ШУМКОВА': (11, 1, '2A', '<<'),
                    'Вера ЧУВАКОВА': (12, 5, '1A', None),
                    'Елизавета ВЕРШИНИНА': (13, 1, '2A', 'q'),
                    'София ПОСЯГИНА': (14, 1, '2A', '<')}
        found = {}
        for p in result['programs']:
            if p['athleteName'] in expected:
                for e in p['elements']:
                    for c in e['components']:
                        if c['jumpFamily'] == 'A':
                            found[p['athleteName']] = (p['startNumber'], e['sequence'],
                                                       c['nominalType'], c['rotationSign'])
        self.assertEqual(found, expected)


if __name__ == '__main__':
    unittest.main()
