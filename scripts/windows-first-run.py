#!/usr/bin/env python3
"""Verify an installed Windows bundle; no dependency installation or inference."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))  # Explicit installed path, also for isolated embedded Python.
spec = importlib.util.spec_from_file_location('windows_release_setup', SCRIPTS / 'setup-release.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

RECEIPT = '.runtime/windows-ready.json'
MODEL_MANIFEST = 'assets/models/manifest-release-v1.json'
BUNDLE = 'windows-bundle.json'


def read_json(path):
    with Path(path).open('rb') as stream:
        body = stream.read(16 * 1024 * 1024 + 1)
    if len(body) > 16 * 1024 * 1024:
        raise setup.SetupError('Bundle metadata is too large')
    return json.loads(body)


def relative_file(root, path, canonical_root=None):
    if not isinstance(path, str) or '\\' in path or ':' in path:
        raise setup.SetupError('Invalid relative bundle path')
    if Path(path).as_posix() != path or (Path(root) / path).is_symlink():
        raise setup.SetupError('Noncanonical or linked bundle path')
    if canonical_root is None:
        return setup.safe_path(root, path)
    relative = Path(path)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise setup.SetupError('Path must be relative to the release directory')
    # Resolve through the supplied root again to detect replacement of its alias.
    result = (Path(root) / relative).resolve()
    try:
        result.relative_to(canonical_root)
    except ValueError:
        raise setup.SetupError('Path resolves outside the release directory') from None
    return result


def fingerprint(path):
    state = path.lstat()
    if not stat.S_ISREG(state.st_mode):
        raise setup.SetupError('Missing or linked bundle file: ' + str(path))
    # Node/libuv uses the legacy 32-bit Windows volume serial; Python3.12 can expose 64 bits.
    device = state.st_dev & 0xffffffff if os.name == 'nt' else state.st_dev
    return dict(sizeBytes=state.st_size, dev=str(device), ino=str(state.st_ino),
                mtimeNs=str(state.st_mtime_ns), ctimeNs=str(state.st_ctime_ns))


def binding(root, canonical_root=None):
    bundle = read_json(root / BUNDLE)
    manifest = setup.select_profile(setup.read_manifest(root))
    if (manifest['_platformId'] != 'windows-x64' or bundle.get('schemaVersion') != 1
            or bundle.get('packageVersion') != '0.2.3' or bundle.get('platformId') != 'windows-x64'
            or bundle.get('nativeProfileSha256') != manifest['_profileSha256']):
        raise setup.SetupError('Windows bundle/profile binding differs from this release')
    interpreters = {n: f'.runtime/venv-{n}/Scripts/python.exe' for n in ('science', 'pose')}
    if (bundle.get('interpreters') != interpreters or bundle.get('node', {}).get('path') != '.runtime/node/node.exe'
            or not re.fullmatch(r'24\.\d+\.\d+', str(bundle.get('node', {}).get('version', '')))):
        raise setup.SetupError('Bundled interpreter or Node binding is invalid')
    rows = bundle.get('files')
    if not isinstance(rows, list) or not rows or len(rows) > 100000:
        raise setup.SetupError('Missing Windows bundle inventory')
    expected = {}
    windows_paths = set()
    for row in rows:
        path = row.get('path')
        relative_file(root, path, canonical_root)
        if path.casefold() in windows_paths or path in (BUNDLE, RECEIPT):
            raise setup.SetupError('Duplicate or dynamic bundle inventory path')
        windows_paths.add(path.casefold())
        if type(row.get('bytes')) is not int or row['bytes'] < 0 or not re.fullmatch(r'[0-9a-f]{64}', row.get('sha256', '')):
            raise setup.SetupError('Invalid bundle size/checksum')
        expected[path] = row['sha256']
    required = set(interpreters.values()) | {'.runtime/node/node.exe', MODEL_MANIFEST,
        '.runtime/frontend-install.json', 'apps/web/dist/server/index.js', manifest['ffmpeg']['path']}
    required |= {f'.runtime/venv-{n}/.release-environment.json' for n in interpreters}
    if not required <= expected.keys():
        raise setup.SetupError('Incomplete Windows runtime inventory')
    for asset in manifest['models']:
        if asset['path'].casefold() in windows_paths and asset['path'] not in expected:
            raise setup.SetupError('Duplicate Windows model path')
        windows_paths.add(asset['path'].casefold())
        if asset['path'] in expected and expected[asset['path']] != asset['sha256']:
            raise setup.SetupError('Model checksum conflicts with bundle inventory')
        expected[asset['path']] = asset['sha256']
    expected[MODEL_MANIFEST] = setup.sha256(root / MODEL_MANIFEST)
    return bundle, manifest, expected


def cached_ready(root):
    root = Path(root).absolute()
    canonical_root = root.resolve()
    try:
        bundle, manifest, expected = binding(root, canonical_root)
        state = read_json(root / RECEIPT)
        if (state.get('schemaVersion') != 1 or state.get('status') != 'complete'
                or state.get('bundleSha256') != setup.sha256(root / BUNDLE)
                or state.get('modelManifestSha256') != expected[MODEL_MANIFEST]
                or state.get('nativeProfileSha256') != manifest['_profileSha256']):
            return False
        rows = state.get('files', [])
        if len(rows) != len(expected) or {r['path'] for r in rows} != set(expected):
            return False
        for row in rows:
            if row.get('sha256') != expected[row['path']]:
                return False
            current = fingerprint(relative_file(root, row['path'], canonical_root))
            if any(row.get(k) != value for k, value in current.items()):
                return False
        return state
    except (OSError, ValueError, KeyError, TypeError, setup.SetupError):
        return False


def publish_receipt(root, value):
    path = root / RECEIPT
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.windows-ready-', suffix='.part', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(',', ':'))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def bootstrap(root, emit):
    supplied_root = Path(root).absolute()
    root = supplied_root.resolve()
    emit(dict(type='progress', stage='verify', message='Проверка компонентов'))
    if cached_ready(supplied_root):
        emit(dict(type='ready', stage='complete', cached=True, message='Готово'))
        return dict(cached=True)
    # Only this bootstrap-owned receipt is invalidated; user jobs and verified models remain.
    (root / RECEIPT).unlink(missing_ok=True)
    bundle, manifest, expected = binding(root)
    total = sum(row['bytes'] for row in bundle['files'])
    verified = 0
    for index, row in enumerate(bundle['files']):
        path = relative_file(root, row['path'])
        current = fingerprint(path)
        if current['sizeBytes'] != row['bytes'] or setup.sha256(path) != row['sha256']:
            raise setup.SetupError('Повреждён компонент: ' + row['path'] + '. Переустановите FS_elem.')
        verified += row['bytes']
        if index % 100 == 0 or index == len(bundle['files']) - 1:
            emit(dict(type='progress', stage='verify', bytes=verified, total=total,
                      message='Проверка файлов приложения'))
    for asset in manifest['models']:
        setup.ensure_asset(root, asset, progress=emit)
    emit(dict(type='progress', stage='verify', message='Проверка библиотек'))
    issues = setup.check_release(root, manifest)
    if issues:
        raise setup.SetupError('\n'.join(issues))
    receipt = dict(schemaVersion=1, status='complete', bundleSha256=setup.sha256(root / BUNDLE),
                   nativeProfileSha256=manifest['_profileSha256'],
                   modelManifestSha256=expected[MODEL_MANIFEST],
                   files=[dict(path=path, sha256=sha, **fingerprint(relative_file(root, path)))
                          for path, sha in sorted(expected.items())])
    publish_receipt(root, receipt)
    emit(dict(type='ready', stage='complete', cached=False, message='Готово'))
    return dict(cached=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=SCRIPTS.parent)
    args = parser.parse_args(argv)
    # ASCII JSON is UTF-8 compatible even when isolated Windows stdout uses a legacy code page.
    emit = lambda value: print(json.dumps(value, ensure_ascii=True), flush=True)
    try:
        bootstrap(args.root, emit)
        return 0
    except (setup.SetupError, OSError, ValueError, KeyError, TypeError) as error:
        emit(dict(type='error', stage='verify', message=str(error)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
