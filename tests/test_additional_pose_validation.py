import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


VALIDATOR = (Path(__file__).resolve().parents[1] / "work" /
             "full-program-additional-pose-v1" / "validate.py")


def fixture():
    item = {
        "videoId": "new12", "sourcePath": "/original/program.mp4",
        "sourceSha256": "a" * 64, "sourceBytes": 7,
        "sourceMetadata": {"sourceFrames": 13, "fps": 50.0,
                           "width": 1280, "height": 720},
        "expectedSampledFrames": 3, "stepSourceFrames": 6,
        "actualSampleRate": 50.0 / 6,
        "outputPath": "/output/new12.json",
    }
    model = {"device": "cpu", "rtmlibVersion": "0.0.15", "checkpointFiles": [
        {"kind": "detector", "sha256": "b" * 64},
        {"kind": "pose", "sha256": "c" * 64},
    ]}
    names = ("nose", "left_eye", "right_eye", "left_ear", "right_ear",
             "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
             "left_wrist", "right_wrist", "left_hip")
    points = [{"name": name, "x": 0.4, "y": 0.6, "confidence": 0.8}
              for name in names]
    pose = {
        "schemaVersion": 1,
        "source": {"path": item["sourcePath"], "sha256": item["sourceSha256"],
                   "fps": 50.0, "frameCount": 13, "durationSeconds": 0.24,
                   "width": 1280, "height": 720},
        "sampling": {"requestedFps": 8.333333, "stepSourceFrames": 6,
                     "actualRate": 50.0 / 6},
        "model": {"name": "RTMW-dw-x-l WholeBody via RTMLib", "device": "cpu",
                  "rtmlibVersion": "0.0.15", "detectorSha256": "b" * 64,
                  "poseSha256": "c" * 64},
        "timing": {"sampledFrames": 3, "poseFrames": 1,
                   "wallSeconds": 1.0, "poseInferenceSeconds": 0.8},
        "frames": [
            {"sampleIndex": 0, "frameIndex": 0, "time": 0.0,
             "bbox": [10, 20, 200, 400], "bodyHeight": 380,
             "trackingStatus": "pose", "landmarks": points},
            {"sampleIndex": 1, "frameIndex": 6, "time": 0.12,
             "bbox": [10, 20, 200, 400], "bodyHeight": 380,
             "trackingStatus": "low_pose_coverage", "landmarks": points[:2]},
            {"sampleIndex": 2, "frameIndex": 12, "time": 0.24,
             "bbox": None, "bodyHeight": None,
             "trackingStatus": "no_person_detection", "landmarks": []},
        ],
    }
    return copy.deepcopy((pose, item, model))


class AdditionalPoseValidationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(VALIDATOR.is_file(), "additional pose validator is not implemented")
        spec = importlib.util.spec_from_file_location("additional_pose_validation", VALIDATOR)
        self.validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.validator)
        self.pose, self.item, self.model = fixture()

    def validate(self):
        return self.validator.validate_pose(self.pose, self.item, self.model)

    def test_reports_observed_status_counts_without_mutating_inputs(self):
        before = copy.deepcopy((self.pose, self.item, self.model))
        report = self.validate()
        self.assertEqual(report["status"], "validated")
        self.assertEqual(report["sampledFrames"], 3)
        self.assertEqual(report["poseFrames"], 1)
        self.assertEqual(report["statusCounts"], {
            "pose": 1, "low_pose_coverage": 1, "no_person_detection": 1})
        self.assertEqual(report["landmarkCount"], 14)
        self.assertNotIn("accuracy", report)
        self.assertEqual((self.pose, self.item, self.model), before)

    def test_rejects_source_path_or_hash_mismatch(self):
        for field, value in (("path", "/other.mp4"), ("sha256", "d" * 64)):
            with self.subTest(field=field):
                self.pose, self.item, self.model = fixture()
                self.pose["source"][field] = value
                with self.assertRaisesRegex(ValueError, field):
                    self.validate()

    def test_rejects_wrong_source_metadata(self):
        for field, value in (("fps", 25.0), ("frameCount", 14),
                             ("width", 640), ("height", 480),
                             ("durationSeconds", 13 / 50)):
            with self.subTest(field=field):
                self.pose, self.item, self.model = fixture()
                self.pose["source"][field] = value
                with self.assertRaisesRegex(ValueError, field):
                    self.validate()

    def test_rejects_reordered_source_frames_even_when_times_are_sorted(self):
        self.pose["frames"][1]["frameIndex"] = 12
        self.pose["frames"][2]["frameIndex"] = 6
        with self.assertRaisesRegex(ValueError, "frameIndex"):
            self.validate()

    def test_rejects_missing_frames_even_when_timing_count_is_rewritten(self):
        self.pose["frames"].pop()
        self.pose["timing"]["sampledFrames"] = 2
        with self.assertRaisesRegex(ValueError, "sampled|frames"):
            self.validate()

    def test_rejects_noncontiguous_sample_indices(self):
        self.pose["frames"][1]["sampleIndex"] = 2
        with self.assertRaisesRegex(ValueError, "sampleIndex"):
            self.validate()

    def test_rejects_wrong_expected_frame_count_in_plan(self):
        self.item["expectedSampledFrames"] = 2
        with self.assertRaisesRegex(ValueError, "expectedSampledFrames"):
            self.validate()

    def test_rejects_wrong_sampling_metadata(self):
        for field, value in (("requestedFps", 10), ("stepSourceFrames", 5),
                             ("actualRate", 8.3)):
            with self.subTest(field=field):
                self.pose, self.item, self.model = fixture()
                self.pose["sampling"][field] = value
                with self.assertRaisesRegex(ValueError, field):
                    self.validate()

    def test_rejects_wrong_timebase_nonfinite_or_repeated_timestamps(self):
        for value in (0.126, 0.0, float("nan"), float("inf"), "0.12", True):
            with self.subTest(value=value):
                self.pose, self.item, self.model = fixture()
                self.pose["frames"][1]["time"] = value
                with self.assertRaisesRegex(ValueError, "time"):
                    self.validate()

    def test_accepts_timestamp_rounding_within_five_milliseconds(self):
        self.pose["frames"][1]["time"] = 0.125
        self.assertEqual(self.validate()["sampledFrames"], 3)

    def test_rejects_changed_or_missing_model_identity(self):
        for field in ("detectorSha256", "poseSha256", "rtmlibVersion", "device"):
            for missing in (False, True):
                with self.subTest(field=field, missing=missing):
                    self.pose, self.item, self.model = fixture()
                    if missing:
                        del self.pose["model"][field]
                    else:
                        self.pose["model"][field] = "changed"
                    with self.assertRaisesRegex(ValueError, field):
                        self.validate()

    def test_rejects_duplicate_landmark_names(self):
        self.pose["frames"][0]["landmarks"][1]["name"] = "nose"
        with self.assertRaisesRegex(ValueError, "name"):
            self.validate()

    def test_rejects_nonfinite_or_unnormalized_landmarks(self):
        for field in ("x", "y", "confidence"):
            for value in (-0.01, 1.01, float("nan"), float("inf"), "0.5", True):
                with self.subTest(field=field, value=value):
                    self.pose, self.item, self.model = fixture()
                    self.pose["frames"][0]["landmarks"][0][field] = value
                    with self.assertRaisesRegex(ValueError, field):
                        self.validate()

    def test_rejects_unknown_tracking_status(self):
        self.pose["frames"][0]["trackingStatus"] = "full_frame_fallback"
        with self.assertRaisesRegex(ValueError, "trackingStatus"):
            self.validate()

    def test_no_detection_must_have_empty_landmarks(self):
        self.pose["frames"][2]["landmarks"] = self.pose["frames"][1]["landmarks"]
        with self.assertRaisesRegex(ValueError, "no_person_detection"):
            self.validate()

    def test_rejects_misleading_timing_counts(self):
        for field in ("sampledFrames", "poseFrames"):
            with self.subTest(field=field):
                self.pose, self.item, self.model = fixture()
                self.pose["timing"][field] = 10
                with self.assertRaisesRegex(ValueError, field):
                    self.validate()

    def test_malformed_required_structure_raises_value_error(self):
        for field in ("source", "sampling", "frames", "model", "timing"):
            with self.subTest(field=field):
                self.pose, self.item, self.model = fixture()
                del self.pose[field]
                with self.assertRaises(ValueError):
                    self.validate()

    def test_file_validation_hashes_source_and_json_readonly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"source!")
            self.item.update(sourcePath=str(source),
                             sourceSha256=hashlib.sha256(b"source!").hexdigest())
            self.pose["source"].update(path=str(source), sha256=self.item["sourceSha256"])
            output = root / "pose.json"
            output.write_text(json.dumps(self.pose))
            original = output.read_bytes()
            report = self.validator.validate_file(output, self.item, self.model)
            self.assertEqual(report["outputSha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(source.read_bytes(), b"source!")
            source.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "[Ss]ource.*[Hh]ash|[Ss]ource.*sha256"):
                self.validator.validate_file(output, self.item, self.model)

    def run_cli(self, present, corrupt=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"source!")
            items = []
            for index, video_id in enumerate(("new12", "new14", "new15")):
                pose, item, model = fixture()
                output = root / (video_id + ".json")
                item.update(videoId=video_id, outputPath=str(output), sourcePath=str(source),
                            sourceSha256=hashlib.sha256(b"source!").hexdigest())
                pose["source"].update(path=str(source), sha256=item["sourceSha256"])
                if corrupt and index == 0:
                    pose["frames"][1]["time"] = 5.0
                if index < present:
                    output.write_text(json.dumps(pose))
                items.append(item)
            plan = root / "plan.json"
            plan.write_text(json.dumps({"model": model, "execution": {"items": items}}))
            result = subprocess.run([sys.executable, "-B", str(VALIDATOR), "--plan", str(plan)],
                                    capture_output=True, text=True, timeout=10)
            report = json.loads((root / "verification.json").read_text())
            return result, report

    def test_cli_absent_outputs_are_pending_not_failure(self):
        result, report = self.run_cli(present=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["status"], "pending")
        self.assertEqual(report["validatedCount"], 1)
        self.assertEqual(report["pendingCount"], 2)
        self.assertEqual(report["invalidCount"], 0)

    def test_cli_completes_only_after_all_three_outputs_validate(self):
        result, report = self.run_cli(present=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["validatedCount"], 3)
        self.assertEqual(report["pendingCount"], 0)

    def test_cli_existing_invalid_output_is_reported(self):
        result, report = self.run_cli(present=3, corrupt=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["status"], "invalid")
        self.assertEqual(report["validatedCount"], 2)
        self.assertEqual(report["invalidCount"], 1)

    def test_cli_invalid_output_takes_priority_over_pending_outputs(self):
        result, report = self.run_cli(present=1, corrupt=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["status"], "invalid")
        self.assertEqual(report["validatedCount"], 0)
        self.assertEqual(report["invalidCount"], 1)
        self.assertEqual(report["pendingCount"], 2)
        self.assertEqual([item["videoId"] for item in report["items"]
                          if item["status"] == "pending"], ["new14", "new15"])
        self.assertIn("time", report["items"][0]["error"])


if __name__ == "__main__":
    unittest.main()
