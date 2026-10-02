#!/usr/bin/env python3
"""Post-hoc athlete-out audit of the frozen MotionBERT yaw features alone."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "work/motionbert-rotation-probe-v1/results.json"
FEATURE_NAMES = [
    "shoulder_signed_yaw_change_degrees",
    "shoulder_absolute_yaw_change_degrees",
    "hip_signed_yaw_change_degrees",
    "hip_absolute_yaw_change_degrees",
]
LABELS = {"apparently_complete", "apparently_short"}


def evaluate_records(records):
    if not isinstance(records, list) or not records:
        raise ValueError("records must be a non-empty array")

    attempt_ids, athletes, truth, features = set(), [], [], []
    for index, row in enumerate(records):
        if not isinstance(row, dict):
            raise ValueError(f"invalid record at index {index}")
        attempt_id = row.get("attemptId")
        athlete = row.get("athlete")
        label = row.get("visualTruth")
        values = row.get("featureValues")
        if not isinstance(attempt_id, str) or not attempt_id.strip() or attempt_id in attempt_ids:
            raise ValueError(f"attemptId values must be unique non-empty strings (row {index})")
        attempt_ids.add(attempt_id)
        if not isinstance(athlete, str) or not athlete.strip():
            raise ValueError(f"athlete group is missing at index {index}")
        if label not in LABELS:
            raise ValueError(f"invalid visual target at index {index}")
        if (not isinstance(values, list) or len(values) != len(FEATURE_NAMES)
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not np.isfinite(value) for value in values)):
            raise ValueError(f"expected four finite yaw features at index {index}")
        athletes.append(athlete)
        truth.append(int(label == "apparently_short"))
        features.append(values)

    if len(set(truth)) < 2:
        raise ValueError("both visual target classes are required")

    from run_rotation_proxy_baseline import evaluate

    x = np.asarray(features, dtype=float)
    y = np.asarray(truth, dtype=int)
    groups = np.asarray(athletes)
    model = evaluate(x, y, groups)
    majority = evaluate(x[:, :1], y, groups, majority=True)
    folds = []
    for row in model["folds"]:
        held_out = row["heldOutAthlete"]
        train_groups = sorted({athletes[i] for i in row["trainIndices"]})
        test_groups = sorted({athletes[i] for i in row["testIndices"]})
        if held_out not in test_groups or held_out in train_groups:
            raise ValueError("athlete leakage in yaw-only evaluation folds")
        folds.append({
            "heldOutAthlete": held_out,
            "trainIndices": row["trainIndices"],
            "testIndices": row["testIndices"],
            "trainingAthletes": train_groups,
            "trainingClassCounts": row["trainingClassCounts"],
        })

    return {
        "schemaVersion": 1,
        "scope": "Post-hoc exploratory re-evaluation of the existing same-event 20-attempt set; not independent validation.",
        "method": "Four frozen MotionBERT yaw summaries only; train-fold mean imputation/standardization and equal-distance nearest class centroid; one held-out athlete per fold; no tuning.",
        "featureNames": FEATURE_NAMES,
        "n": len(records),
        "athleteCount": len(set(athletes)),
        "classCounts": {
            "apparently_complete": int(np.sum(y == 0)),
            "apparently_short": int(np.sum(y == 1)),
        },
        "yawOnly": {
            "metrics": model["metrics"],
            "predictions": model["predictions"],
        },
        "foldTrainingMajority": {"metrics": majority["metrics"]},
        "folds": folds,
        "rows": [
            {"attemptId": row["attemptId"], "athlete": row["athlete"],
             "visualTruth": row["visualTruth"], "featureValues": row["featureValues"],
             "prediction": prediction}
            for row, prediction in zip(records, model["predictions"])
        ],
        "limitations": [
            "Same inspected competition and labels used in previous feature/model comparisons; this diagnostic is post hoc and non-confirmatory.",
            "Camera-space torso-axis yaw is not blade orientation, physical underrotation degrees, or a validated revolution count.",
            "Only five complete and fifteen short examples from one event; apparent athlete-out folds do not establish cross-event or population transfer.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output", type=Path, default=ROOT / "work/motionbert-yaw-only-v1/results.json")
    args = parser.parse_args()
    input_path = args.input.resolve()
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    if output_path.exists():
        raise ValueError(f"Refusing to overwrite existing audit: {output_path}")
    source = json.loads(input_path.read_text(encoding="utf-8"))
    if source.get("schemaVersion") != 1 or not isinstance(source.get("records"), list):
        raise ValueError("unsupported MotionBERT result schema")
    result = evaluate_records(source["records"])
    result["inputSha256"] = hashlib.sha256(input_path.read_bytes()).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "yawOnly": result["yawOnly"]["metrics"],
        "foldTrainingMajority": result["foldTrainingMajority"]["metrics"],
    }, indent=2))


if __name__ == "__main__":
    main()
