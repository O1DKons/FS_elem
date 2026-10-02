import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from evaluate_full_program_scan import evaluate


SOURCE = "a" * 64


def scan(candidates):
    return {
        "schemaVersion": 1,
        "sourceSha256": SOURCE,
        "duration": 40.0,
        "candidates": candidates,
    }


def review(events, *, coverage=True, source=SOURCE):
    return {
        "schemaVersion": 1,
        "reviewId": "competition-20-full-program",
        "sourceSha256": source,
        "durationSeconds": 40.0,
        "fps": 10.0,
        "coverageReviewed": coverage,
        "events": events,
    }


def event(event_id, kind, start, end, code="", rotation="not_applicable"):
    return {
        "id": event_id,
        "eventClass": kind,
        "elementCode": code,
        "rotationAssessment": rotation,
        "lastContactFrame": start,
        "firstContactFrame": end,
    }


def candidate(start, end, element="1A", margin=0.2):
    return {
        "start": start,
        "end": end,
        "elementProposal": element,
        "uncalibratedMargin": margin,
    }


class FullProgramEvaluationTests(unittest.TestCase):
    def test_one_to_one_axel_recall_and_candidate_precision_are_separate(self):
        result = evaluate(
            scan([
                candidate(10, 12, "1A"),
                candidate(20, 22, "2A"),
                candidate(37, 39, "1A"),
            ]),
            review([
                event("a1", "axel", 100, 110, "1A", "apparently_complete"),
                event("o1", "other_jump", 200, 220, "2F"),
                event("a2", "axel", 300, 310, "2A", "apparently_short"),
            ]),
        )

        self.assertEqual(result["metrics"]["expertAxels"], 2)
        self.assertEqual(result["metrics"]["detectedAxels"], 1)
        self.assertEqual(result["metrics"]["axelRecall"], 0.5)
        self.assertEqual(result["metrics"]["candidatePrecision"], 1 / 3)
        self.assertEqual(result["metrics"]["correctElementTypeAmongDetected"], 1.0)
        self.assertEqual(result["metrics"]["falsePositiveCandidates"], 2)
        self.assertEqual(result["falsePositiveCandidateIndices"], [1, 2])
        self.assertEqual(result["metrics"]["falsePositiveProposalsPerMinute"], 3.0)
        self.assertEqual(result["rotationLabelCounts"], {
            "apparently_complete": 1,
            "apparently_short": 1,
            "unclear": 0,
        })

    def test_axel_sign_suffix_is_preserved_but_type_scoring_uses_nominal_jump(self):
        result = evaluate(
            scan([candidate(10, 11, "2A")]),
            review([event("a1", "axel", 100, 110, "2A<<", "apparently_short")]),
        )
        self.assertEqual(result["matches"][0]["expertElement"], "2A")
        self.assertEqual(result["matches"][0]["expertElementCode"], "2A<<")
        self.assertTrue(result["matches"][0]["elementTypeCorrect"])
        self.assertEqual(result["rotationLabelCounts"]["apparently_short"], 1)

    def test_duplicate_proposals_do_not_count_one_axel_twice(self):
        result = evaluate(
            scan([candidate(10, 12), candidate(10.25, 11.75)]),
            review([event("a1", "axel", 100, 110, "1A", "apparently_short")]),
        )
        self.assertEqual(result["metrics"]["detectedAxels"], 1)
        self.assertEqual(result["metrics"]["falsePositiveCandidates"], 1)

    def test_matching_uses_augmenting_path_to_preserve_both_axels(self):
        result = evaluate(
            scan([candidate(10, 20), candidate(11.5, 12.5)]),
            review([
                event("a1", "axel", 119, 121, "1A", "apparently_short"),
                event("a2", "axel", 179, 181, "1A", "apparently_complete"),
            ]),
        )
        self.assertEqual(result["metrics"]["detectedAxels"], 2)
        self.assertEqual(result["metrics"]["candidatePrecision"], 1.0)

    def test_candidate_window_includes_exact_event_midpoint_boundaries(self):
        result = evaluate(
            scan([candidate(12, 13)]),
            review([event("a1", "axel", 110, 130, "1A", "apparently_short")]),
        )
        self.assertEqual(result["metrics"]["detectedAxels"], 1)

    def test_rejects_missing_or_malformed_source_digest_and_review_id(self):
        model = scan([])
        for bad_review in (
            {**review([]), "sourceSha256": None},
            {**review([]), "sourceSha256": "not-a-digest"},
            {**review([]), "reviewId": ""},
        ):
            with self.subTest(review=bad_review):
                with self.assertRaises(ValueError):
                    evaluate(model, bad_review)

    def test_rejects_non_object_rows_and_boolean_numeric_values(self):
        with self.assertRaisesRegex(ValueError, "JSON objects"):
            evaluate([], review([]))
        with self.assertRaisesRegex(ValueError, "candidate row"):
            evaluate(scan(["not an object"]), review([]))
        with self.assertRaisesRegex(ValueError, "event row"):
            evaluate(scan([]), review([None]))
        with self.assertRaisesRegex(ValueError, "candidate interval"):
            evaluate(scan([candidate(True, 12)]), review([]))
        with self.assertRaisesRegex(ValueError, "fps"):
            evaluate(scan([]), {**review([]), "fps": True})

    def test_proposals_on_uncertain_events_are_reported_separately(self):
        result = evaluate(
            scan([candidate(10, 12), candidate(25, 27)]),
            review([
                event("u1", "uncertain", 100, 110),
                event("a1", "axel", 250, 260, "1A", "apparently_complete"),
            ]),
        )
        self.assertEqual(result["metrics"]["unresolvedCandidates"], 1)
        self.assertEqual(result["metrics"]["knownCandidateCount"], 1)
        self.assertEqual(result["metrics"]["candidatePrecision"], 1.0)

    def test_rejects_incomplete_or_mismatched_manual_review(self):
        model = scan([])
        with self.assertRaisesRegex(ValueError, "complete program"):
            evaluate(model, review([], coverage=False))
        with self.assertRaisesRegex(ValueError, "source SHA-256"):
            evaluate(model, review([], source="b" * 64))

    def test_rejects_invalid_contact_order(self):
        with self.assertRaisesRegex(ValueError, "contact frames"):
            evaluate(scan([]), review([event("a1", "axel", 20, 20, "1A", "unclear")]))


if __name__ == "__main__":
    unittest.main()
