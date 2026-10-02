import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from add_competition import planned_episodes


class CompetitionPlanTest(unittest.TestCase):
    def test_one_draft_per_jump_component_and_no_boundaries(self):
        program = {'startNumber': 24, 'elements': [
            {'sequence': 1, 'code': '2A<<', 'jumpComponents': ['2A<<']},
            {'sequence': 2, 'code': 'CCoSp3', 'jumpComponents': []},
            {'sequence': 3, 'code': '2F+2Tq+1A+SEQ', 'jumpComponents': ['2F', '2Tq', '1A+SEQ']},
        ]}
        result = planned_episodes(program)
        self.assertEqual([e['id'] for e in result], ['competition-24-01-01', 'competition-24-03-01', 'competition-24-03-02', 'competition-24-03-03'])
        self.assertEqual([e['start'] for e in result], [None] * 4)
        self.assertEqual([e['end'] for e in result], [None] * 4)
        self.assertIn('2Tq', result[2]['note'])
        self.assertEqual(result[3]['protocolCode'], '1A')


if __name__ == '__main__':
    unittest.main()
