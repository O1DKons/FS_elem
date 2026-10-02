"""Fixed binary-run proposals and class-neutral technical-jump event scoring."""

import math

import numpy as np


def _duration(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Duration must be positive and finite")
    return value


def decode_events(times, probability, usable, duration):
    """Keep >=2 adjacent usable samples with posterior strictly above one half.

    Internal boundaries are neighboring timestamp midpoints. At the source
    edges, half the median sampled interval is used, clamped to the source.
    Missing predictions and unusable poses break runs. Equal peak values use
    the earliest sample; no event count or maximum duration is imposed.
    """
    duration = _duration(duration)
    times = np.asarray(times, dtype=float)
    probability = np.asarray(probability, dtype=float)
    usable = np.asarray(usable)
    if (times.ndim != 1 or probability.shape != times.shape
            or usable.shape != times.shape or usable.dtype.kind != "b"):
        raise ValueError("Expected aligned one-dimensional arrays and boolean usable mask")
    if (not np.isfinite(times).all() or np.any(np.diff(times) <= 0)
            or np.any(times < 0) or np.any(times > duration)):
        raise ValueError("Times must be finite, strictly increasing, and within the source")
    observed = ~np.isnan(probability)
    if (not np.isfinite(probability[observed]).all()
            or np.any(probability[observed] < 0) or np.any(probability[observed] > 1)):
        raise ValueError("Probabilities must be in [0,1], or NaN for missing")
    if len(times) < 2:
        return []
    half_interval = float(np.median(np.diff(times))) / 2
    active = usable & observed & (probability > 0.5)
    proposals, first = [], None
    for index, positive in enumerate(np.append(active, False)):
        if positive and first is None:
            first = index
        elif not positive and first is not None:
            last = index - 1
            if last - first + 1 >= 2:
                start = ((times[first - 1] + times[first]) / 2 if first > 0
                         else max(0.0, times[first] - half_interval))
                end = ((times[last] + times[last + 1]) / 2 if last + 1 < len(times)
                       else min(duration, times[last] + half_interval))
                peak = first + int(np.argmax(probability[first:last + 1]))
                proposals.append(dict(start=float(start), end=float(end),
                                      peakTime=float(times[peak]),
                                      startSample=first, endSample=last))
            first = None
    return proposals


def _interval(row, duration):
    start, end = float(row["start"]), float(row["end"])
    if (not math.isfinite(start) or not math.isfinite(end)
            or start < 0 or end <= start or end > duration):
        raise ValueError("Intervals must be finite, positive-length, and within the source")
    return start, end


def evaluate_events(proposals, events, duration, exhaustive):
    """Maximum one-to-one matching: expert midpoint inside and temporal IoU >=.3.

    The task is technical-jump flight detection, so both Axel and other-jump
    annotations are positives. An unmatched candidate covering an uncertain
    midpoint is unresolved unless it also has a valid known-event edge; this
    preserves the false-positive penalty for duplicate known-event proposals.
    Unmatched proposals on partial annotations have no false-positive verdict.
    """
    duration = _duration(duration)
    if type(exhaustive) is not bool:
        raise ValueError("Exhaustive annotation status must be explicit boolean")
    intervals = [_interval(row, duration) for row in proposals]
    event_intervals = [_interval(row, duration) for row in events]
    ids = [row["id"] for row in events]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("Event IDs must be nonempty and unique")
    if any(row["eventClass"] not in {"axel", "other_jump", "uncertain"} for row in events):
        raise ValueError("Unsupported event class")
    known = [i for i, row in enumerate(events) if row["eventClass"] != "uncertain"]
    uncertain = [i for i, row in enumerate(events) if row["eventClass"] == "uncertain"]
    centers = [(start + end) / 2 for start, end in event_intervals]
    edges, overlaps = {}, {}
    for index, (start, end) in enumerate(intervals):
        eligible = []
        for event_index in known:
            event_start, event_end = event_intervals[event_index]
            overlap = max(0.0, min(end, event_end) - max(start, event_start))
            union = (end - start) + (event_end - event_start) - overlap
            iou = overlap / union
            if start <= centers[event_index] <= end and iou >= 0.3:
                eligible.append(event_index)
                overlaps[index, event_index] = iou
        edges[index] = sorted(eligible, key=lambda i: (abs((start + end) / 2 - centers[i]), i))

    assigned = {}

    def assign(proposal_index, visited):
        for event_index in edges[proposal_index]:
            if event_index in visited:
                continue
            visited.add(event_index)
            previous = assigned.get(event_index)
            if previous is None or assign(previous, visited):
                assigned[event_index] = proposal_index
                return True
        return False

    for index in sorted(edges, key=lambda i: (intervals[i][0], i)):
        assign(index, set())
    matched = {proposal_index: event_index for event_index, proposal_index in assigned.items()}
    unmatched = [i for i in range(len(proposals)) if i not in matched]
    unresolved = [i for i in unmatched if not edges[i]
                  and any(intervals[i][0] <= centers[j] <= intervals[i][1] for j in uncertain)]
    false_proposals = [i for i in unmatched if i not in set(unresolved)]
    rows = []
    for index, event_index in sorted(matched.items()):
        start, end = intervals[index]
        event_start, event_end = event_intervals[event_index]
        rows.append(dict(proposalIndex=index, eventId=ids[event_index],
                         eventClass=events[event_index]["eventClass"],
                         intervalIoU=overlaps[index, event_index],
                         takeoffBoundaryErrorSeconds=start - event_start,
                         landingBoundaryErrorSeconds=end - event_end,
                         centerErrorSeconds=(start + end) / 2 - centers[event_index]))
    matched_count = len(matched)
    axel_count = sum(events[i]["eventClass"] == "axel" for i in known)
    matched_axels = sum(row["eventClass"] == "axel" for row in rows)
    known_count = len(proposals) - len(unresolved)
    f1_denominator = known_count + len(known)
    return dict(
        metrics=dict(
            annotatedEvents=len(known), matchedEvents=matched_count,
            eventRecall=matched_count / len(known) if known else None,
            annotatedAxels=axel_count, matchedAxels=matched_axels,
            axelRecall=matched_axels / axel_count if axel_count else None,
            candidateCount=len(proposals), unresolvedCandidates=len(unresolved),
            knownCandidateCount=known_count,
            candidatePrecision=matched_count / known_count if exhaustive and known_count else None,
            falsePositiveCandidates=len(false_proposals) if exhaustive else None,
            falsePositiveProposalsPerMinute=len(false_proposals) * 60 / duration if exhaustive else None,
            eventF1=2 * matched_count / f1_denominator if exhaustive and f1_denominator else None,
        ),
        matches=rows,
        missedEventIds=[ids[i] for i in known if i not in assigned],
        unmatchedProposalIndices=unmatched,
        unresolvedProposalIndices=unresolved,
        falsePositiveProposalIndices=false_proposals if exhaustive else None,
    )
