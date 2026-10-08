"""SOURCE ONLY shared plumbing for the one granted Windows platform smoke."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import threading
import time
from types import SimpleNamespace
import importlib.util
_core_spec = importlib.util.spec_from_file_location("_fs_elem_windows_nn_core", Path(__file__).resolve().with_name("windows_nn_operator.py"))
core = importlib.util.module_from_spec(_core_spec)
sys.modules[_core_spec.name] = core
_core_spec.loader.exec_module(core)

ROOT = None
SCRIPT = Path(__file__).resolve().parent
def first_cause(error):
    if core.CAUSE is None:
        core.CAUSE = type(error).__name__ + ":" + str(error)
    return core.CAUSE

def capture_original():
    if os.name != "nt" or struct.calcsize("P") != 8:
        core.fail("native-Windows-x64-required")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    tick, freq = ctypes.c_longlong(), ctypes.c_longlong()
    for name in ("QueryPerformanceCounter", "QueryPerformanceFrequency"):
        fn = getattr(kernel, name)
        fn.argtypes, fn.restype = [ctypes.POINTER(ctypes.c_longlong)], wintypes.BOOL
    if not kernel.QueryPerformanceFrequency(ctypes.byref(freq)) or not kernel.QueryPerformanceCounter(ctypes.byref(tick)):
        core.fail("original-native-QPC-unknown")
    core.bind_original_qpc(str(tick.value), str(freq.value))
    return str(tick.value), str(freq.value)

def arguments(external=False):
    global ROOT
    flags = ["--root-grant", "--root-grant-sha256", "--package", "--owner"]
    if not external:
        flags += ["--origin-qpc-ticks", "--qpc-frequency"]
    values = sys.argv[1:]
    if len(values) != 2 * len(flags) or values[::2] != flags:
        raise RuntimeError("explicit-bound-remote-arguments-required")
    if external:
        origin, frequency = capture_original()
    else:
        origin, frequency = values[9], values[11]
        core.bind_original_qpc(origin, frequency)
    grant = json.loads(core.read_metadata(Path(values[1]), maximum=131072, sha=values[3]))
    gate = grant["executionGate"]
    if not external and (gate["originQpcTicksDecimal"] != origin or gate["qpcFrequencyDecimal"] != frequency):
        core.fail("propagated-original-QPC-mismatch")
    package, ROOT = Path(values[5]).resolve(), Path(values[7]).resolve()
    plan = json.loads(core.read_metadata(SCRIPT / "source-plan.json", sha=core.PLAN_SHA))
    for key, name in (("operator","windows_nn_operator.py"),("plan","source-plan.json"),
            ("sourceFreeze","source-freeze.json"),("remoteContract","remote-contract.json"),
            ("remoteSupport","remote_support.py"),("remoteEntry","remote_entry.py"),
            ("remoteOuter","remote_outer.py"),("remoteWitness","remote_witness.py")):
        ref = gate["sourcePins"][key]
        core.read_metadata(SCRIPT / name, sha=ref["sha256"], size=ref["bytes"])
    if gate.get("remoteOuterExecutableSourceBound") is not True:
        core.fail("exact-executable-outer-Source-not-admitted")
    if external:
        core.verify_authority(plan, gate, package, ROOT / "controller")
        if ROOT.exists() or Path(os.environ["RUNNER_TEMP"]).resolve() not in ROOT.parents:
            core.fail("external-OWN-not-fresh")
    else:
        if gate["exactCommit"] != os.environ.get("GITHUB_SHA") or str(gate["runId"]) != os.environ.get("GITHUB_RUN_ID") or str(gate["runAttempt"]) != os.environ.get("GITHUB_RUN_ATTEMPT"):
            core.fail("remote-run-binding-mismatch")
        if not ROOT.is_dir():
            core.fail("external-OWN-missing")
    core.OWN = ROOT
    return grant, gate, package, origin, frequency

def save(name, value):
    core.write_exclusive(ROOT / name, core.encoded(value))

def read(name, maximum=131072):
    return json.loads(core.read_metadata(ROOT / name, maximum=maximum))

def runtime_argv(name, grant_sha, package, origin, frequency, owner=None):
    return [sys.executable, "-I", "-S", "-B", str(SCRIPT / name),
        "--root-grant", str(ROOT / "runtime-grant.json"), "--root-grant-sha256", grant_sha,
        "--package", str(package), "--owner", str(ROOT if owner is None else owner),
        "--origin-qpc-ticks", origin, "--qpc-frequency", frequency]

def environment():
    result = dict(os.environ)
    result.update({"TEMP":str(ROOT / "tmp"),"TMP":str(ROOT / "tmp"),"TMPDIR":str(ROOT / "tmp"),
        "PYTHONDONTWRITEBYTECODE":"1","PYTHONUNBUFFERED":"1","PYTHONIOENCODING":"utf-8"})
    return result

def load_owner(package):
    return core.load_pinned_module("_fs_elem_remote_default_owner",
        package / "services" / "analysis" / "process_owner.py",
        core.OWNER_SOURCE_SHA, core.OWNER_SOURCE_BYTES)

def requested_stop():
    path = ROOT / "root-stop.json"
    if path.exists():
        reason = read("root-stop.json",32768)
        core.fail("independent-root-stop:" + str(reason["firstCause"]))

def storage_snapshot():
    view = core.storage_guard()
    child_tmp = ROOT / "controller" / "tmp"
    try:
        child_tmp.lstat()
    except FileNotFoundError:
        child_bytes = 0
    else:
        child_bytes = core.tree_bytes(child_tmp)
    combined = view["currentTmpBytes"] + child_bytes
    if combined > core.CAPS["tmp"]:
        core.fail("combined-current-OWN-TMP-subset-cap")
    view.update({"outerTmpBytes":view["currentTmpBytes"],"controllerTmpBytes":child_bytes,
        "combinedCurrentTmpSubsetBytes":combined,
        "tmpQualification":"combined current subset; unsampled high-water unknown"})
    return view

def guard():
    core.clock(True)
    requested_stop()
    return storage_snapshot()

class RawReader:
    def __init__(self, stream, name, cap=16384):
        self.stream, self.name, self.cap = stream, name, cap
        self.count, self.error = 0, None
        self.thread = threading.Thread(target=self.run, daemon=True)
    def start(self):
        self.thread.start()
    def join(self, timeout):
        self.thread.join(timeout)
    def is_alive(self):
        return self.thread.is_alive()
    def run(self):
        try:
            with (ROOT / "logs" / self.name).open("xb") as output:
                while True:
                    raw = self.stream.read1(8192)
                    if not raw:
                        return
                    self.count += len(raw)
                    if self.count > self.cap:
                        self.error = "shared-diagnostic-raw-log-cap"
                        return
                    output.write(raw)
                    output.flush()
        except BaseException as error:
            self.error = str(error)

def diagnostic_bytes():
    result = 0
    for name in ("outer-raw.bin","witness-raw.bin"):
        path = ROOT / "logs" / name
        try:
            result += path.stat().st_size
        except FileNotFoundError:
            pass
    return result

def log_guard(extra=0):
    diagnostic = diagnostic_bytes() + extra
    path = ROOT / "controller" / "logs" / "child-stdout-stderr.bin"
    try:
        science = path.stat().st_size
    except FileNotFoundError:
        science = 0
    if diagnostic > 16384 or science > 245760 or diagnostic + science > 262144:
        core.fail("combined-raw-science-and-outer-log-cap")
    return {"scienceRawBytesSaved":science,"diagnosticBytesObserved":diagnostic,
        "continuousRawHighWaterVerified":False}

def emit(value):
    data = core.encoded(value)
    log_guard(len(data))
    core.clock()
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()

def close_popen_handle(process):
    handle = process._handle
    if not callable(getattr(handle,"Close",None)):
        core.fail("retained-Popen-handle-close-unsupported")
    handle.Close()

def borrowed_job(handle, kernel):
    class Accounting(ctypes.Structure):
        _fields_ = [(name,ctypes.c_longlong) for name in ("user","kernel","period_user","period_kernel")] + [
            (name,wintypes.DWORD) for name in ("faults","total","active","terminated")]
    kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE,ctypes.c_int,wintypes.LPVOID,wintypes.DWORD,wintypes.LPVOID]
    kernel.QueryInformationJobObject.restype = wintypes.BOOL
    if ctypes.sizeof(Accounting) != 48:
        core.fail("native-accounting-layout")
    return SimpleNamespace(handle=handle,kernel=kernel,ctypes=ctypes,accounting_type=Accounting)

def job_accounting(job):
    value = job.accounting_type()
    if not job.kernel.QueryInformationJobObject(job.handle,1,ctypes.byref(value),ctypes.sizeof(value),None):
        core.fail("Root-independent-Job-accounting-unknown")
    return {"active":int(value.active),"total":int(value.total),"terminated":int(value.terminated)}

def source_stat(path):
    s = path.stat()
    return list(core.file_fields(s))
