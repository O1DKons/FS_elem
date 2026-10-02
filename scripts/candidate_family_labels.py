"""Conservative family-training labels; None means exclude, not negative.

The caller supplies the existing one-to-one match and confirmed review coverage.
No inference decisions or event boundaries are changed by this helper.
"""
import math


def _interval(row):
    start, end = float(row['start']), float(row['end'])
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError('Invalid interval')
    return start, end


def training_label(proposal, events, matched_event_id, exhaustive):
    if type(exhaustive) is not bool:
        raise ValueError('Coverage must be explicit boolean')
    start, end = _interval(proposal)
    overlap = []
    seen = set()
    for event in events:
        if event['id'] in seen:
            raise ValueError('Duplicate event id')
        seen.add(event['id'])
        a, b = _interval(event)
        if max(start, a) < min(end, b):
            overlap.append(event)
    matched = next((e for e in overlap if e['id'] == matched_event_id), None)
    if matched_event_id is not None and matched is None:
        raise ValueError('Match is absent or does not overlap')
    # A fragment or mixed window must never become a hard negative.
    axels = [e for e in overlap if e['eventClass'] == 'axel']
    if axels:
        return 'axel' if matched in axels and len(overlap) == 1 else None
    if matched is not None:
        return 'other' if matched['eventClass'] == 'other_jump' else None
    return 'other' if exhaustive and all(e['eventClass'] == 'other_jump' for e in overlap) else None
