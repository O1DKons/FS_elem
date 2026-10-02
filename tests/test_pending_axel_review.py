import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publish_pending_axel_review as publisher


class PendingReviewTests(unittest.TestCase):
    def test_known_answer_is_not_requested_again(self):
        manifest = {'items': [{'id': 'a', 'sourceSha256': 'a'*64}, {'id': 'b', 'sourceSha256': 'b'*64}]}
        reconciliation = {'alreadyKnownFromExactEventReviews': [{'id': 'a', 'sourceSha256': 'a'*64, 'label': '1A'}],
                          'pendingExactCandidateAnswers': [{'id': 'b', 'sourceSha256': 'b'*64}]}
        pending, known = publisher.pending_items(manifest, reconciliation)
        self.assertEqual([row['id'] for row in pending], ['b'])
        self.assertEqual(known['a']['label'], '1A')

    def test_incomplete_reconciliation_cannot_silently_hide_candidate(self):
        manifest = {'items': [{'id': 'a', 'sourceSha256': 'a'*64}]}
        with self.assertRaises(ValueError):
            publisher.pending_items(manifest, {'alreadyKnownFromExactEventReviews': [], 'pendingExactCandidateAnswers': []})


if __name__ == '__main__':
    unittest.main()
