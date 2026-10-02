"""Sparse full-program RTMW inference; research cache only, never modifies FS_elem UI."""
import argparse
import hashlib
import json
import math
import time
from pathlib import Path


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expanded_keypoint_box(points, scores, source_box, width, height):
    valid = [(float(p[0]), float(p[1])) for p, score in zip(points, scores)
             if math.isfinite(float(score)) and float(score) >= 0.5
             and math.isfinite(float(p[0])) and math.isfinite(float(p[1]))]
    if len(valid) < 6:
        return source_box
    xs, ys = [p[0] for p in valid], [p[1] for p in valid]
    padding = max(24.0, 0.12 * (max(ys) - min(ys)))
    box = [max(0.0, min(xs)-padding), max(0.0, min(ys)-padding),
           min(float(width-1), max(xs)+padding), min(float(height-1), max(ys)+padding)]
    return box if box[2] > box[0] and box[3] > box[1] else source_box


def extract(video, output, sample_fps=8.333333):
    import cv2
    import importlib.metadata
    import sys

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "scripts"))
    from infer_jump_landmarks import DETECTOR, POSE, models, track_box, normalize_wholebody

    video, output = Path(video).resolve(), Path(output).resolve()
    if not video.is_file():
        raise ValueError("Input video does not exist")
    if output.exists():
        raise ValueError("Refusing to overwrite an existing inference artifact")
    if not (DETECTOR.is_file() and POSE.is_file()):
        raise ValueError("RTMW detector and pose weights must already exist locally")

    cap = cv2.VideoCapture(str(video))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not cap.isOpened() or fps <= 0 or frame_count <= 0:
        cap.release()
        raise ValueError("Cannot read source video metadata")
    step = max(1, round(fps / sample_fps))
    detector, pose = models()
    frames, previous_box, last_detect_sample = [], None, -100
    elapsed_inference = 0.0
    sample_index = 0
    source_index = 0
    started = time.perf_counter()
    while True:
        ok, image = cap.read()
        if not ok:
            break
        if source_index % step == 0:
            timestamp = float(cap.get(cv2.CAP_PROP_POS_MSEC)) / 1000.0
            detection_due = previous_box is None or sample_index-last_detect_sample >= 5
            if detection_due:
                tick = time.perf_counter()
                boxes = detector(image)
                previous_box = track_box(boxes, previous_box)
                last_detect_sample = sample_index
            raw_points, raw_scores = [], []
            if previous_box is not None:
                tick = time.perf_counter()
                keypoints, confidence = pose(image, bboxes=[previous_box])
                elapsed_inference += time.perf_counter() - tick
                raw_points, raw_scores = keypoints[0, :23].tolist(), confidence[0, :23].tolist()
                landmarks = normalize_wholebody(raw_points, raw_scores, width, height)
                previous_box = expanded_keypoint_box(raw_points, raw_scores,
                                                     previous_box, width, height)
                state = "pose" if len(landmarks) >= 12 else "low_pose_coverage"
            else:
                landmarks, state = [], "no_person_detection"
            frames.append({"sampleIndex": sample_index,
                           "frameIndex": source_index,
                           "time": timestamp,
                           "bbox": previous_box,
                           "bodyHeight": None if previous_box is None else previous_box[3]-previous_box[1],
                           "trackingStatus": state,
                           "landmarks": landmarks})
            sample_index += 1
        source_index += 1
        if source_index % 500 == 0:
            print("decoded", source_index, "sampled", sample_index,
                  "pose_seconds", round(elapsed_inference, 1), flush=True)
    cap.release()
    if source_index != frame_count:
        raise ValueError("Decoded frame count does not match video metadata")
    if not frames:
        raise ValueError("No source frames were sampled")
    result = {
        "schemaVersion": 1,
        "scope": "Sparse RTMW full-program landmark cache for flight-proposal research; no element prediction or rotation verdict.",
        "source": {"path": str(video), "sha256": sha(video), "fps": fps,
                   "frameCount": frame_count, "durationSeconds": (frame_count-1)/fps,
                   "width": width, "height": height},
        "sampling": {"requestedFps": sample_fps, "stepSourceFrames": step,
                     "actualRate": fps/step},
        "model": {"name": "RTMW-dw-x-l WholeBody via RTMLib", "device": "cpu",
                  "rtmlibVersion": importlib.metadata.version("rtmlib"),
                  "detectorSha256": sha(DETECTOR), "poseSha256": sha(POSE)},
        "timing": {"poseInferenceSeconds": elapsed_inference,
                   "wallSeconds": time.perf_counter()-started,
                   "sampledFrames": len(frames),
                   "poseFrames": sum(f["trackingStatus"] == "pose" for f in frames)},
        "frames": frames,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False))
    print(json.dumps({k: result[k] for k in ("source", "sampling", "timing")},
                     ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-fps", type=float, default=8.333333)
    args = parser.parse_args()
    extract(args.video, args.output, args.sample_fps)
