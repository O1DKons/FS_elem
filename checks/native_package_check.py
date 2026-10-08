"""Native package checks; invocation is separate from source preparation.

Uses real release entry/SDK/SQLite and production OwnedProcess ownership.
Cancels the whole launcher tree, not an uploaded video via the UI cancel button.
No accepted-video POST, inference, training, or model accuracy claims.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

PACKAGE = Path(__file__).resolve().parents[1]
LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
sys.path.insert(0, str(PACKAGE / 'services/analysis'))


def write_receipt(name, value):
    target = PACKAGE / '.runtime' / name
    with target.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
    print(json.dumps(value))


class BoundedOutput:
    def __init__(self, limit):
        self.limit = limit
        self.total = 0
        self.retained = 0
        self.buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        self.lock = threading.Lock()
        self.exceeded = threading.Event()
        self.failure = None

    def drain(self, stream, name):
        try:
            while True:
                block = stream.read(1024)
                if not block:
                    return
                if isinstance(block, str):
                    block = block.encode('utf-8', 'replace')
                with self.lock:
                    self.total += len(block)
                    kept = block[:max(0, self.limit - self.retained)]
                    self.buffers[name].extend(kept)
                    self.retained += len(kept)
                    if self.total > self.limit:
                        self.exceeded.set()
        except BaseException as error:
            with self.lock:
                if self.failure is None:
                    self.failure = error

    def check(self):
        if self.failure is not None:
            raise self.failure
        if self.exceeded.is_set():
            raise RuntimeError('native output exceeded its declared byte cap')


def ffmpeg_check():
    binary = PACKAGE / '.runtime/bin' / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    records = []
    for flag in ['-version', '-L']:
        child = subprocess.Popen([str(binary), flag], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        capture = BoundedOutput(16384)
        readers = []
        first_failure = None
        try:
            for name in ['stdout', 'stderr']:
                reader = threading.Thread(target=capture.drain, args=(getattr(child, name), name), daemon=True)
                reader.start(); readers.append(reader)
            deadline = time.monotonic() + 15
            while child.poll() is None:
                capture.check()
                if time.monotonic() >= deadline:
                    raise RuntimeError('native FFmpeg query timed out')
                time.sleep(.02)
            capture.check()
            if child.returncode:
                raise RuntimeError('native FFmpeg query failed')
        except BaseException as error:
            first_failure = error
        finally:
            # Every cleanup is attempted on this retained child/its streams only.
            # Excess output reaches immediate stop/kill, not another communicate.
            operations = [lambda: child.terminate() if child.poll() is None else None,
                          lambda: child.kill() if child.poll() is None else None,
                          lambda: child.wait(timeout=3)]
            for operation in operations:
                try:
                    operation()
                except BaseException as error:
                    if first_failure is None:
                        first_failure = error
            for reader in readers:
                try:
                    reader.join(timeout=2)
                    if reader.is_alive():
                        raise RuntimeError('retained FFmpeg output reader did not finish')
                except BaseException as error:
                    if first_failure is None:
                        first_failure = error
            for stream in [child.stdout, child.stderr]:
                try:
                    stream.close()
                except BaseException as error:
                    if first_failure is None:
                        first_failure = error
            try:
                capture.check()
            except BaseException as error:
                if first_failure is None:
                    first_failure = error
        if first_failure:
            raise first_failure
        records.append({'flag': flag, 'exitCode': child.returncode,
                        'stdout': capture.buffers['stdout'].decode('utf-8', 'replace'),
                        'stderr': capture.buffers['stderr'].decode('utf-8', 'replace'),
                        'combinedOutputBytes': capture.total, 'outputExceeded': False,
                        'waitReaped': True})
    write_receipt('native-ffmpeg-check.json', {'platform': sys.platform, 'observed': records,
                                            'licenseApproval': 'not inferred from successful -L'})


def request(path, body=None, content_type=None):
    req = urllib.request.Request('http://127.0.0.1:5174' + path, data=body)
    if content_type:
        req.add_header('Content-Type', content_type)
    try:
        with LOCAL_HTTP.open(req, timeout=2) as response:
            return response.status, response.read(8192)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read(8192)


def strict_idle(health):
    return (isinstance(health, dict) and health.get('status') == 'ready'
            and health.get('inferenceAvailable') is True
            and 'activeJobId' in health and health['activeJobId'] is None)


def wait_ready(owner, deadline, capture):
    last = None
    while time.monotonic() < deadline:
        capture.check()
        attempted_path = '/api/analysis/health'
        try:
            code, body = request(attempted_path)
            health = json.loads(body)
            attempted_path = '/analysis'
            web_code, _ = request(attempted_path)
            if code == 200 and strict_idle(health) and web_code == 200:
                capture.check()
                return {'healthStatus': code, 'analysisStatus': web_code,
                        'inferenceAvailable': True, 'activeJobId': health['activeJobId']}
            last = 'health/compiled UI not ready'
            if os.name == 'nt':
                last += f' (healthStatus={code}, analysisStatus={web_code}, strictIdle={strict_idle(health)})'
        except (OSError, ValueError) as error:
            last = type(error).__name__
            if os.name == 'nt':
                # Diagnostic formatting must not replace the readiness failure.
                try:
                    reason = getattr(error, 'reason', error)
                    last = json.dumps({'url': 'http://127.0.0.1:5174' + attempted_path,
                        'exceptionType': type(error).__name__, 'message': str(error)[:512],
                        'reasonType': type(reason).__name__, 'reason': str(reason)[:512],
                        'errno': getattr(reason, 'errno', None), 'winerror': getattr(reason, 'winerror', None)},
                        ensure_ascii=True)
                except BaseException:
                    pass
        time.sleep(.2)
    raise RuntimeError('bounded real package readiness failed: ' + str(last))


def require_unavailable():
    for port in [5174, 5175]:
        try:
            connection = socket.create_connection(('127.0.0.1', port), timeout=.5)
        except OSError:
            continue
        connection.close()
        raise RuntimeError('web/API port remains reachable outside owned tree')


def emit_windows_lifecycle_failure(cycle, capture):
    # Called only after the existing retained cleanup; never changes first_failure.
    try:
        with capture.lock:
            value = {'diagnostic': 'windows native lifecycle startup capture', 'cycle': cycle + 1,
                'outputBytes': capture.total, 'retainedBytes': capture.retained,
                'outputLimitBytes': capture.limit, 'outputExceeded': capture.exceeded.is_set(),
                'drainFailed': capture.failure is not None,
                'startupStdoutIsBoundedPrefix': True,
                'startupStdout': bytes(capture.buffers['stdout']).decode('utf-8', 'replace')}
        # Existing capture is at most 8192 bytes; ASCII JSON is at most 6x that plus metadata.
        print(json.dumps(value, ensure_ascii=True), file=sys.stderr, flush=True)
    except BaseException:
        # Secondary diagnostic/pipe failure cannot mask the original first cause.
        pass


def lifecycle_check():
    from process_owner import OwnedProcess
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node is required')
    require_unavailable()
    cycles = []
    for cycle in range(2):
        owner = OwnedProcess.launch([node, str(PACKAGE / 'scripts/start-release.mjs')], cwd=PACKAGE, env=os.environ.copy())
        capture = BoundedOutput(8192)
        reader = threading.Thread(target=capture.drain, args=(owner.stdout, 'stdout'), daemon=True)
        reader.start()
        record = {'cycle': cycle + 1, 'scope': 'whole launcher tree cancellation/restart'}
        first_failure = None
        try:
            record.update(wait_ready(owner, time.monotonic() + 45, capture))
            boundary = 'fs-elem-inert-native-check'
            inert = ('--' + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="unsupported.txt"\r\nContent-Type: text/plain\r\n\r\ninert\r\n--' + boundary + '--\r\n').encode()
            status, _ = request('/api/analysis/jobs', inert, 'multipart/form-data; boundary=' + boundary)
            if status != 415:
                raise RuntimeError('inert unsupported upload must return 415 without inference')
            record['unsupportedUploadStatus'] = status
            capture.check()
            after_code, after_body = request('/api/analysis/health')
            after_health = json.loads(after_body)
            if after_code != 200 or not strict_idle(after_health):
                raise RuntimeError('API must remain explicitly ready and idle after inert 415')
            record['postUnsupportedHealth'] = {'status': after_health['status'],
                'inferenceAvailable': after_health['inferenceAvailable'], 'activeJobId': after_health['activeJobId']}
            capture.check()
        except BaseException as error:
            first_failure = error
        finally:
            for operation in [owner.stop, lambda: owner.wait(timeout=5)]:
                try:
                    operation()
                except BaseException as error:
                    if first_failure is None:
                        first_failure = error
            reader.join(timeout=2)
            if reader.is_alive() and first_failure is None:
                first_failure = RuntimeError('owned output stream did not close')
            try:
                owner.stdout.close()
            except BaseException as error:
                if first_failure is None:
                    first_failure = error
            # Output arriving during stop/wait/drain also prevents a PASS receipt.
            try:
                capture.check()
            except BaseException as error:
                if first_failure is None:
                    first_failure = error
        if first_failure:
            if os.name == 'nt':
                emit_windows_lifecycle_failure(cycle, capture)
            raise first_failure
        require_unavailable()
        record.update({'ownedTreeStopped': True, 'outputBytes': capture.total,
                       'outputTruncated': False, 'outputExceeded': False,
                       'stdout': capture.buffers['stdout'].decode('utf-8', 'replace')})
        cycles.append(record)
    write_receipt('native-package-lifecycle.json', {'platform': sys.platform, 'cycles': cycles,
                  'NN': 0, 'FIT': 0, 'acceptedVideoUploads': 0,
                  'desktopUX': 'pending; HTTP production startup only',
                  'analysisJobCancel': 'covered by separate ten controlled backend tests, not this HTTP smoke'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['ffmpeg', 'lifecycle'])
    args = parser.parse_args()
    (ffmpeg_check if args.phase == 'ffmpeg' else lifecycle_check)()
