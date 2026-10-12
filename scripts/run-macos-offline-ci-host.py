#!/usr/bin/env python3
"""Inert Source preparation: exact generated Root grant required for execution.

No target imports, compilation, downloads, native checks or CI have been run.
Tool discovery, XCTest, builder and installed-app check retain separate horizons.
"""
import time
HOST_ORIGIN_NS = time.monotonic_ns()
HOST_END_NS = HOST_ORIGIN_NS + 3900_000_000_000

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import platform
import plistlib
import pwd
import re
import signal
import stat
import subprocess
import sys
import threading

HOST_STREAM_LIMIT = 256 * 1024
HOST_RAW_LIMIT = 192 * 1024
HOST_RECEIPT_LIMIT = 56 * 1024
RUNTIME_IDENTITIES = [
    {"id": "node", "version": "22.23.3", "bytes": 49963763,
     "sha256": "23b25245dcfb9af7262f8ff142e9e2e0af025368117329e7a7458a51e5922f53"},
    {"id": "sciencePython", "version": "3.12.15", "bytes": 25030095,
     "sha256": "233f8e15255b3e1d1fd47ea5dd5230dfed803f371138e896e54d98c60ae19f6f"},
    {"id": "posePython", "version": "3.9.20", "bytes": 16569829,
     "sha256": "e7551a119bded40bfc268c850110b6a5af1d5fdd63842a56569477490d20e0a6"},
]
RUNTIME_NOTICES = [
    {"runtimeId": "node", "buildRelativePath": "runtime/LICENSE",
     "appRelativePath": "Contents/Resources/payload/.runtime/LICENSE"},
    {"runtimeId": "sciencePython", "buildRelativePath": "runtime/venv-science/lib/python3.12/LICENSE.txt",
     "appRelativePath": "Contents/Resources/payload/.runtime/venv-science/lib/python3.12/LICENSE.txt"},
    {"runtimeId": "posePython", "buildRelativePath": "runtime/venv-pose/lib/python3.9/LICENSE.txt",
     "appRelativePath": "Contents/Resources/payload/.runtime/venv-pose/lib/python3.9/LICENSE.txt"},
]
TEST_NAMES = [
    "testPrivateWritableShutdownHasRetainedWaitAndBothEOF",
    "testMalformedFrameDrainsLaterOutputToPhysicalEOF",
    "testOldGenerationCannotEnableBrowserAfterRetry",
    "testStoppedMessageCannotReplaceWaitAndBothEOF",
    "testRetainedWaitWithoutGroupDisappearanceBlocksRetry",
    "testExternalOrCredentialedURLCannotEnableOpenButton",
    "testMalformedProgressAndOversizedFramesFailClosed",
]
PHASES = {
    "discovery": {"wholeSeconds": 30, "workSeconds": 25, "cleanupSeconds": 5,
                  "sampledRssBytes": 536870912, "outputBytes": 1048576, "tmpBytes": 1048576, "logBytes": 65536},
    "xctest": {"wholeSeconds": 120, "workSeconds": 100, "cleanupSeconds": 20,
               "sampledRssBytes": 1610612736, "outputBytes": 268435456, "tmpBytes": 201326592, "logBytes": 262144},
    "build": {"wholeSeconds": 2700, "workSeconds": 2670, "cleanupSeconds": 30,
              "sampledRssBytes": 4294967296, "outputBytes": 8589934592, "tmpBytes": 4294967296, "logBytes": 16777216},
    "native": {"wholeSeconds": 600, "workSeconds": 570, "cleanupSeconds": 30,
               "sampledRssBytes": 4294967296, "outputBytes": 1610612736, "tmpBytes": 33554432,
               "newUserAndTmpBytes": 67108864, "logBytes": 262144},
}


def need(value, reason):
    if not value:
        raise RuntimeError(reason)


def before(limit_ns):
    need(time.monotonic_ns() < min(limit_ns, HOST_END_NS), "original horizon expired")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def valid_sha(value, size=64):
    return isinstance(value, str) and len(value) == size and all(x in "0123456789abcdef" for x in value)


def raw_file(path, maximum):
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and not path.is_symlink() and info.st_size <= maximum, "regular bounded file required")
    data = path.read_bytes()
    after = path.lstat()
    need((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) ==
         (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) and len(data) == info.st_size,
         "file identity changed")
    return data


def rooted(root, relative):
    need(isinstance(relative, str) and relative and "\\" not in relative, "invalid relative path")
    parts = pathlib.PurePosixPath(relative)
    need(not parts.is_absolute() and all(x not in ("", ".", "..") for x in parts.parts), "unconfined relative path")
    path = root.joinpath(*parts.parts)
    cursor = path
    while cursor != root:
        need(not cursor.is_symlink(), "link in admitted Source/output path")
        cursor = cursor.parent
    need(not root.is_symlink() and path.resolve().is_relative_to(root.resolve()), "path escaped root")
    return path


def file_pin(path, limit_ns, maximum=256 * 1024**2):
    before(limit_ns)
    info = path.lstat()
    regular, linked = stat.S_ISREG(info.st_mode), path.is_symlink()
    need(regular and not linked and info.st_size <= maximum,
         f"tool/input size or type rejected path={path} mode={info.st_mode:#o} "
         f"regular={regular} symlink={linked} actualBytes={info.st_size} capBytes={maximum}")
    value = hashlib.sha256()
    with path.open("rb") as reader:
        while True:
            before(limit_ns)
            part = reader.read(1024 * 1024)
            if not part:
                break
            value.update(part)
    after = path.lstat()
    need((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) ==
         (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), "tool/input changed while hashing")
    return {"path": str(path), "bytes": info.st_size, "sha256": value.hexdigest()}


def selected_swift_pin(path, developer, limit_ns):
    before(limit_ns)
    subtree = developer / "Toolchains"
    need(path.is_absolute() and path.is_relative_to(subtree) and ".." not in path.parts,
         "selected Swift invocation escaped genuine Developer/Toolchains")
    alias_before = path.lstat()
    linked = stat.S_ISLNK(alias_before.st_mode)
    need(linked or stat.S_ISREG(alias_before.st_mode), "selected Swift invocation type rejected")
    link = os.readlink(path) if linked else None
    target = path.resolve(strict=True)
    need(target.is_relative_to(subtree), "selected Swift target escaped genuine Developer/Toolchains")
    pin = file_pin(target, limit_ns, maximum=1024 * 1024**2)
    alias_after = path.lstat()
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    need(all(getattr(alias_before, field) == getattr(alias_after, field) for field in fields)
         and path.resolve(strict=True) == target and (not linked or os.readlink(path) == link),
         "selected Swift invocation alias changed during target hashing")
    before(limit_ns)
    return {**pin, "path": str(path), "resolvedTargetPath": str(target),
            "invocationAlias": {"symbolicLink": linked, "linkTarget": link,
                "dev": str(alias_before.st_dev), "ino": str(alias_before.st_ino),
                "mode": alias_before.st_mode, "bytes": alias_before.st_size,
                "mtimeNs": str(alias_before.st_mtime_ns), "ctimeNs": str(alias_before.st_ctime_ns)}}


def tree_bytes(root, end_ns, allowed_links=(), read_only_mounts=()):
    total = 0
    if root.exists():
        for parent, dirs, files in os.walk(root, followlinks=False):
            before(end_ns)
            dirs[:] = [name for name in dirs if pathlib.Path(parent) / name not in read_only_mounts]
            for name in dirs + files:
                item = pathlib.Path(parent) / name
                if item.is_symlink():
                    need(item in allowed_links and os.readlink(item) == "/Applications", "unexpected link in owned output namespace")
                    continue  # Intentional DMG drag-link is not followed or app inventory.
                info = item.lstat()
                if stat.S_ISREG(info.st_mode):
                    total += info.st_size
                else:
                    need(stat.S_ISDIR(info.st_mode), "special file in owned output namespace")
    return total


class Phase:
    def __init__(self, host, name):
        self.host, self.name, self.limits = host, name, PHASES[name]
        self.origin_ns = time.monotonic_ns()
        self.work_end_ns = min(HOST_END_NS, self.origin_ns + self.limits["workSeconds"] * 1_000_000_000)
        self.whole_end_ns = min(HOST_END_NS, self.origin_ns + self.limits["wholeSeconds"] * 1_000_000_000)
        self.root = host.output / name
        self.tmp = self.root / ("tmp" if name == "native" else "TMP")
        self.root.mkdir()
        self.tmp.mkdir()
        self.known, self.children = {}, []
        self.lock = threading.Lock()
        self.log_count = 0
        self.pipe_failure = None
        self.first_failure = None
        self.cleanup_errors = []
        self.sample_count = 0
        self.rss_max = self.output_max = self.tmp_max = 0
        self.external_app = None
        self.additional_outputs = []
        self.user_root = None
        self.additional_tmp = None
        self.allowed_links = []
        self.new_user_tmp_max = 0
        self.mount = None
        self.read_only_mounts = []
        self.result = None

    def observe(self, row):
        need(len(self.known) < 1024 or self.host.native.key(row) in self.known, "OWN phase process ledger cap")
        self.known[self.host.native.key(row)] = row

    def sample(self):
        before(self.work_end_ns)
        need(self.pipe_failure is None, self.pipe_failure or "pipe failure")
        rows = self.host.native.snapshot()
        current = {row["pid"]: row for row in rows}
        if self.external_app:
            for row in rows:
                if row["executable"] == str(self.external_app) and row["uid"] == os.getuid():
                    self.observe(row)
        live = {row["pid"] for row in self.known.values() if self.host.native.same(row, current.get(row["pid"]))}
        changed = True
        while changed:
            changed = False
            for row in rows:
                if row["ppid"] in live and row["uid"] == os.getuid() and self.host.native.key(row) not in self.known:
                    self.observe(row)
                    live.add(row["pid"])
                    changed = True
        rss = self.host.native.rss(self.host.native.identity(os.getpid()))
        rss += sum(self.host.native.rss(row) for row in self.known.values()
                   if self.host.native.same(row, current.get(row["pid"])))
        output = tree_bytes(self.root, self.work_end_ns, self.allowed_links, self.read_only_mounts)
        output += sum(tree_bytes(root, self.work_end_ns) for root in self.additional_outputs)
        temporary = tree_bytes(self.tmp, self.work_end_ns)
        if self.additional_tmp:
            temporary += tree_bytes(self.additional_tmp, self.work_end_ns)
        self.rss_max, self.output_max, self.tmp_max = max(self.rss_max, rss), max(self.output_max, output), max(self.tmp_max, temporary)
        self.sample_count += 1
        need(rss <= self.limits["sampledRssBytes"], "sampled phase OWN RSS cap exceeded")
        need(output <= self.limits["outputBytes"] and temporary <= self.limits["tmpBytes"], "phase output/TMP cap exceeded")
        if self.user_root:
            combined = tree_bytes(self.user_root, self.work_end_ns) + temporary
            self.new_user_tmp_max = max(self.new_user_tmp_max, combined)
            need(combined <= self.limits["newUserAndTmpBytes"], "sampled new user plus TMP exceeded combined64MiB")
        before(self.work_end_ns)

    def execute(self, name, argv, environment=None, *, allow_fast_terminal_discovery=False):
        self.sample()
        need(isinstance(argv, list) and argv and all(isinstance(x, str) and "\x00" not in x for x in argv), "invalid exact argv")
        if allow_fast_terminal_discovery:
            need(self.name == "discovery" and environment is None and (name, tuple(argv)) in {
                ("xcode-select", ("/usr/bin/xcode-select", "-p")),
                ("selected-sdk", ("/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path")),
                ("selected-swiftc", ("/usr/bin/xcrun", "-f", "swiftc")),
            }, "fast terminal allowance restricted to three fixed discovery queries")
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True, env=environment)
        item = {"name": name, "argv": argv, "handle": child, "identity": None, "readers": [],
                "buffers": [bytearray(), bytearray()], "errors": [], "closed": False, "saved": False}
        self.children.append(item)
        def drain(index, pipe):
            try:
                while True:
                    part = pipe.read(4096)
                    if not part:
                        return
                    with self.host.capture_lock:
                        left = max(0, min(self.limits["logBytes"] - self.log_count,
                                          HOST_RAW_LIMIT - self.host.capture_count))
                        item["buffers"][index].extend(part[:left])
                        self.log_count += len(part)
                        self.host.capture_count += len(part)
                        if self.log_count > self.limits["logBytes"]:
                            self.pipe_failure = "combined phase child-stream cap exceeded"
                        if self.host.capture_count > HOST_RAW_LIMIT:
                            self.pipe_failure = "combined outer host child-stream192KiB cap exceeded"
            except Exception as error:
                item["errors"].append(str(error)[:256])
                self.pipe_failure = "phase pipe-reader failure"
        for index, pipe in enumerate((child.stdout, child.stderr)):
            thread = threading.Thread(target=drain, args=(index, pipe), daemon=True)
            item["readers"].append(thread)
            thread.start()
        item["identity"] = self.host.native.identity(child.pid)
        if item["identity"] is None and allow_fast_terminal_discovery:
            terminal = child.poll()
            proof = {"terminalPollExitCode": terminal, "accepted": False,
                     "freshPidAbsent": False, "freshPgidEmpty": False, "freshNativePidAbsent": False,
                     "originalIdentityUnknown": True, "creationIdentityUnknown": True,
                     "continuousLifetimeAuditProven": False, "signalAuthorityGranted": False}
            item["fastTerminalDiscovery"] = proof
            need(terminal == 0, "unbound discovery child is not already terminal/successful")
            before(self.work_end_ns)
            self.wait_and_save(item, self.work_end_ns)
            self.sample()
            before(self.work_end_ns)
            need(self.host.native.identity(child.pid) is None, "fast discovery PID reused or remains live")
            proof["freshNativePidAbsent"] = True
            import errno
            for label, probe in (("PID", os.kill), ("PGID", os.killpg)):
                before(self.work_end_ns)
                try:
                    probe(child.pid, 0)  # Existence only; no signal is delivered.
                except OSError as error:
                    need(error.errno == errno.ESRCH,
                         "fast discovery " + label + " absence unknown: errno=" + str(error.errno))
                else:
                    need(False, "fast discovery " + label + " nonempty/reused; no signal authority")
                proof["freshPidAbsent" if label == "PID" else "freshPgidEmpty"] = True
            before(self.work_end_ns)
            proof["accepted"] = True
            return bytes(item["buffers"][0])
        need(item["identity"] and item["identity"]["pgid"] == child.pid, "new retained phase group identity unknown")
        self.observe(item["identity"])
        while child.poll() is None:
            self.sample()
            time.sleep(min(0.1, max(0, self.work_end_ns - time.monotonic_ns()) / 1e9))
        self.wait_and_save(item, self.work_end_ns)
        self.sample()
        need(child.returncode == 0, "retained phase child failed: " + name + " exit=" + str(child.returncode))
        return bytes(item["buffers"][0])

    def wait_and_save(self, item, end_ns):
        child = item["handle"]
        child.wait(timeout=max(0.001, (end_ns - time.monotonic_ns()) / 1e9))
        for reader in item["readers"]:
            reader.join(timeout=max(0, (end_ns - time.monotonic_ns()) / 1e9))
        need(all(not reader.is_alive() for reader in item["readers"]), "retained reader EOF/stop unknown")
        child.stdout.close()
        child.stderr.close()
        item["closed"] = True
        need(not item["errors"], "retained reader failed")
        if not item["saved"]:
            for index, suffix in enumerate(("stdout", "stderr")):
                (self.root / (item["name"] + "." + suffix + ".log")).write_bytes(item["buffers"][index])
            item["saved"] = True

    def cleanup(self):
        end = min(self.whole_end_ns, time.monotonic_ns() + self.limits["cleanupSeconds"] * 1_000_000_000)
        # Only actually observed OWN generations; no process-name/global-system kill.
        for row in reversed(list(self.known.values())):
            try:
                before(end)
                self.host.native.signal_owned(row, signal.SIGKILL)
            except Exception as error:
                self.cleanup_errors.append(str(error)[:256])
        for item in self.children:
            if not item["closed"]:
                try:
                    if item["identity"] is None and item["handle"].poll() is None:
                        item["handle"].kill()  # Direct retained unreaped child; no reused PID.
                    self.wait_and_save(item, end)
                except Exception as error:
                    self.cleanup_errors.append(str(error)[:256])
        for row in self.known.values():
            try:
                need(not self.host.native.same(row, self.host.native.identity(row["pid"])), "OWN phase generation remains live")
            except Exception as error:
                self.cleanup_errors.append(str(error)[:256])
        if self.mount and not self.mount.get("detachAttempted"):
            try:
                # Failure-path unmount uses only the freshly owned mountpoint,
                # or the exact plist-bound device. It never uses force/global detach.
                self.detach_owned_mount(end, cleanup=True)
            except Exception as error:
                self.cleanup_errors.append(str(error)[:256])
        if self.mount and pathlib.Path(self.mount["mountPoint"]).is_mount():
            self.cleanup_errors.append("OWN development DMG volume remains mounted; no retry/force detach")
        if self.log_count > self.limits["logBytes"] or self.pipe_failure:
            self.cleanup_errors.append(self.pipe_failure or "phase log cap exceeded")
        if time.monotonic_ns() >= end:
            self.cleanup_errors.append("original phase cleanup horizon expired")
        self.host.phases.append(self.record())

    def record(self):
        children = [{"name": item["name"], "argv": item["argv"], "originalIdentity": item["identity"],
                     "retainedWaitExitCode": item["handle"].returncode if item["closed"] else None,
                     "readersStopped": all(not value.is_alive() for value in item["readers"]),
                     "pipesClosed": item["closed"], "readerErrors": item["errors"],
                     "fastTerminalDiscovery": item.get("fastTerminalDiscovery")} for item in self.children]
        return {"name": self.name, "originalOriginMonotonicNs": str(self.origin_ns),
                "originalWorkDeadlineNs": str(self.work_end_ns), "originalWholeDeadlineNs": str(self.whole_end_ns),
                "limits": self.limits, "firstFailure": self.first_failure, "cleanupErrors": self.cleanup_errors[:16],
                "cleanupErrorCount": len(self.cleanup_errors), "retainedChildren": children,
                "knownOwnedIdentities": list(self.known.values())[:16], "knownOwnedIdentityCount": len(self.known),
                "identityDisplayTruncated": len(self.known) > 16, "sampleCount": self.sample_count,
                "sampledRssMaxBytes": self.rss_max, "sampledOutputMaxBytes": self.output_max,
                "sampledTmpMaxBytes": self.tmp_max, "observedStreamBytes": self.log_count,
                "sampledNewUserAndTmpMaxBytes": self.new_user_tmp_max,
                "actualDmgMount": self.mount,
                "independentParentReapOrContinuousResourceProof": False, "result": self.result}

    def detach_owned_mount(self, end_ns, cleanup=False):
        mount = self.mount
        need(mount and not mount.get("detachAttempted"), "OWN mount detach already attempted")
        point = pathlib.Path(mount["mountPoint"])
        if not point.is_mount():
            mount["detached"] = True
            return
        current = point.stat().st_dev
        recorded = mount.get("mountedDeviceId")
        # A partial attach may fail before plist parsing. The new exact owned
        # point is still permitted only when its actual readonly device is bound.
        need(recorded is not None and current == recorded and current != mount["originalDeviceId"]
             and bool(os.statvfs(point).f_flag & os.ST_RDONLY), "OWN mounted volume identity/readonly state unknown")
        target = mount.get("device") or str(point)
        mount["detachAttempted"] = True
        if not cleanup:
            self.execute("detach-owned-development-dmg", [self.host.tools["tools"]["hdiutil"]["path"], "detach", target],
                         self.host.environment(self))
        else:
            # Cleanup keeps the original end, and never creates a child after it.
            argv = [self.host.tools["tools"]["hdiutil"]["path"], "detach", target]
            item = {"name": "cleanup-detach-owned-dmg", "argv": argv,
                    "handle": None, "identity": None, "readers": [], "buffers": [bytearray(), bytearray()],
                    "errors": [], "closed": False, "saved": False}
            qualification = {"originalEndMonotonicNs": str(end_ns), "endAdmissionPassed": False,
                             "childCreated": False, "identityAdmissionPassed": False,
                             "readerAdmissionComplete": False, "retainedWaitCompleted": False,
                             "bothReaderEOFVerified": False, "pipesClosed": False, "firstCause": None}
            mount["cleanupDetachLifecycle"] = qualification
            child = None
            first_cause = None
            def drain(index, pipe):
                try:
                    while True:
                        data = pipe.read(4096)
                        if not data:
                            return
                        with self.host.capture_lock:
                            available = max(0, HOST_RAW_LIMIT - self.host.capture_count)
                            item["buffers"][index].extend(data[:available])
                            self.host.capture_count += len(data)
                            self.log_count += len(data)
                            if self.host.capture_count > HOST_RAW_LIMIT:
                                self.pipe_failure = "cleanup detach output cap exceeded"
                except Exception as error:
                    item["errors"].append(str(error)[:256])
            try:
                before(end_ns)  # Mandatory original-end admission BEFORE Popen.
                qualification["endAdmissionPassed"] = True
                child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         start_new_session=True, env=self.host.environment(self))
                item["handle"] = child  # Bind retained direct handle immediately.
                self.children.append(item)
                qualification["childCreated"] = True
                qualification["originalPid"] = child.pid
                # All metadata, group and reader admissions are inside this lifecycle.
                for index, pipe in enumerate((child.stdout, child.stderr)):
                    reader = threading.Thread(target=drain, args=(index, pipe), daemon=True)
                    reader.start()
                    item["readers"].append(reader)
                qualification["readerAdmissionComplete"] = len(item["readers"]) == 2
                item["identity"] = self.host.native.identity(child.pid)
                need(item["identity"] and item["identity"]["pgid"] == child.pid, "detach retained group identity unknown")
                self.observe(item["identity"])
                qualification["identityAdmissionPassed"] = True
                before(end_ns)
                self.wait_and_save(item, end_ns)
                qualification["retainedWaitCompleted"] = True
                qualification["bothReaderEOFVerified"] = True
                qualification["pipesClosed"] = True
                need(child.returncode == 0, "OWN readonly DMG cleanup detach failed")
            except BaseException as error:
                first_cause = error
                qualification["firstCause"] = str(error)[:512] or type(error).__name__
            finally:
                # This child was added AFTER the common cleanup loop. Complete its
                # own handle lifecycle here even if native identity/readers failed.
                if child is not None and not item["closed"]:
                    try:
                        if child.poll() is None:
                            # An unreaped retained direct child cannot have a reused
                            # PID. This grants no signal authority over foreign PIDs.
                            child.kill()
                    except BaseException as error:
                        self.cleanup_errors.append(str(error)[:256])
                    try:
                        self.wait_and_save(item, end_ns)
                        qualification["retainedWaitCompleted"] = True
                        qualification["bothReaderEOFVerified"] = qualification["readerAdmissionComplete"]
                    except BaseException as error:
                        self.cleanup_errors.append(str(error)[:256])
                        # Partial reader admission must still reap this OWN handle
                        # and close its pipes; incomplete EOF proof remains unknown.
                        try:
                            child.wait(timeout=max(0.001, (end_ns - time.monotonic_ns()) / 1e9))
                            qualification["retainedWaitCompleted"] = True
                        except BaseException as wait_error:
                            self.cleanup_errors.append(str(wait_error)[:256])
                        for reader in item["readers"]:
                            reader.join(timeout=max(0, (end_ns - time.monotonic_ns()) / 1e9))
                        for pipe in (child.stdout, child.stderr):
                            try:
                                pipe.close()
                            except BaseException as close_error:
                                self.cleanup_errors.append(str(close_error)[:256])
                        item["closed"] = (qualification["retainedWaitCompleted"]
                            and all(not reader.is_alive() for reader in item["readers"])
                            and child.stdout.closed and child.stderr.closed)
                    qualification["pipesClosed"] = child.stdout.closed and child.stderr.closed
                    if not item["closed"]:
                        self.cleanup_errors.append("cleanup detach retained lifecycle remains incomplete")
                if time.monotonic_ns() >= min(end_ns, HOST_END_NS):
                    self.cleanup_errors.append("cleanup detach exceeded original end; no horizon renewal")
            if first_cause is not None:
                raise first_cause
        need(not point.is_mount() and (not point.exists() or point.stat().st_dev == mount["originalDeviceId"]),
             "OWN volume remains mounted after retained detach")
        mount["detached"] = True


class Host:
    def __init__(self, args):
        self.args = args
        self.output = pathlib.Path(args.output_dir).absolute()
        self.source = pathlib.Path(os.environ.get("GITHUB_WORKSPACE", "")).absolute()
        self.native = None
        self.phases = []
        self.first_failure = None
        self.grant = None
        self.result = {"status": "failed", "unsignedDevelopmentOnly": True,
                       "consumerReleaseAccepted": False, "publication": False,
                       "hostOriginMonotonicNs": str(HOST_ORIGIN_NS), "hostOuterSeconds": 3900,
                       "sharedParentChildClockOriginClaim": False}
        self.capture_lock = threading.Lock()
        self.capture_count = 0

    def bound_source(self, relative):
        rows = [row for row in self.grant["sourcePins"] if row["path"] == relative]
        need(len(rows) == 1, "exact Root source pin missing: " + str(relative))
        path = rooted(self.source, relative)
        raw = raw_file(path, 4 * 1024**2)
        need(len(raw) == rows[0]["bytes"] and digest(raw) == rows[0]["sha256"], "Source pin mismatch")
        return path, raw

    def admit(self):
        before(HOST_END_NS)
        need(platform.system() == "Darwin" and platform.machine() == "arm64"
             and int(platform.mac_ver()[0].split(".")[0]) >= 13, "real arm64 macOS13+ host required")
        actual_home = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir)
        need(pathlib.Path.home() == actual_home and os.environ.get("HOME") == str(actual_home), "genuine account HOME required")
        raw = raw_file(pathlib.Path(self.args.root_grant), 65536)
        need(valid_sha(self.args.root_grant_sha256) and digest(raw) == self.args.root_grant_sha256, "host Root grant SHA mismatch")
        self.grant = json.loads(raw)
        need(self.grant.get("kind") == "ROOT_ADMITTED_GENERATED_MAC_OFFLINE_CI_HOST_GRANT"
             and self.grant.get("actualAuthorization") is True, "actual Root host admission required")
        for field, environment in (("sourceCommit", "GITHUB_SHA"), ("sourceRef", "GITHUB_REF"),
                                   ("runId", "GITHUB_RUN_ID"), ("runAttempt", "GITHUB_RUN_ATTEMPT")):
            value = self.grant.get(field)
            need(isinstance(value, str) and value and value == os.environ.get(environment), "actual CI identity mismatch")
        need(valid_sha(self.grant["sourceCommit"], 40) and self.grant["sourceRef"] == "refs/heads/release/v0.2.6", "unauthorized branch/commit")
        need(self.grant.get("phaseLimits") == PHASES and type(self.grant.get("retry")) is int and self.grant.get("retry") == 0
             and self.grant.get("unsignedDevelopmentOnly") is True, "host scope limits/policy mismatch")
        need(self.grant.get("builderInterfaceAccepted") is True and self.grant.get("nativeInterfaceAccepted") is True
             and self.grant.get("runtimeInputsAccepted") is True, "pending interfaces cannot execute")
        need(self.grant.get("runtimeArchiveIdentities") == RUNTIME_IDENTITIES, "runtime literal identities mismatch")
        need(self.grant.get("runtimeNoticeMappings") == RUNTIME_NOTICES,
             "exact newly accepted extracted-licence path mapping absent")
        need(isinstance(self.grant.get("sourcePins"), list) and 1 <= len(self.grant["sourcePins"]) <= 128, "Source pin list absent")
        need(self.grant.get("outputDir") == str(self.output) and not self.output.exists()
             and self.output.parent.is_dir() and not self.output.parent.is_symlink(), "fresh outside-Source output required")
        need(not self.output.resolve().is_relative_to(self.source.resolve())
             and not self.source.resolve().is_relative_to(self.output.resolve()), "work root overlaps Source")
        need(self.grant.get("hostSha256") == digest(raw_file(pathlib.Path(__file__), 100 * 1024)), "host Source SHA mismatch")
        self.checker, checker_raw = self.bound_source(self.grant["nativeCheckerPath"])
        profile, _ = self.bound_source(self.grant["sandboxProfilePath"])
        self.profile = profile
        self.public_video, video = self.bound_source(self.grant["offlineVideoPath"])
        need(len(video) == 818120 and digest(video) == "b142e4df68b709475cc016c35b67d2a6999afc8c7644b91722093cd2e4355b5d", "public sample pin mismatch")
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("root_admitted_native_operator", self.checker)
        need(spec and spec.loader, "admitted native support module unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.native = module.Native()
        self.native.key = module.Check.key
        self.output.mkdir()
        self.result.update({"rootGrantSha256": digest(raw), "sourceCommit": self.grant["sourceCommit"],
                            "runId": self.grant["runId"], "runAttempt": self.grant["runAttempt"],
                            "macOS": platform.mac_ver()[0], "architecture": platform.machine(),
                            "nativeCheckerSha256": digest(checker_raw)})

    def phase(self, name, operation):
        phase = Phase(self, name)
        try:
            value = operation(phase)
            phase.sample()
            phase.result = value
        except BaseException as error:
            phase.first_failure = str(error)[:2048] or type(error).__name__
        finally:
            phase.cleanup()
        need(phase.first_failure is None and not phase.cleanup_errors, phase.first_failure or "phase cleanup failed: " + name)
        return phase.result

    def discovery(self, phase):
        developer = phase.execute("xcode-select", ["/usr/bin/xcode-select", "-p"], allow_fast_terminal_discovery=True).decode().strip()
        sdk = phase.execute("selected-sdk", ["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"], allow_fast_terminal_discovery=True).decode().strip()
        swift = phase.execute("selected-swiftc", ["/usr/bin/xcrun", "-f", "swiftc"], allow_fast_terminal_discovery=True).decode().strip()
        developer, sdk = pathlib.Path(developer).resolve(), pathlib.Path(sdk).resolve()
        swift_invocation = pathlib.Path(swift)
        swift = swift_invocation.resolve()
        need(developer.is_dir() and str(developer).endswith(".app/Contents/Developer")
             and "CommandLineTools" not in str(developer), "genuine full selected Xcode required")
        need(sdk.is_dir() and sdk.is_relative_to(developer) and swift.is_file() and swift.is_relative_to(developer), "selected SDK/compiler lineage mismatch")
        frameworks = developer / "Platforms/MacOSX.platform/Developer/Library/Frameworks"
        libraries = developer / "Platforms/MacOSX.platform/Developer/usr/lib"
        need((frameworks / "XCTest.framework").is_dir() and libraries.is_dir(), "genuine selected-Xcode XCTest unavailable")
        overlay_candidates = [
            libraries / "XCTest.swiftmodule",
            libraries / "swift/XCTest.swiftmodule",
            frameworks / "XCTest.framework/Modules/XCTest.swiftmodule",
            frameworks / "XCTest.framework/Versions/A/Modules/XCTest.swiftmodule",
            swift.parent.parent / "lib/swift/macosx/XCTest.swiftmodule",
        ]
        overlay = next((path for path in overlay_candidates if path.exists()
                        and path.resolve().is_relative_to(developer) and (path.is_dir() or path.is_file())), None)
        need(overlay is not None, "selected-Xcode Swift XCTest overlay unavailable; checked five bounded paths")
        tools = {"python": file_pin(pathlib.Path(sys.executable).resolve(), phase.work_end_ns),
                 "swiftc": selected_swift_pin(swift_invocation, developer, phase.work_end_ns)}
        for name in ("lipo", "otool", "hdiutil"):
            path = pathlib.Path("/usr/bin") / name
            need(path.is_file() and os.access(path, os.X_OK), "required genuine system tool unavailable")
            tools[name] = file_pin(path.resolve(), phase.work_end_ns)
        need(len(phase.children) == 3, "discovery query bound exceeded")
        return {"developer": str(developer), "sdkPath": str(sdk), "frameworks": str(frameworks),
                "libraries": str(libraries), "xctestSwiftImport": str(overlay.parent),
                "xctestSwiftOverlay": str(overlay.resolve()), "tools": tools,
                "toolQueries": 3, "maximumToolQueries": 8}

    def xctest(self, phase):
        expected = [
            ("swiftAppPath", 22469, "48fa07b7285268c120c2bf358980bfb4afef0e54ef521a60bb3e089fc6a386f0"),
            ("swiftFixturePath", 5745, "23aafc2779b3665f22f45765fe1f83db5359b0a0fd503f78de10f5514055e418"),
            ("swiftRunnerPath", 2026, "ba7ba7749231d66147cbfbccb1caecb6919af26eb2066c968de3aec1800713bd"),
        ]
        paths = []
        for field, size, sha in expected:
            path, raw = self.bound_source(self.grant[field])
            need(len(raw) == size and digest(raw) == sha, "original seven-test fixture identity mismatch")
            paths.append(str(path))
        binary = phase.root / "LauncherContractTests"
        compiler = self.tools["tools"]["swiftc"]["path"]
        phase.execute("compile-existing-seven", [compiler, "-D", "FS_ELEM_TESTING", "-sdk", self.tools["sdkPath"],
            "-F", self.tools["frameworks"], "-I", self.tools["xctestSwiftImport"],
            "-L", self.tools["libraries"], "-framework", "XCTest",
            "-Xlinker", "-rpath", "-Xlinker", self.tools["frameworks"],
            "-Xlinker", "-rpath", "-Xlinker", self.tools["libraries"], "-o", str(binary), *paths],
            self.environment(phase))
        pin = file_pin(binary, phase.work_end_ns, 8 * 1024**2)
        raw = phase.execute("run-existing-seven", [str(binary)], self.environment(phase))
        text = (raw + b"\n" + bytes(phase.children[-1]["buffers"][1])).decode("utf-8", "strict")
        need(re.search(r"Executed 7 tests?, with 0 failures", text), "exact seven-test successful summary missing")
        for name in TEST_NAMES:
            need(re.search(r"Test Case .*" + re.escape(name) + r".* passed", text), "exact test name/pass missing: " + name)
        return {"tests": 7, "exactTestNames": TEST_NAMES, "compiledFixture": pin, "selectedXcode": self.tools["developer"]}

    def environment(self, phase):
        allowed = ("HOME", "LANG", "LC_CTYPE", "GITHUB_SHA", "GITHUB_REF", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_WORKSPACE")
        value = {key: data for key, data in os.environ.items() if key in allowed}
        value.update({"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": str(phase.tmp) + "/",
                      "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                      "DEVELOPER_DIR": self.tools["developer"]})
        return value

    def build(self, phase):
        builder, _ = self.bound_source(self.grant["builderPath"])
        runtime, _ = self.bound_source(self.grant["runtimeInputsPath"])
        recipe, recipe_raw = self.bound_source(self.grant["recipeBindingPath"])
        entry, entry_raw = self.bound_source(self.grant["desktopEntryDescriptorPath"])
        source_rows = self.grant.get("builderSourcePins")
        need(isinstance(source_rows, list) and 1 <= len(source_rows) <= 128, "accepted builder Source rows absent")
        for row in source_rows:
            path, raw = self.bound_source(row["path"])
            need(len(raw) == row["bytes"] and digest(raw) == row["sha256"], "builder Source row mismatch")
        builder_grant = {"scope": "mac-offline-build-v026", "allowBuild": True, "retry": 0,
            "wholeSeconds": 2700, "cleanupSeconds": 30, "outputBytes": 8589934592, "tmpBytes": 4294967296,
            "ownSampledRSSBytes": 4294967296, "combinedLogBytes": 16777216, "sourcePins": source_rows,
            "tools": self.tools["tools"], "sdkPath": self.tools["sdkPath"]}
        grant_path = phase.root / "generated-builder-grant.json"
        encoded = json.dumps(builder_grant, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        grant_path.write_bytes(encoded)
        work = phase.root / "builder-work"
        phase.additional_tmp = work / "tmp"
        phase.allowed_links = [work / "dmg-folder/Applications"]
        python = self.tools["tools"]["python"]["path"]
        phase.execute("build-offline-development-dmg", [python, "-I", "-B", str(builder),
            "--package-root", str(self.source), "--work-root", str(work), "--grant", str(grant_path),
            "--grant-sha256", digest(encoded), "--runtime-inputs", str(runtime),
            "--recipe-binding", str(recipe), "--recipe-binding-sha256", digest(recipe_raw),
            "--desktop-entry-descriptor", str(entry), "--desktop-entry-descriptor-sha256", digest(entry_raw)],
            self.environment(phase))
        summary_path = rooted(work, "build-summary.json")
        summary_raw = raw_file(summary_path, 1024 * 1024)
        summary = json.loads(summary_raw)
        need(summary.get("status") == "development-artifact-built-not-native-release-accepted", "builder terminal status mismatch")
        app, dmg = pathlib.Path(summary.get("app", "")), pathlib.Path(summary.get("dmg", ""))
        need(app.is_absolute() and app.is_dir() and not app.is_symlink() and app.resolve().is_relative_to(work.resolve()), "builder app path escaped")
        need(dmg.is_absolute() and dmg.is_file() and not dmg.is_symlink() and dmg.resolve().is_relative_to(work.resolve()), "builder DMG path escaped")
        dmg_pin = file_pin(dmg, phase.work_end_ns, 4 * 1024**3)
        need(dmg_pin["bytes"] == summary.get("dmgBytes") and dmg_pin["sha256"] == summary.get("dmgSha256"), "actual DMG identity mismatch")
        for name in ("staging-receipt.json", "resolved-runtime-inputs.json"):
            raw_file(rooted(work, name), 4 * 1024**2)
        self.built_app, self.built_dmg = app, dmg
        self.recipe_raw, self.recipe = recipe_raw, json.loads(recipe_raw)
        # Root maps actual archive/install destinations after Source freeze.
        # Proposed names alone never stand in for actual extracted file evidence.
        licences = []
        for row in RUNTIME_NOTICES:
            licence = raw_file(rooted(work, row["buildRelativePath"]), 1024 * 1024)
            app_licence = raw_file(rooted(app, row["appRelativePath"]), 1024 * 1024)
            need(licence.strip() and licence == app_licence, "actual extracted/app runtime licence missing, empty or different")
            licences.append({**row, "bytes": len(licence), "sha256": digest(licence)})
        self.licences = licences
        app_inventory, app_read_bytes = {}, 0
        for base, dirs, files in os.walk(app, followlinks=False):
            phase.sample()
            for name in dirs:
                need(not (pathlib.Path(base) / name).is_symlink(), "built app contains directory link")
            for name in files:
                path = pathlib.Path(base) / name
                relative = path.relative_to(app).as_posix()
                pin = file_pin(path, phase.work_end_ns, 1610612736)
                app_read_bytes += pin["bytes"]
                need(app_read_bytes <= 1610612736 and len(app_inventory) < 65536, "built app closed-inventory cap exceeded")
                app_inventory[relative] = {"bytes": pin["bytes"], "sha256": pin["sha256"],
                                           "mode": stat.S_IMODE(path.lstat().st_mode)}
        need(app_inventory, "built app closed inventory empty")
        self.app_inventory = app_inventory
        return {"status": summary["status"], "summarySha256": digest(summary_raw), "app": str(app), "dmg": dmg_pin,
                "builderGrantSha256": digest(encoded), "archiveDownloadsBy": "accepted builder only; host never fetches",
                "actualLicenseFileEvidence": licences,
                "closedBuiltAppInventoryFiles": len(app_inventory), "closedBuiltAppHashReadBytes": app_read_bytes,
                "licenseEvidence": "accepted runtime input declarations still require actual extracted-file verification; no unrestricted clearance claim"}

    def install_and_native(self, phase):
        home = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir)
        applications = home / "Applications"
        need(not applications.is_symlink(), "Applications parent is a link")
        applications.mkdir(exist_ok=True)
        name = "FS_elem Проверка 0.2.6 " + self.grant["runId"] + "-" + self.grant["runAttempt"] + ".app"
        installed = applications / name
        need(not installed.exists() and not installed.is_symlink(), "fresh Unicode application path occupied")
        user_root = home / "Library/Application Support/FS_elem"
        need(not user_root.exists() and not user_root.is_symlink(), "default Foundation user root already exists")
        mountpoint = phase.root / "mounted-development-dmg"
        mountpoint.mkdir()
        original_device = mountpoint.stat().st_dev
        phase.mount = {"mountPoint": str(mountpoint), "originalDeviceId": original_device,
                       "imagePath": str(self.built_dmg), "readonlyRequested": True,
                       "device": None, "mountedDeviceId": None, "detachAttempted": False,
                       "detached": False, "plistIdentityVerified": False}
        phase.read_only_mounts = [mountpoint]
        try:
            attached = phase.execute("mount-readonly-development-dmg", [self.tools["tools"]["hdiutil"]["path"],
                "attach", str(self.built_dmg), "-readonly", "-nobrowse", "-noautoopen", "-plist", "-mountpoint", str(mountpoint)],
                self.environment(phase))
        finally:
            if mountpoint.is_mount():
                phase.mount["mountedDeviceId"] = mountpoint.stat().st_dev
                phase.mount["kernelReadonly"] = bool(os.statvfs(mountpoint).f_flag & os.ST_RDONLY)
        need(len(attached) <= 65536 and mountpoint.is_mount(), "actual DMG mount receipt absent/oversized")
        need(phase.mount["mountedDeviceId"] != original_device and phase.mount["kernelReadonly"], "actual readonly mounted device unproved")
        plist = plistlib.loads(attached)
        entities = plist.get("system-entities")
        need(isinstance(entities, list), "actual hdiutil plist entities absent")
        matched = [row for row in entities if row.get("mount-point") == str(mountpoint)]
        need(len(matched) == 1 and re.fullmatch(r"/dev/disk[0-9]+(?:s[0-9]+)?", matched[0].get("dev-entry", "")),
             "exact own mount/device identity missing or ambiguous")
        phase.mount["device"] = matched[0]["dev-entry"]
        phase.mount["plistIdentityVerified"] = True
        phase.mount["attachPlistSha256"] = digest(attached)
        mounted_app = mountpoint / "FS_elem.app"
        need(mounted_app.is_dir() and not mounted_app.is_symlink(), "actual mounted FS_elem.app missing")
        installed.mkdir()
        phase.additional_outputs = [installed]
        phase.user_root = user_root
        inventory, copied = [], 0
        for base, dirs, files in os.walk(mounted_app, followlinks=False):
            phase.sample()
            relative = pathlib.Path(base).relative_to(mounted_app)
            target = installed / relative
            target.mkdir(exist_ok=True)
            for name in dirs:
                need(not (pathlib.Path(base) / name).is_symlink(), "installed inventory contains directory link")
            for name in files:
                source = pathlib.Path(base) / name
                need(not source.is_symlink(), "installed payload must contain materialized regular files")
                info = source.lstat()
                need(stat.S_ISREG(info.st_mode), "special file in built app")
                destination = target / name
                hashed = hashlib.sha256()
                with source.open("rb") as reader, destination.open("xb") as writer:
                    while True:
                        before(phase.work_end_ns)
                        data = reader.read(1024 * 1024)
                        if not data:
                            break
                        copied += len(data)
                        need(copied <= 1610612736, "native fresh application copy cap exceeded")
                        hashed.update(data)
                        writer.write(data)
                os.chmod(destination, stat.S_IMODE(info.st_mode))
                after = source.lstat()
                need((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) ==
                     (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), "build app changed while copying")
                row = {"path": destination.relative_to(installed).as_posix(), "bytes": info.st_size, "sha256": hashed.hexdigest()}
                expected = self.app_inventory.get(row["path"])
                need(expected == {"bytes": row["bytes"], "sha256": row["sha256"], "mode": stat.S_IMODE(info.st_mode)},
                     "mounted/copied app differs from exact closed builder inventory")
                inventory.append(row)
                need(len(inventory) <= 65536, "closed installed inventory row cap")
        need({row["path"] for row in inventory} == set(self.app_inventory), "mounted app closed inventory not equal")
        phase.mount["mountedAppClosedInventoryEqual"] = True
        phase.mount["copiedFiles"] = len(inventory)
        phase.mount["copiedBytes"] = copied
        phase.detach_owned_mount(phase.work_end_ns)
        payload = rooted(installed, "Contents/Resources/payload")
        metadata_path = rooted(payload, "macOS-bundle.json")
        metadata_raw = raw_file(metadata_path, 1024 * 1024)
        metadata = json.loads(metadata_raw)
        need(metadata.get("recipeBindingPath") == "configs/mac-recipe-binding.json"
             and metadata.get("recipeBindingSha256") == digest(self.recipe_raw)
             and metadata.get("recipeBinding") == self.recipe, "copied raw Root recipe metadata mismatch")
        # Exact five model row aliases supplied by Root after actual builder schema acceptance.
        model_paths = self.grant.get("modelInventoryPaths")
        need(isinstance(model_paths, dict) and set(model_paths) == {"flight", "family", "nominal", "yolox", "rtmw"}, "Root model path mapping unknown")
        for model, relative in model_paths.items():
            rows = [row for row in inventory if row["path"] == relative]
            need(len(rows) == 1, "installed model row not unique")
            rows[0]["model"] = model
        for notice in self.licences:
            rows = [row for row in inventory if row["path"] == notice["appRelativePath"]]
            need(len(rows) == 1 and rows[0]["bytes"] == notice["bytes"] and rows[0]["sha256"] == notice["sha256"],
                 "fresh installed runtime licence bytes differ from extracted evidence")
        inventory.sort(key=lambda row: row["path"])
        inventory_path = phase.root / "generated-installed-inventory.json"
        inventory_raw = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        need(len(inventory_raw) <= 4 * 1024**2, "external Root inventory cap exceeded")
        inventory_path.write_bytes(inventory_raw)
        info = __import__("plistlib").loads(raw_file(rooted(installed, "Contents/Info.plist"), 65536))
        need(info.get("CFBundleIdentifier") == "org.fs-elem.desktop", "installed bundle identifier mismatch")
        executable = info.get("CFBundleExecutable")
        need(isinstance(executable, str) and executable and "/" not in executable, "actual application executable unknown")
        phase.external_app = rooted(installed, "Contents/MacOS/" + executable)
        need(not any(row["executable"] == str(phase.external_app) for row in self.native.snapshot()), "new installed app already active")
        native_grant = {"kind": "ROOT_ADMITTED_GENERATED_MAC_OFFLINE_NATIVE_GRANT", "actualAuthorization": True,
            "sourceRef": self.grant["sourceRef"], "sourceCommit": self.grant["sourceCommit"],
            "runId": self.grant["runId"], "runAttempt": self.grant["runAttempt"],
            "checkerSha256": self.result["nativeCheckerSha256"], "installedApp": str(installed), "userRoot": str(user_root),
            "unsignedDevelopmentOnly": True, "freshApplicationInstall": True, "allowOwnedApplicationRemoval": True,
            "packageMetadataRelativePath": "Contents/Resources/payload/macOS-bundle.json", "packageMetadataSha256": digest(metadata_raw),
            "recipeBindingRelativePath": "configs/mac-recipe-binding.json", "recipeBindingSha256": digest(self.recipe_raw), "recipeBinding": self.recipe,
            "installedInventoryPath": str(inventory_path), "installedInventoryBytes": len(inventory_raw),
            "installedInventorySha256": digest(inventory_raw), "installedReadBytesCap": 1610612736,
            "uiBaseUrl": "http://127.0.0.1:5174", "healthPath": "/api/analysis/health", "jobsPath": "/api/analysis/jobs", "uiPath": "/analysis",
            "sciencePythonRelativePath": self.grant.get("sciencePythonRelativePath"),
            "sandboxProfileSha256": digest(raw_file(self.profile, 4096)), "admitDocumentationAddressDenialProbe": True,
            "limits": {"wholeSeconds": 600, "workSeconds": 570, "cleanupSeconds": 30, "ownSampledRssBytes": 4294967296,
                       "newUserBytes": 67108864, "combinedLogsBytes": 262144, "retries": 0}}
        need(isinstance(native_grant["sciencePythonRelativePath"], str) and native_grant["sciencePythonRelativePath"], "exact portable science Python path unknown")
        native_path = phase.root / "generated-native-grant.json"
        native_raw = json.dumps(native_grant, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        need(len(native_raw) <= 65536, "native grant cap exceeded")
        native_path.write_bytes(native_raw)
        phase.execute("installed-offline-native-check", [self.tools["tools"]["python"]["path"], "-I", "-B", str(self.checker),
            "--installed-app", str(installed), "--root-grant", str(native_path), "--root-grant-sha256", digest(native_raw),
            "--offline-video", str(self.public_video), "--sandbox-profile", str(self.profile), "--output-dir", str(phase.root / "checker-output")],
            self.environment(phase))
        receipt_raw = raw_file(rooted(phase.root, "checker-output/native-check.json"), 65536)
        receipt = json.loads(receipt_raw)
        need(receipt.get("status") == "passed" and receipt.get("rootGrantSha256") == digest(native_raw)
             and receipt.get("checksCompletedBeforeCleanup") is True and not receipt.get("cleanupErrors")
             and receipt.get("firstFailure") is None, "native functional/lifecycle receipt not accepted")
        need(not installed.exists() and user_root.is_dir(), "actual app removal/user preservation incomplete")
        return {"nativeReceiptSha256": digest(receipt_raw), "nativeGrantSha256": digest(native_raw),
                "installedInventorySha256": digest(inventory_raw), "installedFiles": len(inventory), "copiedBytes": copied,
                "childOriginMonotonicNs": receipt.get("originMonotonicNs"), "parentIncludesCopyBeforeChildEntry": True,
                "parentAndChildOriginsAreIndependent": True, "developmentNativeChecksPassed": True,
                "consumerReleaseAccepted": False, "gatekeeperNotarizationProof": False}

    def run(self):
        self.admit()
        self.tools = self.phase("discovery", self.discovery)
        self.phase("xctest", self.xctest)
        self.phase("build", self.build)
        self.phase("native", self.install_and_native)
        before(HOST_END_NS)
        self.result["status"] = "development-build-and-native-checks-passed-not-consumer-release"

    def finish(self):
        self.result.update({"firstFailure": self.first_failure, "phases": self.phases,
                            "elapsedSeconds": (time.monotonic_ns() - HOST_ORIGIN_NS) / 1e9,
                            "outerChildStreamBytesObserved": self.capture_count,
                            "continuousResourceProof": False, "independentRootParentReapOrSyscallProof": False})
        encoded = json.dumps(self.result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        if len(encoded) > HOST_RECEIPT_LIMIT or self.capture_count > HOST_RAW_LIMIT:
            self.first_failure = self.first_failure or "host final receipt cap exceeded"
            encoded = json.dumps({"status": "failed", "firstFailure": self.first_failure, "receiptOmitted": True}).encode() + b"\n"
        if self.output.is_dir():
            (self.output / "host-result.json").write_bytes(encoded)
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
        if time.monotonic_ns() >= HOST_END_NS:
            self.first_failure = self.first_failure or "terminal output exceeded original host horizon"
            if self.output.is_dir():
                (self.output / "host-result.json").write_text(json.dumps({"status": "failed", "firstFailure": self.first_failure}) + "\n")
            sys.stderr.write("FAILED: original host horizon exceeded\n")
        return 1 if self.first_failure else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-grant", required=True)
    parser.add_argument("--root-grant-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    host = Host(parser.parse_args())
    try:
        host.run()
    except BaseException as error:
        host.first_failure = str(error)[:2048] or type(error).__name__
        host.result["status"] = "failed"
    return host.finish()


if __name__ == "__main__":
    raise SystemExit(main())
