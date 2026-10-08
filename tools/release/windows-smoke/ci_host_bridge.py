"""INERT SOURCE: external CI parent for the admitted E300 Windows smoke."""
import time
HOST_ORIGIN_NS = time.monotonic_ns()
HOST_WHOLE_NS = HOST_ORIGIN_NS + 330_000_000_000
import ctypes
from ctypes import wintypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading

PROCESS = READER = CORE = HOST = NN = None
WAITED = HANDLE_CLOSED = EXIT_SAVED = False
CAUSE = None
RAW_READ = RAW_SAVED = 0
READER_ERROR = None
RECEIPT = {"sourceOnly":False,"releaseAccepted":False,"actualGranted":False,
    "eExitCode":None,"retainedEWaitReturned":False,"eCreationIdentity":None}

def failure(reason):
    global CAUSE
    if CAUSE is None:
        CAUSE = reason
    raise RuntimeError(reason)

def host_clock():
    now = time.monotonic_ns()
    if now >= HOST_WHOLE_NS:
        failure("external-host-330s-boundary")
    return now

def remaining(ceiling):
    return min(ceiling,max(0.0,(HOST_WHOLE_NS - host_clock()) / 1e9))

def fields(value):
    return (value.st_dev,value.st_ino,value.st_mode,value.st_size,value.st_mtime_ns,value.st_ctime_ns)

def initial_source(path,maximum,sha=None):
    # Bootstrap only: independently stable path/fd fields and exact supplied SHA.
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or getattr(before,"st_file_attributes",0) & 0x400 or before.st_size > maximum:
        failure("bootstrap-source-type-or-size")
    fd = os.open(path,os.O_RDONLY | getattr(os,"O_BINARY",0) | getattr(os,"O_NOFOLLOW",0))
    try:
        first = os.fstat(fd)
        data = os.read(fd,before.st_size + 1)
        final = os.fstat(fd)
        after = path.lstat()
        if fields(first) != fields(final) or fields(before) != fields(after) or len(data) != before.st_size:
            failure("bootstrap-source-stability")
    finally:
        os.close(fd)
    if sha is not None and hashlib.sha256(data).hexdigest() != sha:
        failure("bootstrap-source-SHA")
    return data

def read_bytes(path,maximum=2 * 1024 * 1024,sha=None,size=None):
    host_clock()
    before = path.lstat()
    expected = before.st_size if size is None else size
    if type(expected) is not int or expected < 0 or expected > maximum or before.st_size != expected:
        failure("host-metadata-size")
    fd = CORE.open_metadata_nofollow(path)
    try:
        first = CORE.metadata_fd_fields(fd)
        if first[3] != expected or CORE.metadata_path_fields(path) != first:
            failure("host-metadata-fd-path")
        data = os.read(fd,expected + 1)
        if CORE.metadata_fd_fields(fd) != first or CORE.metadata_path_fields(path) != first or fields(path.lstat()) != fields(before):
            failure("host-metadata-stable-six")
    finally:
        os.close(fd)
    if len(data) != expected or (sha is not None and hashlib.sha256(data).hexdigest() != sha):
        failure("host-metadata-byte-or-SHA")
    host_clock()
    return data

def ref(value):
    if not isinstance(value,dict) or set(value) != {"name","bytes","sha256"}:
        failure("sanitized-metadata-ref-required")
    if not isinstance(value["name"],str) or Path(value["name"]).name != value["name"] or any(c in value["name"] for c in "/\\:"):
        failure("private-path-in-metadata-ref")
    if type(value["bytes"]) is not int or value["bytes"] <= 0:
        failure("metadata-ref-bytes")
    if len(value["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in value["sha256"]):
        failure("metadata-ref-SHA")
    return dict(value)

def save(path,value):
    data = (json.dumps(value,ensure_ascii=False,indent=2) + "\n").encode("utf-8")
    if len(data) > 2 * 1024 * 1024:
        failure("host-receipt-bound")
    with path.open("xb") as output:
        output.write(data)
    return {"name":path.name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}

def record_numeric_exit():
    global EXIT_SAVED
    if HOST is not None and WAITED and not EXIT_SAVED:
        save(HOST / "e-numeric-exit.json",{"eExitCode":RECEIPT["eExitCode"],
            "retainedEWaitReturned":True,"eCreationIdentity":RECEIPT["eCreationIdentity"],
            "hostObservedMonotonicNs":str(time.monotonic_ns())})
        EXIT_SAVED = True

def native_identity(handle,pid):
    kernel = ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    values = [wintypes.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle,*[ctypes.byref(v) for v in values]):
        failure("retained-E-creation-identity-unknown")
    return {"pid":pid,"creationFiletime100nsDecimal":str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)}

def retrospective_memory_or_unknown(handle):
    try:
        class Memory(ctypes.Structure):
            _fields_ = [("cb",wintypes.DWORD),("faults",wintypes.DWORD)] + [
                (name,ctypes.c_size_t) for name in ("peak","working","qpp","qp","qnp","qn","page","peakpage","private")]
        value = Memory()
        value.cb = ctypes.sizeof(value)
        api = ctypes.WinDLL("psapi",use_last_error=True).GetProcessMemoryInfo
        api.argtypes = [wintypes.HANDLE,ctypes.POINTER(Memory),wintypes.DWORD]
        api.restype = wintypes.BOOL
        if api(handle,ctypes.byref(value),ctypes.sizeof(value)):
            return {"workingSetBytes":int(value.working),"processPeakWorkingSetBytes":int(value.peak),
                "qualification":"single retrospective process observation; not aggregate maximum"}
    except BaseException:
        pass
    return None

def raw_reader():
    global RAW_READ,RAW_SAVED,READER_ERROR
    try:
        with (HOST / "e-raw-transcript.bin").open("xb") as out:
            while True:
                raw = PROCESS.stdout.read1(8192)
                if not raw:
                    return
                RAW_READ += len(raw)
                if RAW_READ > 65536:
                    READER_ERROR = "separate-host-raw-transcript-64KiB-cap"
                    return
                out.write(raw);out.flush();RAW_SAVED += len(raw)
    except BaseException as error:
        READER_ERROR = type(error).__name__

def attempt(name,action):
    global CAUSE
    try:
        return action()
    except BaseException as error:
        RECEIPT.setdefault("hostPhaseErrors",[]).append(name + ":" + type(error).__name__ + ":" + str(error))
        if CAUSE is None:
            CAUSE = name + ":" + type(error).__name__
        return None

try:
    args = sys.argv[1:]
    if len(args) != 6 or args[::2] != ["--template","--template-sha256","--prerequisites"]:
        failure("explicit-template-and-fresh-prerequisites-required")
    template_path = Path(args[1]).resolve()
    template = json.loads(initial_source(template_path,131072,args[3]))
    selector = template["selector"]
    event = json.loads(initial_source(Path(os.environ["GITHUB_EVENT_PATH"]),2 * 1024 * 1024))
    selected = (os.environ.get("GITHUB_EVENT_NAME") == selector["event"]
        and os.environ.get("GITHUB_REF") == selector["ref"]
        and os.environ.get("GITHUB_RUN_ATTEMPT") == selector["runAttempt"]
        and os.environ.get("GITHUB_RUN_NUMBER") == selector["runNumber"]
        and event.get("head_commit",{}).get("message") == selector["commitMessage"]
        and event.get("head_commit",{}).get("id") == os.environ.get("GITHUB_SHA"))
    if not selected:
        print("SKIPPED_NO_NN")
        raise SystemExit(0)
    binding_text = os.environ.get(template["privateBindingEnvironment"],"")
    if len(binding_text.encode("utf-8")) > 32768:
        failure("private-sanitized-binding-size")
    binding = json.loads(binding_text)
    if binding.get("authorizedSelectedPush") is not True or binding.get("triggerNonce") != selector["nonce"] or binding.get("allowedCommit") != os.environ.get("GITHUB_SHA"):
        failure("external-selected-push-authorization-missing")
    if len(binding["allowedCommit"]) != 40 or any(c not in "0123456789abcdef" for c in binding["allowedCommit"]):
        failure("exact-external-prepared-commit-required")
    for name in template["privateBindingRequiredFields"]:
        if name not in binding:
            failure("missing-sanitized-binding-field:" + name)
    for name in ("firstNoNNWindowsCIAccepted","macPublicNNClosed","oneHeavySlotReserved","focusedSourcePeerAccepted","bridgeSourcesBound","installerPrerequisitesAccepted"):
        if binding[name] is not True:
            failure("mandatory-Root-admission-unresolved:" + name)
    if type(binding["allowedRunNumber"]) is not int or binding["allowedRunNumber"] != 1 or str(binding["allowedRunNumber"]) != os.environ.get("GITHUB_RUN_NUMBER"):
        failure("one-externally-authorized-workflow-event-required")
    metadata_refs = {name:ref(binding[name]) for name in
        ("scopeRef","noNNWindowsAcceptedRef","macNNClosedAcceptedRef","focusedSourcePeerRef",
         "bridgeSourcePeerRef","preparedTreeRef","bridgeSourceRef")}
    script = template_path.parent
    core_pin = template["sourcePins"]["operator"]
    initial_source(script / core_pin["name"],core_pin["bytes"],core_pin["sha256"])
    spec = importlib.util.spec_from_file_location("_fs_elem_admitted_windows_core",script / core_pin["name"])
    CORE = importlib.util.module_from_spec(spec);sys.modules[spec.name] = CORE;spec.loader.exec_module(CORE)
    for key,pin in template["sourcePins"].items():
        read_bytes(script / pin["name"],maximum=2 * 1024 * 1024,sha=pin["sha256"],size=pin["bytes"])
    read_bytes(Path(__file__).resolve(),sha=metadata_refs["bridgeSourceRef"]["sha256"],size=metadata_refs["bridgeSourceRef"]["bytes"])
    prereq = json.loads(read_bytes(Path(args[5]).resolve(),maximum=131072))
    identity = {"exactCommit":os.environ["GITHUB_SHA"],"runId":os.environ["GITHUB_RUN_ID"],"runAttempt":os.environ["GITHUB_RUN_ATTEMPT"]}
    if prereq.get("phase") != "PRE_NN_FRESH_NATIVE_PREREQUISITES" or (type(prereq.get("numericExitCode")) is not int or prereq["numericExitCode"] != 0) or any(str(prereq.get(k)) != v for k,v in identity.items()):
        failure("fresh-host-prerequisite-record-mismatch")
    package = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    for pin in template["installerSourcePins"]:
        read_bytes(package / pin["path"],sha=pin["sha256"],size=pin["bytes"])
    if not (package / ".runtime/venv-science/Scripts/python.exe").is_file():
        failure("fresh-science-runtime-missing")
    runner = Path(os.environ["RUNNER_TEMP"]).resolve()
    HOST = runner / ("fs-elem-v021-host-" + identity["runId"] + "-" + identity["runAttempt"])
    HOST.mkdir()
    NN = HOST / "nn-own"
    gate = dict(template["fixedGate"])
    gate.update(identity)
    gate.update({name:True for name in ("actualGranted","firstNoNNWindowsCIAccepted","macPublicNNClosed",
        "oneHeavySlotReserved","focusedSourcePeerAccepted","remoteOuterContractBound",
        "remoteOuterExecutableSourceBound","runtimeProjectionAllowed")})
    gate.update({"sourcePins":template["sourcePins"],"noNNWindowsAcceptedRef":metadata_refs["noNNWindowsAcceptedRef"],
        "macNNClosedAcceptedRef":metadata_refs["macNNClosedAcceptedRef"],"focusedSourcePeerRef":metadata_refs["focusedSourcePeerRef"],
        "remoteOuterContractSourceRef":template["rootSourceAcceptanceRef"]})
    projection = {"executionGate":gate,"externalSelectedPushScopeRef":metadata_refs["scopeRef"],
        "preparedTreeRef":metadata_refs["preparedTreeRef"],"bridgeSourcePeerRef":metadata_refs["bridgeSourcePeerRef"]}
    gate_pin = save(HOST / "sanitized-runtime-gate.json",projection)
    RECEIPT.update({"actualGranted":True,"runtimeIdentity":identity,"generatedGatePin":gate_pin,
        "templateSha256":args[3],"externalSelectedPushScopeRef":metadata_refs["scopeRef"],"authorizedRunNumber":binding["allowedRunNumber"],
        "sourcePins":template["sourcePins"],"prerequisitesPhase":prereq["phase"]})
    argv = [sys.executable,"-I","-S","-B",str(script / "remote_entry.py"),
        "--root-grant",str(HOST / "sanitized-runtime-gate.json"),"--root-grant-sha256",gate_pin["sha256"],
        "--package",str(package),"--owner",str(NN)]
    host_clock()
    e_env = dict(os.environ)
    e_env.pop(template["privateBindingEnvironment"],None)
    PROCESS = subprocess.Popen(argv,cwd=package,env=e_env,stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=-1)
    READER = threading.Thread(target=raw_reader,daemon=True);READER.start()
    RECEIPT["eCreationIdentity"] = native_identity(int(PROCESS._handle),PROCESS.pid)
    while PROCESS.poll() is None:
        host_clock()
        if READER_ERROR:
            failure(READER_ERROR)
        if time.monotonic_ns() - HOST_ORIGIN_NS >= 320_000_000_000:
            failure("external-host-wait-320s-limit")
        time.sleep(0.02)
    RECEIPT["eExitCode"] = PROCESS.wait(timeout=remaining(3));WAITED = True
    record_numeric_exit()
    if RECEIPT["eExitCode"] != 0:
        failure("E-original-numeric-exit-nonzero")
    physical_path = NN / "root-physical-result.json"
    data = read_bytes(physical_path)
    physical = json.loads(data)
    RECEIPT["ePhysicalResultRef"] = {"name":physical_path.name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),
        "postStat":list(fields(physical_path.stat()))}
    if physical.get("firstCause") is not None or physical.get("status") != "COMPLETED_PENDING_ROOT_ACCEPTANCE" or not physical.get("retainedExternalWitnessWaitReturned") or not physical.get("witnessPopenHandleClosed"):
        failure("saved-E-physical-contract")
    pins = physical.get("freshSavedOutputPins")
    if not isinstance(pins,list) or {p.get("name") for p in pins} != {"research-result.json","result.json","pose.json"} or physical.get("savedResultPoseSourceIdentical") is not True:
        failure("E-fresh-saved-output-ref-contract")
    for pin in pins:
        if type(pin.get("bytes")) is not int or pin["bytes"] <= 0 or len(pin.get("sha256","")) != 64 or any(c not in "0123456789abcdef" for c in pin["sha256"]):
            failure("E-fresh-saved-output-pin")
    RECEIPT["eFreshSourceAndSavedOutputRefs"] = pins
except SystemExit:
    raise
except BaseException as error:
    if CAUSE is None:
        CAUSE = type(error).__name__ + ":" + str(error)
finally:
    if PROCESS is not None:
        if CAUSE is not None and NN is not None and NN.exists() and not (NN / "root-stop.json").exists():
            attempt("request-E-default-tree-stop",lambda:save(NN / "root-stop.json",{"firstCause":"external-host-boundary-failure"}))
        def wait_e():
            global WAITED
            if not WAITED:
                try:
                    PROCESS.wait(timeout=remaining(6));WAITED = True
                except BaseException as error:
                    attempt("terminate-only-retained-E-Popen",PROCESS.terminate)
                    try:
                        wait_time = remaining(3)
                    except BaseException:
                        wait_time = 0
                    PROCESS.wait(timeout=wait_time);WAITED = True
            RECEIPT["eExitCode"] = PROCESS.returncode
            record_numeric_exit()
        attempt("external-retained-E-wait",wait_e)
        if WAITED:
            RECEIPT["freshRetainedEIdentityAfterWait"] = attempt("E-identity-after-wait",
                lambda:native_identity(int(PROCESS._handle),PROCESS.pid))
            if RECEIPT["freshRetainedEIdentityAfterWait"] != RECEIPT["eCreationIdentity"]:
                attempt("E-retained-creation-identity-mismatch",lambda:failure("retained-E-identity-changed-or-unknown"))
            def native_signaled():
                fn = ctypes.WinDLL("kernel32",use_last_error=True).WaitForSingleObject
                fn.argtypes,fn.restype = [wintypes.HANDLE,wintypes.DWORD],wintypes.DWORD
                if fn(int(PROCESS._handle),0) != 0:
                    failure("external-E-native-wait-not-signaled")
                return True
            RECEIPT["retainedENativeSignaled"] = attempt("E-native-signaled",native_signaled)
            RECEIPT["postExitEProcessMemoryOrUnknown"] = retrospective_memory_or_unknown(int(PROCESS._handle))
        if READER is not None:
            def finish_reader():
                READER.join(remaining(2))
                if READER.is_alive() or READER_ERROR:
                    failure("external-E-transcript-reader-unjoined-or-error")
                PROCESS.stdout.close()
                return True
            RECEIPT["transcriptReaderJoinedAndStdoutClosed"] = attempt("raw-transcript-join",finish_reader)
        if WAITED:
            def close_handle():
                global HANDLE_CLOSED
                handle = PROCESS._handle
                if not callable(getattr(handle,"Close",None)):
                    failure("external-retained-E-handle-close-unsupported")
                handle.Close();HANDLE_CLOSED = True
            attempt("E-original-Popen-handle-close",close_handle)
    if HOST is not None:
        try:
            host_clock()
            RECEIPT.update({"firstCause":CAUSE,"hostStatus":"COMPLETED_PENDING_ROOT_ACCEPTANCE" if CAUSE is None else "FAILED",
                "retainedEWaitReturned":WAITED,"retainedEPopenHandleClosed":HANDLE_CLOSED,
                "hostOriginMonotonicNs":str(HOST_ORIGIN_NS),"hostWholeDeadlineMonotonicNs":str(HOST_WHOLE_NS),
                "externalHostElapsedNs":time.monotonic_ns() - HOST_ORIGIN_NS,
                "hostBoundarySeconds":330,"E300_270_30Unchanged":True,
                "rawETranscriptBytesRead":RAW_READ,"rawETranscriptBytesSaved":RAW_SAVED,
                "rawETranscriptError":READER_ERROR,"continuousResidentMaximumVerified":False,
                "hostFinalPeakAndCIParentReapVerified":False,"retryAllowed":False,
                "privateGateExcludedFromUpload":True})
            RECEIPT["transcriptRef"] = {"name":"e-raw-transcript.bin","bytes":RAW_SAVED,
                "sha256":hashlib.sha256(read_bytes(HOST / "e-raw-transcript.bin",maximum=65536)).hexdigest()}
            saved = save(HOST / "ci-host-result.json",RECEIPT)
            print(json.dumps({"hostStatus":RECEIPT["hostStatus"],"eExitCode":RECEIPT["eExitCode"],"hostReceipt":saved,
                "releaseAccepted":False},ensure_ascii=False))
        except BaseException as error:
            if CAUSE is None:
                CAUSE = "host-receipt:" + type(error).__name__
            sys.stderr.write("HOST-FAIL-CLOSED:" + CAUSE[:256] + "\n")
raise SystemExit(0 if CAUSE is None else 1)
