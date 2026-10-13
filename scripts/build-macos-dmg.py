#!/usr/bin/env python3
"""Root-gated offline Mac development builder. No end-user acquisition or release signing."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import posixpath
import re
import resource
import selectors
import shutil
import signal
import stat
import subprocess
import tarfile
import threading
import time
import urllib.request

VERSION = '0.2.6'
POLICY = 'UNSIGNED_DEVELOPMENT_PREPARATION_ONLY'
ARTIFACT_SHA = {
    'node': '23b25245dcfb9af7262f8ff142e9e2e0af025368117329e7a7458a51e5922f53',
    'science': '233f8e15255b3e1d1fd47ea5dd5230dfed803f371138e896e54d98c60ae19f6f',
    'pose': 'e7551a119bded40bfc268c850110b6a5af1d5fdd63842a56569477490d20e0a6',
}
PYTHON_VERSION = {'science': '3.12.15', 'pose': '3.9.20'}


def need(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path, expected=None, cap=65536):
    path = Path(path)
    need(path.is_file() and not path.is_symlink() and path.stat().st_size <= cap, 'Unsafe bounded metadata')
    body = path.read_bytes()
    need(expected is None or hashlib.sha256(body).hexdigest() == expected, 'Metadata pin changed')
    return json.loads(body)


def rel(name):
    p = PurePosixPath(name)
    need(isinstance(name, str) and name and not p.is_absolute()
         and '..' not in p.parts and '\\' not in name and ':' not in name
         and p.as_posix() == name, 'Noncanonical relative path')
    return p


def disk_bytes(root, deadline, on_missing=None):
    import errno
    import stat
    total = 0
    def missing(error, path):
        if (isinstance(error, FileNotFoundError) and error.errno == errno.ENOENT
                and on_missing is not None and path is not None and path.is_relative_to(root)):
            on_missing(path)
            return True
        return False
    def walk_error(error):
        path = Path(error.filename) if error.filename else None
        if not missing(error, path):
            raise error
    for base, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        need(time.monotonic() < deadline, 'Original resource-walk horizon exhausted')
        for name in list(dirs) + files:
            p = Path(base, name)
            try:
                mode = p.lstat()
            except OSError as error:
                if missing(error, p):
                    if name in dirs:
                        dirs.remove(name)
                    continue
                raise
            if stat.S_ISLNK(mode.st_mode):
                if name in dirs:
                    dirs.remove(name)  # Existing resource accounting excludes links; payload admission remains separate.
            elif stat.S_ISREG(mode.st_mode):
                total += mode.st_size
            need(time.monotonic() < deadline, 'Original resource-walk horizon exhausted')
    need(time.monotonic() < deadline, 'Original resource-walk horizon exhausted')
    return total


class Build:
    def __init__(self, root, original):
        self.root = root
        self.original = original
        self.deadline = original + 2700
        self.work_end = self.deadline - 30
        self.logs = root / 'logs'
        self.logs.mkdir()
        self.tmp = root / 'tmp'
        self.tmp.mkdir()
        self.stream_bytes = 0
        self.stream_lock = threading.Lock()
        self.commands = []
        self.last_disk_check = 0
        self.incomplete_resource_samples = self.missing_resource_events = 0
        self.strict_resource_samples = 0
        self.last_resource_sample_incomplete = False
        self.env = dict(os.environ)
        for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'NODE_OPTIONS'):
            self.env.pop(key, None)
        self.env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1',
                        PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_NO_CACHE_DIR='1',
                        TMPDIR=str(self.tmp), npm_config_cache=str(self.tmp / 'npm-cache'))

    def check(self, producer=None, strict=False):
        need(time.monotonic() < self.work_end, 'Original 45min work horizon exhausted')
        need(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss <= 4294967296,
             'Sampled own RSS exceeds4GiB; no hard/aggregate RSS claim')
        if strict or time.monotonic() - self.last_disk_check >= 1:
            # Retained unreaped OWN child: this sample only, including completion mid-walk.
            live_token = not strict and producer is not None and producer.poll() is None
            incomplete = False
            def missing(path):
                nonlocal incomplete
                need(time.monotonic() < self.work_end, 'Original resource-walk horizon exhausted')
                self.missing_resource_events += 1
                incomplete = True
            callback = missing if live_token else None
            output = disk_bytes(self.root, self.work_end, callback)
            temporary = disk_bytes(self.tmp, self.work_end, callback)
            if incomplete:
                self.incomplete_resource_samples += 1
            self.last_resource_sample_incomplete = incomplete
            need(output <= 8589934592 and temporary <= 4294967296,
                 'Build output/TMP budget exceeded')
            if strict:
                need(not incomplete, 'Strict post-reap resource sample incomplete')
                self.strict_resource_samples += 1
            self.last_disk_check = time.monotonic()

    def observe_group(self, pgid, cleanup_end, label):
        # EPERM is unknown, never absence. ONE full bounded OS snapshot is allowed.
        argv = ['/bin/ps', '-axo', 'pid=,pgid=']
        record = {'argv': argv, 'targetPgid': pgid, 'pid': None, 'pgid': None,
                  'exitCode': None, 'retainedWaitCompleted': False,
                  'stdoutEOF': False, 'stderrEOF': False, 'pipesClosed': False,
                  'snapshotAccepted': False, 'groupPresent': None, 'error': None,
                  'cleanupErrors': []}
        child = None
        selector = None
        chunks = [bytearray(), bytearray()]
        counts = [0, 0]
        try:
            need(time.monotonic() < cleanup_end, 'Original cleanup deadline prevents ps snapshot')
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       env=self.env, start_new_session=True)
            record.update(pid=child.pid, pgid=child.pid)
            selector = selectors.DefaultSelector()
            for index, incoming in enumerate((child.stdout, child.stderr)):
                os.set_blocking(incoming.fileno(), False)
                selector.register(incoming, selectors.EVENT_READ, index)
            while selector.get_map():
                remaining = cleanup_end - time.monotonic()
                need(remaining > 0, 'Original cleanup deadline exhausted during ps snapshot')
                need(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss <= 4294967296,
                     'Sampled own RSS exceeds4GiB during ps snapshot')
                for key, _event in selector.select(timeout=min(0.05, remaining)):
                    block = os.read(key.fileobj.fileno(), 4096)
                    if not block:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        record['stdoutEOF' if key.data == 0 else 'stderrEOF'] = True
                        continue
                    counts[key.data] += len(block)
                    with self.stream_lock:
                        self.stream_bytes += len(block)
                        need(self.stream_bytes <= 16777216, 'Combined log cap16MiB during ps snapshot')
                    need(sum(counts) <= 65536, 'Combined ps snapshot exceeds64KiB')
                    chunks[key.data].extend(block)
            child.wait(timeout=max(0.001, cleanup_end - time.monotonic()))
            record['retainedWaitCompleted'] = True
            need(child.returncode == 0, 'Retained ps snapshot did not exit0')
            need(not chunks[1], 'Retained ps snapshot emitted stderr')
            rows = bytes(chunks[0]).decode('ascii').splitlines()
            need(bool(rows), 'Empty ps snapshot cannot establish global enumeration')
            pairs = []
            for row in rows:
                match = re.fullmatch(r'\s*(\d+)\s+(\d+)\s*', row)
                need(match is not None, 'Nonregular row in full ps snapshot')
                pairs.append((int(match.group(1)), int(match.group(2))))
            need(time.monotonic() < cleanup_end, 'Late ps snapshot is not accepted')
            record.update(snapshotAccepted=True, groupPresent=any(g == pgid for _p, g in pairs),
                          rowCount=len(pairs), snapshotBytes=len(chunks[0]),
                          snapshotSha256=hashlib.sha256(chunks[0]).hexdigest())
        except Exception as error:
            record['error'] = type(error).__name__ + ': ' + str(error)
        finally:
            if child is not None:
                try:
                    if child.poll() is None:
                        # Only this separately retained metadata child's own SID/PGID.
                        try:
                            os.killpg(child.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    child.wait(timeout=max(0.001, cleanup_end - time.monotonic()))
                    record['retainedWaitCompleted'] = True
                except Exception as error:
                    record['cleanupErrors'].append(type(error).__name__ + ': ' + str(error))
                for incoming in (child.stdout, child.stderr):
                    try:
                        incoming.close()
                    except Exception as error:
                        record['cleanupErrors'].append(type(error).__name__ + ': ' + str(error))
                record['exitCode'] = child.returncode
                record['pipesClosed'] = child.stdout.closed and child.stderr.closed
            if selector is not None:
                try:
                    selector.close()
                except Exception as error:
                    record['cleanupErrors'].append(type(error).__name__ + ': ' + str(error))
            record['stdoutObservedBytes'], record['stderrObservedBytes'] = counts
            try:
                for index, suffix in enumerate(('stdout', 'stderr')):
                    path = self.logs / (label + '-group-observation.' + suffix + '.log')
                    with path.open('xb') as outgoing:
                        outgoing.write(chunks[index])
                need(disk_bytes(self.root, cleanup_end) <= 8589934592 and disk_bytes(self.tmp, cleanup_end) <= 4294967296,
                     'Build output/TMP budget exceeded during ps snapshot')
                need(time.monotonic() < cleanup_end, 'Original cleanup deadline exhausted after ps snapshot output')
            except Exception as error:
                record['cleanupErrors'].append(type(error).__name__ + ': ' + str(error))
            if record['cleanupErrors'] or not record['retainedWaitCompleted'] or not record['pipesClosed']:
                record['snapshotAccepted'] = False
                record['groupPresent'] = None
        return record

    def run(self, label, argv, cwd, phase_seconds=None, env=None):
        self.check()
        end = self.work_end if phase_seconds is None else min(self.work_end, time.monotonic() + phase_seconds)
        local = dict(self.env)
        if env:
            local.update(env)
        child = subprocess.Popen([str(a) for a in argv], cwd=cwd, env=local,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, start_new_session=True)
        failures = []
        counts = [0, 0]
        threads = []
        lock = self.stream_lock
        for index, stream in enumerate((child.stdout, child.stderr)):
            output = self.logs / (label + ('.stdout.log' if index == 0 else '.stderr.log'))
            def drain(i=index, incoming=stream, path=output):
                try:
                    with path.open('xb') as outgoing:
                        while True:
                            block = incoming.read(4096)
                            if not block:
                                break
                            with lock:
                                self.stream_bytes += len(block)
                                counts[i] += len(block)
                                if self.stream_bytes > 16777216:
                                    failures.append('Combined log cap16MiB')
                                    continue
                                outgoing.write(block)
                except Exception as error:
                    failures.append(type(error).__name__ + ': ' + str(error))
                finally:
                    incoming.close()
            thread = threading.Thread(target=drain, daemon=True)
            thread.start()
            threads.append(thread)
        first = None
        code = None
        try:
            while child.poll() is None:
                if failures:
                    raise RuntimeError(failures[0])
                need(time.monotonic() < end, 'Original command deadline exceeded: ' + label)
                self.check(producer=child)
                time.sleep(0.05)
            code = child.wait(timeout=max(0.001, self.deadline - time.monotonic()))
            need(code == 0, 'Command failed: ' + label + ' exit=' + str(code))
        except Exception as error:
            first = str(error)
        finally:
            # The original owned group can outlive its retained leader.
            cleanup_end = min(self.deadline, time.monotonic() + 30)
            cleanup_errors = []
            group_gone = False
            waited = False
            kill_requested = False
            group_observation = None

            def group_alive():
                nonlocal group_observation
                try:
                    os.killpg(child.pid, 0)
                except ProcessLookupError:
                    return False
                except PermissionError:
                    if group_observation is None:
                        group_observation = self.observe_group(child.pid, cleanup_end, label)
                    # Present, malformed, truncated, late or failed remains live/unknown.
                    return not (group_observation['snapshotAccepted']
                                and group_observation['groupPresent'] is False)
                return True

            try:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                term_end = min(cleanup_end, time.monotonic() + 5)
                while group_alive() and time.monotonic() < term_end:
                    child.poll()
                    time.sleep(min(0.05, max(0, term_end - time.monotonic())))
                if group_alive():
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                        kill_requested = True
                    except ProcessLookupError:
                        pass
                child.wait(timeout=max(0.001, cleanup_end - time.monotonic()))
                waited = True
                while group_alive() and time.monotonic() < cleanup_end:
                    time.sleep(min(0.05, max(0, cleanup_end - time.monotonic())))
                group_gone = not group_alive()
                if not group_gone:
                    cleanup_errors.append('Original owned child group remains')
            except Exception as error:
                cleanup_errors.append(type(error).__name__ + ': ' + str(error))
            for thread in threads:
                thread.join(timeout=max(0, cleanup_end - time.monotonic()))
            readers_joined = all(not thread.is_alive() for thread in threads)
            if not readers_joined:
                cleanup_errors.append('Physical pipe EOF/reader join unresolved')
            if time.monotonic() >= self.deadline:
                cleanup_errors.append('Original whole build horizon exhausted during cleanup')
            # Metadata closure is mandatory even if a later target probe is absent.
            if group_observation is not None:
                if group_observation['error'] is not None:
                    cleanup_errors.append('Metadata ps error: ' + group_observation['error'])
                cleanup_errors.extend('Metadata ps cleanup: ' + error
                                      for error in group_observation['cleanupErrors'])
                if not (group_observation['snapshotAccepted']
                        and group_observation['stdoutEOF'] and group_observation['stderrEOF']
                        and group_observation['retainedWaitCompleted']
                        and group_observation['exitCode'] == 0 and group_observation['pipesClosed']):
                    cleanup_errors.append('Metadata ps full snapshot/wait/EOF/pipe gate failed')
                if (group_observation['stdoutObservedBytes']
                        + group_observation['stderrObservedBytes'] > 65536
                        or self.stream_bytes > 16777216):
                    cleanup_errors.append('Metadata ps snapshot/shared stream cap failed')
            if first is None and failures:
                first = failures[0]
            record = {'label': label, 'argv': [str(a) for a in argv], 'cwd': str(cwd),
                      'pid': child.pid, 'pgid': child.pid, 'exitCode': child.returncode,
                      'retainedWaitCompleted': waited, 'readersJoined': readers_joined,
                      'originalGroupGone': group_gone, 'killRequested': kill_requested,
                      'stdoutBytes': counts[0], 'stderrBytes': counts[1],
                      'firstFailure': first, 'cleanupErrors': cleanup_errors,
                      'groupObservation': group_observation}
            self.commands.append(record)
        need(first is None and not failures and not cleanup_errors,
             first or (cleanup_errors[0] if cleanup_errors else 'Command failed'))
        need(waited and readers_joined and group_gone, 'Strict resource sample requires retained reap/EOF/group closure')
        self.check(strict=True)
        return self.logs / (label + '.stdout.log')

    def fetch(self, item, target):
        self.check()
        need(item.get('sha256') in ARTIFACT_SHA.values(), 'Unpinned candidate archive')
        need(item['url'].startswith('https://'), 'Archive URL must be HTTPS')
        count = 0
        try:
            with urllib.request.urlopen(item['url'], timeout=min(30, max(1, self.work_end - time.monotonic()))) as incoming, target.open('xb') as outgoing:
                while True:
                    block = incoming.read(1048576)
                    if not block:
                        break
                    count += len(block)
                    need(count <= 1073741824, 'Archive stream exceeds1GiB')
                    outgoing.write(block)
                    self.check()
            need(item.get('bytes') is None or count == item['bytes'], 'Exact archive size differs')
            need(sha(target) == item['sha256'], 'Exact archive SHA differs')
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return count


def extract_closed_tar(archive, destination):
    """Materialize only verified archive-internal FILE aliases; never extract links."""
    need(not destination.exists(), 'Extraction destination must be new')
    with tarfile.open(archive, 'r:gz') as source:
        entries = {}
        prefix = None
        total = 0
        for info in source.getmembers():
            name = info.name.rstrip('/')
            path = rel(name)
            if prefix is None:
                prefix = path.parts[0]
            need(path.parts[0] == prefix, 'Archive must have one closed root')
            need(not info.isdev() and not info.isfifo(), 'Special archive object forbidden')
            key = name.casefold()
            need(key not in entries, 'Case collision in archive')
            entries[key] = info
            total += info.size
            need(total <= 4294967296, 'Expanded archive exceeds4GiB')
        def resolved(info):
            visited = set()
            while info.issym() or info.islnk():
                need(info.name not in visited and len(visited) < 32, 'Archive link cycle')
                visited.add(info.name)
                link = info.linkname
                need(link and not link.startswith('/') and '\\' not in link, 'Absolute/escaped alias')
                target = posixpath.normpath(posixpath.join(posixpath.dirname(info.name), link) if info.issym() else link)
                need(target.startswith(prefix + '/') and target.casefold() in entries, 'Alias leaves archive')
                info = entries[target.casefold()]
            need(info.isfile(), 'Only regular-file aliases admitted; directory/dangling links rejected')
            return info
        planned = []
        materialized_bytes = 0
        for info in entries.values():
            parts = PurePosixPath(info.name.rstrip('/')).parts[1:]
            if not parts:
                need(info.isdir(), 'Archive root must be directory')
                continue
            target = destination.joinpath(*parts)
            if info.isdir():
                planned.append((None, target, 0))
            else:
                real = resolved(info)
                materialized_bytes += real.size
                need(materialized_bytes <= 4294967296, 'Materialized aliases exceed4GiB')
                planned.append((real, target, info.mode & 0o755))
        destination.mkdir(parents=True)
        for info, target, mode in planned:
            if info is None:
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(info) as incoming, target.open('xb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 1048576)
                need(target.stat().st_size == info.size, 'Materialized archive size mismatch')
                target.chmod(mode)


def close_file_aliases(root):
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            target = path.resolve(strict=True)
            need(target.is_relative_to(root.resolve()) and target.is_file(),
                 'Only internal regular-file aliases admitted')
            temporary = path.with_name(path.name + '.closed-copy')
            need(not temporary.exists(), 'Alias materialization collision')
            shutil.copy2(target, temporary)
            path.unlink()
            temporary.rename(path)


def inventory(root):
    rows = []
    for path in sorted(root.rglob('*')):
        need(not path.is_symlink() and (path.is_dir() or path.is_file()), 'Unclosed/special staging')
        if path.is_file():
            rows.append({'path': path.relative_to(root).as_posix(),
                         'bytes': path.stat().st_size, 'sha256': sha(path)})
    need(len(rows) == len({r['path'].casefold() for r in rows}), 'Inventory case collision')
    return rows


def macho_checks(build, root, tools, namespace):
    magics = {bytes.fromhex(s) for s in ('cffaedfe', 'feedfacf', 'cafebabe',
                                          'bebafeca', 'cafebabf', 'bfbafeca')}
    count = 0
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            magic = stream.read(4)
        if magic not in magics:
            continue
        count += 1
        arch = build.run(namespace + '-macho-' + str(count) + '-arch', [tools['lipo'], '-archs', path], root).read_text()
        need('arm64' in arch.split(), 'Mach-O lacks arm64')
        output = build.run(namespace + '-macho-' + str(count) + '-load', [tools['otool'], '-arch', 'arm64', '-l', path], root).read_text()
        versions = re.findall(r'(?m)^\s*(?:minos|version)\s+(\d+\.\d+(?:\.\d+)?)\s*$', output)
        need(versions and all(tuple(int(p) for p in v.split('.'))[:2] <= (13, 0) for v in versions),
             'Mach-O deployment target absent or above macOS13')
        need(not re.search(r'(?m)^\s*name\s+(?:/Users/|/private/|/var/folders/|/opt/homebrew/)', output),
             'Mach-O dylib depends on build-host private path')
    need(count > 0, 'No Mach-O identities found')


def main():
    original = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('package-root', 'work-root', 'grant', 'grant-sha256', 'runtime-inputs',
                 'recipe-binding', 'recipe-binding-sha256', 'desktop-entry-descriptor',
                 'desktop-entry-descriptor-sha256'):
        parser.add_argument('--' + flag, required=True)
    args = parser.parse_args()
    source = Path(args.package_root).resolve()
    work = Path(args.work_root).absolute()
    summary = {'status': 'failed', 'readyForRelease': False, 'NN': 0, 'commands': []}
    build = None
    try:
        grant = read_json(args.grant, args.grant_sha256)
        need(grant.get('scope') == 'mac-offline-build-v026'
             and grant.get('allowBuild') is True and grant.get('retry') == 0
             and grant.get('wholeSeconds') == 2700 and grant.get('cleanupSeconds') == 30
             and grant.get('outputBytes') == 8589934592 and grant.get('tmpBytes') == 4294967296
             and grant.get('ownSampledRSSBytes') == 4294967296
             and grant.get('combinedLogBytes') == 16777216,
             'Exact Root future build admission missing')
        need(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Actual Mac arm64 required')
        need(int(platform.mac_ver()[0].split('.')[0]) >= 13, 'Actual macOS13+ required')
        need(not work.exists() and not work.is_symlink() and not work.is_relative_to(source),
             'Work root must be new/outside Source')
        need(read_json(args.recipe_binding, args.recipe_binding_sha256).get('status') == 'source-accepted'
             and read_json(args.desktop_entry_descriptor, args.desktop_entry_descriptor_sha256).get('status') == 'source-accepted',
             'Future Root recipe/entry accepted descriptors unresolved')
        source_rows = grant.get('sourcePins', [])
        need(source_rows, 'Root Source closure missing')
        required = {'scripts/build-macos-dmg.py', 'scripts/prepare-macos-bundle.py',
                    'apps/macos-launcher/FS_elemApp.swift', 'scripts/macos-first-run.py',
                    'scripts/macos-bundle.mjs', 'scripts/start-macos-desktop.mjs',
                    'scripts/prepare-windows-bundle.py', 'packaging/macos/Info.plist',
                    'services/analysis/requirements-science-macos-arm64.lock',
                    'services/analysis/requirements-pose-macos-arm64.lock',
                    'assets/models/manifest-offline-macos-v026.json',
                    'configs/axel-release-offline-macos-arm64-parent-v026.json',
                    'configs/axel-release-ort4-macos-app.json'}
        need(required.issubset({r['path'] for r in source_rows}), 'Root required Source pins incomplete')
        for row in source_rows:
            path = source / rel(row['path'])
            need(path.is_file() and not path.is_symlink() and path.stat().st_size == row['bytes']
                 and sha(path) == row['sha256'], 'Source pin differs')
        tools = grant.get('tools', {})
        for name in ('python', 'swiftc', 'lipo', 'otool', 'hdiutil'):
            item = tools.get(name, {})
            path = Path(item.get('path', ''))
            need(path.is_absolute() and path.is_file() and path.stat().st_size == item.get('bytes')
                 and sha(path) == item.get('sha256'), 'Root tool identity missing: ' + name)
        paths = {n: tools[n]['path'] for n in tools}
        need(Path(grant.get('sdkPath', '')).is_dir(), 'Root selected SDK unresolved')
        inputs = read_json(args.runtime_inputs)
        need(inputs.get('packageVersion') == VERSION and inputs.get('offline') is True
             and inputs.get('signing', {}).get('policyKind') == POLICY
             and inputs['signing'].get('readyForRelease') is False, 'Wrong candidate/signing policy')
        work.mkdir(parents=True)
        build = Build(work, original)
        runtime = work / 'runtime'
        runtime.mkdir()
        artifact_receipts = {}
        for name in ('node', 'science', 'pose'):
            item = inputs['runtimes'][name]
            need(item['sha256'] == ARTIFACT_SHA[name], 'Candidate artifact differs')
            archive = build.tmp / (name + '.tar.gz')
            size = build.fetch(item, archive)
            destination = runtime if name == 'node' else runtime / ('venv-' + name)
            if name == 'node':
                # Runtime root is already reserved; extract separately then move contents.
                stage = work / 'node-extracted'
                extract_closed_tar(archive, stage)
                for child in stage.iterdir():
                    shutil.move(str(child), runtime / child.name)
                stage.rmdir()
            else:
                extract_closed_tar(archive, destination)
                stem = 'python' + ('3.12' if name == 'science' else '3.9')
                executable = destination / 'bin/python'
                if not executable.exists():
                    shutil.copy2(destination / ('bin/' + stem), executable)
            artifact_receipts[name] = {'bytes': size, 'sha256': sha(archive), 'url': item['url']}
            inputs['runtimes'][name]['bytes'] = size
            archive.unlink()
        node = runtime / 'bin/node'
        science = runtime / 'venv-science/bin/python'
        pose = runtime / 'venv-pose/bin/python'
        build.run('node-version', [node, '-e', "if(process.version!=='v22.23.3')process.exit(1);console.log(process.version)"], work)
        for name, executable, minor in (('science', science, '3.12'), ('pose', pose, '3.9')):
            build.run(name + '-version', [executable, '-I', '-c',
                "import sys;assert '.'.join(map(str,sys.version_info[:3]))=='" + PYTHON_VERSION[name] + "';print(sys.version)"], work)
            site = runtime / ('venv-' + name) / ('lib/python' + minor + '/site-packages')
            build.run(name + '-locked-dependencies', [executable, '-I', '-m', 'pip', 'install',
                '--platform', 'macosx_13_0_arm64',
                '--target', site, '--require-hashes', '--only-binary=:all:', '--no-compile',
                '--no-cache-dir', '-r', source / ('services/analysis/requirements-' + name + '-macos-arm64.lock')], work)
            # Unused generated CLI scripts can contain build-host shebangs.
            shutil.rmtree(site / 'bin', ignore_errors=True)
            build.run(name + '-pip-check', [executable, '-I', '-m', 'pip', 'check'], work)
            evidence = inputs['runtimes'][name].get('licenseEvidence')
            need(isinstance(evidence, str) and (runtime / rel(evidence)).is_file(),
                 'Actual Python component notice binding missing')
        ffmpeg_meta = read_json(source / 'assets/models/manifest-offline-macos-v026.json', cap=1048576)['platforms']['macos-arm64']['ffmpeg']
        binaries = runtime / 'venv-science/lib/python3.12/site-packages/imageio_ffmpeg/binaries'
        candidates = [p for p in binaries.iterdir() if p.is_file() and p.stat().st_size == ffmpeg_meta['sizeBytes'] and sha(p) == ffmpeg_meta['sha256']]
        need(len(candidates) == 1, 'Exact pinned FFmpeg wheel member missing')
        shutil.copy2(candidates[0], runtime / 'bin/ffmpeg')
        ffmpeg_notices = runtime / 'licenses/ffmpeg-runtime-evidence'
        ffmpeg_notices.mkdir(parents=True)
        for flag in ('-version', '-L', '-buildconf'):
            label = 'ffmpeg-' + flag[1:]
            build.run(label, [runtime / 'bin/ffmpeg', flag], work)
            for stream in ('stdout', 'stderr'):
                shutil.copy2(build.logs / (label + '.' + stream + '.log'),
                             ffmpeg_notices / (label + '.' + stream + '.txt'))
        # Build-host-only acquisition reuses the unchanged reviewed Windows helper.
        models = work / 'models'
        build.run('models-build-host-only', [paths['python'], '-I', '-B',
                  source / 'scripts/prepare-windows-bundle.py', '--source', source,
                  '--acquire-models', models], work)
        web = work / 'web'
        web.mkdir()
        for name in ('package.json', 'pnpm-lock.yaml', 'pnpm-workspace.yaml'):
            shutil.copy2(source / 'apps/web' / name, web / name)
        npm = runtime / 'lib/node_modules/npm/bin/npm-cli.js'
        bootstrap = work / 'pnpm'
        build.run('pinned-pnpm-build-host-only', [node, npm, 'install', '--prefix', bootstrap,
                  '--no-save', '--package-lock=false', '--ignore-scripts', '--bin-links=false',
                  '--no-audit', '--no-fund', 'pnpm@11.19.0'], work)
        pnpm = bootstrap / 'node_modules/pnpm/bin/pnpm.cjs'
        build.run('web-runtime', [node, pnpm, '--dir', web, 'install', '--prod',
                  '--frozen-lockfile', '--node-linker=hoisted', '--config.bin-links=false'], work)
        close_file_aliases(web / 'node_modules')
        # Source checkout is immutable: combine in a new closed regular staging.
        combined = work / 'package'
        shutil.copytree(source, combined, ignore=shutil.ignore_patterns('.git', '.github', 'work',
                        '.runtime', 'node_modules', '__pycache__', '*.pyc', 'grant-demo'))
        shutil.copytree(web / 'node_modules', combined / 'apps/web/node_modules')
        need((combined / 'apps/web/dist/server/index.js').is_file(), 'Root compiled frontend Source input missing')
        runtime_notices = inputs['runtimes']['node'].get('licenseEvidence')
        need(isinstance(runtime_notices, str) and (runtime / rel(runtime_notices)).is_file(), 'Node notice binding missing')
        for name in ('science', 'pose'):
            executable = runtime / ('venv-' + name + '/bin/python')
            build.run(name + '-imports', [executable, '-I', '-c',
                      'import numpy,sklearn,joblib' if name == 'science' else 'import cv2,onnxruntime,rtmlib;assert "CPUExecutionProvider" in onnxruntime.get_available_providers()'], work)
        build.run('packaged-analysis-help', [science, '-B', combined / 'runtime/analyze_job.py', '--help'], work)
        launcher = work / 'FS_elem'
        build.run('compile-AppKit', [paths['swiftc'], '-parse-as-library', '-O', '-sdk', grant['sdkPath'],
                  '-target', 'arm64-apple-macosx13.0', '-framework', 'AppKit',
                  combined / 'apps/macos-launcher/FS_elemApp.swift', '-o', launcher], work)
        macho_checks(build, runtime, paths, 'runtime')
        # Check the same compiled binary via a closed one-file directory.
        launcher_check = work / 'launcher-check'
        launcher_check.mkdir()
        shutil.copy2(launcher, launcher_check / 'FS_elem')
        macho_checks(build, launcher_check, paths, 'launcher')
        receipt = {'schemaVersion': 1, 'platformId': 'macos-arm64', 'packageVersion': VERSION,
                   'offline': True, 'signingPolicyKind': POLICY, 'files': inventory(runtime),
                   'artifactSha256': ARTIFACT_SHA, 'artifacts': artifact_receipts}
        receipt_path = work / 'staging-receipt.json'
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        inputs['stagingReceipt'] = {'sha256': sha(receipt_path)}
        inputs['launcher'] = {'bytes': launcher.stat().st_size, 'sha256': sha(launcher)}
        resolved_inputs = work / 'resolved-runtime-inputs.json'
        resolved_inputs.write_text(json.dumps(inputs, indent=2) + '\n')
        image_folder = work / 'dmg-folder'
        image_folder.mkdir()
        app = image_folder / 'FS_elem.app'
        build.run('assemble-offline-app', [paths['python'], '-I', '-B',
                  combined / 'scripts/prepare-macos-bundle.py', '--source-root', combined,
                  '--runtime-root', runtime, '--launcher', launcher, '--inputs', resolved_inputs,
                  '--staging-receipt', receipt_path, '--app-output', app,
                  '--models-root', models, '--recipe-binding', args.recipe_binding,
                  '--recipe-binding-sha256', args.recipe_binding_sha256,
                  '--desktop-entry-descriptor', args.desktop_entry_descriptor,
                  '--desktop-entry-descriptor-sha256', args.desktop_entry_descriptor_sha256], work)
        # This intentional Applications link is DMG navigation, outside payload inventory.
        (image_folder / 'Applications').symlink_to('/Applications', target_is_directory=True)
        dmg = work / 'FS_elem-0.2.6-arm64-DEVELOPMENT.dmg'
        build.run('create-development-dmg', [paths['hdiutil'], 'create', '-ov', '-fs', 'HFS+',
                  '-format', 'UDZO', '-volname', 'FS_elem', '-srcfolder', image_folder, dmg], work)
        dmg_sha = sha(dmg)
        build.check(strict=True)
        summary.update(status='development-artifact-built-not-native-release-accepted',
                       app=str(app), dmg=str(dmg), dmgBytes=dmg.stat().st_size, dmgSha256=dmg_sha,
                       signingPolicyKind=POLICY, readyForRelease=False,
                       gatekeeperQualified=False, sampledOwnPeakRSSBytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except Exception as error:
        summary['firstFailure'] = type(error).__name__ + ': ' + str(error)
    finally:
        if build:
            summary['commands'] = build.commands
            summary['combinedStreamBytes'] = build.stream_bytes
            summary['elapsedSeconds'] = time.monotonic() - original
            summary['incompleteResourceSampleCount'] = build.incomplete_resource_samples
            summary['disappearedMutablePathEventCount'] = build.missing_resource_events
            summary['strictAfterReapSampleCount'] = build.strict_resource_samples
            summary['lastResourceSampleIncomplete'] = build.last_resource_sample_incomplete
            summary['resourceByteTotalsQualification'] = ('Includes counted live-output lower bounds; no continuous peak proof'
                if build.incomplete_resource_samples else 'Strict walks; no continuous peak proof')
        try:
            if build:
                (work / 'build-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
            need(time.monotonic() < original + 2700, 'Original whole horizon exhausted before terminal output')
            print(json.dumps({k: v for k, v in summary.items() if k != 'commands'}), flush=True)
            need(time.monotonic() < original + 2700, 'Original whole horizon exhausted after terminal output')
        except Exception as error:
            summary['status'] = 'failed'
            summary['firstFailure'] = summary.get('firstFailure') or type(error).__name__ + ': ' + str(error)
            if build:
                try:
                    (work / 'build-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
                except Exception as receipt_error:
                    summary['terminalReceiptError'] = type(receipt_error).__name__ + ': ' + str(receipt_error)
            # A late terminal failure has one bounded stderr witness, never exit0.
            os.write(2, (json.dumps({'status': 'failed', 'firstFailure': summary['firstFailure'][:1024]}) + '\n').encode())
    return 0 if summary['status'] == 'development-artifact-built-not-native-release-accepted' else 1


if __name__ == '__main__':
    raise SystemExit(main())
