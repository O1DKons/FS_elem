"""Sparse68D geometry on externally bound full-source presentation timestamps.

This opt-in adapter does not relax or rewrite the frozen frameIndex/FPS adapter.
Models may use it only with a declared feature contract and verified source PTS.
"""
import hashlib
import json
import math
import numpy as np
from full_context_contact import features as uniform_features

CONTRACT = 'sparse68-actual-source-pts-v1'
NAMES = ('nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
         'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
         'left_wrist', 'right_wrist', 'left_hip', 'right_hip', 'left_knee',
         'right_knee', 'left_ankle', 'right_ankle')


def timestamps_sha256(times):
    return hashlib.sha256(json.dumps(times, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def pose_arrays_pts(pose, timeline, expected):
    """Return68D, visibility, original indices and unmodified sampled source times.

    expected binds source metadata, model weights, sampling and the complete time
    sequence independently of the pose cache. Labels in seconds remain seconds.
    """
    for key in ('fps', 'frameCount', 'width', 'height'):
        if pose['source'][key] != expected[key] or timeline[key] != expected[key]:
            raise ValueError('PTS source metadata differs from external contract')
    if (pose['source']['sha256'] != expected['sourceSha256']
            or timeline['sourceSha256'] != expected['sourceSha256']
            or pose['model']['poseSha256'] != expected['poseSha256']
            or pose['model']['detectorSha256'] != expected['detectorSha256']):
        raise ValueError('PTS source/model identity differs')
    fps, count = expected['fps'], expected['frameCount']
    step = expected['stepSourceFrames']
    if (type(step) is not int or step < 1 or type(count) is not int or count < 3
            or type(fps) not in (int, float) or not math.isfinite(fps) or fps <= 0
            or any(type(expected[k]) is not int or expected[k] <= 0 for k in ('width', 'height'))):
        raise ValueError('Invalid external PTS contract')
    raw_times = timeline['timestampsSeconds']
    if (not isinstance(raw_times, list) or len(raw_times) != count
            or any(type(t) not in (int, float) or not math.isfinite(t) for t in raw_times)
            or raw_times[0] < 0 or any(b <= a for a, b in zip(raw_times, raw_times[1:]))
            or timestamps_sha256(raw_times) != expected['timestampsSha256']):
        raise ValueError('Incomplete, changed or invalid source PTS')
    sampling = pose['sampling']
    if (sampling['stepSourceFrames'] != step or sampling['requestedFps'] != expected['requestedFps']
            or not np.isclose(sampling['actualRate'], fps / step, rtol=0, atol=1e-8)):
        raise ValueError('PTS sampling differs from external contract')
    frames = pose['frames']
    if (len(frames) < 3 or any(type(f['frameIndex']) is not int for f in frames)
            or [f['frameIndex'] for f in frames] != list(range(0, count, step))):
        raise ValueError('Truncated or reordered PTS pose coverage')
    indices = np.asarray([f['frameIndex'] for f in frames])
    times = np.asarray([f['time'] for f in frames], float)
    source_times = np.asarray(raw_times, float)[indices]
    if (not np.isfinite(times).all() or np.any(np.diff(times) <= 0)
            or not np.allclose(times, source_times, rtol=0, atol=1e-6)):
        raise ValueError('Pose observations do not match bound source PTS')
    points = np.full((len(frames), 17, 2), np.nan)
    scores = np.zeros((len(frames), 17))
    for i, frame in enumerate(frames):
        landmarks = frame['landmarks']
        by_name = {p['name']: p for p in landmarks}
        if len(by_name) != len(landmarks):
            raise ValueError('Duplicate PTS landmark')
        for landmark in landmarks:
            if any(type(landmark[k]) not in (int, float) or not math.isfinite(landmark[k])
                   or not 0 <= landmark[k] <= 1 for k in ('x', 'y', 'confidence')):
                raise ValueError('Invalid normalized PTS landmark')
        for j, name in enumerate(NAMES):
            if name not in by_name:
                continue
            value = by_name[name]
            points[i, j] = [value['x'] * expected['width'], value['y'] * expected['height']]
            scores[i, j] = value['confidence']
    # The first34 channels are unchanged normalized geometry; discard the old
    # uniform-rate derivative and compute velocity at the actual observation times.
    geometry = uniform_features(points, scores, fps / step)[:, :34]
    x = np.column_stack([geometry, np.gradient(geometry, times, axis=0)])
    torso = np.linalg.norm(points[:, 5:7].mean(1) - points[:, 11:13].mean(1), axis=1)
    anchors = [5, 6, 11, 12]
    usable = (np.isfinite(points[:, anchors]).all((1, 2)) & np.isfinite(scores[:, anchors]).all(1)
              & (scores[:, anchors] >= .3).all(1) & (torso >= 2))
    return x, usable, indices, times
