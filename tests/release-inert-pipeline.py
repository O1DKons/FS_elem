"""Synthetic external pipeline boundary ONLY; never opens video or imports a model."""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

directory = Path(sys.argv[1])
payload = next(directory.glob('video.*')).read_bytes()
job = json.loads((directory / 'job.json').read_text())
if payload == b'fixture:hold':
    # An owned descendant tests process-group cleanup, not merely the parent exit.
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    (directory / 'fixture-pids.json').write_text(json.dumps([os.getpid(), child.pid]))
    print(json.dumps({'stage': 'sparse', 'currentFrame': 3, 'totalFrames': 7}), flush=True)
    time.sleep(30)
if payload == b'fixture:fail':
    (directory / 'result.json').write_text('{"events":[]}')  # Partial file is not success.
    raise SystemExit(7)
source = {'sha256': hashlib.sha256(payload).hexdigest(), 'width': 1920, 'height': 1080,
          'fps': 50, 'frameCount': 100, 'durationSeconds': 1.98, 'rotationDegrees': 0}
base = {'schemaVersion': 1, 'jobId': job['jobId'], 'source': source}
result = {**base, 'status': 'completed', 'events': [], 'candidateCount': 0, 'noEvents': True,
          'provenance': {'syntheticFixture': True}, 'timings': {},
          'limitations': ['Synthetic process fixture; not inference evidence']}
pose = {**base, 'coordinateSpace': 'displayed-source-pixels', 'frames': []}
(directory / 'result.json').write_text(json.dumps(result))
(directory / 'pose.json').write_text(json.dumps(pose))
print(json.dumps({'stage': 'export', 'currentFrame': 100, 'totalFrames': 100}), flush=True)
