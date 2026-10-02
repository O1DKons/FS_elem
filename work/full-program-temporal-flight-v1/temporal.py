"""Fixed offline temporal context for one recording's sparse pose features."""

import numpy as np


OFFSETS_SECONDS = (-0.24, -0.12, 0.0, 0.12, 0.24)
NEAREST_TOLERANCE_SECONDS = 0.065
MAX_GAP_SECONDS = 0.18


def context_features(x, times, usable):
    """Concatenate five timestamp-aligned feature blocks without filling gaps.

    ``x`` is an n-by-d numeric matrix; sparse NaN coordinates remain NaN,
    while infinities are rejected. ``times`` must be finite and strictly
    increasing, and ``usable`` must be a length-n boolean mask. The returned
    n-by-(5*d) float matrix has blocks in ``OFFSETS_SECONDS`` order.

    Each nonzero offset selects the nearest observed timestamp, with earlier
    timestamps winning ties. A block stays NaN if its target is outside the
    recording, the nearest sample is over 0.065 seconds away, or the path to
    that sample includes an unusable row or adjacent time gap over 0.18
    seconds. An unusable center produces an entirely NaN row. There is no
    interpolation, padding, fallback to a farther usable sample, or state
    shared between calls. Floating comparisons allow only machine roundoff.

    Positive offsets use future frames: this is an offline feature.
    """
    x = np.asarray(x, dtype=float)
    times = np.asarray(times, dtype=float)
    usable = np.asarray(usable)
    if x.ndim != 2:
        raise ValueError('x must be an n-by-d matrix')
    n, width = x.shape
    if times.ndim != 1 or times.shape != (n,):
        raise ValueError('times must be a length-n vector')
    if usable.ndim != 1 or usable.shape != (n,) or usable.dtype != np.dtype(bool):
        raise ValueError('usable must be a length-n boolean vector')
    if not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError('times must be finite and strictly increasing')
    if np.isinf(x).any():
        raise ValueError('x may contain NaN coordinates, but not infinity')

    result = np.full((n, len(OFFSETS_SECONDS) * width), np.nan)
    if n == 0:
        return result

    # Segment identity makes every intervening boundary part of the gate.
    epsilon = 8 * np.finfo(float).eps
    gap_roundoff = epsilon * np.maximum(1, np.maximum(np.abs(times[:-1]), np.abs(times[1:])))
    breaks = (~usable[:-1] | ~usable[1:]
              | (np.diff(times) > MAX_GAP_SECONDS + gap_roundoff))
    segments = np.cumsum(np.r_[True, breaks])
    for block, offset in enumerate(OFFSETS_SECONDS):
        start, end = block * width, (block + 1) * width
        if offset == 0:
            result[usable, start:end] = x[usable]
            continue
        target = times + offset
        roundoff = epsilon * np.maximum(1, np.abs(target))
        insertion = np.searchsorted(times, target)
        left = np.clip(insertion - 1, 0, n - 1)
        right = np.clip(insertion, 0, n - 1)
        left_distance = np.abs(times[left] - target)
        right_distance = np.abs(times[right] - target)
        nearest = np.where(right_distance < left_distance - roundoff, right, left)
        valid = (usable & usable[nearest]
                 & (target >= times[0] - roundoff)
                 & (target <= times[-1] + roundoff)
                 & (np.abs(times[nearest] - target) <= NEAREST_TOLERANCE_SECONDS + roundoff)
                 & (segments == segments[nearest]))
        result[valid, start:end] = x[nearest[valid]]
    return result
