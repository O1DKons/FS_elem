"""Score one frozen full-program scan against complete manual annotations."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re


ELEMENTS = {"1A", "2A", "3A", "4A"}
ROTATION_LABELS = {"apparently_complete", "apparently_short", "unclear"}
EVENT_CLASSES = {"axel", "other_jump", "uncertain"}
AXEL_CODE = re.compile(r"^(1A|2A|3A|4A)(?:q|<|<<)?$")


def _read_json(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")), hashlib.sha256(path.read_bytes()).hexdigest()


def _validate(scan, review):
    if not isinstance(scan, dict) or not isinstance(review, dict):
        raise ValueError("scan and review inputs must be JSON objects")
    if scan.get("schemaVersion") != 1 or review.get("schemaVersion") != 1:
        raise ValueError("unsupported input schema")
    if review.get("coverageReviewed") is not True:
        raise ValueError("manual review must confirm complete program coverage")
    source_hash = review.get("sourceSha256")
    if (not isinstance(source_hash, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", source_hash) is None
            or scan.get("sourceSha256") != source_hash):
        raise ValueError("source SHA-256 mismatch")
    fps = review.get("fps")
    duration = review.get("durationSeconds")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps) or fps <= 0:
        raise ValueError("fps must be positive and finite")
    if (isinstance(duration, bool) or not isinstance(duration, (int, float))
            or not math.isfinite(duration) or duration <= 0):
        raise ValueError("review duration must be positive and finite")
    scan_duration = scan.get("duration")
    if (isinstance(scan_duration, bool) or not isinstance(scan_duration, (int, float))
            or not math.isfinite(scan_duration)):
        raise ValueError("scan duration is missing")
    if abs(float(scan_duration) - float(duration)) > 0.25:
        raise ValueError("scan and review durations do not match")
    if not isinstance(scan.get("candidates"), list) or not isinstance(review.get("events"), list):
        raise ValueError("scan candidates and review events must be arrays")
    if not isinstance(review.get("reviewId"), str) or not review["reviewId"].strip():
        raise ValueError("reviewId must be a non-empty string")

    candidates = []
    for index, row in enumerate(scan["candidates"]):
        if not isinstance(row, dict):
            raise ValueError(f"invalid candidate row at index {index}")
        start, end = row.get("start"), row.get("end")
        element = row.get("elementProposal")
        if (isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(start)
                or isinstance(end, bool) or not isinstance(end, (int, float)) or not math.isfinite(end)
                or start < 0 or end <= start or end > duration + 0.25):
            raise ValueError(f"invalid candidate interval at index {index}")
        if not isinstance(element, str) or element not in ELEMENTS:
            raise ValueError(f"invalid Axel proposal at index {index}")
        candidates.append({"index": index, "start": float(start), "end": float(end), "element": element})

    events = []
    seen_ids = set()
    for index, row in enumerate(review["events"]):
        if not isinstance(row, dict):
            raise ValueError(f"invalid event row at index {index}")
        event_id = row.get("id")
        kind = row.get("eventClass")
        start, end = row.get("lastContactFrame"), row.get("firstContactFrame")
        if not isinstance(event_id, str) or not event_id or event_id in seen_ids:
            raise ValueError(f"invalid or duplicate event id at index {index}")
        seen_ids.add(event_id)
        if not isinstance(kind, str) or kind not in EVENT_CLASSES:
            raise ValueError(f"invalid event class at index {index}")
        if type(start) is not int or type(end) is not int or end <= start:
            raise ValueError(f"invalid contact frames at index {index}")
        start_seconds, end_seconds = start / fps, end / fps
        if start_seconds < 0 or end_seconds > duration + 0.1:
            raise ValueError(f"contact frames outside source at index {index}")
        raw_code = str(row.get("elementCode") or "").strip().upper()
        code = raw_code
        rotation = row.get("rotationAssessment")
        if kind == "axel":
            code_match = AXEL_CODE.fullmatch(raw_code)
            if code_match is None:
                raise ValueError(f"Axel type must be one of {sorted(ELEMENTS)} at index {index}")
            code = code_match.group(1)
            if not isinstance(rotation, str) or rotation not in ROTATION_LABELS:
                raise ValueError(f"invalid visual rotation label at index {index}")
        events.append({
            "index": index,
            "id": event_id,
            "class": kind,
            "element": code,
            "element_code": raw_code,
            "rotation": rotation if kind == "axel" else "not_applicable",
            "start": start_seconds,
            "end": end_seconds,
            "center": (start_seconds + end_seconds) / 2,
        })
    return candidates, events, float(duration), float(fps)


def _maximum_matching(candidate_indices, event_indices, candidates, events):
    """Match each proposal/event at most once when the event midpoint is inside it."""
    event_to_candidate = {}

    def assign(candidate_index, visited):
        candidate = candidates[candidate_index]
        eligible = [
            event_index for event_index in event_indices
            if candidate["start"] <= events[event_index]["center"] <= candidate["end"]
        ]
        eligible.sort(key=lambda i: (abs((candidate["start"] + candidate["end"]) / 2 - events[i]["center"]), i))
        for event_index in eligible:
            if event_index in visited:
                continue
            visited.add(event_index)
            previous = event_to_candidate.get(event_index)
            if previous is None or assign(previous, visited):
                event_to_candidate[event_index] = candidate_index
                return True
        return False

    for candidate_index in candidate_indices:
        assign(candidate_index, set())
    return {candidate_index: event_index for event_index, candidate_index in event_to_candidate.items()}


def evaluate(scan, review):
    candidates, events, duration, fps = _validate(scan, review)
    by_class = {
        kind: [event["index"] for event in events if event["class"] == kind]
        for kind in EVENT_CLASSES
    }
    candidate_order = sorted(range(len(candidates)), key=lambda i: (candidates[i]["start"], i))
    axel_matches = _maximum_matching(candidate_order, by_class["axel"], candidates, events)
    used = set(axel_matches)
    other_matches = _maximum_matching(
        [i for i in candidate_order if i not in used], by_class["other_jump"], candidates, events
    )
    used.update(other_matches)

    unresolved = sorted(
        candidate_index for candidate_index in candidate_order if candidate_index not in used
        and any(candidates[candidate_index]["start"] <= events[event_index]["center"] <= candidates[candidate_index]["end"]
                for event_index in by_class["uncertain"])
    )
    known_candidate_count = len(candidates) - len(unresolved)
    false_positive_candidates = sorted(
        candidate_index for candidate_index in candidate_order
        if candidate_index not in axel_matches and candidate_index not in unresolved
    )
    detected = len(axel_matches)
    false_positives = len(false_positive_candidates)
    expert_axels = by_class["axel"]
    rotation_counts = {label: sum(events[i]["rotation"] == label for i in expert_axels)
                       for label in sorted(ROTATION_LABELS)}

    matches = []
    for candidate_index, event_index in sorted(axel_matches.items()):
        candidate, event = candidates[candidate_index], events[event_index]
        matches.append({
            "candidateIndex": candidate_index,
            "eventId": event["id"],
            "eventClass": "axel",
            "predictedElement": candidate["element"],
            "expertElement": event["element"],
            "expertElementCode": event["element_code"],
            "elementTypeCorrect": candidate["element"] == event["element"],
            "expertRotationAssessment": event["rotation"],
            "candidateCenterMinusExpertCenterSeconds": round((candidate["start"] + candidate["end"]) / 2 - event["center"], 4),
        })
    for candidate_index, event_index in sorted(other_matches.items()):
        candidate, event = candidates[candidate_index], events[event_index]
        matches.append({
            "candidateIndex": candidate_index,
            "eventId": event["id"],
            "eventClass": "other_jump",
            "predictedElement": candidate["element"],
            "expertElement": event["element"],
            "expertElementCode": event["element_code"],
            "elementTypeCorrect": False,
            "candidateCenterMinusExpertCenterSeconds": round((candidate["start"] + candidate["end"]) / 2 - event["center"], 4),
        })
    matched_axel_types = [row["elementTypeCorrect"] for row in matches if row["eventClass"] == "axel"]
    precision = detected / known_candidate_count if known_candidate_count else None
    recall = detected / len(expert_axels) if expert_axels else None
    type_accuracy = sum(matched_axel_types) / len(matched_axel_types) if matched_axel_types else None
    return {
        "schemaVersion": 1,
        "scope": "One complete manually reviewed program; measures event proposals only. Not athlete-held-out rotation accuracy or revolutions.",
        "sourceSha256": review["sourceSha256"],
        "reviewId": review["reviewId"],
        "durationSeconds": duration,
        "fps": fps,
        "metrics": {
            "expertAxels": len(expert_axels),
            "expertOtherJumps": len(by_class["other_jump"]),
            "uncertainEvents": len(by_class["uncertain"]),
            "candidateCount": len(candidates),
            "detectedAxels": detected,
            "axelRecall": recall,
            "knownCandidateCount": known_candidate_count,
            "candidatePrecision": precision,
            "falsePositiveCandidates": false_positives if known_candidate_count else None,
            "falsePositiveProposalsPerMinute": round(false_positives * 60 / duration, 4) if known_candidate_count else None,
            "unresolvedCandidates": len(unresolved),
            "correctElementTypeAmongDetected": type_accuracy,
        },
        "rotationLabelCounts": rotation_counts,
        "matches": matches,
        "missedAxelEventIds": sorted(events[i]["id"] for i in expert_axels if i not in set(axel_matches.values())),
        "falsePositiveCandidateIndices": false_positive_candidates,
        "unresolvedCandidateIndices": unresolved,
        "interpretation": "Candidate hits are defined by the proposal window containing the expert takeoff-to-landing midpoint. Proposals and events are matched one-to-one. Unknown events are excluded from precision; all remaining unmatched proposals count as false positives.",
        "limitations": [
            "One program cannot establish performance on new athletes or events.",
            "A positive Axel candidate does not produce a revolution count or clean/short verdict.",
            "Visual rotation labels are manual categorical assessments, not measured blade angles.",
            "The candidate window is coarse; midpoint inclusion is an event-detection metric, not boundary accuracy.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Refusing to overwrite existing evaluation")
    scan, scan_sha = _read_json(args.scan)
    review, review_sha = _read_json(args.review)
    result = evaluate(scan, review)
    result["inputSha256"] = {"scan": scan_sha, "expertReview": review_sha}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
