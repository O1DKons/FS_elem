"""Select dense observations from real PTS and automatic candidate seconds."""
import numpy as np
from axel_features import spectrum


def dense_window(times, start, end):
    times = np.asarray(times, float)
    if (times.ndim != 1 or len(times) < 3 or not np.isfinite(times).all()
            or np.any(np.diff(times) <= 0) or not np.isfinite([start, end]).all()
            or not 0 <= start < end <= times[-1] + .1):
        raise ValueError('Invalid real-PTS automatic window')
    interior = np.flatnonzero((times > start) & (times < end))
    crop = np.flatnonzero((times >= max(times[0], start - .6)) & (times <= end + .3))
    if not len(crop):
        raise ValueError('No dense context frames in source')
    return dict(startSeconds=float(start), endSeconds=float(end),
        cropStartFrame=int(crop[0]), cropEndFrame=int(crop[-1]), flightFrames=interior.tolist())


def nominal_features(document, window):
    signals = []
    for i in window['flightFrames']:
        row = document['frames'][str(i)]
        p = np.asarray(row['points'], float)
        s = np.asarray(row['scores'], float)
        values = np.full(4, np.nan)
        if (p.shape == (23, 2) and s.shape == (23,)
                and np.isfinite(p[[5, 6, 11, 12]]).all() and (s[[5, 6, 11, 12]] >= .5).all()):
            scale = np.linalg.norm((p[5] + p[6] - p[11] - p[12]) / 2)
            if scale > 1:
                values = np.r_[(p[12] - p[11]) / scale, (p[6] - p[5]) / scale]
        signals.append(values)
    signals = np.asarray(signals).reshape(-1, 4)
    x = np.r_[window['endSeconds'] - window['startSeconds'],
               *[spectrum(signals[:, i]) for i in range(4)]]
    return x, dict(flightFrames=len(signals), usableTorsoFrames=int(np.isfinite(signals).all(1).sum()),
                   finiteSpectralFeatures=int(np.isfinite(x[1:]).sum()))
