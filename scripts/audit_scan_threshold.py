#!/usr/bin/env python3
"""Nested group-CV audit of a full-program Axel-vs-other score threshold."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRAIN_RESULTS = ROOT / "work/video-type-pilot-v1/results.json"
DEFAULT_TRAIN_MANIFEST = ROOT / "data/skatingverse-pilot-v1/manifest.json"
DEFAULT_SCAN = ROOT / "work/full-program-scan-probe-2026-09-23/comp-20.json"
DEFAULT_REVIEW = ROOT / "work/full-program-scan-probe-2026-09-23/competition-20-full-program-expert-review.json"
DEFAULT_OUTPUT = ROOT / "work/full-program-scan-probe-2026-09-23/threshold-audit-2026-09-23.json"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def binary_margin(scores, classes):
    """Return max(1A/2A/3A score) - other score for each row."""
    values = np.asarray(scores, dtype=float)
    names = [str(name) for name in classes]
    if values.ndim != 2 or values.shape[1] != len(names) or not np.isfinite(values).all():
        raise ValueError("scores must be a finite matrix aligned to classes")
    if len(set(names)) != len(names) or "other" not in names:
        raise ValueError("classes must uniquely include other")
    axel_columns = [index for index, name in enumerate(names) if name in {"1A", "2A", "3A"}]
    if not axel_columns:
        raise ValueError("classes must include at least one Axel type")
    return values[:, axel_columns].max(axis=1) - values[:, names.index("other")]


def select_balanced_threshold(margins, truth):
    """Select score threshold maximizing balanced accuracy; ties prefer higher threshold."""
    margins = np.asarray(margins, dtype=float)
    truth = np.asarray(truth)
    if margins.ndim != 1 or truth.ndim != 1 or len(margins) != len(truth) or not len(truth):
        raise ValueError("margins and truth must be non-empty aligned vectors")
    if not np.isfinite(margins).all() or not np.isin(truth, [0, 1]).all():
        raise ValueError("margins must be finite and truth must be binary")
    if set(truth.tolist()) != {0, 1}:
        raise ValueError("both classes are required to select a balanced threshold")

    values = np.unique(margins)
    thresholds = np.concatenate(([np.nextafter(values[0], -np.inf)], values,
                                 [np.nextafter(values[-1], np.inf)]))
    candidates = []
    for threshold in thresholds:
        predicted = margins > threshold
        recall = float(np.mean(predicted[truth == 1]))
        specificity = float(np.mean(~predicted[truth == 0]))
        candidates.append({
            "threshold": float(threshold),
            "balancedAccuracy": (recall + specificity) / 2,
            "recall": recall,
            "specificity": specificity,
        })
    best_score = max(row["balancedAccuracy"] for row in candidates)
    return max((row for row in candidates if abs(row["balancedAccuracy"] - best_score) < 1e-12),
               key=lambda row: row["threshold"])


def _binary_metrics(truth, predicted):
    truth = np.asarray(truth, dtype=int)
    predicted = np.asarray(predicted, dtype=int)
    recall = float(np.mean(predicted[truth == 1] == 1))
    specificity = float(np.mean(predicted[truth == 0] == 0))
    return {
        "n": len(truth),
        "axels": int(truth.sum()),
        "other": int(len(truth) - truth.sum()),
        "accuracy": float(np.mean(predicted == truth)),
        "balancedAccuracy": (recall + specificity) / 2,
        "recall": recall,
        "specificity": specificity,
        "confusionTrueRowsPredictedColumns": [
            [int(np.sum((truth == label) & (predicted == prediction))) for prediction in (0, 1)]
            for label in (0, 1)
        ],
    }


def nested_group_threshold_cv(features, labels, groups, *, outer_splits=5, inner_splits=4):
    """Estimate threshold selection with outer group holdout and inner OOF tuning."""
    from video_type_model import fit_classifier, grouped_folds, score_classifier

    x = np.asarray(features, dtype=float)
    labels = np.asarray(labels)
    groups = np.asarray(groups)
    if x.ndim != 2 or len(x) != len(labels) or len(labels) != len(groups) or not len(labels):
        raise ValueError("features, labels and groups must be non-empty and aligned")
    if not np.isfinite(x).all() or len(set(labels.tolist())) < 2:
        raise ValueError("features must be finite and labels must contain multiple classes")
    y = (labels != "other").astype(int)
    if set(y.tolist()) != {0, 1}:
        raise ValueError("both Axel and other examples are required")

    prediction = np.zeros(len(y), dtype=int)
    folds = []
    outer = grouped_folds(groups, outer_splits)
    for fold_index, (outer_train, outer_test) in enumerate(outer):
        inner_oof_margin = np.empty(len(outer_train), dtype=float)
        inner = grouped_folds(groups[outer_train], inner_splits)
        for inner_train, inner_test in inner:
            train_indices, test_indices = outer_train[inner_train], outer_train[inner_test]
            model = fit_classifier(x[train_indices], labels[train_indices], "ridge")
            inner_oof_margin[inner_test] = binary_margin(
                score_classifier(model, x[test_indices]), model["classes"]
            )
        selected = select_balanced_threshold(inner_oof_margin, y[outer_train])
        model = fit_classifier(x[outer_train], labels[outer_train], "ridge")
        test_margin = binary_margin(score_classifier(model, x[outer_test]), model["classes"])
        prediction[outer_test] = (test_margin > selected["threshold"]).astype(int)
        train_groups = sorted(set(groups[outer_train].tolist()))
        test_groups = sorted(set(groups[outer_test].tolist()))
        if set(train_groups) & set(test_groups):
            raise ValueError("group leakage in outer threshold-evaluation fold")
        folds.append({
            "fold": fold_index,
            "threshold": selected["threshold"],
            "innerBalancedAccuracy": selected["balancedAccuracy"],
            "innerRecall": selected["recall"],
            "innerSpecificity": selected["specificity"],
            "trainingGroups": train_groups,
            "heldOutGroups": test_groups,
            "testCount": len(outer_test),
        })
    return {"metrics": _binary_metrics(y, prediction), "folds": folds}


def crossfit_threshold(features, labels, groups, *, splits=5):
    """Choose the final threshold from grouped out-of-fold scores on training data."""
    from video_type_model import fit_classifier, grouped_folds, score_classifier

    x, labels, groups = np.asarray(features), np.asarray(labels), np.asarray(groups)
    y = (labels != "other").astype(int)
    margins = np.empty(len(y), dtype=float)
    for train, test in grouped_folds(groups, splits):
        model = fit_classifier(x[train], labels[train], "ridge")
        margins[test] = binary_margin(score_classifier(model, x[test]), model["classes"])
    return select_balanced_threshold(margins, y)


def _proposals_at_threshold(scan, threshold):
    proposals = []
    for row in scan["windows"]:
        scores = row["prediction"]["raw_scores"]
        axel_scores = {name: scores[name] for name in ("1A", "2A", "3A") if name in scores}
        if not axel_scores or "other" not in scores:
            continue
        margin = max(axel_scores.values()) - scores["other"]
        if margin > threshold:
            proposals.append({
                "start": row["start"], "end": row["end"],
                "elementProposal": max(axel_scores, key=axel_scores.get),
                "uncalibratedMargin": margin,
                "rotationAssessment": None, "measuredRevolutions": None,
            })
    kept = []
    for row in sorted(proposals, key=lambda item: -item["uncalibratedMargin"]):
        if any(
            max(0, min(row["end"], prior["end"]) - max(row["start"], prior["start"]))
            / min(row["end"] - row["start"], prior["end"] - prior["start"]) > 0.3
            for prior in kept
        ):
            continue
        kept.append(row)
    return sorted(kept, key=lambda item: item["start"])


def run_audit(train_manifest_path, train_results_path, scan_path, review_path):
    from evaluate_full_program_scan import evaluate
    from video_type_model import LABEL_MAP, embedding

    train_manifest_path, train_results_path = map(Path, (train_manifest_path, train_results_path))
    scan_path, review_path = map(Path, (scan_path, review_path))
    manifest = json.loads(train_manifest_path.read_text(encoding="utf-8"))
    results = json.loads(train_results_path.read_text(encoding="utf-8"))
    if manifest.get("originalSplit") != "train" or any(row.get("split", "train") != "train" for row in manifest["items"]):
        raise ValueError("only the official training split is allowed for threshold calibration")
    if results.get("manifest_sha256") != sha256(train_manifest_path):
        raise ValueError("training manifest does not match the frozen feature results")
    items = {row["file"]: row for row in manifest["items"]}
    features, labels, groups = [], [], []
    for record in results["records"]:
        item = items.get(record["file"])
        if item is None:
            raise ValueError(f"training result is absent from manifest: {record['file']}")
        path = train_manifest_path.parent / item["file"]
        digest = sha256(path)
        if digest != item["sha256"] or digest != record["sha256"]:
            raise ValueError(f"source hash mismatch: {path}")
        truth = LABEL_MAP.get(int(item["label"]))
        if truth != record["truth"] or item["group"] != record["group"]:
            raise ValueError(f"frozen training label/group mismatch: {path}")
        feature, embedded_digest = embedding(path)
        if embedded_digest != digest:
            raise ValueError(f"embedding provenance mismatch: {path}")
        features.append(feature)
        labels.append(truth)
        groups.append(record["group"])

    features, labels, groups = np.stack(features), np.asarray(labels), np.asarray(groups)
    nested = nested_group_threshold_cv(features, labels, groups)
    final_threshold = crossfit_threshold(features, labels, groups)
    scan = json.loads(scan_path.read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    diagnostic_scan = dict(scan)
    diagnostic_scan["candidates"] = _proposals_at_threshold(scan, final_threshold["threshold"])
    diagnosis = evaluate(diagnostic_scan, review)
    return {
        "schemaVersion": 1,
        "scope": "Nested prefix-group CV on official training clips; one post-hoc diagnostic on the already inspected comp-20 program. Prefix groups are not verified athlete identities.",
        "method": "Ridge Axel-minus-other score. Select the threshold maximizing inner grouped-OOF balanced accuracy; ties choose the higher threshold. Outer group-held-out folds estimate threshold selection. Final threshold uses grouped OOF scores on the full official training subset.",
        "inputs": {
            "trainingManifestSha256": sha256(train_manifest_path),
            "trainingResultsSha256": sha256(train_results_path),
            "fullProgramScanSha256": sha256(scan_path),
            "expertReviewSha256": sha256(review_path),
            "fullProgramVideoSha256": review.get("sourceSha256"),
            "modelSha256": scan.get("modelSha256"),
        },
        "training": {"records": len(labels), "groups": len(set(groups.tolist())),
                     "axels": int(np.sum(labels != "other")), "other": int(np.sum(labels == "other"))},
        "nestedThresholdEvaluation": nested,
        "finalThreshold": final_threshold,
        "alreadyInspectedProgramDiagnostic": {
            "threshold": final_threshold["threshold"],
            "metrics": diagnosis["metrics"],
            "matches": diagnosis["matches"],
            "scopeNote": "Post-hoc development diagnostic, not independent validation; the comp-20 scan and review had already been inspected before this threshold analysis.",
        },
        "limitations": [
            "Validation group prefixes are not verified athlete identities.",
            "Training clips are pre-cropped single elements; they do not reproduce the full-program background or window-level class prior.",
            "The comp-20 full program was already inspected, so this diagnostic is not a confirmatory performance estimate.",
            "This audit measures only Axel candidate proposals, not underrotation, turn count, or physical angle.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-manifest", type=Path, default=DEFAULT_TRAIN_MANIFEST)
    parser.add_argument("--training-results", type=Path, default=DEFAULT_TRAIN_RESULTS)
    parser.add_argument("--scan", type=Path, default=DEFAULT_SCAN)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    if output.exists():
        raise ValueError(f"Refusing to overwrite existing audit: {output}")
    result = run_audit(args.training_manifest, args.training_results, args.scan, args.review)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "nested": result["nestedThresholdEvaluation"]["metrics"],
        "threshold": result["finalThreshold"],
        "comp20": result["alreadyInspectedProgramDiagnostic"]["metrics"],
        "output": str(output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
