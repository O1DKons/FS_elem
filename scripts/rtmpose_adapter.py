"""COCO-17 -> FS_elem source-image coordinates; no side swaps or smoothing."""
import math
import statistics

COCO_NAMES = ('nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
              'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
              'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
              'left_knee', 'right_knee', 'left_ankle', 'right_ankle')


def normalize_coco(points, scores, width, height, score_kind="bounded"):
    if score_kind not in ("bounded", "heatmap_peak"):
        raise ValueError("Unknown score kind")
    if len(points) != 17 or len(scores) != 17 or width <= 0 or height <= 0:
        raise ValueError('Expected COCO-17 points and positive source dimensions')
    result = []
    for name, point, score in zip(COCO_NAMES, points, scores):
        x, y = float(point[0])/width, float(point[1])/height
        score = float(score)
        # Heatmap maxima are not probabilities. Retain raw peaks in inference files.
        if score_kind == "heatmap_peak" and math.isfinite(score):
            score = max(0.0, min(1.0, score))
        if all(math.isfinite(v) for v in (x, y, score)) and 0 <= x <= 1 and 0 <= y <= 1 and 0 <= score <= 1:
            result.append(dict(name=name, x=x, y=y, confidence=score))
    return result


def select_bbox(boxes):
    """Largest visible person for these single-skater pilot clips, not a tracker."""
    valid = [list(map(float, b[:4])) for b in boxes
             if len(b) >= 4 and all(math.isfinite(float(v)) for v in b[:4])
             and b[2] > b[0] and b[3] > b[1]]
    return max(valid, key=lambda b: (b[2]-b[0])*(b[3]-b[1])) if valid else None


def evaluate(references, predictions):
    rows, unknown = [], 0
    for frame in references:
        models = {label: {p['name']: p for p in frames.get((frame['id'], frame['frameIndex']), [])}
                  for label, frames in predictions.items()}
        for name, ref in frame['joints'].items():
            if ref['status'] == 'unassessable':
                unknown += 1
                continue
            if ref['status'] != 'located':
                raise ValueError('Unknown reference status')
            errors = {}
            for label, points in models.items():
                p = points.get(name)
                errors[label] = None if p is None else math.hypot(
                    (p['x']-ref['x'])*frame['width'], (p['y']-ref['y'])*frame['height'])
            rows.append(dict(id=frame['id'], frameIndex=frame['frameIndex'], joint=name, errors=errors))
    def stats(items, label):
        errors = [r['errors'][label] for r in items if r['errors'][label] is not None]
        return dict(predicted=len(errors), missing=len(items)-len(errors),
                    meanPx=statistics.mean(errors) if errors else None,
                    medianPx=statistics.median(errors) if errors else None,
                    maxPx=max(errors) if errors else None)
    paired = [r for r in rows if all(v is not None for v in r['errors'].values())]
    return dict(located=len(rows), unassessable=unknown,
                models={label: stats(rows, label) for label in predictions},
                commonPoints=len(paired), paired={label: stats(paired, label) for label in predictions},
                perFrame={f"{f['id']}:{f['frameIndex']}": {
                    label: stats([r for r in rows if r['id'] == f['id'] and r['frameIndex'] == f['frameIndex']], label)
                    for label in predictions} for f in references}, rows=rows)


def integrate(demo, proposals, label='RTMPose'):
    """Join only complete, source-bound predictions; preserve prior data and flags."""
    import copy
    result = copy.deepcopy(demo)
    w, h = demo['width'], demo['height']
    joints = [side+'_'+part for side in ('left','right')
              for part in ('shoulder','elbow','wrist','hip','knee','ankle')]
    for clip in result['clips']:
        proposal = proposals[clip['id']]
        if (proposal['sourceSha256'] != clip['sourceSha256'] or
            proposal['coordinateSpace']['width'] != w or proposal['coordinateSpace']['height'] != h):
            raise ValueError('Source binding mismatch')
        identity = lambda frames: [(f['frameIndex'], f['time']) for f in frames]
        if identity(proposal['frames']) != identity(clip['frames']):
            raise ValueError('Incomplete or misaligned frame sequence')
        previous, previous_frame = {}, None
        for frame, predicted in zip(clip['frames'], proposal['frames']):
            points = {p['name']:p for p in predicted['landmarks']}
            peer = {p['name']:p for p in frame['pose']['Full']}
            flags = {}
            contiguous = previous_frame is not None and frame['frameIndex'] == previous_frame['frameIndex']+1 and 0 < frame['time']-previous_frame['time'] <= .021
            for name in joints:
                p = points.get(name)
                reasons = []
                if p is None:
                    reasons.append('missing')
                else:
                    # RTMPose score is not calibrated against MediaPipe visibility.
                    if p['confidence'] < .3:
                        reasons.append('low_confidence')
                    for other, threshold, reason in ((peer.get(name), .02, 'model_disagreement'),
                        (previous.get(name) if contiguous else None, .03, 'temporal_step')):
                        if other and math.hypot((p['x']-other['x'])*w, (p['y']-other['y'])*h) > math.hypot(w,h)*threshold:
                            reasons.append(reason)
                flags[name] = reasons
            frame['pose'][label] = copy.deepcopy(predicted['landmarks'])
            frame['flags'][label] = flags
            previous, previous_frame = points, frame
    return result
