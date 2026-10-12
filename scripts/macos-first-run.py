"""Import-safe Mac bundle admission. Source candidate; native validation is separate."""
import argparse
import copy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import posixpath
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading

VERSION = "0.2.6"
PYTHON_VERSIONS = {"science": "3.12.15", "pose": "3.9.20"}
BUNDLE_NAME = "macOS-bundle.json"
OWNER_PATH = "services/analysis/process_owner.py"
NATIVE_PROFILE = {
  "status": "ready",
  "platform": {
    "system": "macOS",
    "architecture": "arm64",
    "minVersion": "13"
  },
  "environments": {
    "science": {
      "pythonMinor": "3.12",
      "lock": "services/analysis/requirements-science-macos-arm64.lock",
      "lockSha256": "1e40e7635b80402059c3be3b5e514fcd7812001640b5e426ee2e5c703f98a821",
      "packages": {
        "cloudpickle": "3.1.2",
        "imageio-ffmpeg": "0.6.0",
        "joblib": "1.6.0",
        "narwhals": "2.26.0",
        "numpy": "2.5.3",
        "scikit-learn": "1.9.0",
        "scipy": "1.18.1",
        "threadpoolctl": "3.6.0"
      }
    },
    "pose": {
      "pythonMinor": "3.9",
      "lock": "services/analysis/requirements-pose-macos-arm64.lock",
      "lockSha256": "4be74d2d4efcd57c700f3e81a4f96e1848338959c1f7f4ada9e33d6a8c7a17dd",
      "packages": {
        "coloredlogs": "15.0.1",
        "flatbuffers": "25.12.19",
        "humanfriendly": "10.0",
        "mpmath": "1.3.0",
        "numpy": "2.0.2",
        "onnxruntime": "1.19.2",
        "opencv-contrib-python": "5.0.0.93",
        "opencv-python": "5.0.0.93",
        "packaging": "26.3",
        "protobuf": "6.33.6",
        "rtmlib": "0.0.15",
        "sympy": "1.14.0",
        "tqdm": "4.70.1"
      }
    }
  },
  "ffmpeg": {
    "id": "ffmpeg",
    "path": ".runtime/bin/ffmpeg",
    "sizeBytes": 49368728,
    "sha256": "6d175a4743ca50256e89a8cdd731100f9cee33bd79aeea46894d209410dc6617",
    "distribution": "imageio-ffmpeg==0.6.0 macOS arm64 wheel; local installation only",
    "version": "7.1",
    "binaryLicense": "GPL-2.0-or-later (verified local executable -L)",
    "wrapperLicense": "BSD-2-Clause"
  }
}
MODEL_ROWS = [
  {
    "id": "flight",
    "path": "assets/models/flight.joblib",
    "sizeBytes": 1916697,
    "sha256": "9d6ca74b3de38dab1366c55f55b8de0bca6052ce1aa0c7dedd45ae17cf0140e7",
    "url": None,
    "format": "raw",
    "downloadSizeBytes": None,
    "downloadSha256": None,
    "origin": "app",
    "cacheDestination": None
  },
  {
    "id": "family",
    "path": "assets/models/family.joblib",
    "sizeBytes": 18228,
    "sha256": "1f696a6ab8a300320b7cdff5875ec22a6206ff32bd731c81db00f905529d5f72",
    "url": None,
    "format": "raw",
    "downloadSizeBytes": None,
    "downloadSha256": None,
    "origin": "app",
    "cacheDestination": None
  },
  {
    "id": "nominal",
    "path": "assets/models/nominal.joblib",
    "sizeBytes": 3097,
    "sha256": "f4c2e2b70400bd161a3c9bed62e5e892d6712134719a647a0dd53877bce792f1",
    "url": None,
    "format": "raw",
    "downloadSizeBytes": None,
    "downloadSha256": None,
    "origin": "app",
    "cacheDestination": None
  },
  {
    "id": "yolox",
    "path": "assets/models/yolox.onnx",
    "sizeBytes": 101400344,
    "sha256": "3dea6513388889f0fff4b77bf7a26013600321b9eb9ceb0e9a400a82572f5f23",
    "url": "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/yolox_m_8xb8-300e_humanart-c2c7a14a.zip",
    "format": "zip",
    "downloadSizeBytes": 94223081,
    "downloadSha256": None,
    "origin": "app",
    "cacheDestination": None
  },
  {
    "id": "rtmw",
    "path": "assets/models/rtmw.onnx",
    "sizeBytes": 229320930,
    "sha256": "bd033156e5104c4f5d2edfe0453e02661e30a2f3da453ec93c8764d561b83054",
    "url": "https://download.openmmlab.com/mmpose/v1/projects/rtmw/onnx_sdk/rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.zip",
    "format": "zip",
    "downloadSizeBytes": 213433855,
    "downloadSha256": None,
    "origin": "app",
    "cacheDestination": None
  }
]
MAX_METADATA = 32 * 1024 * 1024


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def relative_name(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("Invalid relative bundle name")
    parts = name.split("/")
    if name.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise ValueError("Noncanonical bundle path")
    return name


def checked_file(root, name, canonical_root=None):
    name = relative_name(name)
    root = Path(root)
    canonical_root = canonical_root or root.resolve(strict=True)
    path = root
    for part in name.split("/"):
        path = path / part
        if stat.S_ISLNK(path.lstat().st_mode):
            raise ValueError("Linked bundle/cache file is not admitted: " + name)
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(canonical_root)
    except ValueError:
        raise ValueError("File escapes original admitted root: " + name)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Expected regular file: " + name)
    return path


def fingerprint(path):
    s = Path(path).lstat()
    if not stat.S_ISREG(s.st_mode):
        raise ValueError("Expected current regular file")
    return dict(dev=str(s.st_dev), ino=str(s.st_ino), bytes=s.st_size,
                mtimeNs=str(s.st_mtime_ns), ctimeNs=str(s.st_ctime_ns))


def read_json(path):
    with Path(path).open("rb") as f:
        body = f.read(MAX_METADATA + 1)
    if len(body) > MAX_METADATA:
        raise ValueError("Metadata too large")
    return json.loads(body), sha_bytes(body)


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def require_external_roots(app_root, user_root):
    app_root, user_root = Path(app_root), Path(user_root)
    if not app_root.is_absolute() or not user_root.is_absolute():
        raise ValueError("Absolute app and user roots are required")
    canonical_app = app_root.resolve(strict=True)
    # Existing symlink user roots are not writable admission targets.
    if user_root.is_symlink():
        raise ValueError("Linked user root")
    prospective_user = user_root.resolve()
    if prospective_user == canonical_app or canonical_app in prospective_user.parents:
        raise ValueError("User data must be external to immutable app")
    if prospective_user in canonical_app.parents:
        raise ValueError("App must not be nested under its user data root")
    return app_root, user_root, canonical_app, prospective_user


def validate_recipe_binding(rule, expected):
    if not isinstance(rule, dict) or rule.get("status") != "source-accepted":
        raise ValueError("Root recipe binding is unresolved")
    paths = {"parent": "configs/axel-release-offline-macos-arm64-parent-v026.json",
             "derived": "configs/axel-release-ort4-macos-app.json",
             "modelManifest": "assets/models/manifest-offline-macos-v026.json"}
    for role, name in paths.items():
        row = rule.get(role, {})
        if (row.get("path") != name or type(row.get("bytes")) is not int or row["bytes"] <= 0
                or not valid_hash(row.get("sha256"))
                or expected.get(name, {}).get("sha256") != row["sha256"]
                or expected.get(name, {}).get("bytes") != row["bytes"]):
            raise ValueError("Root recipe/manifest inventory binding differs: " + role)
    updates = rule.get("sourceUpdates")
    if not isinstance(updates, list) or len(updates) > 128 or not isinstance(rule.get("packagingProvenance"), dict):
        raise ValueError("Root Source update/provenance binding unresolved")
    seen = set()
    for row in updates:
        name = relative_name(row.get("path"))
        key = "../" + name
        if (not name.startswith(("runtime/", "services/", "scripts/")) or row.get("key") != key
                or key in seen or type(row.get("bytes")) is not int or row["bytes"] <= 0
                or not valid_hash(row.get("sha256"))
                or expected.get(name, {}).get("sha256") != row["sha256"]
                or expected.get(name, {}).get("bytes") != row["bytes"]):
            raise ValueError("Invalid/unbound Root Source update")
        seen.add(key)
    return rule


def expected_derived_recipe(original, rule):
    want = copy.deepcopy(original)
    for row in rule["sourceUpdates"]:
        key = row["key"]
        tables = (want["inputSha256"], want["backendSourceProvenance"]["runtimeHashes"], want["backendSourceProvenance"]["runtimeBytes"])
        present = [key in table for table in tables]
        owner_additions = {"scripts/macos-first-run.py", "scripts/macos-bundle.mjs", "scripts/start-macos-desktop.mjs"}
        if not all(present) and not (not any(present) and row["path"] in owner_additions):
            raise ValueError("Root Source update is outside original source maps or exact Main additions")
        want["inputSha256"][key] = row["sha256"]
        want["backendSourceProvenance"]["runtimeHashes"][key] = row["sha256"]
        want["backendSourceProvenance"]["runtimeBytes"][key] = row["bytes"]
    want["packagingProvenance"] = rule["packagingProvenance"]
    return want


def validate_derived_recipe(original, derived, rule):
    if derived != expected_derived_recipe(original, rule):
        raise ValueError("Derived recipe changes outside Root Source/provenance bindings")


def load_binding(app_root, user_root):
    app, user, canonical_app, canonical_user = require_external_roots(app_root, user_root)
    bundle_path = checked_file(app, BUNDLE_NAME, canonical_app)
    bundle, bundle_sha = read_json(bundle_path)
    if (type(bundle.get("schemaVersion")) is not int or bundle.get("schemaVersion") != 1 or bundle.get("packageVersion") != VERSION
            or bundle.get("platformId") != "macos-arm64" or bundle.get("offline") is not True
            or bundle.get("pythonVersions") != PYTHON_VERSIONS):
        raise ValueError("Unsupported Mac bundle")
    if bundle.get("nativeProfileSha256") != sha_bytes(canonical(NATIVE_PROFILE)):
        raise ValueError("Native profile binding differs")
    if bundle.get("interpreters") != {"science": ".runtime/venv-science/bin/python",
                                      "pose": ".runtime/venv-pose/bin/python"}:
        raise ValueError("Interpreter map differs")
    node = bundle.get("node", {})
    if (node.get("path") != ".runtime/bin/node" or type(node.get("major")) is not int or node["major"] != 22
            or node.get("version") != "22.23.3"):
        raise ValueError("Exact bundled Node22 binding is unresolved")
    if (bundle.get("modelManifestPath") != "assets/models/manifest-offline-macos-v026.json"
            or bundle.get("recipePath") != "configs/axel-release-ort4-macos-app.json"
            or bundle.get("originalRecipePath") != "configs/axel-release-offline-macos-arm64-parent-v026.json"):
        raise ValueError("Root recipe/model paths differ")
    rows = bundle.get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Empty bundle inventory")
    expected = {}
    folded = set()
    for row in rows:
        name = relative_name(row.get("path"))
        if (name == BUNDLE_NAME or name.casefold() in folded
                or type(row.get("bytes")) is not int or row["bytes"] < 0
                or not valid_hash(row.get("sha256"))):
            raise ValueError("Invalid/duplicate authoritative inventory row")
        folded.add(name.casefold())
        expected[name] = row
    required = {bundle["modelManifestPath"], bundle["recipePath"], bundle["originalRecipePath"],
                OWNER_PATH, "configs/mac-recipe-binding.json", ".runtime/bin/node", ".runtime/bin/ffmpeg",
                *bundle["interpreters"].values()}
    required.update(r["path"] for r in MODEL_ROWS if r["origin"] == "app")
    required.update(v["lock"] for v in NATIVE_PROFILE["environments"].values())
    if not required <= set(expected):
        raise ValueError("Missing mandatory static inventory file")
    for row in MODEL_ROWS:
        if row["origin"] == "app":
            actual = expected[row["path"]]
            if actual["sha256"] != row["sha256"] or actual["bytes"] != row["sizeBytes"]:
                raise ValueError("Static model authoritative binding differs")
    ff = NATIVE_PROFILE["ffmpeg"]
    if expected[ff["path"]]["sha256"] != ff["sha256"] or expected[ff["path"]]["bytes"] != ff["sizeBytes"]:
        raise ValueError("FFmpeg native profile/inventory binding differs")
    for declaration in NATIVE_PROFILE["environments"].values():
        if expected[declaration["lock"]]["sha256"] != declaration["lockSha256"]:
            raise ValueError("Native environment lock differs")
    if (bundle.get("recipeBindingPath") != "configs/mac-recipe-binding.json"
            or not valid_hash(bundle.get("recipeBindingSha256"))):
        raise ValueError("Root recipe descriptor path/SHA unresolved")
    descriptor_path = checked_file(app, bundle["recipeBindingPath"], canonical_app)
    rule, rule_sha = read_json(descriptor_path)
    if (rule_sha != bundle["recipeBindingSha256"]
            or expected[bundle["recipeBindingPath"]]["sha256"] != rule_sha
            or rule != bundle.get("recipeBinding")):
        raise ValueError("Root recipe descriptor bytes/inventory differs")
    validate_recipe_binding(rule, expected)
    original_path = checked_file(app, rule["parent"]["path"], canonical_app)
    original, original_sha = read_json(original_path)
    if original_sha != rule["parent"]["sha256"] or bundle.get("originalRecipeSha256") != original_sha:
        raise ValueError("Original Root recipe binding differs")
    if expected[bundle["modelManifestPath"]]["sha256"] != rule["modelManifest"]["sha256"]:
        raise ValueError("Model manifest authoritative binding differs")
    derived, derived_sha = read_json(checked_file(app, rule["derived"]["path"], canonical_app))
    validate_derived_recipe(original, derived, rule)
    if derived_sha != rule["derived"]["sha256"]:
        raise ValueError("Derived Root recipe inventory checksum differs")
    binding = dict(app=app, user=user, canonicalApp=canonical_app, canonicalUser=canonical_user, bundle=bundle,
                   bundleSha256=bundle_sha, expected=expected, recipe=derived,
                   derivedRecipeSha256=derived_sha, originalRecipeSha256=original_sha)
    # Fail before downloads for stale Source pins or paths containing literal work.
    materialize_recipe(binding)
    return binding


def scan_static(binding, hash_bodies):
    result = {}
    for name, row in binding["expected"].items():
        path = checked_file(binding["app"], name, binding["canonicalApp"])
        before = fingerprint(path)
        if before["bytes"] != row["bytes"]:
            raise ValueError("Static file size changed: " + name)
        if hash_bodies and sha_file(path) != row["sha256"]:
            raise ValueError("Static file checksum changed: " + name)
        if fingerprint(path) != before:
            raise ValueError("Static file changed during admission")
        result[name] = dict(path=name, sha256=row["sha256"], **before)
    return result


def model_locations(binding):
    rows = {}
    for row in MODEL_ROWS:
        if row["origin"] != "app":
            raise ValueError("Offline model must belong to immutable app")
        rows[row["id"]] = dict(root=binding["app"], path=row["path"], spec=row,
                               canonicalRoot=binding["canonicalApp"])
    return rows


def receipt_preflight(binding, receipt):
    if (type(receipt.get("schemaVersion")) is not int or receipt.get("schemaVersion") != 1 or receipt.get("packageVersion") != VERSION or receipt.get("offline") is not True
            or receipt.get("pythonVersions") != PYTHON_VERSIONS
            or receipt.get("bundleSha256") != binding["bundleSha256"]
            or receipt.get("appRoot") != str(binding["app"])
            or receipt.get("canonicalAppRoot") != str(binding["canonicalApp"])
            or receipt.get("userRoot") != str(binding["user"])
            or receipt.get("canonicalUserRoot") != str(binding["canonicalUser"])
            or receipt.get("nativeProfileSha256") != binding["bundle"]["nativeProfileSha256"]):
        raise ValueError("Stale receipt/root/header binding")
    rows = receipt.get("files")
    if not isinstance(rows, list) or len(rows) != len(binding["expected"]):
        raise ValueError("Receipt inventory composition differs")
    seen = set()
    for row in rows:
        name = relative_name(row.get("path"))
        if name.casefold() in seen or name not in binding["expected"]:
            raise ValueError("Receipt inventory duplicate/extra entry")
        seen.add(name.casefold())
        if row.get("sha256") != binding["expected"][name]["sha256"]:
            raise ValueError("Receipt authoritative digest differs")
    models = receipt.get("models")
    if not isinstance(models, dict) or set(models) != {r["id"] for r in MODEL_ROWS}:
        raise ValueError("Receipt model roles differ")
    for role, location in model_locations(binding).items():
        row, spec = models[role], location["spec"]
        absolute = str(location["root"] / location["path"])
        if (row.get("absolutePath") != absolute or row.get("sha256") != spec["sha256"]
                or row.get("bytes") != spec["sizeBytes"] or row.get("origin") != spec["origin"]):
            raise ValueError("Receipt model map differs")
    return {r["path"]: r for r in rows}


def validate_receipt(binding, receipt):
    expected = receipt_preflight(binding, receipt)
    fresh = scan_static(binding, False)
    if fresh != expected:
        raise ValueError("Current static metadata differs from receipt")
    for role, loc in model_locations(binding).items():
        path = checked_file(loc["root"], loc["path"], loc["canonicalRoot"])
        row = receipt["models"][role]
        if fingerprint(path) != {k: row[k] for k in ("dev", "ino", "bytes", "mtimeNs", "ctimeNs")}:
            raise ValueError("Current model metadata differs")
    current, current_sha = read_selected_generation(binding, receipt)
    if current != materialize_recipe(binding):
        raise ValueError("External recipe content differs")
    return receipt


def materialize_recipe(binding):
    recipe = copy.deepcopy(binding["recipe"])
    locations = model_locations(binding)
    config_parent = PurePosixPath(binding["bundle"]["recipePath"]).parent
    external_parent = binding["user"] / "configs"
    model_names = {r["path"]: r for r in MODEL_ROWS}
    def mapped(value):
        if not isinstance(value, str) or Path(value).is_absolute():
            raise ValueError("Expected original config-relative path")
        name = relative_name(posixpath.normpath(str(config_parent / value)))
        if name in model_names:
            loc = locations[model_names[name]["id"]]
            target = loc["root"] / loc["path"]
        else:
            if name not in binding["expected"]:
                raise ValueError("Unbound path in recipe: " + value)
            target = binding["app"] / name
        # support.py rejects absolute/Windows-drive/literal-work paths.
        relative = Path(os.path.relpath(target, external_parent)).as_posix()
        if (Path(relative).is_absolute() or ":" in relative or "\\\\" in relative
                or "work" in relative.split("/")):
            raise ValueError("Destination cannot satisfy unchanged pipeline relative-path guard")
        if Path(os.path.abspath(external_parent / relative)) != Path(os.path.abspath(target)):
            raise ValueError("Relative overlay changes destination")
        allowed = binding["canonicalApp"]
        prospective = target.resolve()
        if prospective != allowed and allowed not in prospective.parents:
            raise ValueError("Mapped recipe path escapes admitted origin")
        return relative
    for key in ("sciencePython", "posePython", "worker", "sparseExtractor"):
        recipe[key] = mapped(recipe[key])
    recipe["helpers"] = {k: mapped(v) for k, v in recipe["helpers"].items()}
    for row in recipe["models"].values():
        row["path"] = mapped(row["path"])
    for row in recipe["checkpoints"].values():
        row["path"] = mapped(row["path"])
    recipe["ffmpeg"]["path"] = mapped(recipe["ffmpeg"]["path"])
    for source_path, digest in recipe["inputSha256"].items():
        name = relative_name(posixpath.normpath(str(config_parent / source_path)))
        if name not in binding["expected"] or binding["expected"][name]["sha256"] != digest:
            raise ValueError("Recipe input SHA disagrees with static inventory: " + name)
    recipe["inputSha256"] = {mapped(k): v for k, v in recipe["inputSha256"].items()}
    provenance = recipe["backendSourceProvenance"]
    for key in ("runtimeHashes", "runtimeBytes"):
        provenance[key] = {mapped(k): v for k, v in provenance[key].items()}
    # Only config-relative addresses change; scientific values and hashes stay.
    return recipe


def atomic_json(path, value, writable_root=None, canonical_root=None):
    path = Path(path)
    if writable_root is not None:
        writable_root = Path(writable_root)
        canonical_root = canonical_root or writable_root.resolve()
        name = relative_name(path.relative_to(writable_root).as_posix())
        current = writable_root
        for part in name.split("/")[:-1]:
            current = current / part
            if current.is_symlink():
                raise ValueError("Linked writable parent")
        resolved = path.parent.resolve()
        if resolved != canonical_root and canonical_root not in resolved.parents:
            raise ValueError("Writable path escapes original user root")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Refuse linked writable target")
    body = json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False).encode("ascii") + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=".mac-write-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return sha_bytes(body)


def generation_relative_path(digest):
    if not valid_hash(digest):
        raise ValueError("Invalid config generation checksum")
    return "configs/axel-release-ort4-macos-app-" + digest + ".json"


def read_selected_generation(binding, receipt):
    digest = receipt.get("configSha256")
    name = generation_relative_path(digest)
    if (receipt.get("configRelativePath") != name
            or receipt.get("configPath") != str(binding["user"] / name)
            or type(receipt.get("configBytes")) is not int or receipt["configBytes"] <= 0):
        raise ValueError("Unconfined config generation selector")
    path = checked_file(binding["user"], name, binding["canonicalUser"])
    before = fingerprint(path)
    if before["bytes"] != receipt["configBytes"]:
        raise ValueError("Config generation bytes differ")
    current, current_sha = read_json(path)
    if current_sha != digest or fingerprint(path) != before:
        raise ValueError("Config generation checksum/metadata differs")
    return current, current_sha


def write_generation_config(binding, recipe):
    body = json.dumps(recipe, ensure_ascii=True, indent=2, allow_nan=False).encode("ascii") + b"\n"
    digest = sha_bytes(body)
    name = generation_relative_path(digest)
    target = binding["user"] / name
    parent = binding["user"] / "configs"
    if parent.is_symlink():
        raise ValueError("Linked generation directory")
    real_parent = parent.resolve()
    if real_parent != binding["canonicalUser"] and binding["canonicalUser"] not in real_parent.parents:
        raise ValueError("Generation directory escapes admitted user root")
    parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        current = checked_file(binding["user"], name, binding["canonicalUser"])
        parsed, existing_sha = read_json(current)
        if existing_sha != digest or current.stat().st_size != len(body) or parsed != recipe:
            raise ValueError("Existing generation does not match its content address")
    else:
        fd, temporary = tempfile.mkstemp(prefix=".mac-generation-", dir=str(parent))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(body);f.flush();os.fsync(f.fileno())
            # Atomic no-replace publication; never overwrite another generation.
            try:
                os.link(temporary, target)
            except FileExistsError:
                current = checked_file(binding["user"], name, binding["canonicalUser"])
                parsed, existing_sha = read_json(current)
                if existing_sha != digest or current.stat().st_size != len(body) or parsed != recipe:
                    raise ValueError("Concurrent generation publication differs")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)  # Only our uncommitted temporary file.
    return dict(configPath=str(target), configRelativePath=name,
                configSha256=digest, configBytes=len(body))


def commit_ready_generation(binding, receipt, recipe, stopped=None):
    selected = write_generation_config(binding, recipe)
    if scan_static(binding, False) != {r["path"]: r for r in receipt["files"]}:
        raise ValueError("Bundle changed after config generation")
    for role, loc in model_locations(binding).items():
        path = checked_file(loc["root"], loc["path"], loc["canonicalRoot"])
        row = receipt["models"][role]
        if fingerprint(path) != {k: row[k] for k in ("dev", "ino", "bytes", "mtimeNs", "ctimeNs")}:
            raise ValueError("Model changed after config generation")
    updated = dict(receipt, **selected)
    parsed, _ = read_selected_generation(binding, updated)
    if parsed != recipe:
        raise ValueError("New config generation changed before receipt commit")
    if stopped is not None and stopped.is_set():
        raise RuntimeError("Preparation stopped before generation selection")
    # Sole selection commit point: all prior generation/config/receipt bytes stay
    # unchanged until this atomic external ready receipt replacement.
    atomic_json(binding["user"] / "desktop/ready.json", updated,
                binding["user"], binding["canonicalUser"])
    return updated


def bounded_environment_probe(argv):
    p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    lock, buffers, failure = threading.Lock(), [bytearray(), bytearray()], threading.Event()
    def drain(stream, index):
        try:
            while True:
                block = stream.read(4096)
                if not block:
                    break
                with lock:
                    if sum(map(len, buffers)) + len(block) > 65536:
                        failure.set()
                        if p.poll() is None:
                            p.kill()
                        return
                    buffers[index].extend(block)
        finally:
            stream.close()
    readers = [threading.Thread(target=drain, args=(stream, i), daemon=True)
               for i, stream in enumerate((p.stdout, p.stderr))]
    for t in readers:
        t.start()
    try:
        code = p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait(timeout=5)
        raise ValueError("Environment probe exceeded deadline")
    finally:
        for t in readers:
            t.join(timeout=2)
    if any(t.is_alive() for t in readers) or failure.is_set() or code != 0:
        raise ValueError("Environment probe not cleanly closed")
    return bytes(buffers[0])


def validate_environments(binding):
    code = ("import json,sys,importlib.metadata as m;"
            "print(json.dumps({'minor':str(sys.version_info[0])+'.'+str(sys.version_info[1]),'version':'.'.join(map(str,sys.version_info[:3])),"
            "'packages':{k:m.version(k) for k in json.loads(sys.argv[1])}}))")
    for name, declaration in NATIVE_PROFILE["environments"].items():
        python = checked_file(binding["app"], binding["bundle"]["interpreters"][name], binding["canonicalApp"])
        output = bounded_environment_probe([str(python), "-c", code, json.dumps(list(declaration["packages"]))])
        result = json.loads(output)
        if result != {"minor": declaration["pythonMinor"], "version": PYTHON_VERSIONS[name], "packages": declaration["packages"]}:
            raise ValueError("Bundled environment versions differ")
        lock = declaration["lock"]
        if binding["expected"][lock]["sha256"] != declaration["lockSha256"]:
            raise ValueError("Environment lock differs")


def verify_offline_models(binding, emit, stopped):
    models = {}
    for role, loc in model_locations(binding).items():
        if stopped.is_set():
            raise RuntimeError("Preparation stopped")
        path = checked_file(loc["root"], loc["path"], loc["canonicalRoot"])
        before = fingerprint(path)
        if before["bytes"] != loc["spec"]["sizeBytes"] or sha_file(path) != loc["spec"]["sha256"]:
            raise ValueError("Current model checksum differs")
        if fingerprint(path) != before:
            raise ValueError("Model changed during admission")
        models[role] = dict(absolutePath=str(path), sha256=loc["spec"]["sha256"],
                           origin=loc["spec"]["origin"], **before)
    return models


def first_run(app_root, user_root, emit, stopped):
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise ValueError("This candidate requires macOS Apple Silicon")
    if int(platform.mac_ver()[0].split(".")[0]) < 13:
        raise ValueError("This candidate requires macOS13+")
    binding = load_binding(app_root, user_root)
    binding["user"].mkdir(parents=True, exist_ok=True)
    if binding["user"].resolve(strict=True) != binding["canonicalUser"]:
        raise ValueError("User root changed during admission")
    receipt_path = binding["user"] / "desktop/ready.json"
    if receipt_path.is_symlink():
        raise ValueError("Linked ready receipt is not a repair target")
    if receipt_path.exists():
        try:
            receipt, _ = read_json(checked_file(binding["user"], "desktop/ready.json", binding["canonicalUser"]))
            validate_receipt(binding, receipt)
        except (ValueError, KeyError, TypeError, OSError) as error:
            # No stale witness is reused. Full admission below must succeed before
            # an atomic replacement; prior ready/config bytes survive failure.
            emit(dict(type="progress", stage="full_readmission", reason=str(error)))
        else:
            if stopped.is_set():
                raise RuntimeError("Parent/control stopped cached admission")
            emit(dict(type="progress", stage="admitted_cached"))
            return receipt
    emit(dict(type="progress", stage="admission"))
    files = scan_static(binding, True)
    validate_environments(binding)
    models = verify_offline_models(binding, emit, stopped)
    if stopped.is_set():
        raise RuntimeError("Preparation stopped before receipt")
    recipe = materialize_recipe(binding)
    receipt = dict(schemaVersion=1, packageVersion=VERSION, offline=True, pythonVersions=PYTHON_VERSIONS, bundleSha256=binding["bundleSha256"],
                   nativeProfileSha256=binding["bundle"]["nativeProfileSha256"],
                   appRoot=str(binding["app"]), canonicalAppRoot=str(binding["canonicalApp"]),
                   userRoot=str(binding["user"]), canonicalUserRoot=str(binding["canonicalUser"]),
                   originalRecipeSha256=binding["originalRecipeSha256"],
                   derivedRecipeSha256=binding["derivedRecipeSha256"],
                   files=list(files.values()), models=models,
                   qualification="bootstrap admission only; supervisor HTTP/ownership ready is separate")
    if stopped.is_set():
        raise RuntimeError("Preparation stopped before config generation")
    receipt = commit_ready_generation(binding, receipt, recipe, stopped)
    emit(dict(type="progress", stage="prepared"))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", required=True, type=Path)
    parser.add_argument("--user-root", required=True, type=Path)
    args = parser.parse_args()
    stopped = threading.Event()
    def control():
        try:
            body = sys.stdin.buffer.readline(65537)
            if not body or len(body) > 65536 or not body.endswith(b"\n"):
                return
            row = json.loads(body)
            if not isinstance(row, dict) or row.get("type") != "shutdown":
                return
        except Exception:
            return
        finally:
            stopped.set()
    threading.Thread(target=control, daemon=True).start()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    def emit(row):
        print(json.dumps(row, ensure_ascii=True, allow_nan=False), flush=True)
    try:
        first_run(args.app_root, args.user_root, emit, stopped)
        return 0
    except Exception as e:
        emit(dict(type="error", message=str(e)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
