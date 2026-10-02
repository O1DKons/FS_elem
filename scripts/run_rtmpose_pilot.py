"""Reproducible offline pilot on the exact source PNGs used by MediaPipe.
Run from repository: work/step23-rtmpose/venv/bin/python scripts/run_rtmpose_pilot.py
No writes to the viewer; results and hashes are stored separately.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time

from rtmpose_adapter import normalize_coco, select_bbox, evaluate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'data/pose-rtmpose-pilot-v1'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--anchors-only', action='store_true')
    args = parser.parse_args()
    import cv2
    from rtmlib import Body
    OUT.mkdir(exist_ok=True)
    references = []
    for version in ('v1', 'v2'):
        references.extend(json.loads((ROOT/f'data/pose-joint-review-{version}/user-annotations.json').read_text())['frames'])
    anchors = {(f['id'], f['frameIndex']) for f in references}
    demo_path = ROOT/'data/axel-demo-v1/data.json'
    demo = json.loads(demo_path.read_text())
    start = time.perf_counter()
    body = Body(mode='balanced', to_openpose=False, backend='onnxruntime', device='cpu')
    settings = dict(name='RTMPose-m body7 + YOLOX-m', version=importlib.metadata.version('rtmlib'),
                    mode='balanced', device='cpu', backend='onnxruntime', selection='largest detection area',
                    noDetection='empty pose; no full-frame fallback', sideConvention='athlete-anatomical',
                    smoothing=False, manualCorrections=False, urls=Body.MODE['balanced'])
    settings['weights'] = {label: dict(path=tool.onnx_model, sha256=sha(Path(tool.onnx_model))) for label, tool in [('detector', body.det_model), ('pose', body.pose_model)]}
    settings['packages'] = {name: importlib.metadata.version(name) for name in ('rtmlib','onnxruntime','numpy','opencv-python')}
    predictions = {label:{} for label in ('Lite', 'Full', 'RTMPose')}
    totals = []
    for clip in demo['clips']:
        frames, raw = [], []
        baseline = json.loads((ROOT/'data/pose-pilot-v1'/f"{clip['id']}.json").read_text())
        for frame in clip['frames']:
            n = frame['frameIndex']
            if args.anchors_only and (clip['id'], n) not in anchors:
                continue
            source = ROOT/'work/step6-pose'/clip['id']/f'{n:06d}.png'
            if sha(source) != frame['originalFrameSha256']:
                raise ValueError(f'Source frame checksum mismatch: {source}')
            image = cv2.imread(str(source))
            if image is None or image.shape[:2] != (demo['height'], demo['width']):
                raise ValueError('Missing image or inconsistent dimensions')
            tick = time.perf_counter()
            boxes = body.det_model(image)
            box = select_bbox(boxes)
            points, scores, landmarks = [], [], []
            if box is not None:
                keypoints, confidence = body.pose_model(image, bboxes=[box])
                points, scores = keypoints[0].tolist(), confidence[0].tolist()
                landmarks = normalize_coco(points, scores, demo['width'], demo['height'])
            elapsed = (time.perf_counter()-tick)*1000
            record = dict(frameIndex=n, time=frame['time'], landmarks=landmarks)
            frames.append(record)
            raw.append(dict(frameIndex=n, sourceFrameSha256=sha(source), detectionCount=len(boxes),
                            selectedBox=box, keypointsPixels=points, scores=scores, inferenceMs=elapsed))
            for label in predictions:
                predictions[label][clip['id'], n] = landmarks if label == 'RTMPose' else frame['pose'][label]
            if len(frames)%20 == 0 or args.anchors_only:
                print(f"{clip['id']} frame {n}: {len(landmarks)} points, {elapsed:.0f} ms", flush=True)
        proposal = {k: baseline[k] for k in ('schemaVersion','kind','status','videoId','sourceSha256','coordinateSpace')}
        proposal.update(model=dict(name=settings['name'], version='rtmlib-'+settings['version'], weightsSha256=settings['weights']['pose']['sha256']), frames=frames)
        suffix = '.anchors' if args.anchors_only else ''
        (OUT/f"{clip['id']}{suffix}.json").write_text(json.dumps(proposal, allow_nan=False))
        (OUT/f"{clip['id']}{suffix}.raw.json").write_text(json.dumps(raw, allow_nan=False))
        totals.extend(raw)
    evaluation = evaluate(references, predictions)
    evaluation.update(method='Source PNGs identical to MediaPipe, user anatomical labels unchanged, no confidence filtering or assistant corrections. Selected hard frames; not an independent test set.',
                      settings=settings, totalInferenceMs=sum(f['inferenceMs'] for f in totals),
                      processedFrames=len(totals), elapsedSeconds=time.perf_counter()-start,
                      baselineDataSha256=sha(demo_path))
    result_path = OUT/('evaluation-anchors.json' if args.anchors_only else 'evaluation.json')
    result_path.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2, allow_nan=False))
    print(json.dumps({k:v for k,v in evaluation.items() if k in ('models','paired','commonPoints','processedFrames','elapsedSeconds')}, indent=2), flush=True)

if __name__ == '__main__':
    main()
