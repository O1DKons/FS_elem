#!/usr/bin/env python3
"""SOURCE ONLY: native Windows public sample NN smoke, never an automatic CI opt-in."""
import time
# The outer wrapper's original native QPC precedes controller startup.
# No controller-local clock origin, renewal or clock-provider fallback.
ORIGIN_QPC = None
QPC_FREQUENCY = None
WORK_QPC = None
WHOLE_QPC = None
QPC_KERNEL = None

import ctypes
from ctypes import wintypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import stat
import sys
import threading

PLAN_SHA = "3b2cf606af4399f749274070c1f50659d577739bd40e12a7a03438a169b90924"
OWNER_SOURCE_SHA = "6b2d4d771b01e420203863f6d0bc1cc7ea26915b8b287c0db3262bd6bbe73876"
OWNER_SOURCE_BYTES = 9015
SAMPLE_SHA = "b142e4df68b709475cc016c35b67d2a6999afc8c7644b91722093cd2e4355b5d"
CAPS = {"rss": 2147483648, "regular": 1073741824, "tmp": 33554432, "logs": 262144}
LOG_RESERVE = 16384
CAUSE = None
OWN = None
OWNED = None
METER = None
READER = None
READ_ERROR = None
RAW_READ = 0
RAW_SAVED = 0
LOG_LOCK = threading.Lock()
STOP_AUDIT = {}
RECEIPT = {"status": "NOT_ENTERED", "actualGranted": False, "releaseAccepted": False}

def fail(reason):
    global CAUSE
    if CAUSE is None:
        CAUSE = reason
    raise RuntimeError(reason)

def bind_original_qpc(origin, frequency):
    global ORIGIN_QPC, QPC_FREQUENCY, WORK_QPC, WHOLE_QPC, QPC_KERNEL
    for value in (origin, frequency):
        if not value.isascii() or not value.isdecimal() or str(int(value)) != value:
            fail("external-original-QPC-integer-required")
    ORIGIN_QPC, QPC_FREQUENCY = int(origin), int(frequency)
    if ORIGIN_QPC <= 0 or QPC_FREQUENCY <= 0:
        fail("external-original-QPC-invalid")
    WORK_QPC = ORIGIN_QPC + 270 * QPC_FREQUENCY
    WHOLE_QPC = ORIGIN_QPC + 300 * QPC_FREQUENCY
    QPC_KERNEL = ctypes.WinDLL("kernel32", use_last_error=True)
    QPC_KERNEL.QueryPerformanceCounter.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
    QPC_KERNEL.QueryPerformanceCounter.restype = wintypes.BOOL
    QPC_KERNEL.QueryPerformanceFrequency.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
    QPC_KERNEL.QueryPerformanceFrequency.restype = wintypes.BOOL
    native_frequency = ctypes.c_longlong()
    if not QPC_KERNEL.QueryPerformanceFrequency(ctypes.byref(native_frequency)) or native_frequency.value != QPC_FREQUENCY:
        fail("external-original-QPC-frequency-mismatch")
    clock(True)

def qpc():
    if QPC_KERNEL is None:
        fail("external-original-QPC-not-bound")
    value = ctypes.c_longlong()
    if not QPC_KERNEL.QueryPerformanceCounter(ctypes.byref(value)):
        fail("native-QPC-readout-unknown")
    if value.value < ORIGIN_QPC:
        fail("external-original-QPC-domain-mismatch")
    return int(value.value)

def clock(work=False):
    now = qpc()
    if now >= (WORK_QPC if work else WHOLE_QPC):
        fail("work-deadline" if work else "whole-deadline")
    return now

def remaining_seconds(ceiling, work=False):
    now = clock(work)
    return min(ceiling, max(0.0, ((WORK_QPC if work else WHOLE_QPC) - now) / QPC_FREQUENCY))

def elapsed_ns_or_unknown():
    if QPC_KERNEL is None:
        return None
    try:
        return (qpc() - ORIGIN_QPC) * 1_000_000_000 // QPC_FREQUENCY
    except BaseException:
        return None

def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")

def file_fields(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)

def open_metadata_nofollow(path):
    # Windows OPEN_REPARSE_POINT opens the final component itself; the fd/path
    # checks reject reparse and nonregular objects without following them.
    if os.name != "nt":
        fail("native-Windows-metadata-open-required")
    import msvcrt
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        fail("metadata-noFollow-open:" + str(ctypes.get_last_error()))
    try:
        return msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise

def metadata_fd_fields(fd):
    # os.fstat and os.lstat may expose different Windows inode/device values.
    # Compare retained fd and a noFollow path handle using the same native fields.
    import msvcrt
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    class Information(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("creation", wintypes.FILETIME),
                    ("access", wintypes.FILETIME), ("write", wintypes.FILETIME),
                    ("volume", wintypes.DWORD), ("sizeHigh", wintypes.DWORD),
                    ("sizeLow", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("indexHigh", wintypes.DWORD), ("indexLow", wintypes.DWORD)]
    class Basic(ctypes.Structure):
        _fields_ = [(name, ctypes.c_longlong) for name in ("creation", "access", "write", "change")] + [
                    ("attributes", wintypes.DWORD)]
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(Information)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    info, basic = Information(), Basic()
    handle = msvcrt.get_osfhandle(fd)
    if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)) or not kernel.GetFileInformationByHandleEx(
            handle, 0, ctypes.byref(basic), ctypes.sizeof(basic)):
        fail("metadata-native-fd-fields-unknown")
    value = os.fstat(fd)
    length = (int(info.sizeHigh) << 32) | int(info.sizeLow)
    if not stat.S_ISREG(value.st_mode) or int(basic.attributes) & 0x410 or value.st_size != length:
        fail("metadata-fd-nonregular-or-reparse")
    # Stable device, inode, mode, size, mtime, ctime from one native view.
    return (int(info.volume), (int(info.indexHigh) << 32) | int(info.indexLow),
            value.st_mode, length, int(basic.write), int(basic.change))

def metadata_path_fields(path):
    fd = open_metadata_nofollow(path)
    try:
        return metadata_fd_fields(fd)
    finally:
        os.close(fd)

def read_metadata(path, maximum=2 * 1024 * 1024, sha=None, size=None):
    clock()
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or getattr(before, "st_file_attributes", 0) & 0x400:
        fail("metadata-nonregular-or-reparse")
    expected = before.st_size if size is None else size
    if type(expected) is not int or expected < 0 or expected > maximum or before.st_size != expected:
        fail("metadata-type-or-size")
    fd = open_metadata_nofollow(path)
    try:
        fd_before = metadata_fd_fields(fd)
        if fd_before[3] != expected or metadata_path_fields(path) != fd_before:
            fail("metadata-fd-path-identity-mismatch")
        data = os.read(fd, expected + 1)
        fd_after = metadata_fd_fields(fd)
        after = path.lstat()
        if fd_after != fd_before or metadata_path_fields(path) != fd_before or file_fields(after) != file_fields(before):
            fail("metadata-stable-six-fd-or-path-fields-mismatch")
        if len(data) != expected:
            fail("metadata-byte-mismatch")
        if sha is not None and hashlib.sha256(data).hexdigest() != sha:
            fail("metadata-sha-mismatch")
        clock()
    finally:
        os.close(fd)
    if file_fields(path.lstat()) != file_fields(before):
        fail("metadata-final-path-changed")
    return data

def tree_bytes(root):
    total = 0
    def walk_error(error):
        fail("current-storage-unknown:" + str(error))
    for parent, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        clock()
        for name in dirs:
            value = (Path(parent) / name).lstat()
            if not stat.S_ISDIR(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
                fail("owner-directory-link-or-unknown")
        for name in files:
            path = Path(parent) / name
            value = path.lstat()
            if not stat.S_ISREG(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
                fail("owner-nonregular-file")
            total += value.st_size
    return total

def storage_guard(reserve=0):
    clock()
    current = tree_bytes(OWN)
    temporary = tree_bytes(OWN / "tmp")
    if current + reserve > CAPS["regular"] or temporary > CAPS["tmp"]:
        fail("regular-or-tmp-cap")
    return {"currentRegularBytes": current, "currentTmpBytes": temporary,
            "measurement": "current snapshot only; unsampled storage high-water is unknown"}

def write_exclusive(path, data):
    storage_guard(len(data))
    with open(path, "xb") as output:
        output.write(data)
    if read_metadata(path, maximum=len(data), size=len(data), sha=hashlib.sha256(data).hexdigest()) != data:
        fail("own-file-readback")

def load_pinned_module(name, path, sha, size):
    read_metadata(path, sha=sha, size=size)
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

class NativeReadout:
    """Read-only OWN measurements; never creates, assigns, terminates or duplicates a Job."""
    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.handles = {}
        self.rows = {}
        self.job_total = 0
        self.sampled_rss = 0
        self.sampled_rss_max = 0
        self.observed_sum_process_peaks_max = 0
        self.closed_handles = []
        self.owned = None
        signatures = {
            "GetCurrentProcess": ([], wintypes.HANDLE),
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "GetProcessTimes": ([wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME)], wintypes.BOOL),
            "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL)
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.kernel, name)
            fn.argtypes = args
            fn.restype = result
        class Memory(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("pageFaults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "peakWorkingSet", "workingSet", "quotaPeakPaged", "quotaPaged",
                    "quotaPeakNonpaged", "quotaNonpaged", "pagefile", "peakPagefile", "privateUsage")]
        class PidList(ctypes.Structure):
            _fields_ = [("assigned", wintypes.DWORD), ("count", wintypes.DWORD),
                        ("ids", ctypes.c_size_t * 64)]
        if ctypes.sizeof(Memory) != 80 or ctypes.sizeof(PidList) != 520:
            fail("unverified-Windows-x64-readout-layout")
        self.Memory = Memory
        self.PidList = PidList
        self.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
        self.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        self.parent_handle = self.kernel.GetCurrentProcess()
        self.parent_identity = self.identity(self.parent_handle, os.getpid())
        self.memory(self.parent_handle)

    def require(self, value, name):
        if not value:
            fail("native-readout-failed:" + name + ":" + str(ctypes.get_last_error()))

    def identity(self, handle, pid):
        a, b, c, d = (wintypes.FILETIME() for _ in range(4))
        self.require(self.kernel.GetProcessTimes(handle, ctypes.byref(a), ctypes.byref(b),
                     ctypes.byref(c), ctypes.byref(d)), "GetProcessTimes")
        return {"pid": int(pid), "creationFiletime100nsDecimal":
                str((int(a.dwHighDateTime) << 32) | int(a.dwLowDateTime))}

    def memory(self, handle):
        result = self.Memory()
        result.cb = ctypes.sizeof(result)
        self.require(self.psapi.GetProcessMemoryInfo(handle, ctypes.byref(result), ctypes.sizeof(result)),
                     "GetProcessMemoryInfo")
        return {"workingSetBytes": int(result.workingSet),
                "processPeakWorkingSetBytes": int(result.peakWorkingSet)}

    def attach(self, owned):
        self.owned = owned

    def sample(self):
        clock(True)
        parent = self.memory(self.parent_handle)
        ids = self.PidList()
        job = self.owned.job
        if job is None or job.handle is None:
            fail("native-owned-job-unavailable")
        self.require(job.kernel.QueryInformationJobObject(job.handle, 3, ctypes.byref(ids),
                     ctypes.sizeof(ids), None), "JobObjectBasicProcessIdList")
        if ids.count > 64 or ids.assigned > 64:
            fail("current-owned-process-list-unknown")
        accounting = job.accounting_type()
        self.require(job.kernel.QueryInformationJobObject(job.handle, 1, ctypes.byref(accounting),
                     ctypes.sizeof(accounting), None), "JobObjectBasicAccountingInformation")
        self.job_total = max(self.job_total, int(accounting.total))
        active_ids = [int(ids.ids[i]) for i in range(int(ids.count))]
        if len(set(active_ids)) != len(active_ids) or int(accounting.active) != len(active_ids):
            fail("current-owned-process-list-inconsistent")
        current = parent["workingSetBytes"]
        for pid in active_ids:
            if pid not in self.handles:
                handle = self.kernel.OpenProcess(0x00100410, False, pid)
                self.require(handle, "OpenProcess-live-owned-member")
                self.handles[pid] = handle
                self.rows[pid] = {"identity": self.identity(handle, pid),
                    "role": "startup-gate" if pid == self.owned.pid else "owned-descendant",
                    "targetRoleMappingIndependentlyVerified": False}
            mem = self.memory(self.handles[pid])
            row = self.rows[pid]
            row["lastMemoryWhileListed"] = mem
            row["observedProcessPeakWorkingSetBytes"] = max(
                row.get("observedProcessPeakWorkingSetBytes", 0), mem["processPeakWorkingSetBytes"])
            current += mem["workingSetBytes"]
        peaks = parent["processPeakWorkingSetBytes"] + sum(
            row.get("observedProcessPeakWorkingSetBytes", 0) for row in self.rows.values())
        self.sampled_rss = current
        self.sampled_rss_max = max(self.sampled_rss_max, current)
        self.observed_sum_process_peaks_max = max(self.observed_sum_process_peaks_max, peaks)
        if current > CAPS["rss"]:
            fail("observed-current-OWN-resident-cap")
        return {"qpcTicksDecimal": str(qpc()), "jobActiveProcesses": int(accounting.active),
                "jobTotalProcessesObserved": self.job_total, "capturedProcessIdentities": len(self.handles),
                "aggregateResidentWorkingSetSampleBytes": current,
                "sampledMaximumAggregateResidentBytes": self.sampled_rss_max,
                "observedSumProcessPeakWorkingSetBytes": peaks,
                "metricQualification": "partial OWN: controller + listed inner Job members; outer must sample complete OWN union once; process peak sums are not aggregate physical maximum; lifetime coverage unknown"}

    def finish_and_close(self):
        failures, observations = [], []
        observed_exit_peaks = {}
        try:
            for pid, handle in self.handles.items():
                try:
                    clock()
                    if self.kernel.WaitForSingleObject(handle, 0) != 0:
                        fail("retained-owned-process-not-signaled")
                    self.rows[pid]["finalWaitSignaled"] = True
                except BaseException as error:
                    failures.append("retained-wait:" + str(pid) + ":" + str(error))
                    continue
                # An exited member's memory API may be unavailable. This is an
                # observation unknown, separate from target/wait/drain/close failure.
                result = self.Memory()
                result.cb = ctypes.sizeof(result)
                if self.psapi.GetProcessMemoryInfo(handle, ctypes.byref(result), ctypes.sizeof(result)):
                    observed_exit_peaks[str(pid)] = int(result.peakWorkingSet)
                    self.rows[pid]["postExitPeakWorkingSetBytes"] = int(result.peakWorkingSet)
                else:
                    self.rows[pid]["postExitPeakWorkingSetBytes"] = None
                    observations.append("post-exit-memory-unknown:" + str(pid))
        finally:
            for pid, handle in list(self.handles.items()):
                if self.kernel.CloseHandle(handle):
                    self.closed_handles.append(pid)
                else:
                    failures.append("readout-CloseHandle:" + str(pid))
                del self.handles[pid]
        captured = len(self.rows)
        population_count_matches = self.job_total >= 1 and self.job_total == captured
        if not population_count_matches:
            observations.append("lifetime-population-coverage-unknown")
        return {"controllerIdentity": self.parent_identity, "members": list(self.rows.values()),
                "jobTotalProcessesObserved": self.job_total, "capturedPopulationCount": captured,
                "cumulativePopulationCountMatchesCaptured": population_count_matches,
                "completeLifetimePopulationIndependentlyVerified": False,
                "postExitPeakWorkingSetByPid": observed_exit_peaks,
                "aggregatePhysicalMaximumResidentBytes": None,
                "sampledMaximumAggregateResidentBytes": self.sampled_rss_max,
                "maximumObservedSumProcessPeakWorkingSetBytes": self.observed_sum_process_peaks_max,
                "closedReadoutProcessHandles": self.closed_handles,
                "cleanupFailures": failures, "observationalUnknowns": observations,
                "controllerFinalPeakAfterExitAndIndependentParentWaitVerified": False}

def audit_stop(owned):
    job = owned.job
    original_active, original_close = job.active, job.close
    def active():
        value = original_active()
        STOP_AUDIT["lastNativeJobActiveReadout"] = value
        STOP_AUDIT["activeZeroReadoutSeen"] = STOP_AUDIT.get("activeZeroReadoutSeen", False) or value == 0
        return value
    def close():
        # The extra readout must never suppress original backend closure.
        try:
            accounting = job.accounting_type()
            ok = job.kernel.QueryInformationJobObject(job.handle, 1, ctypes.byref(accounting),
                    ctypes.sizeof(accounting), None)
            if ok:
                STOP_AUDIT["finalAccountingBeforeBackendClose"] = {
                    "total": int(accounting.total), "active": int(accounting.active),
                    "terminated": int(accounting.terminated)}
                METER.job_total = max(METER.job_total, int(accounting.total))
            else:
                STOP_AUDIT["finalAccountingReadoutError"] = str(ctypes.get_last_error())
        except BaseException as error:
            STOP_AUDIT["finalAccountingReadoutError"] = str(error)
        finally:
            original_close()
        STOP_AUDIT["backendJobCloseReturned"] = True
        STOP_AUDIT["backendJobHandleIsNone"] = job.handle is None
        STOP_AUDIT["independentRootCloseHandleObservation"] = False
    job.active, job.close = active, close

def pump(stream, path):
    global RAW_READ, RAW_SAVED, READ_ERROR
    try:
        with open(path, "xb") as output:
            while True:
                data = stream.buffer.read1(8192)
                if not data:
                    return
                with LOG_LOCK:
                    RAW_READ += len(data)
                    if RAW_READ > CAPS["logs"] - LOG_RESERVE:
                        READ_ERROR = "combined-raw-log-cap"
                        return
                    output.write(data)
                    output.flush()
                    RAW_SAVED += len(data)
    except BaseException as error:
        READ_ERROR = "raw-log-reader:" + str(error)

def verify_authority(plan, gate, package, owner):
    required = ["actualGranted", "firstNoNNWindowsCIAccepted", "macPublicNNClosed",
        "oneHeavySlotReserved", "focusedSourcePeerAccepted", "remoteOuterContractBound",
        "externalWaitAndFreshPhysicalRequired", "canonicalCPU4_1AndModelsPreserved"]
    if any(gate.get(name) is not True for name in required):
        fail("mandatory-platform-or-distinct-Root-admission-unresolved")
    if gate["exactCommit"] != os.environ.get("GITHUB_SHA") or not gate["exactCommit"]:
        fail("remote-exact-commit-mismatch")
    if str(gate["runId"]) != os.environ.get("GITHUB_RUN_ID") or str(gate["runAttempt"]) != os.environ.get("GITHUB_RUN_ATTEMPT"):
        fail("remote-run-identity-mismatch")
    if gate["wholeSeconds"] != 300 or gate["workSeconds"] != 270 or gate["cleanupSeconds"] != 30 or gate["retry"] != 0:
        fail("root-deadline-or-retry-mismatch")
    if gate["capsBytes"] != CAPS:
        fail("root-resource-caps-mismatch")
    for key in ("noNNWindowsAcceptedRef", "macNNClosedAcceptedRef", "focusedSourcePeerRef",
                "remoteOuterContractSourceRef"):
        ref = gate[key]
        if not isinstance(ref, dict) or len(ref.get("sha256", "")) != 64 or any(c not in "0123456789abcdef" for c in ref["sha256"]):
            fail("missing-exact-authority-ref:" + key)
    if os.path.normcase(str(package)) != os.path.normcase(os.environ.get("GITHUB_WORKSPACE", "")):
        fail("package-is-not-exact-remote-workspace")
    runner_tmp = Path(os.environ["RUNNER_TEMP"]).resolve()
    if runner_tmp not in owner.parents or owner.exists():
        fail("owner-not-fresh-under-runner-temp")
    if plan["actualGranted"] is not False:
        fail("Source-plan-inferred-execution-authority")

def run():
    global OWN, OWNED, METER, READER
    if os.name != "nt" or struct.calcsize("P") != 8:
        fail("native-Windows-x64-required")
    args = sys.argv[1:]
    if len(args) != 12 or args[::2] != ["--root-grant", "--root-grant-sha256", "--package", "--owner",
            "--origin-qpc-ticks", "--qpc-frequency"]:
        fail("explicit-root-grant-fresh-owner-original-QPC-required")
    bind_original_qpc(args[9], args[11])
    script_root = Path(__file__).resolve().parent
    plan = json.loads(read_metadata(script_root / "source-plan.json", sha=PLAN_SHA))
    grant = json.loads(read_metadata(Path(args[1]), maximum=131072, sha=args[3]))
    gate = grant["executionGate"]
    if gate["originQpcTicksDecimal"] != args[9] or gate["qpcFrequencyDecimal"] != args[11]:
        fail("Root-remote-original-QPC-binding-mismatch")
    for key, path in (("operator", Path(__file__).resolve()), ("plan", script_root / "source-plan.json"),
                      ("sourceFreeze", script_root / "source-freeze.json"), ("remoteContract", script_root / "remote-contract.json")):
        ref = gate["sourcePins"][key]
        read_metadata(path, sha=ref["sha256"], size=ref["bytes"])
    if gate["sourcePins"]["plan"]["sha256"] != PLAN_SHA:
        fail("root-frozen-plan-mismatch")
    package, owner = Path(args[5]).resolve(), Path(args[7]).resolve()
    verify_authority(plan, gate, package, owner)
    RECEIPT.update({"actualGranted": True, "executionGrantSha256": args[3],
        "exactCommit": gate["exactCommit"], "runId": gate["runId"], "runAttempt": gate["runAttempt"],
        "sourcePins": gate["sourcePins"], "externalAcceptanceStillRequired": True})
    METER = NativeReadout()
    owner.mkdir()
    OWN = owner
    for name in ("job", "tmp", "logs"):
        (OWN / name).mkdir()
    write_exclusive(OWN / "entry.json", encoded({
        "status": "DISTINCT_ONE_NATIVE_ATTEMPT_ENTERED", "controllerPid": os.getpid(),
        "controllerIdentity": METER.parent_identity, "originQpcTicksDecimal": str(ORIGIN_QPC),
        "qpcFrequencyDecimal": str(QPC_FREQUENCY), "workDeadlineQpcTicksDecimal": str(WORK_QPC),
        "wholeDeadlineQpcTicksDecimal": str(WHOLE_QPC), "controllerEntryQpcTicksDecimal": str(qpc()),
        "exactCommit": gate["exactCommit"], "runId": gate["runId"], "runAttempt": gate["runAttempt"]}))
    write_exclusive(OWN / "job" / "job.json", encoded(plan["jobSeed"]))
    video = package / "grant-demo" / "media" / "example-1a.mp4"
    before_video = video.stat()
    if before_video.st_size != 818120:
        fail("canonical-public-sample-byte-mismatch")
    config = package / "configs" / "axel-release-ort4-windows-x64-v2.json"
    before_config = config.stat()
    owner_module = load_pinned_module("_fs_elem_native_windows_owner",
        package / "services" / "analysis" / "process_owner.py", OWNER_SOURCE_SHA, OWNER_SOURCE_BYTES)
    science = package / ".runtime" / "venv-science" / "Scripts" / "python.exe"
    argv = [str(science), "-B", str(package / "runtime" / "analyze_job.py"),
            "--job", str(OWN / "job"), "--video", str(video), "--config", str(config)]
    env = dict(os.environ)
    env.update({"TEMP": str(OWN / "tmp"), "TMP": str(OWN / "tmp"), "TMPDIR": str(OWN / "tmp"),
                "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    # CPU and preinstalled model/cache settings come from admitted canonical config/environment.
    clock(True)
    OWNED = owner_module.OwnedProcess.launch(argv, cwd=package, env=env)
    if OWNED.job is None:
        fail("native-JobObject-owner-required")
    audit_stop(OWNED)
    METER.attach(OWNED)
    READER = threading.Thread(target=pump, args=(OWNED.stdout, OWN / "logs" / "child-stdout-stderr.bin"), daemon=True)
    READER.start()
    samples = 0
    last = None
    while True:
        clock(True)
        if READ_ERROR:
            fail(READ_ERROR)
        storage_guard()
        if OWNED.poll() is not None:
            break
        last = METER.sample()
        samples += 1
        time.sleep(0.02)
    exit_code = OWNED.wait(timeout=remaining_seconds(1, work=True))
    if exit_code != 0:
        fail("canonical-science-command-exit:" + str(exit_code))
    outputs = {}
    for name in ("research-result.json", "result.json", "pose.json"):
        clock(True)
        outputs[name] = json.loads(read_metadata(OWN / "job" / name, maximum=32 * 1024 * 1024))
    if not isinstance(outputs["research-result.json"], dict):
        fail("research-result-not-object")
    result_source = outputs["result.json"]["source"]
    if result_source != outputs["pose.json"]["source"] or result_source.get("sha256") != SAMPLE_SHA:
        fail("published-result-pose-source-contract")
    after_video, after_config = video.stat(), config.stat()
    if file_fields(before_video) != file_fields(after_video):
        fail("public-sample-stat-changed")
    if file_fields(before_config) != file_fields(after_config):
        fail("canonical-config-stat-changed")
    clock(True)
    RECEIPT.update({"status": "CANONICAL_COMMAND_AND_OUTPUT_METADATA_COMPLETED", "actualGranted": True,
        "controllerPid": os.getpid(), "startupGatePid": OWNED.pid, "argv": argv,
        "samples": samples, "lastNativeReadoutBeforeStop": last, "targetExitCode": exit_code,
        "expectedOutputsPresent": list(outputs), "resultPoseSourceIdentical": True,
        "sourceSha256": SAMPLE_SHA, "wholeClipCommandHasNoTrimArguments": True,
        "scientificCorrectnessOrProcessedFrameCoverageVerified": False,
        "modelCPUConfigurationAltered": False, "nativeExternalAcceptancePending": True})

def cleanup():
    global CAUSE
    errors = []
    def attempt(name, action):
        global CAUSE
        try:
            return action()
        except BaseException as error:
            errors.append(name + ":" + type(error).__name__ + ":" + str(error))
            if CAUSE is None:
                CAUSE = errors[-1]
            return None
    if OWNED is not None:
        def stop():
            started = qpc()
            if remaining_seconds(6) < 6:
                fail("insufficient-original-deadline-for-accepted-stop")
            OWNED.stop()
            STOP_AUDIT["publicStopReturned"] = True
            STOP_AUDIT["stopElapsedNs"] = (qpc() - started) * 1_000_000_000 // QPC_FREQUENCY
        attempt("accepted-stop", stop)
        def wait():
            clock()
            value = OWNED.wait(timeout=remaining_seconds(3))
            STOP_AUDIT["retainedFinalWaitExitCode"] = value
            return value
        waited = attempt("retained-final-wait", wait)
        if READER is not None:
            def join():
                clock()
                READER.join(timeout=remaining_seconds(3))
                if READER.is_alive():
                    fail("raw-reader-not-joined")
                STOP_AUDIT["rawReaderJoined"] = True
            attempt("raw-reader-join", join)
        if READER is None or not READER.is_alive():
            def close_stdout():
                if OWNED.stdout:
                    OWNED.stdout.close()
                    STOP_AUDIT["stdoutClosed"] = OWNED.stdout.closed
            attempt("stdout-close", close_stdout)
        else:
            STOP_AUDIT["stdoutCloseDeferredToControllerExit"] = True
        if waited is not None:
            def close_original():
                handle = OWNED.process._handle
                if not callable(getattr(handle, "Close", None)):
                    fail("retained-original-process-handle-close-unresolved")
                handle.Close()
                STOP_AUDIT["retainedOriginalProcessHandleCloseReturned"] = True
            attempt("original-process-handle-close", close_original)
    # Close meter-owned handles even after launch/sample/stop failures.
    if METER is not None:
        final = attempt("readout-finalization", METER.finish_and_close)
        RECEIPT["nativeFinalReadout"] = final
        if OWNED is not None and final is None:
            errors.append("native-readout-finalization-failed")
        if final is not None:
            errors.extend(final["cleanupFailures"])
    if OWNED is not None:
        accounting = STOP_AUDIT.get("finalAccountingBeforeBackendClose", {})
        if not STOP_AUDIT.get("activeZeroReadoutSeen") or accounting.get("active") != 0 or not STOP_AUDIT.get("backendJobCloseReturned"):
            errors.append("owned-native-drain-or-backend-close-unresolved")
    if errors:
        RECEIPT["cleanupErrors"] = errors
        if CAUSE is None:
            CAUSE = errors[0]
    attempt("final-whole-clock", clock)

if __name__ == "__main__":
    try:
        run()
    except BaseException as error:
        if CAUSE is None:
            CAUSE = type(error).__name__ + ":" + str(error)
    try:
        cleanup()
    except BaseException as error:
        if CAUSE is None:
            CAUSE = "cleanup:" + type(error).__name__ + ":" + str(error)
        RECEIPT["cleanupError"] = str(error)
    RECEIPT.update({"firstCause": CAUSE, "status":
        "NATIVE_NN_COMMAND_COMPLETED_PENDING_REMOTE_PHYSICAL_ACCEPTANCE" if CAUSE is None else "FAILED",
        "originQpcTicksDecimal": None if ORIGIN_QPC is None else str(ORIGIN_QPC),
        "qpcFrequencyDecimal": None if QPC_FREQUENCY is None else str(QPC_FREQUENCY),
        "wholeDeadlineQpcTicksDecimal": None if WHOLE_QPC is None else str(WHOLE_QPC),
        "elapsedNs": elapsed_ns_or_unknown(), "stopAudit": STOP_AUDIT,
        "rawCombinedChildLogBytesRead": RAW_READ, "rawCombinedChildLogBytesSaved": RAW_SAVED,
        "rawReaderError": READ_ERROR, "sameScopeRetryAllowed": False,
        "ownControllerReapAndFinalPeakIndependentlyVerified": False,
        "releaseAccepted": False, "sourcePlanWasExecutionAuthority": False})
    if READ_ERROR and CAUSE is None:
        CAUSE = READ_ERROR
        RECEIPT["firstCause"] = CAUSE
        RECEIPT["status"] = "FAILED"
    try:
        clock()
        if OWN is not None:
            RECEIPT["finalStorageSnapshot"] = storage_guard()
            receipt_data = encoded(RECEIPT)
            write_exclusive(OWN / "receipt.json", receipt_data)
            terminal = encoded({"status": RECEIPT["status"], "firstCause": CAUSE,
                "receiptPath": str(OWN / "receipt.json"), "receiptBytes": len(receipt_data),
                "receiptSha256": hashlib.sha256(receipt_data).hexdigest(),
                "controllerPid": os.getpid(), "remoteExternalCompletionAndPhysicalReadoutRequired": True})
        else:
            terminal = encoded({"status": "NOT_ENTERED", "firstCause": CAUSE})
        if RAW_READ + len(terminal) > CAPS["logs"]:
            fail("combined-child-parent-log-cap")
        clock()
        sys.stdout.buffer.write(terminal)
        sys.stdout.buffer.flush()
    except BaseException as error:
        CAUSE = CAUSE or "receipt:" + str(error)
        sys.stderr.write("FAIL-CLOSED:" + CAUSE[:512] + "\n")
    raise SystemExit(0 if CAUSE is None else 1)
