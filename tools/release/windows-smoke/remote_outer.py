"""SOURCE ONLY: contained parent retaining the direct controller Popen."""
import subprocess
import sys
import time
import importlib.util
from pathlib import Path
_spec = importlib.util.spec_from_file_location("_fs_elem_remote_support", Path(__file__).resolve().with_name("remote_support.py"))
shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = shared
_spec.loader.exec_module(shared)
core = shared.core
process = reader = None
waited = closed = joined = False
result = {"releaseAccepted":False,"actualGranted":False}
try:
    grant, gate, package, origin, frequency = shared.arguments()
    while not (shared.ROOT / "root-retained.json").exists():
        shared.guard()
        time.sleep(0.02)
    retained = shared.read("root-retained.json")
    if retained["runtimeGrantSha256"] != sys.argv[3] or retained["originQpcTicksDecimal"] != origin:
        core.fail("Root-retained-Job-ack-mismatch")
    shared.guard()
    argv = shared.runtime_argv("windows_nn_operator.py",sys.argv[3],package,origin,frequency,
        shared.ROOT / "controller")
    process = subprocess.Popen(argv,cwd=package,env=shared.environment(),
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=-1)
    shared.save("controller-parent-entry.json",{"controllerPid":process.pid,"originQpcTicksDecimal":origin,
        "qpcFrequencyDecimal":frequency,"runtimeGrantSha256":sys.argv[3]})
    reader = shared.RawReader(process.stdout,"controller-raw.bin")
    # Preserve raw controller output for the external supervisor, without decoding.
    def forward():
        try:
            import sys
            while True:
                raw = process.stdout.read1(8192)
                if not raw:
                    return
                reader.count += len(raw)
                if reader.count > 16384:
                    reader.error = "controller-diagnostic-cap"
                    return
                sys.stdout.buffer.write(raw)
                sys.stdout.buffer.flush()
        except BaseException as error:
            reader.error = str(error)
    reader.thread = shared.threading.Thread(target=forward,daemon=True)
    reader.start()
    while process.poll() is None:
        shared.guard()
        if reader.error:
            core.fail(reader.error)
        time.sleep(0.02)
    code = process.wait(timeout=core.remaining_seconds(3))
    waited = True
    result.update({"actualGranted":True,"controllerPid":process.pid,"controllerExitCode":code})
    if code != 0:
        core.fail("controller-nonzero-exit:" + str(code))
except BaseException as error:
    shared.first_cause(error)
finally:
    if process is not None:
        try:
            if not waited:
                try:
                    process.wait(timeout=core.remaining_seconds(6))
                    waited = True
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=core.remaining_seconds(3))
                    waited = True
        except BaseException as error:
            shared.first_cause(error)
        try:
            if reader is not None:
                reader.join(core.remaining_seconds(2))
                joined = not reader.is_alive()
                if not joined or reader.error:
                    core.fail("controller-raw-reader-unjoined-or-error")
            if reader is None or joined:
                process.stdout.close()
            if waited:
                shared.close_popen_handle(process)
                closed = True
        except BaseException as error:
            shared.first_cause(error)
    try:
        result.update({"firstCause":core.CAUSE,"retainedControllerWaitReturned":waited,
            "retainedControllerPopenHandleClosed":closed,"rawReaderJoined":joined,
            "controllerRawBytesRead":0 if reader is None else reader.count,
            "originQpcTicksDecimal":None if core.ORIGIN_QPC is None else str(core.ORIGIN_QPC),
            "observationalPeakOrHistoricalCensusVerified":False})
        if shared.ROOT is not None:
            result["finalCombinedStorageSnapshot"] = shared.storage_snapshot()
            shared.save("controller-parent-result.json",result)
        shared.emit({"role":"contained-controller-parent","firstCause":core.CAUSE})
    except BaseException as error:
        shared.first_cause(error)
raise SystemExit(0 if core.CAUSE is None else 1)
