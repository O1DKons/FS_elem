"""Unchanged v4 binary-run automatic event proposals; inference only."""
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
