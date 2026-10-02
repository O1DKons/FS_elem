import copy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "work/full-program-flight-transfer-v1/review_validation.py"
spec = importlib.util.spec_from_file_location("transfer_review_validation", MODULE_PATH)
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)

SOURCE = "a" * 64


def target():
    return {
        "videoId": "new12",
        "sourceSha256": SOURCE,
        "sourceMetadata": {"sourceFrames": 1000, "fps": 50.0},
    }


def event(identifier="a", kind="axel", last=50, first=75, code="1A"):
    return {
        "id": identifier,
        "eventClass": kind,
        "elementCode": code,
        "rotationAssessment": "",
        "lastContactFrame": last,
        "firstContactFrame": first,
    }


def review(events=None):
    return {
        "schemaVersion": 1,
        "reviewId": "new-program-12-full-program",
        "sourceSha256": SOURCE,
        "durationSeconds": 20.0,
        "fps": 50.0,
        "coverageReviewed": True,
        "events": [event()] if events is None else events,
    }


class TransferReviewValidationTests(unittest.TestCase):
    def test_converts_contacts_to_class_preserving_seconds_without_mutation(self):
        document = review([
            event("other", "other_jump", 150, 175, "2Tq"),
            event("axel", "axel", 50, 75, "2A<<"),
            event("unknown", "uncertain", 250, 300, ""),
        ])
        document["events"][0]["rotationAssessment"] = "apparently_short"
        document["events"][1]["rotationAssessment"] = "apparently_complete"
        before = copy.deepcopy(document)
        source = target()
        source_before = copy.deepcopy(source)
        self.assertEqual(validation.validated_events(document, source), [
            {"id": "other", "eventClass": "other_jump", "start": 3.0, "end": 3.5},
            {"id": "axel", "eventClass": "axel", "start": 1.0, "end": 1.5},
            {"id": "unknown", "eventClass": "uncertain", "start": 5.0, "end": 6.0},
        ])
        self.assertEqual(document, before)
        self.assertEqual(source, source_before)

    def test_requires_integer_schema_one_and_explicit_complete_coverage(self):
        for key, values in (
            ("schemaVersion", (None, True, 1.0, "1", 2)),
            ("coverageReviewed", (None, False, 1, "true")),
        ):
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validation.validated_events({**review(), key: value}, target())

    def test_rejects_source_mismatch_and_missing_hash(self):
        for source in ("b" * 64, "", None):
            with self.subTest(source=source), self.assertRaises(ValueError):
                validation.validated_events({**review(), "sourceSha256": source}, target())
        with self.assertRaises(ValueError):
            validation.validated_events({**review(), "sourceSha256": None},
                                        {**target(), "sourceSha256": None})

    def test_review_identity_is_derived_from_target_video(self):
        for identifier in ("new-program-14-full-program", "new12", "", None):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                validation.validated_events({**review(), "reviewId": identifier}, target())
        self.assertEqual(len(validation.validated_events(
            {**review(), "reviewId": "new-program-14-full-program"},
            {**target(), "videoId": "new14"})), 1)
        with self.assertRaises(ValueError):
            validation.validated_events(review(), {**target(), "videoId": "other12"})

    def test_fps_must_be_numeric_positive_finite_and_match_source(self):
        for fps in (True, "50", None, 0, -50, float("nan"), float("inf"), 25.0,
                    50.00000002):
            with self.subTest(fps=fps), self.assertRaises(ValueError):
                validation.validated_events({**review(), "fps": fps}, target())
        self.assertEqual(len(validation.validated_events(
            {**review(), "fps": 50.000000005}, target())), 1)

    def test_duration_must_be_numeric_positive_finite_and_match_frame_count(self):
        for duration in (True, "20", None, 0, -20, float("nan"), float("inf"),
                         19.749, 20.251):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                validation.validated_events({**review(), "durationSeconds": duration}, target())
        for duration in (19.75, 20.25):
            with self.subTest(duration=duration):
                self.assertEqual(len(validation.validated_events(
                    {**review(), "durationSeconds": duration}, target())), 1)

    def test_frames_use_source_frame_count_even_when_duration_is_tolerated(self):
        self.assertEqual(validation.validated_events(
            review([event(last=0, first=999)]), target()),
            [{"id": "a", "eventClass": "axel", "start": 0.0, "end": 19.98}])
        with self.assertRaises(ValueError):
            validation.validated_events(
                {**review([event(last=999, first=1000)]), "durationSeconds": 20.25}, target())

    def test_rejects_non_integer_boolean_negative_reversed_and_outside_contacts(self):
        for last, first in ((True, 75), (50, True), (50.0, 75), (50, 75.0),
                            ("50", 75), (None, 75), (50, float("inf")),
                            (float("nan"), 75), (-1, 75), (50, 50),
                            (75, 50), (50, 1000), (1000, 1001)):
            with self.subTest(last=last, first=first), self.assertRaises(ValueError):
                validation.validated_events(review([event(last=last, first=first)]), target())

    def test_requires_list_of_event_objects_with_nonempty_unique_ids(self):
        for events in (None, {}, "events", [None], ["event"],
                       [event(identifier="")], [event(identifier="  ")],
                       [event(identifier=1)], [event(), event(last=100, first=125)]):
            with self.subTest(events=events), self.assertRaises(ValueError):
                validation.validated_events({**review(), "events": events}, target())
        self.assertEqual(validation.validated_events(review([]), target()), [])

    def test_rejects_unknown_event_class(self):
        for kind in (None, "jump", "Axel", []):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validation.validated_events(review([event(kind=kind)]), target())

    def test_overlapping_confirmed_flights_are_rejected_independent_of_order(self):
        for events in (
            [event("a", last=50, first=100), event("b", "other_jump", 75, 125, "2F")],
            [event("b", "other_jump", 75, 125, "2F"), event("a", last=50, first=100)],
            [event("outer", last=50, first=150), event("inner", last=75, first=100)],
        ):
            with self.subTest(events=events), self.assertRaises(ValueError):
                validation.validated_events(review(events), target())

    def test_touching_confirmed_flights_and_uncertain_overlaps_are_allowed(self):
        document = review([
            event("a", last=50, first=100),
            event("unknown", "uncertain", 40, 160, ""),
            event("b", "other_jump", 100, 150, "2T"),
        ])
        self.assertEqual(len(validation.validated_events(document, target())), 3)

    def test_axel_accepts_nominal_and_q_underrotation_suffixes_case_insensitively(self):
        for code in ("1A", "2Aq", "3A<", "4A<<", "2aQ", "3a<"):
            with self.subTest(code=code):
                self.assertEqual(validation.validated_events(review([event(code=code)]), target()),
                                 [{"id": "a", "eventClass": "axel", "start": 1.0, "end": 1.5}])

    def test_axel_rejects_invalid_nominal_codes_or_suffixes(self):
        for code in ("", None, 1, "0A", "5A", "2F", "2A<<<", "2Aq<", "A2"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                validation.validated_events(review([event(code=code)]), target())

    def test_other_jump_rejects_contradictory_axel_codes(self):
        for code in ("1A", "2Aq", "3a<", "4A<<"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                validation.validated_events(review([event(kind="other_jump", code=code)]), target())

    def test_other_and_uncertain_codes_and_rotation_assessments_do_not_become_features(self):
        for kind in ("other_jump", "uncertain"):
            for code in ("", "2F", "2Tq", "2Lz", "custom-code"):
                row = event(kind=kind, code=code)
                del row["rotationAssessment"]
                with self.subTest(kind=kind, code=code):
                    self.assertEqual(validation.validated_events(review([row]), target()),
                                     [{"id": "a", "eventClass": kind, "start": 1.0, "end": 1.5}])

    def test_rejects_non_object_documents_and_invalid_target_timebase(self):
        for document, source in ((None, target()), ([], target()), (review(), None),
                                 (review(), {**target(), "sourceMetadata": None})):
            with self.subTest(document=document, source=source), self.assertRaises(ValueError):
                validation.validated_events(document, source)
        for key, values in (("sourceFrames", (True, 0, -1, 1000.0, None)),
                            ("fps", (True, 0, float("nan"), float("inf"), None))):
            for value in values:
                source = target()
                source["sourceMetadata"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validation.validated_events(review(), source)


if __name__ == "__main__":
    unittest.main()
