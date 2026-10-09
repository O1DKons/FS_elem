#!/usr/bin/env python3
"""Assemble a relocatable Windows application from build-host inputs. No inference."""
import argparse
import hashlib
import json
import pathlib
import shutil
import stat
import zipfile

LIMIT = 1024 * 1024 * 1024


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
        "../../../services/analysis\n../../../runtime/pipeline\nimport site\n",
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
    # Only public release manifest models are allowed in the payload.
    allowed = {x["path"] for x in manifest["models"] if not x.get("url")}
    for asset in manifest["models"]:
        if asset.get("url") and (app / asset["path"]).exists():
            raise ValueError("Upstream model must be obtained by first-run downloader")
        if not asset.get("url"):
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
        "schemaVersion": 1, "packageVersion": "0.2.4", "platformId": "windows-x64",
        "nativeProfileSha256": profile_sha,
        "node": {"path": ".runtime/node/node.exe", "version": args.node_version},
        "interpreters": {"science": ".runtime/venv-science/Scripts/python.exe",
                         "pose": ".runtime/venv-pose/Scripts/python.exe"},
        "files": files})
    print(json.dumps({"bundle": str(app), "files": len(files),
                      "bytes": sum(x["bytes"] for x in files), "NN": 0}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "output", "node-zip", "node-version", "science-zip", "science-site",
                 "pose-zip", "pose-site", "web-modules", "launcher", "vc-runtime"):
        p.add_argument("--" + name, required=True)
    try:
        assemble(p.parse_args())
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        p.exit(1, "Bundle assembly failed: " + str(error) + "\n")


if __name__ == "__main__":
    main()
