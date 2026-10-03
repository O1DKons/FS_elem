#!/usr/bin/env python3
"""Install a fixed release in project-owned directories. Standard library only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from urllib.parse import urlparse
from urllib.request import urlopen


class SetupError(RuntimeError):
    pass


def safe_path(root, relative):
    root = Path(root).resolve()
    p = Path(relative)
    if p.is_absolute() or '..' in p.parts or not p.parts:
        raise SetupError('Path must be relative to the release directory')
    result = (root / p).resolve()
    try:
        result.relative_to(root)
    except ValueError:
        raise SetupError('Path resolves outside the release directory')
    return result


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_manifest(root):
    p = safe_path(root, 'assets/models/manifest-release-v1.json')
    data = json.loads(p.read_text())
    if data.get('schemaVersion') != 1 or not isinstance(data.get('models'), list) or not data['models']:
        raise SetupError('Invalid release model manifest')
    ids = set()
    paths = set()
    for asset in data['models']:
        dest = safe_path(root, asset['path'])
        if asset['id'] in ids or dest in paths:
            raise SetupError('Duplicate model in release manifest')
        ids.add(asset['id']); paths.add(dest)
        if not isinstance(asset.get('sizeBytes'), int) or asset['sizeBytes'] <= 0:
            raise SetupError('Invalid model size')
        digest = asset.get('sha256', '')
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise SetupError('Invalid model checksum')
        if asset.get('url'):
            validate_url(asset['url'])
        if asset.get('format', 'raw') not in ('raw', 'zip'):
            raise SetupError('Unsupported model download format')
        if asset.get('format') == 'zip' and (not isinstance(asset.get('downloadSizeBytes'), int) or asset['downloadSizeBytes'] <= 0):
            raise SetupError('ZIP download size must be pinned separately from ONNX size')
    return data


def validate_url(url):
    p = urlparse(url)
    # HTTP is allowed only for loopback fixture servers, never a remote asset.
    if p.scheme != 'https' and not (p.scheme == 'http' and p.hostname in ('127.0.0.1', 'localhost', '::1')):
        raise SetupError('Model URL must use HTTPS')
    if p.username or p.password or not p.hostname:
        raise SetupError('Invalid model URL')


def verify_asset(path, asset):
    if not path.is_file() or path.stat().st_size != asset['sizeBytes']:
        raise SetupError(f"{asset['id']}: size/checksum mismatch at {asset['path']}; existing file preserved")
    if sha256(path) != asset['sha256']:
        raise SetupError(f"{asset['id']}: checksum mismatch at {asset['path']}; existing file preserved")


def ensure_asset(root, asset):
    path = safe_path(root, asset['path'])
    if path.exists():
        verify_asset(path, asset)
        return path
    url = asset.get('url')
    if not url:
        raise SetupError(f"Missing bundled model {asset['path']}; obtain the complete release package")
    validate_url(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', suffix='.part', dir=path.parent)
    temp = Path(name)
    extracted = None
    try:
        count = 0
        download_size = asset.get('downloadSizeBytes', asset['sizeBytes'])
        with os.fdopen(fd, 'wb') as target, urlopen(url, timeout=60) as response:
            validate_url(response.geturl())
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                count += len(block)
                if count > download_size:
                    raise SetupError(f"{asset['id']}: download exceeds pinned size")
                target.write(block)
        if count != download_size:
            raise SetupError(f"{asset['id']}: download size differs from manifest")
        if asset.get('downloadSha256') and sha256(temp) != asset['downloadSha256']:
            raise SetupError(f"{asset['id']}: archive checksum differs from manifest")
        publish = temp
        if asset.get('format') == 'zip':
            fd, name = tempfile.mkstemp(prefix='.' + path.name + '-onnx-', suffix='.part', dir=path.parent)
            extracted = Path(name)
            try:
                with os.fdopen(fd, 'wb') as output, zipfile.ZipFile(temp) as archive:
                    members = archive.infolist()
                    if len(members) > 1000:
                        raise SetupError('Model archive has too many members')
                    onnx = [m for m in members if not m.is_dir() and m.filename.lower().endswith('.onnx')]
                    if len(onnx) != 1:
                        raise SetupError('Model archive must contain exactly one ONNX file')
                    if onnx[0].file_size != asset['sizeBytes']:
                        raise SetupError('ONNX member size differs from manifest')
                    count = 0
                    with archive.open(onnx[0]) as stream:
                        while True:
                            block = stream.read(1024 * 1024)
                            if not block:
                                break
                            count += len(block)
                            if count > asset['sizeBytes']:
                                raise SetupError('Extracted ONNX exceeds pinned size')
                            output.write(block)
            except (zipfile.BadZipFile, RuntimeError) as error:
                if isinstance(error, SetupError):
                    raise
                raise SetupError('Invalid model ZIP: ' + str(error)) from error
            publish = extracted
        verify_asset(publish, asset)
        # Exclusive publication protects even a file created while downloading.
        try:
            os.link(publish, path)
        except FileExistsError:
            verify_asset(path, asset)
        return path
    finally:
        temp.unlink(missing_ok=True)
        if extracted:
            extracted.unlink(missing_ok=True)


def run(args, capture=False):
    try:
        result = subprocess.run([str(x) for x in args], check=True, text=True,
                                stdout=subprocess.PIPE if capture else None)
        return result.stdout.strip() if capture else None
    except (subprocess.CalledProcessError, OSError) as error:
        raise SetupError(f'Command failed: {args[0]}: {error}') from error


def interpreter_info(executable):
    return json.loads(run([executable, '-c',
        'import json,sys,platform;print(json.dumps({"version":list(sys.version_info[:3]),"machine":platform.machine()}))'], True))


def ensure_environment(root, name, executable, lock_relative):
    if name not in ('science', 'pose'):
        raise SetupError('Unknown release environment')
    dest = safe_path(root, '.runtime/venv-' + name)
    marker = dest / '.release-environment.json'
    if dest.exists() and not marker.is_file():
        raise SetupError(f'Refusing unmanaged environment {dest}; existing contents preserved')
    lock = safe_path(root, lock_relative)
    lock_sha = sha256(lock)
    minor = [3, 12] if name == 'science' else [3, 9]
    if dest.exists():
        state = json.loads(marker.read_text())
        if state.get('status') != 'complete' or state.get('lockSha256') != lock_sha:
            raise SetupError(f'Incomplete or changed managed environment {dest}; see INSTALL.md repair instructions')
        info = interpreter_info(dest / 'bin/python')
        if info['version'][:2] != minor or info['machine'] != 'arm64':
            raise SetupError(f'Wrong interpreter in {dest}')
        run([dest / 'bin/python', '-m', 'pip', 'check'])
        return dest
    info = interpreter_info(executable)
    if info['version'][:2] != minor or info['machine'] != 'arm64':
        raise SetupError(f'{name} requires ARM64 Python {minor[0]}.{minor[1]}; got {info}')
    dest.parent.mkdir(parents=True, exist_ok=True)
    run([executable, '-m', 'venv', dest])
    marker.write_text(json.dumps({'status': 'installing', 'lockSha256': lock_sha, 'pythonMinor': minor}) + '\n')
    run([dest / 'bin/python', '-m', 'pip', 'install', '--no-cache-dir', '--require-hashes', '--only-binary=:all:', '-r', lock])
    run([dest / 'bin/python', '-m', 'pip', 'check'])
    marker.write_text(json.dumps({'status': 'complete', 'lockSha256': lock_sha, 'pythonMinor': minor}) + '\n')
    return dest


def ensure_ffmpeg(root, manifest):
    dest = safe_path(root, '.runtime/bin/ffmpeg')
    asset = manifest['ffmpeg']
    if dest.exists():
        verify_asset(dest, asset)
        return
    # Normal venv interpreters are symlinks to a user-installed Python outside
    # the project. Contain the environment directory, not its interpreter link.
    python = safe_path(root, '.runtime/venv-science') / 'bin/python'
    source = Path(run([python, '-c', 'import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())'], True))
    verify_asset(source, asset)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # The verified wheel binary is copied without modifying the package/cache.
    fd, temp_name = tempfile.mkstemp(prefix='.ffmpeg-', dir=dest.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        shutil.copyfile(source, temp)
        temp.chmod(0o755)
        os.link(temp, dest)
    finally:
        temp.unlink(missing_ok=True)


def check_release(root, manifest):
    issues = []
    for asset in manifest['models']:
        try:
            verify_asset(safe_path(root, asset['path']), asset)
        except SetupError as error:
            issues.append(str(error))
    for name, minor in (('science', [3, 12]), ('pose', [3, 9])):
        try:
            env = safe_path(root, '.runtime/venv-' + name)
            state = json.loads((env / '.release-environment.json').read_text())
            lock = safe_path(root, f'services/analysis/requirements-{name}-macos-arm64.lock')
            if state.get('status') != 'complete' or state.get('lockSha256') != sha256(lock) or sha256(lock) != manifest['environments'][name]['lockSha256']:
                raise SetupError(f'{name}: environment does not match the release lock')
            info = interpreter_info(env / 'bin/python')
            if info['version'][:2] != minor or info['machine'] != 'arm64':
                raise SetupError(f'{name}: wrong Python interpreter')
            pins = manifest['environments'][name]['packages']
            versions = json.loads(run([env / 'bin/python', '-c',
                'import importlib.metadata,json,sys;print(json.dumps({n:importlib.metadata.version(n) for n in sys.argv[1:]}))', *pins], True))
            if versions != pins:
                raise SetupError(f'{name}: installed package versions differ from manifest')
        except (SetupError, OSError, ValueError) as error:
            issues.append(str(error))
    try:
        verify_asset(safe_path(root, '.runtime/bin/ffmpeg'), manifest['ffmpeg'])
    except SetupError as error:
        issues.append(str(error))
    for relative in manifest.get('requiredRuntimeFiles', []):
        if not safe_path(root, relative).is_file():
            issues.append('Missing runtime file: ' + relative)
    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--install', action='store_true', help='Create release environments and obtain pinned models')
    action.add_argument('--check', action='store_true', help='Verify installed assets/dependencies offline; no inference')
    parser.add_argument('--science-python', default='python3.12')
    parser.add_argument('--pose-python', default='python3.9')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        manifest = read_manifest(root)
        for name in ('science', 'pose'):
            environment = manifest['environments'][name]
            if sha256(safe_path(root, environment['lock'])) != environment['lockSha256']:
                raise SetupError(name + ': requirements lock checksum differs from manifest')
        if platform.system() != 'Darwin' or platform.machine() != 'arm64' or int(platform.mac_ver()[0].split('.')[0]) < 13:
            raise SetupError('Release v1 requires macOS 13+ on Apple Silicon (ARM64)')
        if args.install:
            for name, executable in (('science', args.science_python), ('pose', args.pose_python)):
                ensure_environment(root, name, executable, f'services/analysis/requirements-{name}-macos-arm64.lock')
            ensure_ffmpeg(root, manifest)
            for asset in manifest['models']:
                print('Verifying ' + asset['id'], flush=True)
                ensure_asset(root, asset)
        issues = check_release(root, manifest)
        if issues:
            raise SetupError('\n'.join(issues))
        print('Release assets and Python environments verified. Run npm run start:release.')
        return 0
    except (SetupError, OSError, ValueError, KeyError) as error:
        print('Setup failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
