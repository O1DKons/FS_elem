"""SOURCE ONLY: Root-controlled entry, retained witness Popen and fresh physical readout."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace
import importlib.util
from pathlib import Path
_spec = importlib.util.spec_from_file_location("_fs_elem_remote_support", Path(__file__).resolve().with_name("remote_support.py"))
shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = shared
_spec.loader.exec_module(shared)
core = shared.core
process = reader = meter = job = None
dup_handle = None
waited = process_handle_closed = False
result = {"releaseAccepted":False,"actualGranted":False}
def try_phase(name, action):
    try:
        return action()
    except BaseException as error:
        result.setdefault("phaseErrors",[]).append(name + ":" + str(error))
        shared.first_cause(error)
        return None
def independent_memory(handle):
    value = meter.Memory()
    value.cb = ctypes.sizeof(value)
    if meter.psapi.GetProcessMemoryInfo(handle,ctypes.byref(value),ctypes.sizeof(value)):
        return {"workingSetBytes":int(value.workingSet),"processPeakWorkingSetBytes":int(value.peakWorkingSet)}
    return None
def complete_live_sample():
    # E + outer Job current members from the reused provider, plus retained W.
    # W is outside that Job, so each declared OWN process appears once.
    row = meter.sample()
    memory = meter.memory(int(process._handle))
    current = row["aggregateResidentWorkingSetSampleBytes"] + memory["workingSetBytes"]
    if current > core.CAPS["rss"]:
        core.fail("complete-current-OWN-resident-cap")
    result["sampledCompleteOwnResidentMaximumBytes"] = max(
        result.get("sampledCompleteOwnResidentMaximumBytes",0),current)
    return {"residentWorkingSetSampleBytes":current,"witnessMemory":memory,"outerJobSample":row,
        "aggregatePhysicalMaximumResidentBytes":None}
try:
    grant, gate, package, origin, frequency = shared.arguments(external=True)
    if gate.get("runtimeProjectionAllowed") is not True:
        core.fail("private-runtime-QPC-projection-not-authorized")
    shared.ROOT.mkdir()
    for name in ("tmp","logs"):
        (shared.ROOT / name).mkdir()
    shared.save("root-entry.json",{"rootParentPid":os.getpid(),"originalGrantSha256":sys.argv[3],
        "originQpcTicksDecimal":origin,"qpcFrequencyDecimal":frequency,
        "workDeadlineQpcTicksDecimal":str(core.WORK_QPC),"wholeDeadlineQpcTicksDecimal":str(core.WHOLE_QPC),
        "exactCommit":gate["exactCommit"],"runId":gate["runId"],"runAttempt":gate["runAttempt"]})
    runtime = json.loads(json.dumps(grant))
    runtime["executionGate"].update({"originQpcTicksDecimal":origin,"qpcFrequencyDecimal":frequency})
    runtime_data = core.encoded(runtime)
    core.write_exclusive(shared.ROOT / "runtime-grant.json",runtime_data)
    runtime_sha = hashlib.sha256(runtime_data).hexdigest()
    meter = core.NativeReadout()
    core.clock(True)
    process = subprocess.Popen(shared.runtime_argv("remote_witness.py",runtime_sha,package,origin,frequency),
        cwd=package,env=shared.environment(),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,bufsize=-1)
    witness_identity = meter.identity(int(process._handle),process.pid)
    reader = shared.RawReader(process.stdout,"witness-raw.bin")
    reader.start()
    while not (shared.ROOT / "witness-entry.json").exists():
        shared.guard()
        shared.log_guard()
        if reader.error:
            core.fail("witness-raw-reader:" + reader.error)
        if process.poll() is not None:
            core.fail("witness-exit-before-retained-Job-entry")
        # Before the Job ack, R cannot launch the NN controller.
        meter.memory(meter.parent_handle)
        meter.memory(int(process._handle))
        time.sleep(0.02)
    entry = shared.read("witness-entry.json")
    if entry["witnessPid"] != process.pid or entry["witnessIdentity"] != witness_identity or entry["runtimeGrantSha256"] != runtime_sha or entry["originQpcTicksDecimal"] != origin or entry["qpcFrequencyDecimal"] != frequency:
        core.fail("fresh-witness-entry-binding")
    kernel = meter.kernel
    kernel.DuplicateHandle.argtypes = [wintypes.HANDLE,wintypes.HANDLE,wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE),wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.DuplicateHandle.restype = wintypes.BOOL
    duplicate = wintypes.HANDLE()
    if not kernel.DuplicateHandle(int(process._handle),int(entry["outerJobHandleDecimal"]),
            kernel.GetCurrentProcess(),ctypes.byref(duplicate),0,False,2):
        core.fail("Root-independent-retained-Job-duplicate")
    dup_handle = duplicate.value
    job = shared.borrowed_job(dup_handle,kernel)
    meter.attach(SimpleNamespace(job=job,pid=entry["outerGatePid"]))
    result["lastLiveCompleteOwnSample"] = complete_live_sample()
    shared.save("root-retained.json",{"runtimeGrantSha256":runtime_sha,"originQpcTicksDecimal":origin,
        "witnessIdentity":witness_identity,"outerGatePid":entry["outerGatePid"],
        "independentRootJobHandleRetained":True})
    samples = 1
    while process.poll() is None:
        shared.guard()
        shared.log_guard()
        if reader.error:
            core.fail("witness-raw-reader:" + reader.error)
        result["lastLiveCompleteOwnSample"] = complete_live_sample()
        samples += 1
        time.sleep(0.02)
    code = process.wait(timeout=core.remaining_seconds(3))
    waited = True
    result.update({"actualGranted":True,"witnessPid":process.pid,"witnessIdentity":witness_identity,
        "witnessExitCode":code,"completeOwnSamples":samples})
    if code != 0:
        core.fail("witness-nonzero-exit:" + str(code))
    witness = shared.read("witness-result.json")
    parent = shared.read("controller-parent-result.json")
    controller = shared.read("controller/receipt.json",2 * 1024 * 1024)
    stop = witness["defaultOwnerStopAudit"]
    if witness["firstCause"] is not None or parent["firstCause"] is not None or controller["firstCause"] is not None:
        core.fail("saved-controller-or-witness-failure")
    if not parent["retainedControllerWaitReturned"] or not parent["retainedControllerPopenHandleClosed"] or not stop.get("publicStopReturned") or not stop.get("activeZeroReadoutSeen") or not stop.get("backendJobCloseReturned") or not stop.get("retainedOriginalProcessHandleCloseReturned"):
        core.fail("saved-retained-wait-drain-close-contract")
    # The duplicated handle survives original W closure for independent fresh readout.
    accounting = shared.job_accounting(job)
    if accounting["active"] != 0:
        core.fail("fresh-independent-Root-Job-not-drained")
    output_pins, sources = [], {}
    for name in ("research-result.json","result.json","pose.json"):
        path = shared.ROOT / "controller" / "job" / name
        data = core.read_metadata(path,maximum=32 * 1024 * 1024)
        value = json.loads(data)
        if not isinstance(value,dict):
            core.fail("fresh-saved-output-not-object")
        if name != "research-result.json":
            sources[name] = value["source"]
        output_pins.append({"name":name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),
            "postStat":shared.source_stat(path)})
        del data, value
    if sources["result.json"] != sources["pose.json"] or sources["result.json"].get("sha256") != core.SAMPLE_SHA:
        core.fail("fresh-saved-result-pose-source-mismatch")
    result.update({"freshIndependentPostWitnessJobAccounting":accounting,
        "freshSavedOutputPins":output_pins,"savedResultPoseSourceIdentical":True,
        "controllerPid":parent["controllerPid"],"scientificAccuracyVerified":False,
        "runtimeGrantSha256":runtime_sha,"originalGrantSha256":sys.argv[3]})
except BaseException as error:
    shared.first_cause(error)
finally:
    if process is not None:
        if core.CAUSE is not None and shared.ROOT is not None and not (shared.ROOT / "root-stop.json").exists():
            try_phase("request-default-stop",lambda: shared.save("root-stop.json",{"firstCause":core.CAUSE}))
        def retained_wait():
            global waited
            if not waited:
                try:
                    process.wait(timeout=core.remaining_seconds(10))
                    waited = True
                except BaseException as error:
                    shared.first_cause(error)
                    # Teardown still attempts termination of this retained Popen
                    # after clock/readout failure; no guessed PID is used.
                    process.terminate()
                    try:
                        timeout = core.remaining_seconds(3)
                    except BaseException as deadline_error:
                        shared.first_cause(deadline_error)
                        timeout = 0
                    process.wait(timeout=timeout)
                    waited = True
            return process.returncode
        try_phase("retained-external-witness-wait",retained_wait)
        if job is not None and waited:
            def fresh_job():
                value = shared.job_accounting(job)
                result["freshJobAfterRetainedWitnessWait"] = value
                if value["active"] != 0:
                    core.fail("post-witness-Root-Job-active")
            try_phase("fresh-Job-after-retained-wait",fresh_job)
        if meter is not None and waited:
            # Retrospective peak unavailability does not erase live failure,
            # and does not manufacture a target failure or complete maximum.
            result["postExitWitnessMemoryOrUnknown"] = try_phase("retrospective-memory-observation",lambda: independent_memory(int(process._handle)))
            result["freshNamedWitnessIdentityAfterRetainedWait"] = try_phase(
                "retained-named-witness-identity",lambda: meter.identity(int(process._handle),process.pid))
            result["retainedNamedWitnessSignaled"] = try_phase("retained-named-witness-signal",
                lambda: meter.kernel.WaitForSingleObject(int(process._handle),0) == 0)
            if result["retainedNamedWitnessSignaled"] is not True:
                shared.first_cause(RuntimeError("named-witness-retained-wait-not-signaled"))
        if dup_handle is not None:
            def close_root_job():
                global dup_handle
                handle, dup_handle = dup_handle, None
                if not meter.kernel.CloseHandle(handle):
                    core.fail("Root-duplicate-Job-handle-close")
                result["independentRootJobHandleClosed"] = True
            try_phase("Root-duplicate-Job-close",close_root_job)
        if meter is not None:
            final = try_phase("fresh-retained-member-waits",meter.finish_and_close)
            result["independentNamedMemberWaitsAndObservations"] = final
            if final is not None and final["cleanupFailures"]:
                shared.first_cause(RuntimeError(str(final["cleanupFailures"])))
        if reader is not None:
            def finish_reader():
                reader.join(core.remaining_seconds(2))
                if reader.is_alive() or reader.error:
                    core.fail("Root-witness-reader-unjoined-or-error")
                process.stdout.close()
                result["rawWitnessReaderJoinedAndStdoutClosed"] = True
            try_phase("raw-witness-reader-join",finish_reader)
        if waited:
            def close_witness():
                global process_handle_closed
                shared.close_popen_handle(process)
                process_handle_closed = True
            try_phase("original-witness-Popen-handle-close",close_witness)
    try:
        core.clock()
        if meter is not None:
            final_parent_memory = meter.memory(meter.parent_handle)
            if final_parent_memory["workingSetBytes"] > core.CAPS["rss"]:
                core.fail("final-current-Root-entry-resident-cap")
            result["finalCurrentRootEntryMemory"] = final_parent_memory
        if shared.ROOT is not None:
            result.update({"firstCause":core.CAUSE,"status":"COMPLETED_PENDING_ROOT_ACCEPTANCE" if core.CAUSE is None else "FAILED",
                "retainedExternalWitnessWaitReturned":waited,"witnessPopenHandleClosed":process_handle_closed,
                "originQpcTicksDecimal":None if core.ORIGIN_QPC is None else str(core.ORIGIN_QPC),
                "qpcFrequencyDecimal":None if core.QPC_FREQUENCY is None else str(core.QPC_FREQUENCY),
                "wholeDeadlineQpcTicksDecimal":None if core.WHOLE_QPC is None else str(core.WHOLE_QPC),
                "elapsedNs":core.elapsed_ns_or_unknown(),"finalStorageSnapshot":shared.storage_snapshot(),
                "rawLogSnapshot":shared.log_guard(),"RootEntryFinalPeakAndItsCIParentWaitVerified":False,
                "aggregatePhysicalMaximumResidentBytes":None,"completeHistoricalPopulationVerified":False,
                "retryAllowed":False,"releaseAccepted":False})
            shared.save("root-physical-result.json",result)
            shared.emit({"status":result["status"],"firstCause":core.CAUSE,"physicalResult":"root-physical-result.json"})
    except BaseException as error:
        shared.first_cause(error)
        sys.stderr.write("FAIL-CLOSED:" + str(core.CAUSE)[:512] + "\n")
raise SystemExit(0 if core.CAUSE is None else 1)
