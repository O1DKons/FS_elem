"""SOURCE ONLY: separate Root-controlled OWN Job witness around the contained parent."""
import os
import sys
import time
import importlib.util
from pathlib import Path
_spec = importlib.util.spec_from_file_location("_fs_elem_remote_support", Path(__file__).resolve().with_name("remote_support.py"))
shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = shared
_spec.loader.exec_module(shared)
core = shared.core
owned = meter = reader = None
waited = False
result = {"releaseAccepted":False,"actualGranted":False}
try:
    grant, gate, package, origin, frequency = shared.arguments()
    owner_module = shared.load_owner(package)
    meter = core.NativeReadout()
    core.METER = meter
    owned = owner_module.OwnedProcess.launch(
        shared.runtime_argv("remote_outer.py",sys.argv[4],package,origin,frequency),
        cwd=package,env=shared.environment())
    core.OWNED = owned
    core.audit_stop(owned)
    meter.attach(owned)
    reader = shared.RawReader(owned.stdout.buffer,"outer-raw.bin")
    core.READER = reader
    reader.start()
    shared.save("witness-entry.json",{"witnessPid":os.getpid(),"witnessIdentity":meter.parent_identity,
        "outerGatePid":owned.pid,"outerJobHandleDecimal":str(int(owned.job.handle)),
        "originQpcTicksDecimal":origin,"qpcFrequencyDecimal":frequency,"runtimeGrantSha256":sys.argv[4]})
    samples, last = 0, None
    while owned.poll() is None:
        shared.guard()
        shared.log_guard()
        if reader.error:
            core.fail("outer-raw-reader:" + reader.error)
        last = meter.sample()
        samples += 1
        time.sleep(0.02)
    code = owned.wait(timeout=core.remaining_seconds(3))
    waited = True
    if code != 0:
        core.fail("contained-parent-nonzero:" + str(code))
    parent = shared.read("controller-parent-result.json")
    if parent["firstCause"] is not None or not parent["retainedControllerWaitReturned"] or not parent["retainedControllerPopenHandleClosed"]:
        core.fail("independent-direct-controller-wait-or-close")
    result.update({"actualGranted":True,"controllerPid":parent["controllerPid"],"parentResult":parent,
        "outerGateExitCode":code,"samples":samples,"lastPartialResidentSample":last,
        "freshJobBeforeDefaultStop":shared.job_accounting(owned.job)})
except BaseException as error:
    shared.first_cause(error)
finally:
    try:
        # Accepted default stop, drain, retained gate wait and handle closure.
        # Audit/readout failure never replaces this cleanup with direct job close.
        core.cleanup()
    except BaseException as error:
        shared.first_cause(error)
    try:
        result.update({"firstCause":core.CAUSE,"outerGateRetainedWaitBeforeStop":waited,
            "defaultOwnerStopAudit":core.STOP_AUDIT,"nativeFinalReadout":core.RECEIPT.get("nativeFinalReadout"),
            "cleanupErrors":core.RECEIPT.get("cleanupErrors",[]),
            "partialResidentProviderExcludesExternalRootParent":True,
            "supervisorFinalPeakAndExternalParentWaitVerifiedHere":False})
        if reader is not None and (reader.is_alive() or reader.error):
            core.fail("outer-raw-reader-error-after-stop")
        result["finalCombinedStorageSnapshot"] = shared.storage_snapshot()
        shared.save("witness-result.json",result)
        shared.emit({"role":"independent-job-witness","firstCause":core.CAUSE,"result":"witness-result.json"})
    except BaseException as error:
        shared.first_cause(error)
raise SystemExit(0 if core.CAUSE is None else 1)
