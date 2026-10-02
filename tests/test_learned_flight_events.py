import importlib.util
from pathlib import Path
import unittest

import numpy as np


MODULE_PATH = (Path(__file__).resolve().parents[1]
               / "work/full-program-learned-flight-v1/events.py")
spec = importlib.util.spec_from_file_location("learned_flight_events", MODULE_PATH)
events_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(events_module)


def event(identifier, start, end, kind="axel"):
    return dict(id=identifier, start=start, end=end, eventClass=kind)


def proposal(start, end):
    return dict(start=start, end=end)


class LearnedFlightEventsTests(unittest.TestCase):
    def decode(self, times, probability, usable=None, duration=10):
        if usable is None:
            usable = np.ones(len(times), dtype=bool)
        return events_module.decode_events(times, probability, usable, duration)

    def evaluate(self, proposals, events, exhaustive=True, duration=10):
        return events_module.evaluate_events(proposals, events, duration, exhaustive)

    def test_no_positive_samples_do_not_force_an_event(self):
        self.assertEqual(self.decode([0, 1, 2], [0.2, 0.5, 0.1]), [])
        self.assertEqual(self.decode([], []), [])

    def test_two_runs_preserve_midpoint_boundaries_and_peak_probability(self):
        result = self.decode([0, 1, 2, 3, 4, 5, 6],
                             [0.1, 0.7, 0.9, 0.2, 0.8, 0.6, 0.1])
        self.assertEqual(result, [
            dict(start=0.5, end=2.5, peakTime=2.0, startSample=1, endSample=2),
            dict(start=3.5, end=5.5, peakTime=4.0, startSample=4, endSample=5),
        ])

    def test_missing_probability_and_unusable_pose_each_break_runs(self):
        result = self.decode(np.arange(8), [0.9, 0.8, np.nan, 0.7, 0.8, 0.9, 0.8, 0.9],
                             [True, True, True, True, True, False, True, True])
        self.assertEqual([(r["startSample"], r["endSample"]) for r in result],
                         [(0, 1), (3, 4), (6, 7)])

    def test_single_positive_sample_is_rejected_but_two_are_retained(self):
        self.assertEqual(self.decode([0, 1, 2], [0.1, 0.9, 0.1]), [])
        self.assertEqual(len(self.decode([0, 1], [0.9, 0.9])), 1)
        self.assertEqual(self.decode([0], [0.9]), [])

    def test_probability_equal_half_breaks_a_run(self):
        self.assertEqual(self.decode([0, 1, 2], [0.9, 0.5, 0.9]), [])

    def test_outer_boundaries_are_clamped_to_source(self):
        result = self.decode([0, 1, 2], [0.9, 0.9, 0.9], duration=2.2)
        self.assertEqual(result[0]["start"], 0.0)
        self.assertEqual(result[0]["end"], 2.2)
        self.assertEqual(result[0]["peakTime"], 0.0)

    def test_irregular_spacing_uses_actual_internal_midpoints(self):
        result = self.decode([0, 1, 3, 6], [0.1, 0.9, 0.8, 0.1])
        self.assertEqual((result[0]["start"], result[0]["end"]), (0.5, 4.5))

    def test_nonincreasing_or_nonfinite_times_are_rejected(self):
        for times in ([0, 0], [1, 0], [0, np.nan], [-1, 0], [0, 11]):
            with self.subTest(times=times), self.assertRaises(ValueError):
                self.decode(times, [0.8, 0.8])

    def test_shape_probability_mask_and_duration_contracts_are_checked(self):
        for probability in ([0.9], [-0.1, 0.9], [0.9, 1.1], [np.inf, 0.9]):
            with self.subTest(probability=probability), self.assertRaises(ValueError):
                self.decode([0, 1], probability)
        with self.assertRaises(ValueError):
            self.decode([0, 1], [0.9, 0.9], [1, 1])
        for duration in (0, -1, np.inf, np.nan):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                self.decode([0, 1], [0.9, 0.9], duration=duration)

    def test_jump_precision_does_not_relabel_other_jumps_as_axels(self):
        result = self.evaluate([proposal(1, 2), proposal(3, 4), proposal(8, 9)],
                               [event("a", 1, 2), event("o", 3, 4, "other_jump"),
                                event("missed", 5, 6)])
        metrics = result["metrics"]
        self.assertEqual(metrics["matchedEvents"], 2)
        self.assertEqual(metrics["eventRecall"], 2 / 3)
        self.assertEqual(metrics["axelRecall"], 0.5)
        self.assertEqual(metrics["candidatePrecision"], 2 / 3)
        self.assertEqual(metrics["eventF1"], 2 / 3)
        self.assertEqual(metrics["falsePositiveProposalsPerMinute"], 6.0)
        self.assertEqual(result["falsePositiveProposalIndices"], [2])
        self.assertEqual({r["eventClass"] for r in result["matches"]}, {"axel", "other_jump"})

    def test_augmenting_path_recovers_both_events(self):
        result = self.evaluate([proposal(0.5, 2.0), proposal(0.6, 1.4)],
                               [event("a", 0.6, 1.4), event("b", 1.2, 2.0)])
        self.assertEqual(result["metrics"]["matchedEvents"], 2)
        self.assertEqual({r["proposalIndex"]: r["eventId"] for r in result["matches"]},
                         {0: "b", 1: "a"})

    def test_exact_midpoint_boundary_and_exact_iou_cutoff_are_inclusive(self):
        result = self.evaluate([proposal(0, 1), proposal(3, 5.5)],
                               [event("edge", 0.5, 1.5), event("iou", 4, 4.75)])
        self.assertEqual(result["metrics"]["matchedEvents"], 2)
        self.assertAlmostEqual(result["matches"][0]["intervalIoU"], 1 / 3)
        self.assertEqual(result["matches"][1]["intervalIoU"], 0.3)

    def test_large_interval_containing_midpoint_fails_iou(self):
        result = self.evaluate([proposal(0, 10)], [event("a", 4, 5)])
        self.assertEqual(result["metrics"]["matchedEvents"], 0)
        self.assertEqual(result["metrics"]["eventF1"], 0.0)

    def test_matching_reports_signed_boundary_errors(self):
        result = self.evaluate([proposal(0.5, 2.5)], [event("a", 1, 2)])
        match = result["matches"][0]
        self.assertEqual(match["intervalIoU"], 0.5)
        self.assertEqual(match["takeoffBoundaryErrorSeconds"], -0.5)
        self.assertEqual(match["landingBoundaryErrorSeconds"], 0.5)
        self.assertEqual(match["centerErrorSeconds"], 0.0)

    def test_partial_annotation_never_reports_precision_or_false_positives(self):
        result = self.evaluate([proposal(1, 2), proposal(7, 8)], [event("a", 1, 2)],
                               exhaustive=False)
        self.assertEqual(result["metrics"]["eventRecall"], 1.0)
        for key in ("candidatePrecision", "falsePositiveCandidates",
                    "falsePositiveProposalsPerMinute", "eventF1"):
            self.assertIsNone(result["metrics"][key])
        self.assertIsNone(result["falsePositiveProposalIndices"])

    def test_uncertain_event_is_excluded_without_hiding_duplicate_known_detection(self):
        result = self.evaluate([proposal(1, 2), proposal(1, 2), proposal(5, 6)],
                               [event("a", 1, 2), event("u1", 1, 2, "uncertain"),
                                event("u2", 5, 6, "uncertain")])
        self.assertEqual(result["metrics"]["annotatedEvents"], 1)
        self.assertEqual(result["metrics"]["unresolvedCandidates"], 1)
        self.assertEqual(result["metrics"]["candidatePrecision"], 0.5)
        self.assertEqual(result["metrics"]["falsePositiveCandidates"], 1)
        self.assertEqual(result["unresolvedProposalIndices"], [2])

    def test_no_events_and_no_proposals_have_undefined_recall_precision(self):
        result = self.evaluate([], [])
        self.assertIsNone(result["metrics"]["eventRecall"])
        self.assertIsNone(result["metrics"]["axelRecall"])
        self.assertIsNone(result["metrics"]["candidatePrecision"])
        self.assertIsNone(result["metrics"]["eventF1"])
        self.assertEqual(result["metrics"]["falsePositiveCandidates"], 0)

    def test_invalid_intervals_duplicate_ids_and_unknown_classes_are_rejected(self):
        for proposals, events in [([proposal(2, 1)], []),
                                  ([proposal(0, 11)], []),
                                  ([], [event("a", 1, 2), event("a", 3, 4)]),
                                  ([], [event("a", 1, 2, "unreviewed")])]:
            with self.subTest(proposals=proposals, events=events), self.assertRaises(ValueError):
                self.evaluate(proposals, events)


if __name__ == "__main__":
    unittest.main()
