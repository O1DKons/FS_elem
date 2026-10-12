#!/usr/bin/env python3
"""Prospective native check. Requires an exact, materialized Root grant.

Source preparation only: this file has not been imported or executed on a Mac.
LaunchServices visibility and sandbox-direct network denial are distinct witnesses.
"""
import time
ORIGIN_NS = time.monotonic_ns()
WORK_END_NS = ORIGIN_NS + 570_000_000_000
WHOLE_END_NS = ORIGIN_NS + 600_000_000_000

import argparse
import ctypes
import errno
import hashlib
import http.client
import json
import math
import os
import pathlib
import plistlib
import platform
import pwd
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
import urllib.parse

RAW_LIMIT = 192 * 1024
RECEIPT_LIMIT = 56 * 1024
STDERR_RESERVE = 8 * 1024
LOG_LIMIT = RAW_LIMIT + RECEIPT_LIMIT + STDERR_RESERVE
OWN_RSS_LIMIT = 4 * 1024**3
USER_LIMIT = 64 * 1024**2
VIDEO_SHA = "b142e4df68b709475cc016c35b67d2a6999afc8c7644b91722093cd2e4355b5d"
MODEL_PINS = {
    "flight": (1916697, "9d6ca74b3de38dab1366c55f55b8de0bca6052ce1aa0c7dedd45ae17cf0140e7"),
    "family": (18228, "1f696a6ab8a300320b7cdff5875ec22a6206ff32bd731c81db00f905529d5f72"),
    "nominal": (3097, "f4c2e2b70400bd161a3c9bed62e5e892d6712134719a647a0dd53877bce792f1"),
    "yolox": (101400344, "3dea6513388889f0fff4b77bf7a26013600321b9eb9ceb0e9a400a82572f5f23"),
    "rtmw": (229320930, "bd033156e5104c4f5d2edfe0453e02661e30a2f3da453ec93c8764d561b83054"),
}
DENIAL_PROBE = '''import errno,json,socket,sys
s=socket.socket();s.settimeout(2)
try:
 s.connect(("192.0.2.1",9));raise RuntimeError("external connect unexpectedly succeeded")
except OSError as e:
 if e.errno not in (errno.EACCES,errno.EPERM):raise RuntimeError("denial unproved errno="+str(e.errno))
finally:s.close()
t=socket.create_connection(("127.0.0.1",int(sys.argv[1])),2)
t.sendall(b"FS-ELEM-LOOPBACK-1");value=t.recv(64);t.close()
if value!=b"FS-ELEM-LOOPBACK-OK":raise RuntimeError("loopback handshake failed")
print(json.dumps({"externalConnectDenied":True,"loopbackHandshake":True,"denialErrnoPolicy":"EACCES-or-EPERM"},sort_keys=True))
'''


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def hex_digest(value, width=64):
    return isinstance(value, str) and len(value) == width and all(c in "0123456789abcdef" for c in value)


def exact_int(value, name, minimum=0):
    require(type(value) is int and value >= minimum, "invalid integer " + name)
    return value


def deadline(limit_ns=WORK_END_NS):
    require(time.monotonic_ns() < limit_ns, "original deadline exceeded")


def confined(root, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative, "invalid relative path")
    rel = pathlib.PurePosixPath(relative)
    require(not rel.is_absolute() and all(x not in ("", ".", "..") for x in rel.parts), "unconfined path")
    candidate = root.joinpath(*rel.parts)
    for parent in [root, *candidate.parents]:
        if parent == root.parent:
            break
        require(not parent.is_symlink(), "symlink in admitted path")
    require(not candidate.is_symlink() and candidate.resolve().is_relative_to(root.resolve()), "escaped path")
    return candidate


def read_regular(path, maximum):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and not path.is_symlink(), "input is not a regular file")
    require(before.st_size <= maximum, "input cap exceeded")
    value = path.read_bytes()
    after = path.lstat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), "input changed")
    require(len(value) == before.st_size, "short input")
    return value


class BSDInfo(ctypes.Structure):
    _fields_ = [(x, ctypes.c_uint32) for x in
                ("flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid", "rgid", "svuid", "svgid", "rfu1")]
    _fields_ += [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
    _fields_ += [(x, ctypes.c_uint32) for x in ("nfiles", "pgid", "pjobc", "tdev", "tpgid")]
    _fields_ += [("nice", ctypes.c_int32), ("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64)]


class Native:
    def __init__(self):
        require(ctypes.sizeof(BSDInfo) == 136, "unsupported proc_bsdinfo ABI")
        self.proc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        self.proc.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        self.proc.proc_pidinfo.restype = ctypes.c_int
        self.proc.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        self.proc.proc_pidpath.restype = ctypes.c_int
        self.proc.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
        self.proc.proc_listpids.restype = ctypes.c_int
        self.cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        self.cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        self.cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
        self.cf.CFPropertyListCreateData.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long,
                                                   ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p)]
        self.cf.CFPropertyListCreateData.restype = ctypes.c_void_p
        self.cf.CFDataGetLength.argtypes = [ctypes.c_void_p]
        self.cf.CFDataGetLength.restype = ctypes.c_long
        self.cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
        self.cf.CFDataGetBytePtr.restype = ctypes.c_void_p
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]
        self.appkit = ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
        self.objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        self.objc.objc_getClass.argtypes = [ctypes.c_char_p]
        self.objc.objc_getClass.restype = ctypes.c_void_p
        self.objc.sel_registerName.argtypes = [ctypes.c_char_p]
        self.objc.sel_registerName.restype = ctypes.c_void_p
        address = ctypes.cast(self.objc.objc_msgSend, ctypes.c_void_p).value
        self.message_pid = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int)(address)
        self.message_bool = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(address)

    def identity(self, pid):
        info = BSDInfo()
        ctypes.set_errno(0)
        returned = self.proc.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
        observed_errno = ctypes.get_errno()
        detail = (f"pid={pid} errno={observed_errno} flavor=3 "
                  f"requestedBytes={ctypes.sizeof(info)} returned={returned}")
        if returned == 0:
            require(observed_errno in (0, errno.ESRCH, errno.ENOENT), "process identity unreadable " + detail)
            return None
        require(returned == ctypes.sizeof(info) and info.pid == pid, "process identity ABI mismatch " + detail)
        if info.uid != os.getuid():
            return None  # Foreign users are neither observation targets nor cleanup targets.
        path = ctypes.create_string_buffer(4096)
        length = self.proc.proc_pidpath(pid, path, len(path))
        require(length > 0 or info.status == 5, "live OWN process executable identity unknown")
        return {"pid": pid, "ppid": info.ppid, "pgid": info.pgid, "uid": info.uid,
                "creationSeconds": str(info.start_sec), "creationMicroseconds": str(info.start_usec),
                "status": info.status, "executable": os.fsdecode(path.value) if length > 0 else None}

    @staticmethod
    def same(left, right):
        return left is not None and right is not None and all(left[x] == right[x] for x in
            ("pid", "uid", "creationSeconds", "creationMicroseconds"))

    def snapshot(self):
        pids = (ctypes.c_int * 4096)()
        ctypes.set_errno(0)
        # Official sys/proc_info.h: PROC_UID_ONLY == 4; proc_listpids returns bytes.
        byte_count = self.proc.proc_listpids(4, os.getuid(), pids, ctypes.sizeof(pids))
        require(0 < byte_count < ctypes.sizeof(pids) and byte_count % ctypes.sizeof(ctypes.c_int) == 0,
                f"OWN UID process snapshot unknown or truncated returnedBytes={byte_count} errno={ctypes.get_errno()}")
        count = byte_count // ctypes.sizeof(ctypes.c_int)
        rows = []
        for pid in pids[:count]:
            if pid > 0:
                item = self.identity(pid)  # An unreadable OWN UID identity still fails; no blanket skip.
                if item is not None:
                    rows.append(item)
        require(any(row["pid"] == os.getpid() and row["uid"] == os.getuid() for row in rows),
                "OWN UID snapshot lacks current process identity")
        return rows

    def rss(self, identity):
        current = self.identity(identity["pid"])
        if current is None:
            return 0
        require(self.same(identity, current), "PID generation changed")
        if current["status"] == 5:
            return 0  # An unreaped zombie still counts as present in closure checks.
        buffer = ctypes.create_string_buffer(256)
        returned = self.proc.proc_pidinfo(identity["pid"], 4, 0, buffer, len(buffer))
        require(returned >= 16, "OWN resident size unavailable")
        size = struct.unpack_from("=QQ", buffer.raw)[1]
        after = self.identity(identity["pid"])
        require(after is None or self.same(identity, after), "RSS generation changed")
        return size

    def visible_window(self, identity):
        require(self.same(identity, self.identity(identity["pid"])), "GUI PID changed")
        values = self.cg.CGWindowListCopyWindowInfo(1 | 16, 0)
        require(values, "on-screen window enumeration unavailable")
        encoded = None
        error = ctypes.c_void_p()
        try:
            encoded = self.cf.CFPropertyListCreateData(None, values, 200, 0, ctypes.byref(error))
            require(encoded and not error.value, "window serialization unavailable")
            count = self.cf.CFDataGetLength(encoded)
            require(0 <= count <= 1024 * 1024, "window metadata cap")
            rows = plistlib.loads(ctypes.string_at(self.cf.CFDataGetBytePtr(encoded), count))
            for row in rows:
                bounds = row.get("kCGWindowBounds", {})
                if (row.get("kCGWindowOwnerPID") == identity["pid"] and row.get("kCGWindowLayer") == 0
                        and row.get("kCGWindowIsOnscreen") is True and row.get("kCGWindowAlpha", 0) > 0
                        and bounds.get("Width", 0) > 0 and bounds.get("Height", 0) > 0):
                    return {"ownerPid": identity["pid"], "windowNumber": row.get("kCGWindowNumber"),
                            "ownerName": row.get("kCGWindowOwnerName"), "title": row.get("kCGWindowName"),
                            "onScreen": True, "bounds": bounds}
            return None
        finally:
            if encoded:
                self.cf.CFRelease(encoded)
            if error.value:
                self.cf.CFRelease(error)
            self.cf.CFRelease(values)

    def cooperative_quit(self, identity):
        require(self.same(identity, self.identity(identity["pid"])), "quit target identity changed")
        cls = self.objc.objc_getClass(b"NSRunningApplication")
        selector = self.objc.sel_registerName(b"runningApplicationWithProcessIdentifier:")
        target = self.message_pid(cls, selector, identity["pid"])
        require(target, "AppKit running application unavailable")
        require(self.same(identity, self.identity(identity["pid"])), "quit target changed before terminate")
        require(self.message_bool(target, self.objc.sel_registerName(b"terminate")), "AppKit cooperative quit refused")

    def signal_owned(self, identity, value):
        current = self.identity(identity["pid"])
        if current is None:
            return
        require(self.same(identity, current) and current["uid"] == os.getuid(), "OWN signal identity mismatch")
        if current["status"] == 5:
            return
        require(current["executable"] == identity["executable"], "OWN executable identity changed")
        os.kill(identity["pid"], value)


class Retained:
    def __init__(self, owner, name, argv, limit_ns, environment=None):
        deadline(limit_ns)
        self.owner, self.name, self.argv, self.limit_ns = owner, name, argv, limit_ns
        self.data = [bytearray(), bytearray()]
        self.errors = []
        self.closed = False
        self.identity = None
        self.threads = []
        self.proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     start_new_session=True, env=environment)
        owner.children.append(self)
        self.threads = [threading.Thread(target=self.drain, args=(i, pipe), daemon=True)
                        for i, pipe in enumerate((self.proc.stdout, self.proc.stderr))]
        for thread in self.threads:
            thread.start()
        self.identity = owner.native.identity(self.proc.pid)
        require(self.identity and self.identity["pgid"] == self.proc.pid, "retained new process group unproved")
        owner.observe_root(self.identity)

    def drain(self, index, pipe):
        try:
            while True:
                piece = pipe.read(4096)
                if not piece:
                    break
                with self.owner.lock:
                    available = max(0, RAW_LIMIT - self.owner.raw_count)
                    self.data[index].extend(piece[:available])
                    self.owner.raw_count += len(piece)
                    if self.owner.raw_count > RAW_LIMIT:
                        self.owner.stream_failure = "combined task stdout/stderr cap exceeded"
        except Exception as error:
            self.errors.append(str(error)[:256])
            self.owner.stream_failure = "retained pipe reader failed"

    def wait(self, limit_ns=None, cleanup=False):
        limit_ns = min(limit_ns or self.limit_ns, WHOLE_END_NS)
        while self.proc.poll() is None:
            deadline(limit_ns)
            if not cleanup:
                self.owner.sample(limit_ns)
            time.sleep(min(0.05, max(0, limit_ns - time.monotonic_ns()) / 1e9))
        code = self.proc.wait(timeout=max(0.001, (limit_ns - time.monotonic_ns()) / 1e9))
        for thread in self.threads:
            thread.join(timeout=max(0, (limit_ns - time.monotonic_ns()) / 1e9))
        require(all(not thread.is_alive() for thread in self.threads), "retained pipe EOF unproved")
        for pipe in (self.proc.stdout, self.proc.stderr):
            pipe.close()
        self.closed = True
        require(not self.errors, "retained reader error")
        return code

    def record(self):
        return {"name": self.name, "argv": self.argv, "originalIdentity": self.identity,
                "retainedWaitExitCode": self.proc.returncode if self.closed else None,
                "readersStopped": all(not x.is_alive() for x in self.threads), "pipesClosed": self.closed,
                "stdoutBytesSaved": len(self.data[0]), "stderrBytesSaved": len(self.data[1]), "readerErrors": self.errors}


class Check:
    def __init__(self, args):
        self.args = args
        self.native = None
        self.children = []
        self.known = {}
        self.root_keys = set()
        self.samples = 0
        self.rss_max_sample = 0
        self.user_bytes_max_sample = 0
        self.raw_count = 0
        self.stream_failure = None
        self.lock = threading.Lock()
        self.first_failure = None
        self.cleanup_errors = []
        self.witnesses = []
        self.output = pathlib.Path(args.output_dir).absolute()
        self.home = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir)
        self.user_root = self.home / "Library/Application Support/FS_elem"
        self.installed = None
        self.original_inventory = []
        self.application_removed = False
        self.analysis_phase_active = False
        self.analysis_whole_end_ns = None
        self.receipt = {"status": "failed", "sourcePreparationOnlyUntilAdmitted": True,
                        "originMonotonicNs": str(ORIGIN_NS), "originalWorkDeadlineNs": str(WORK_END_NS),
                        "originalWholeDeadlineNs": str(WHOLE_END_NS), "workSeconds": 570, "wholeSeconds": 600,
                        "cleanupSeconds": 30, "retries": 0, "networkBoundary": {
                            "launchServicesCoverage": "unknown; brokered process may escape profile",
                            "sandboxDirectCoverage": "unverified until native profile/probe/direct launch"},
                        "continuousResourceCoverage": False, "independentParentReapOrSyscallAudit": False}

    @staticmethod
    def key(row):
        return (row["pid"], row["creationSeconds"], row["creationMicroseconds"], row["uid"])

    def observe_root(self, row):
        self.known[self.key(row)] = row
        self.root_keys.add(self.key(row))

    def sample(self, limit_ns=WORK_END_NS):
        deadline(limit_ns)
        require(self.stream_failure is None, self.stream_failure or "stream failure")
        rows = self.native.snapshot()
        by_pid = {row["pid"]: row for row in rows}
        live_pids = {row["pid"] for row in self.known.values()
                     if self.native.same(row, by_pid.get(row["pid"]))}
        changed = True
        while changed:
            changed = False
            for row in rows:
                if row["ppid"] in live_pids and row["uid"] == os.getuid() and self.key(row) not in self.known:
                    require(len(self.known) < 128, "OWN process identity ledger cap")
                    self.known[self.key(row)] = row
                    live_pids.add(row["pid"])
                    changed = True
        own = [row for row in self.known.values() if self.native.same(row, by_pid.get(row["pid"]))]
        require(all(not row["executable"] or pathlib.Path(row["executable"]).name not in ("Terminal", "iTerm2") for row in own),
                "owned console application observed")
        rss = self.native.rss(self.native.identity(os.getpid())) + sum(self.native.rss(row) for row in own)
        self.rss_max_sample = max(self.rss_max_sample, rss)
        require(rss <= OWN_RSS_LIMIT, "sampled OWN RSS exceeded 4 GiB")
        user_size = 0
        if self.user_root.exists():
            for base, directories, files in os.walk(self.user_root, followlinks=False):
                for name in directories + files:
                    item = pathlib.Path(base) / name
                    info = item.lstat()
                    require(not stat.S_ISLNK(info.st_mode), "symlink in fresh user root")
                    if stat.S_ISREG(info.st_mode):
                        user_size += info.st_size
                        require(user_size <= USER_LIMIT, "new user state exceeded 64 MiB")
        self.user_bytes_max_sample = max(self.user_bytes_max_sample, user_size)
        self.samples += 1
        deadline(limit_ns)
        return rows

    def bind(self):
        deadline()
        require(platform.system() == "Darwin" and platform.machine() == "arm64", "native arm64 Mac required")
        version = platform.mac_ver()[0]
        require(version and int(version.split(".")[0]) >= 13, "macOS 13 or newer required")
        grant_raw = read_regular(pathlib.Path(self.args.root_grant), 65536)
        require(hex_digest(self.args.root_grant_sha256) and sha_bytes(grant_raw) == self.args.root_grant_sha256,
                "Root grant SHA mismatch")
        grant = json.loads(grant_raw)
        require(grant.get("kind") == "ROOT_ADMITTED_GENERATED_MAC_OFFLINE_NATIVE_GRANT"
                and grant.get("actualAuthorization") is True, "actual materialized Root grant required")
        require(grant.get("sourceRef") == "refs/heads/release/v0.2.6"
                and hex_digest(grant.get("sourceCommit"), 40), "release identity invalid")
        for field, env in (("sourceRef", "GITHUB_REF"), ("sourceCommit", "GITHUB_SHA"),
                           ("runId", "GITHUB_RUN_ID"), ("runAttempt", "GITHUB_RUN_ATTEMPT")):
            require(isinstance(grant.get(field), str) and grant[field] and grant[field] == os.environ.get(env),
                    "actual workflow identity mismatch: " + field)
        require(grant.get("checkerSha256") == sha_bytes(read_regular(pathlib.Path(__file__), 65536)), "checker pin mismatch")
        require(grant.get("limits") == {"wholeSeconds": 600, "workSeconds": 570, "cleanupSeconds": 30,
                    "ownSampledRssBytes": OWN_RSS_LIMIT, "newUserBytes": USER_LIMIT,
                    "combinedLogsBytes": LOG_LIMIT, "retries": 0}, "resource admission mismatch")
        require(pathlib.Path.home() == self.home and os.environ.get("HOME") == str(self.home),
                "genuine unchanged OS user home required")
        require(grant.get("unsignedDevelopmentOnly") is True, "unsigned native policy admission absent")
        require(grant.get("allowOwnedApplicationRemoval") is True and grant.get("freshApplicationInstall") is True,
                "fresh owned application removal admission absent")
        self.installed = pathlib.Path(self.args.installed_app).absolute()
        applications = (pathlib.Path("/Applications"), self.home / "Applications")
        require(self.installed.parent in applications and self.installed.suffix == ".app"
                and not self.installed.is_symlink() and self.installed.is_dir(), "ordinary Applications installation required")
        require(grant.get("installedApp") == str(self.installed), "installed application path not admitted")
        require(grant.get("userRoot") == str(self.user_root), "actual Swift default user root not admitted")
        require(not self.user_root.exists() and not self.user_root.is_symlink(), "preexisting user state: refuse to alter it")
        require(not self.output.exists() and self.output.parent.is_dir(), "fresh bounded output directory required")
        self.output.mkdir()
        payload = confined(self.installed, "Contents/Resources/payload")
        metadata_path = confined(self.installed, grant["packageMetadataRelativePath"])
        metadata_raw = read_regular(metadata_path, 1024 * 1024)
        require(sha_bytes(metadata_raw) == grant.get("packageMetadataSha256"), "package metadata mismatch")
        metadata = json.loads(metadata_raw)
        descriptor_relative = grant.get("recipeBindingRelativePath")
        require(descriptor_relative == "configs/mac-recipe-binding.json", "Root recipe binding path unknown")
        require(metadata.get("recipeBindingPath") == descriptor_relative, "metadata binding path mismatch")
        descriptor = read_regular(confined(payload, descriptor_relative), 65536)
        binding = json.loads(descriptor)
        require(metadata.get("recipeBindingSha256") == sha_bytes(descriptor)
                and grant.get("recipeBindingSha256") == sha_bytes(descriptor)
                and metadata.get("recipeBinding") == binding and grant.get("recipeBinding") == binding,
                "raw descriptor/object binding mismatch")
        require(metadata.get("version") == "0.2.6", "package version mismatch")
        info = plistlib.loads(read_regular(confined(self.installed, "Contents/Info.plist"), 65536))
        executable_name = info.get("CFBundleExecutable")
        require(isinstance(executable_name, str) and executable_name and "/" not in executable_name, "invalid app executable")
        self.app_exe = confined(self.installed, "Contents/MacOS/" + executable_name)
        require(os.access(self.app_exe, os.X_OK), "application executable absent")
        self.base = grant.get("uiBaseUrl")
        split = urllib.parse.urlsplit(self.base or "")
        require(split.scheme == "http" and split.hostname == "127.0.0.1" and split.port == 5174
                and split.path == "" and not split.query and not split.fragment and not split.username,
                "exact owned loopback UI URL required")
        require(grant.get("healthPath") == "/api/analysis/health" and grant.get("jobsPath") == "/api/analysis/jobs"
                and grant.get("uiPath") == "/analysis", "new Main endpoint contract not admitted")
        self.port = split.port
        profile = read_regular(pathlib.Path(self.args.sandbox_profile), 4096)
        require(sha_bytes(profile) == grant.get("sandboxProfileSha256"), "sandbox profile pin mismatch")
        require(grant.get("admitDocumentationAddressDenialProbe") is True, "actual external denial probe not admitted")
        science_relative = grant.get("sciencePythonRelativePath")
        require(science_relative, "portable science Python path unknown")
        self.science_python = confined(payload, science_relative)
        require(os.access(self.science_python, os.X_OK), "bundled science Python unavailable")
        video = read_regular(pathlib.Path(self.args.offline_video), 818120)
        require(len(video) == 818120 and sha_bytes(video) == VIDEO_SHA, "approved public sample mismatch")
        self.video = video
        inventory_path = pathlib.Path(grant.get("installedInventoryPath") or "")
        require(inventory_path.is_absolute() and not inventory_path.resolve().is_relative_to(self.installed.resolve()),
                "separate generated Root inventory path required; avoid self-hash cycles")
        inventory_size = exact_int(grant.get("installedInventoryBytes"), "installedInventoryBytes", 1)
        require(inventory_size <= 4 * 1024**2, "installed inventory input cap exceeded")
        inventory_raw = read_regular(inventory_path, inventory_size)
        require(len(inventory_raw) == inventory_size and sha_bytes(inventory_raw) == grant.get("installedInventorySha256"),
                "exact generated installed inventory mismatch")
        inventory = json.loads(inventory_raw)
        require(isinstance(inventory, list) and 5 <= len(inventory) <= 65536, "bound installed inventory absent")
        admitted_total = exact_int(grant.get("installedReadBytesCap"), "installedReadBytesCap", 1)
        require(admitted_total <= 1536 * 1024**2, "installed read cap too large")
        seen, total, models = set(), 0, set()
        for item in inventory:
            deadline()
            relative, size, digest = item.get("path"), exact_int(item.get("bytes"), "inventory.bytes"), item.get("sha256")
            require(relative not in seen and hex_digest(digest), "duplicate or unbound inventory row")
            seen.add(relative)
            file = confined(self.installed, relative)
            before = file.lstat()
            require(stat.S_ISREG(before.st_mode) and before.st_size == size, "installed file identity mismatch")
            total += size
            require(total <= admitted_total, "installed read budget exceeded")
            calculated = hashlib.sha256()
            with file.open("rb") as stream:
                while True:
                    deadline()
                    block = stream.read(1024 * 1024)
                    if not block:
                        break
                    calculated.update(block)
            after = file.lstat()
            require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    and calculated.hexdigest() == digest, "installed content changed or SHA mismatch")
            model = item.get("model")
            if model is not None:
                require(model in MODEL_PINS and (size, digest) == MODEL_PINS[model] and model not in models,
                        "bundled model identity mismatch")
                models.add(model)
            self.original_inventory.append((relative, size, digest))
        require(models == set(MODEL_PINS), "all five exact offline models required")
        self.native = Native()
        self.before_processes = {self.key(row) for row in self.native.snapshot()}
        require(not any(row["executable"] == str(self.app_exe) for row in self.native.snapshot()), "application already running")
        self.require_port_free()
        self.receipt.update({"sourcePreparationOnlyUntilAdmitted": False, "rootGrantSha256": sha_bytes(grant_raw),
                             "sourceCommit": grant["sourceCommit"], "runId": grant["runId"], "runAttempt": grant["runAttempt"],
                             "macOS": version, "architecture": "arm64", "installedApp": str(self.installed),
                             "userRoot": str(self.user_root), "installedReadBytes": total,
                             "installedInventorySha256": sha_bytes(inventory_raw), "installedInventoryFiles": len(inventory),
                             "recipeBindingSha256": sha_bytes(descriptor), "unsignedDevelopmentOnly": True,
                             "gatekeeperNotarizationProof": False, "models": sorted(models)})

    def require_port_free(self):
        with socket.socket() as probe:
            probe.settimeout(0.2)
            require(probe.connect_ex(("127.0.0.1", self.port)) != 0, "admitted UI port already occupied")

    def request(self, method, path, body=None, headers=None, maximum=1024 * 1024, limit_ns=WORK_END_NS):
        limit_ns = min(limit_ns, WORK_END_NS)
        deadline(limit_ns)
        require(path.startswith("/") and not path.startswith("//"), "relative HTTP path required")
        remaining = max(0.001, min(2.0, (limit_ns - time.monotonic_ns()) / 1e9))
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=remaining)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            data = response.read(maximum + 1)
            require(len(data) <= maximum, "HTTP response cap exceeded")
            deadline(limit_ns)
            return response.status, data
        finally:
            connection.close()

    def app_ready(self, flow, app_handle):
        local_end = min(WORK_END_NS, time.monotonic_ns() + 90_000_000_000)
        app_identity, window = None, None
        first_transient = None
        while True:
            rows = self.sample(local_end)
            require(app_handle.proc.poll() is None, "launch waiter/process exited before readiness")
            matches = [row for row in rows if row["executable"] == str(self.app_exe)
                       and row["uid"] == os.getuid() and self.key(row) not in self.before_processes]
            require(len(matches) <= 1, "ambiguous fresh application identity")
            if matches:
                if app_identity is None:
                    app_identity = matches[0]
                    self.observe_root(app_identity)
                require(self.native.same(app_identity, matches[0]), "application generation changed during readiness")
                window = self.native.visible_window(app_identity)
                if window:
                    try:
                        status, data = self.request("GET", "/api/analysis/health", maximum=65536)
                        health = json.loads(data) if status == 200 else {}
                        if (status == 200 and health.get("status") == "ready" and health.get("inferenceAvailable") is True
                                and "activeJobId" in health and health["activeJobId"] is None):
                            ui_status, _ = self.request("GET", "/analysis")
                            if ui_status == 200:
                                require(self.native.same(app_identity, self.native.identity(app_identity["pid"]))
                                        and app_handle.proc.poll() is None, "application exited after health await")
                                deadline(local_end)
                                self.witnesses.append({"flow": flow, "applicationIdentity": app_identity,
                                                       "visibleWindow": window, "uiHttpStatus": 200,
                                                       "strictIdleHealth": True, "firstTransient": first_transient})
                                return app_identity
                    except (OSError, ValueError, http.client.HTTPException) as error:
                        first_transient = first_transient or str(error)[:256]
            time.sleep(0.1)

    def close_cooperatively(self, app, handle, flow, phase_end=None):
        end = min(WORK_END_NS, time.monotonic_ns() + 31_000_000_000, phase_end or WORK_END_NS)
        self.sample(end)
        self.native.cooperative_quit(app)
        while True:
            handle.proc.poll()  # Reap the retained direct app before requiring generation absence.
            if not self.native.same(app, self.native.identity(app["pid"])):
                break
            self.sample(end)
            time.sleep(0.05)
        code = handle.wait(end)
        require(code == 0, "cooperative launch waiter/app exit nonzero")
        self.require_known_closed(end)
        self.require_port_free()
        self.witnesses.append({"flow": flow, "cooperativeQuit": True, "retainedWaitExitCode": code,
                               "knownOwnedGenerationsGone": True, "continuousDescendantCoverage": False})

    def require_known_closed(self, limit_ns):
        while True:
            for child in self.children:
                if not child.closed:
                    child.proc.poll()  # Reap retained zombies; wait() still proves exit and pipe closure.
            self.sample(limit_ns)
            alive = [row for row in self.known.values()
                     if self.native.same(row, self.native.identity(row["pid"]))]
            if not alive:
                return
            time.sleep(0.05)

    def network_probe(self):
        listener = socket.socket()
        peer = None
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(min(3, max(0.001, (WORK_END_NS - time.monotonic_ns()) / 1e9)))
            end = min(WORK_END_NS, time.monotonic_ns() + 10_000_000_000)
            probe = Retained(self, "sandbox-denial-loopback-probe", ["/usr/bin/sandbox-exec", "-f",
                self.args.sandbox_profile, str(self.science_python), "-I", "-B", "-c", DENIAL_PROBE,
                str(listener.getsockname()[1])], end)
            peer, address = listener.accept()
            require(address[0] == "127.0.0.1", "loopback peer mismatch")
            peer.settimeout(2)
            require(peer.recv(64) == b"FS-ELEM-LOOPBACK-1", "loopback probe handshake invalid")
            peer.sendall(b"FS-ELEM-LOOPBACK-OK")
            require(probe.wait(end) == 0, "native sandbox denial/loopback probe failed")
            data = json.loads(bytes(probe.data[0]))
            require(data.get("externalConnectDenied") is True and data.get("loopbackHandshake") is True,
                    "native sandbox denial receipt incomplete")
            self.receipt["networkBoundary"]["sandboxDirectCoverage"] = (
                "same exact sandbox profile: probe EACCES/EPERM and real loopback; direct app inherits profile; "
                "Finder flow separate; no packet trace or global network policy proof")
            self.witnesses.append({"flow": "sandbox-profile-preflight", "probe": data})
        finally:
            if peer:
                peer.close()
            listener.close()

    def direct_launch(self, name):
        self.require_port_free()
        env = {key: value for key, value in os.environ.items() if key in ("HOME", "TMPDIR", "LANG", "LC_CTYPE")}
        env["PATH"] = "/usr/bin:/bin"
        return Retained(self, name, ["/usr/bin/sandbox-exec", "-f", self.args.sandbox_profile, str(self.app_exe)],
                        WORK_END_NS, env)

    def one_analysis(self):
        status, _ = self.request("POST", "/api/analysis/jobs", b"not a video",
                                 {"X-Filename": "not-a-video.txt", "Content-Type": "application/octet-stream"})
        require(status == 415, "unsupported media must produce HTTP415")
        self.analysis_origin_ns = time.monotonic_ns()
        self.analysis_whole_end_ns = self.analysis_origin_ns + 150_000_000_000
        self.analysis_phase_active = True
        end = min(WORK_END_NS, self.analysis_origin_ns + 120_000_000_000)
        status, raw = self.request("POST", "/api/analysis/jobs", self.video,
            {"X-Filename": "example-1a.mp4", "Content-Type": "application/octet-stream"}, maximum=65536, limit_ns=end)
        require(status == 202, "one approved public upload not accepted")
        job = json.loads(raw).get("jobId")
        require(isinstance(job, str) and 0 < len(job) <= 128 and all(c.isalnum() or c in "-_" for c in job),
                "invalid job identifier")
        path = "/api/analysis/jobs/" + urllib.parse.quote(job, safe="")
        while True:
            self.sample(end)
            status, raw = self.request("GET", path, maximum=65536, limit_ns=end)
            require(status == 200, "job polling HTTP failure")
            poll = json.loads(raw)
            state = poll.get("state")
            require(state not in ("failed", "cancelled"), "native analysis failed: " + str(poll.get("error"))[:256])
            if state == "succeeded":
                break
            time.sleep(0.1)
        status, result_raw = self.request("GET", path + "/result", limit_ns=end)
        require(status == 200, "completed result HTTP failure")
        result = json.loads(result_raw)
        source = result.get("source", {})
        require(result.get("status") == "completed" and source.get("sha256") == VIDEO_SHA
                and source.get("frameCount") == 181 and type(source.get("durationSeconds")) in (int, float)
                and abs(source["durationSeconds"] - 3.0) <= 0.1, "completed result/source identity mismatch")
        require(any(item.get("family") == "axel" and item.get("nominal") == "1A"
                    for item in result.get("events", [])), "familiar sample nominal1A result absent")
        status, pose_raw = self.request("GET", path + "/pose", limit_ns=end)
        require(status == 200, "pose HTTP failure")
        pose = json.loads(pose_raw)
        frames = pose.get("frames")
        require(pose.get("source", {}).get("sha256") == VIDEO_SHA
                and pose.get("layout") == "coco-wholebody-first23"
                and isinstance(frames, list) and 0 < len(frames) <= 181, "pose source/layout/frame-count mismatch")
        finite_count, null_count = 0, 0
        for frame in frames:
            points = frame.get("points")
            require(isinstance(points, list) and len(points) == 23, "pose23 slots absent")
            for point in points:
                if point is None:
                    null_count += 1
                    continue
                require(isinstance(point, dict) and all(type(point.get(key)) in (int, float)
                        and math.isfinite(point[key]) for key in ("x", "y", "confidence")), "nonfinite pose point")
                finite_count += 1
        require(finite_count > 0, "no finite located pose point")
        deadline(end)
        self.sample(end)
        self.analysis_work_end_ns = time.monotonic_ns()
        deadline(end)
        self.result_path, self.result_sha = path + "/result", sha_bytes(result_raw)
        self.witnesses.append({"flow": "sandbox-direct-one-public-analysis", "jobId": job, "resultStatus": "completed",
                               "sourceSha256": VIDEO_SHA, "resultSha256": self.result_sha,
                               "poseSha256": sha_bytes(pose_raw), "poseFrames": len(frames), "poseSlotsPerFrame": 23,
                               "finiteLocatedPoints": finite_count, "nullSlots": null_count,
                               "accuracyOrPhysicalTurnsProof": False, "scoresAreProbabilities": False})

    def persisted_results(self):
        root = self.user_root / "jobs"
        require(root.is_dir() and not root.is_symlink(), "actual persisted jobs root absent")
        rows = []
        for base, dirs, files in os.walk(root, followlinks=False):
            for name in dirs + files:
                path = pathlib.Path(base) / name
                require(not path.is_symlink(), "symlink in persisted results")
            for name in files:
                path = pathlib.Path(base) / name
                raw = read_regular(path, USER_LIMIT)
                rows.append({"path": path.relative_to(root).as_posix(), "bytes": len(raw), "sha256": sha_bytes(raw)})
                require(len(rows) <= 128, "persisted result inventory cap")
                deadline()
        require(rows, "persisted results empty")
        return sorted(rows, key=lambda row: row["path"])

    def remove_owned_application(self):
        require(self.installed and not self.application_removed, "owned application removal binding absent")
        self.require_known_closed(WORK_END_NS)
        require(set(path.relative_to(self.installed).as_posix() for path in self.installed.rglob("*") if path.is_file())
                == {row[0] for row in self.original_inventory}, "unadmitted application removal file")
        for path in sorted(self.installed.rglob("*"), key=lambda value: len(value.parts), reverse=True):
            deadline()
            require(not path.is_symlink(), "refuse symlink during owned application removal")
            if path.is_dir():
                path.rmdir()
            else:
                require(path.is_file(), "unadmitted special file during application removal")
                path.unlink()
        self.installed.rmdir()
        self.application_removed = True

    def run(self):
        self.bind()
        self.network_probe()
        require(not self.user_root.exists(), "network preflight changed fresh GUI user state")
        direct = self.direct_launch("sandbox-direct-first-run")
        app = self.app_ready("sandbox-direct-visible-gui", direct)
        self.receipt["firstGuiUserStateFresh"] = True
        self.receipt["osColdCacheProved"] = False
        self.one_analysis()
        analysis_cleanup_started_ns = time.monotonic_ns()
        analysis_cleanup_end_ns = min(WORK_END_NS, self.analysis_whole_end_ns,
                                      analysis_cleanup_started_ns + 30_000_000_000)
        self.sample(analysis_cleanup_end_ns)
        status, health_raw = self.request("GET", "/api/analysis/health", maximum=65536, limit_ns=analysis_cleanup_end_ns)
        health = json.loads(health_raw) if status == 200 else {}
        require(status == 200 and health.get("status") == "ready" and health.get("inferenceAvailable") is True
                and "activeJobId" in health and health["activeJobId"] is None, "post-analysis strict idle absent")
        self.close_cooperatively(app, direct, "sandbox-direct-after-analysis", analysis_cleanup_end_ns)
        analysis_closed_ns = time.monotonic_ns()
        deadline(analysis_cleanup_end_ns)
        self.receipt["analysisPhase"] = {"originalOriginMonotonicNs": str(self.analysis_origin_ns),
            "originalWorkSeconds": 120, "originalWholeSeconds": 150, "cleanupSeconds": 30,
            "actualWorkSeconds": (self.analysis_work_end_ns - self.analysis_origin_ns) / 1e9,
            "actualWholeSeconds": (analysis_closed_ns - self.analysis_origin_ns) / 1e9,
            "actualCleanupSeconds": (analysis_closed_ns - analysis_cleanup_started_ns) / 1e9}
        self.analysis_phase_active = False  # Later relaunch/removal has its original outer scope.
        saved = self.persisted_results()
        finder = Retained(self, "launchservices-waiter", ["/usr/bin/open", "-W", "-n", "-a", str(self.installed)], WORK_END_NS)
        app = self.app_ready("ordinary-launchservices-visible-gui", finder)
        status, result = self.request("GET", self.result_path)
        require(status == 200 and sha_bytes(result) == self.result_sha, "LaunchServices relaunch result changed")
        self.close_cooperatively(app, finder, "ordinary-launchservices-visible-gui")
        require(self.persisted_results() == saved, "LaunchServices relaunch persisted results changed")
        relaunch = self.direct_launch("sandbox-direct-relaunch")
        app = self.app_ready("sandbox-direct-relaunch", relaunch)
        status, result = self.request("GET", self.result_path)
        require(status == 200 and sha_bytes(result) == self.result_sha, "relaunch result changed")
        require(self.persisted_results() == saved, "relaunch persisted results changed")
        self.sample()
        self.native.signal_owned(app, signal.SIGKILL)
        end = min(WORK_END_NS, time.monotonic_ns() + 30_000_000_000)
        self.require_known_closed(end)
        require(relaunch.wait(end) == -signal.SIGKILL, "forced original app wait did not report SIGKILL")
        self.require_port_free()
        require(self.persisted_results() == saved, "forced closure changed results")
        self.remove_owned_application()
        require(self.persisted_results() == saved, "application removal changed user results")
        self.witnesses.append({"flow": "forced-closure-and-removal", "originalApplicationIdentity": app,
                               "knownOwnedGenerationsGone": True, "forcedRetainedWait": -signal.SIGKILL,
                               "relaunchResultSha256Equal": True, "applicationRemoved": True,
                               "userResultsPreserved": True, "persistedFiles": len(saved),
                               "continuousDescendantCoverage": False})
        deadline()
        self.receipt["checksCompletedBeforeCleanup"] = True

    def cleanup(self):
        # Cleanup uses the original 600s horizon; this never renews it.
        end = min(WHOLE_END_NS, time.monotonic_ns() + 30_000_000_000)
        if self.analysis_phase_active:
            end = min(end, self.analysis_whole_end_ns)
        if self.native:
            retained_keys = {self.key(child.identity) for child in self.children if child.identity is not None}
            for row in reversed(list(self.known.values())):
                if self.key(row) in retained_keys:
                    continue  # Same retained generation may have exec'd; its handle is checked below.
                try:
                    deadline(end)
                    self.native.signal_owned(row, signal.SIGKILL)
                except Exception as error:
                    self.cleanup_errors.append(str(error)[:256])
            for child in self.children:
                if not child.closed:
                    try:
                        if child.proc.poll() is None:
                            if child.identity is not None:
                                current = self.native.identity(child.proc.pid)
                                if current is None:
                                    require(child.proc.poll() is not None, "retained live cleanup identity unavailable")
                                else:
                                    require(self.native.same(child.identity, current) and current["uid"] == os.getuid(),
                                            "retained cleanup PID/UID/creation mismatch")
                            # An unreaped direct Popen child cannot have a recycled PID; exec keeps its generation.
                            # A missing initial native identity still prevents PASS through the first failure.
                            if child.proc.poll() is None:
                                child.proc.kill()
                        child.wait(end, cleanup=True)
                    except Exception as error:
                        self.cleanup_errors.append(str(error)[:256])
            for row in self.known.values():
                try:
                    current = self.native.identity(row["pid"])
                    if self.native.same(row, current):
                        self.cleanup_errors.append("known OWN generation still live: " + str(row["pid"]))
                except Exception as error:
                    self.cleanup_errors.append(str(error)[:256])
        elif self.children:
            self.cleanup_errors.append("native identity unavailable for retained cleanup")
        if time.monotonic_ns() >= end:
            self.cleanup_errors.append("original cleanup horizon exceeded")
        self.receipt.update({"firstFailure": self.first_failure, "cleanupErrors": self.cleanup_errors[:16],
                             "cleanupErrorCount": len(self.cleanup_errors), "witnesses": self.witnesses,
                             "retainedChildren": [child.record() for child in self.children],
                             "knownOwnedIdentities": list(self.known.values())[:128], "knownOwnedIdentityCount": len(self.known),
                             "sampleCount": self.samples, "sampledOwnRssMaxBytes": self.rss_max_sample,
                             "sampledNewUserBytesMax": self.user_bytes_max_sample, "streamBytesObserved": self.raw_count,
                             "streamFailure": self.stream_failure, "elapsedSeconds": (time.monotonic_ns() - ORIGIN_NS) / 1e9})

    def finish(self):
        # PASS is possible only after the actual checker, waits, readers and closure.
        positive = (self.first_failure is None and not self.cleanup_errors and self.stream_failure is None
                    and self.receipt.get("checksCompletedBeforeCleanup") is True
                    and all(child.closed for child in self.children) and time.monotonic_ns() < WHOLE_END_NS)
        self.receipt["status"] = "passed" if positive else "failed"
        encoded = json.dumps(self.receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) + 1 > RECEIPT_LIMIT:
            self.receipt = {"status": "failed", "firstFailure": self.first_failure or "final receipt cap exceeded",
                            "originalOriginMonotonicNs": str(ORIGIN_NS), "elapsedSeconds": (time.monotonic_ns()-ORIGIN_NS)/1e9,
                            "cleanupErrorCount": len(self.cleanup_errors), "fullReceiptOmitted": True}
            encoded = json.dumps(self.receipt, sort_keys=True).encode("utf-8")
            positive = False
        if self.output.is_dir():
            for i, child in enumerate(self.children):
                for j, suffix in enumerate(("stdout", "stderr")):
                    (self.output / (str(i) + "-" + child.name + "." + suffix + ".log")).write_bytes(child.data[j])
            (self.output / "native-check.json").write_bytes(encoded + b"\n")
        sys.stdout.buffer.write(encoded + b"\n")
        sys.stdout.buffer.flush()
        if time.monotonic_ns() >= WHOLE_END_NS:
            positive = False
            if self.output.is_dir():
                failed = {"status": "failed", "firstFailure": "terminal output exceeded original whole horizon",
                          "earlierPositiveReceiptRejected": True}
                (self.output / "native-check.json").write_text(json.dumps(failed) + "\n", encoding="utf-8")
            sys.stderr.write("FAILED: terminal output exceeded original whole horizon\n")
        return 0 if positive else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--installed-app", required=True)
    parser.add_argument("--root-grant", required=True)
    parser.add_argument("--root-grant-sha256", required=True)
    parser.add_argument("--offline-video", required=True)
    parser.add_argument("--sandbox-profile", required=True)
    parser.add_argument("--output-dir", required=True)
    checker = Check(parser.parse_args())
    try:
        checker.run()
    except BaseException as error:
        checker.first_failure = str(error)[:2048] or type(error).__name__
    finally:
        checker.cleanup()
    return checker.finish()


if __name__ == "__main__":
    raise SystemExit(main())
