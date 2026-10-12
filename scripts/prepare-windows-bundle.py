#!/usr/bin/env python3
"""Assemble a relocatable Windows application from build-host inputs. No inference."""
import argparse
import hashlib
import json
import pathlib
import shutil
import stat
import tempfile
import urllib.parse
import urllib.request
import zipfile

LIMIT = 1024 * 1024 * 1024


def model_assets(manifest):
    assets = [x for x in manifest['models'] if x.get('url')]
    if {x['id'] for x in assets} != {'yolox', 'rtmw'} or len(assets) != 2:
        raise ValueError('Offline release requires exactly the two existing upstream models')
    for asset in assets:
        if asset['path'] != 'assets/models/' + asset['id'] + '.onnx':
            raise ValueError('Unexpected offline model destination')
        url = urllib.parse.urlsplit(asset['url'])
        if url.scheme != 'https' or url.hostname != 'download.openmmlab.com' or url.username or url.password:
            raise ValueError('Offline build requires the existing official upstream HTTPS source')
        if asset.get('format') != 'zip' or not isinstance(asset['sizeBytes'], int) or not 0 < asset['sizeBytes'] <= LIMIT:
            raise ValueError('Invalid offline model size/format')
        if len(asset['sha256']) != 64 or any(c not in '0123456789abcdef' for c in asset['sha256']):
            raise ValueError('Invalid offline model digest')
    return assets


def safe_member(name):
    parts = pathlib.PurePosixPath(name).parts
    return bool(parts) and pathlib.PurePosixPath(name).as_posix() == name and not name.startswith('/') and '\\' not in name and all(
        p not in ('.', '..') and ':' not in p and p.rstrip(' .') == p for p in parts)


def extract_model(archive, asset, target):
    target = pathlib.Path(target)
    if target.exists() or target.is_symlink():
        raise ValueError('Offline model target must be new')
    with zipfile.ZipFile(archive) as source:
        members = [m for m in source.infolist() if not m.is_dir() and m.filename.lower().endswith('.onnx')]
        if len(members) != 1:
            raise ValueError('Expected exactly one ONNX archive member')
        member = members[0]
        if not safe_member(member.filename) or stat.S_ISLNK(member.external_attr >> 16):
            raise ValueError('Unsafe ONNX archive member')
        if asset.get('archiveMember') and member.filename != asset['archiveMember']:
            raise ValueError('Exact ONNX member name mismatch')
        if member.file_size != asset['sizeBytes']:
            raise ValueError('ONNX archive member size mismatch')
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.model-', suffix='.part', dir=target.parent)
        partial = pathlib.Path(name)
        try:
            count = 0
            h = hashlib.sha256()
            with open(fd, 'wb', closefd=True) as outgoing, source.open(member) as incoming:
                for block in iter(lambda: incoming.read(1024 * 1024), b''):
                    count += len(block)
                    if count > asset['sizeBytes']:
                        raise ValueError('ONNX extraction exceeds exact size')
                    h.update(block)
                    outgoing.write(block)
            if count != asset['sizeBytes'] or h.hexdigest() != asset['sha256']:
                raise ValueError('ONNX extracted bytes/SHA256 mismatch')
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
        return member.filename


def acquire_models(source, output):
    """Build-host only. Never imported/called by the installed launcher."""
    source, output = pathlib.Path(source), pathlib.Path(output)
    assets = model_assets(json.loads((source / 'assets/models/manifest-release-v1.json').read_text('utf-8')))
    if output.exists():
        raise ValueError('Model acquisition output must be new')
    output.mkdir(parents=True)
    records = []
    for asset in assets:
        expected = asset['downloadSizeBytes']
        if not isinstance(expected, int) or not 0 < expected <= LIMIT:
            raise ValueError('Invalid upstream archive size')
        archive = output / (asset['id'] + '.zip.part')
        try:
            request = urllib.request.Request(asset['url'], headers={'User-Agent': 'FS_elem-build/0.2.5'})
            with urllib.request.urlopen(request, timeout=30) as incoming, archive.open('xb') as outgoing:
                resolved = urllib.parse.urlsplit(incoming.geturl())
                if resolved.scheme != 'https' or resolved.hostname != 'download.openmmlab.com':
                    raise ValueError('Unexpected upstream model redirect')
                count = 0
                for block in iter(lambda: incoming.read(1024 * 1024), b''):
                    count += len(block)
                    if count > expected:
                        raise ValueError('Upstream archive exceeds exact download size')
                    outgoing.write(block)
            if archive.stat().st_size != expected:
                raise ValueError('Upstream archive size mismatch')
            archive_sha = digest(archive)
            if asset.get('downloadSha256') and archive_sha != asset['downloadSha256']:
                raise ValueError('Upstream archive SHA256 mismatch')
            member = extract_model(archive, asset, output / asset['path'])
            records.append({**asset, 'archiveMember': member, 'archiveBytes': expected,
                            'archiveSha256': archive_sha})
        finally:
            archive.unlink(missing_ok=True)
    write_json(output / 'offline-models.json', {'schemaVersion': 1, 'models': records,
               'qualification': 'Build-host acquisition; final ONNX SHA/size bound. Preserve manifest checkpoint-license qualification.'})


def verify_offline_models(manifest, models_root):
    root = pathlib.Path(models_root)
    receipt_path = root / 'offline-models.json'
    if root.is_symlink() or receipt_path.is_symlink() or not receipt_path.is_file() or receipt_path.stat().st_size > 65536:
        raise ValueError('Offline model acquisition receipt missing/unsafe')
    root = root.resolve()
    receipt = json.loads(receipt_path.read_text('utf-8'))
    records = receipt.get('models', [])
    assets = model_assets(manifest)
    if len(records) != 2 or {r['id'] for r in records} != {'yolox', 'rtmw'}:
        raise ValueError('Offline model receipt incomplete')
    for asset in assets:
        record = next(r for r in records if r['id'] == asset['id'])
        if any(record.get(k) != asset.get(k) for k in ('path', 'sizeBytes', 'sha256', 'url', 'licenseEvidence', 'checkpointLicenseStatus')):
            raise ValueError('Offline model receipt binding mismatch')
        if not safe_member(record.get('archiveMember', '')) or not record['archiveMember'].lower().endswith('.onnx'):
            raise ValueError('Offline model member receipt invalid')
        if not isinstance(record.get('archiveBytes'), int) or record['archiveBytes'] <= 0 or len(record.get('archiveSha256', '')) != 64:
            raise ValueError('Offline archive receipt identity missing')
        if any(c not in '0123456789abcdef' for c in record['archiveSha256']):
            raise ValueError('Offline archive receipt digest invalid')
        if asset.get('downloadSizeBytes') and record['archiveBytes'] != asset['downloadSizeBytes']:
            raise ValueError('Offline archive receipt size binding changed')
        if asset.get('downloadSha256') and record['archiveSha256'] != asset['downloadSha256']:
            raise ValueError('Offline archive receipt digest binding changed')
        if asset.get('archiveMember') and record['archiveMember'] != asset['archiveMember']:
            raise ValueError('Offline exact archive member binding changed')
        p = root / asset['path']
        if any(q.is_symlink() for q in [p, *p.parents]) or not p.is_file() or p.stat().st_size != asset['sizeBytes'] or digest(p) != asset['sha256']:
            raise ValueError('Offline model missing or corrupt: ' + asset['id'])
    return receipt


def stage_offline_models(manifest, models_root, app):
    app = pathlib.Path(app)
    if app.is_symlink():
        raise ValueError('Offline app destination is a symlink')
    app = app.resolve()
    receipt = verify_offline_models(manifest, models_root)
    assets = model_assets(manifest)
    for asset in assets:
        evidence = asset['licenseEvidence']
        if not safe_member(evidence) or (app / evidence).is_symlink() or not (app / evidence).is_file():
            raise ValueError('Model license evidence missing from payload')
    for asset in assets:
        target = app / asset['path']
        if any(q.is_symlink() for q in [target, *target.parents]):
            raise ValueError('Unsafe offline model destination')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pathlib.Path(models_root) / asset['path'], target)
        if target.stat().st_size != asset['sizeBytes'] or digest(target) != asset['sha256']:
            raise ValueError('Copied offline model binding failed')
    write_json(app / '.runtime/offline-models-receipt.json', receipt)


def digest(path):
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def extract_zip(archive, dest, strip_first=False):
    dest = pathlib.Path(dest)
    if dest.is_symlink():
        raise ValueError("Archive destination is a symlink")
    dest = dest.resolve()
    with zipfile.ZipFile(archive) as source:
        planned = []
        seen = set()
        total = 0
        first = None
        for info in source.infolist():
            name = info.filename
            parts = pathlib.PurePosixPath(name).parts
            if not parts or name.startswith("/") or "\\" in name or any(
                    p in ("..", ".") or ":" in p or p.rstrip(" .") != p for p in parts):
                raise ValueError("Unsafe archive path: " + name)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Archive symlinks are not supported")
            if strip_first:
                if first is None:
                    first = parts[0]
                if parts[0] != first:
                    raise ValueError("Expected one archive root")
                parts = parts[1:]
                if not parts:
                    continue
            target = dest.joinpath(*parts)
            key = str(target).casefold()
            if key in seen:
                raise ValueError("Duplicate Windows archive path")
            seen.add(key)
            if target.exists() and not (info.is_dir() and target.is_dir()):
                raise ValueError("Refusing to overwrite payload file")
            if any(p.is_symlink() for p in [target, *target.parents]):
                raise ValueError("Archive destination contains symlink")
            total += info.file_size
            if total > LIMIT:
                raise ValueError("Runtime archive exceeds extraction bound")
            planned.append((info, target))
        for info, target in planned:
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(info) as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 1024 * 1024)


def copy_tree(source, dest, exclude=()):
    source, dest = pathlib.Path(source), pathlib.Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for p in source.iterdir():
        if p.name in exclude or p.name == "__pycache__" or p.suffix == ".pyc":
            continue
        if p.is_symlink():
            raise ValueError("Portable input must not contain symlinks: " + str(p))
        target = dest / p.name
        if p.is_dir():
            copy_tree(p, target, exclude)
        elif p.is_file():
            if target.exists():
                raise ValueError("Duplicate payload input: " + str(target))
            shutil.copy2(p, target)


def assemble_python(archive, site, dest, minor):
    dest = pathlib.Path(dest)
    scripts = dest / "Scripts"
    extract_zip(archive, scripts)
    stem = "python" + minor.replace(".", "")
    for name in ["python.exe", stem + ".dll", stem + ".zip"]:
        if not (scripts / name).is_file():
            raise ValueError("Embedded Python runtime is incomplete: " + name)
    if (dest / "pyvenv.cfg").exists():
        raise ValueError("Build-host venv cannot be shipped")
    copy_tree(site, dest / "Lib" / "site-packages")
    # Paths remain valid when the entire app is installed elsewhere.
    (scripts / (stem + "._pth")).write_text(
        stem + ".zip\n.\n../Lib/site-packages\n../../..\n../../../scripts\n"
        "../../../services/analysis\n../../../runtime\n../../../runtime/pipeline\nimport site\n",
        encoding="utf-8")


def inventory(root):
    root = pathlib.Path(root)
    result = []
    names = set()
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise ValueError("Payload symlink: " + str(p))
        if not p.is_file():
            continue
        name = p.relative_to(root).as_posix()
        if name.casefold() in names:
            raise ValueError("Case-insensitive payload collision")
        names.add(name.casefold())
        if name == "windows-bundle.json":
            continue
        result.append({"path": name, "bytes": p.stat().st_size, "sha256": digest(p)})
    return result


def write_json(path, value):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def assemble(args):
    app = pathlib.Path(args.output)
    if app.exists():
        raise ValueError("Bundle output must be a new directory")
    source = pathlib.Path(args.source)
    package_version = json.loads((source / 'package.json').read_text('utf-8'))['version']
    if package_version != '0.2.5':
        raise ValueError('Offline assembly requires Root candidate version0.2.5')
    manifest = json.loads((source / 'assets/models/manifest-release-v1.json').read_text('utf-8'))
    verify_offline_models(manifest, args.models_root)
    copy_tree(source, app, exclude=(".git", ".github", ".runtime", "node_modules",
                                    "tests", "tools", "work", "grant-demo"))
    extract_zip(args.node_zip, app / ".runtime" / "node", strip_first=True)
    if not (app / ".runtime/node/node.exe").is_file():
        raise ValueError("Node runtime is incomplete")
    if not args.node_version.startswith("24."):
        raise ValueError("Release requires Node24")
    manifest = json.loads((app / "assets/models/manifest-release-v1.json").read_text("utf-8"))
    native = manifest["platforms"]["windows-x64"]
    profile_sha = hashlib.sha256(json.dumps(native, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    for name, archive, site, minor in [
            ("science", args.science_zip, args.science_site, "3.12"),
            ("pose", args.pose_zip, args.pose_site, "3.9")]:
        env = app / ".runtime" / ("venv-" + name)
        assemble_python(archive, site, env, minor)
        # App-local Microsoft redistributable DLLs; no VC installer on the user host.
        for dll in pathlib.Path(args.vc_runtime).glob("*.dll"):
            dest = env / "Scripts" / dll.name
            if not dest.exists():
                shutil.copy2(dll, dest)
        lock = native["environments"][name]
        if digest(app / lock["lock"]) != lock["lockSha256"]:
            raise ValueError("Release dependency lock binding failed")
        write_json(env / ".release-environment.json", {
            "schemaVersion": 2, "lockSha256": lock["lockSha256"],
            "pythonMinor": [int(x) for x in minor.split(".")],
            "platformId": "windows-x64", "profileSha256": profile_sha, "status": "complete"})
    # FFmpeg is the same pinned science wheel member; no replacement binary.
    ffmpeg = app / ".runtime/venv-science/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe"
    expected = native["ffmpeg"]
    if not ffmpeg.is_file() or ffmpeg.stat().st_size != expected["sizeBytes"] or digest(ffmpeg) != expected["sha256"]:
        raise ValueError("FFmpeg does not match accepted Windows recipe")
    target = app / expected["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ffmpeg, target)
    copy_tree(args.web_modules, app / "apps/web/node_modules")
    for required in ["apps/web/dist/server/index.js", "apps/web/node_modules/vinext/dist/cli.js"]:
        if not (app / required).is_file():
            raise ValueError("Compiled UI/dependencies are incomplete")
    write_json(app / ".runtime/frontend-install.json", {
        "lockSha256": digest(app / "apps/web/pnpm-lock.yaml"), "nodeMajor": 24,
        "pnpmVersion": "11.19.0"})
    launcher = app / "FS_elem.exe"
    shutil.copy2(args.launcher, launcher)
    # Human-authorized offline installer includes only these existing manifest models.
    stage_offline_models(manifest, args.models_root, app)
    allowed = {x["path"] for x in manifest["models"]}
    for asset in manifest["models"]:
        p = app / asset["path"]
        if not p.is_file() or p.stat().st_size != asset["sizeBytes"] or digest(p) != asset["sha256"]:
            raise ValueError("Bundled public model binding failed")
    for p in (app / "assets/models").iterdir():
        if p.suffix in (".onnx", ".joblib") and p.relative_to(app).as_posix() not in allowed:
            raise ValueError("Unlisted model in payload")
    write_json(app / ".runtime/runtime-inputs-receipt.json", {
        "nodeVersion": args.node_version,
        "archives": [{"id": name, "bytes": pathlib.Path(path).stat().st_size, "sha256": digest(path)}
                     for name, path in [("node", args.node_zip), ("science", args.science_zip), ("pose", args.pose_zip)]]})
    files = inventory(app)
    write_json(app / "windows-bundle.json", {
        "schemaVersion": 1, "packageVersion": package_version, "platformId": "windows-x64",
        "offline": True,
        "nativeProfileSha256": profile_sha,
        "node": {"path": ".runtime/node/node.exe", "version": args.node_version},
        "interpreters": {"science": ".runtime/venv-science/Scripts/python.exe",
                         "pose": ".runtime/venv-pose/Scripts/python.exe"},
        "files": files})
    print(json.dumps({"bundle": str(app), "files": len(files),
                      "bytes": sum(x["bytes"] for x in files), "NN": 0}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--acquire-models')
    p.add_argument('--source', required=True)
    for name in ("output", "node-zip", "node-version", "science-zip", "science-site",
                 "pose-zip", "pose-site", "web-modules", "launcher", "vc-runtime", "models-root"):
        p.add_argument("--" + name)
    try:
        args = p.parse_args()
        if args.acquire_models:
            acquire_models(args.source, args.acquire_models)
        else:
            for name in ('output', 'node_zip', 'node_version', 'science_zip', 'science_site', 'pose_zip', 'pose_site', 'web_modules', 'launcher', 'vc_runtime', 'models_root'):
                if not getattr(args, name):
                    raise ValueError('Missing assembly input: ' + name)
            assemble(args)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        p.exit(1, "Bundle assembly failed: " + str(error) + "\n")


if __name__ == "__main__":
    main()
