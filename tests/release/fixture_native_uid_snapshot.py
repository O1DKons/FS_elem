#!/usr/bin/env python3
"""Prepared PURE fake-API tests. No CDLL/API/native execution; Root must grant imports/tests separately."""
import argparse
import ctypes
import errno
import importlib.util
import os
import sys
import unittest


class FakeProc:
    def __init__(self, returned_bytes=None):
        self.returned_bytes = returned_bytes
        self.calls = []
        self.pids = [os.getpid(), 1000007, 1000008]

    def proc_listallpids(self, *args):
        raise AssertionError("foreign/all-PID enumeration must not be called")

    def proc_listpids(self, kind, uid, buffer, capacity):
        self.calls.append((kind, uid, capacity))
        if kind != 4 or uid != os.getuid():
            raise AssertionError("must enumerate every current-UID process using official selector4")
        for index, pid in enumerate(self.pids):
            buffer[index] = pid
        return len(self.pids) * ctypes.sizeof(ctypes.c_int) if self.returned_bytes is None else self.returned_bytes

    def proc_pidinfo(self, pid, flavor, arg, buffer, capacity):
        ctypes.set_errno(errno.EPERM)
        return 0


class OwnUIDSnapshotTests(unittest.TestCase):
    def fake_native(self, returned_bytes=None):
        native = MODULE.Native.__new__(MODULE.Native)  # Bypass actual native library admission.
        native.proc = FakeProc(returned_bytes)
        return native

    def test_uid_only_keeps_all_returned_own_generations(self):
        native = self.fake_native()
        rows = [{"pid": pid, "uid": os.getuid(), "ppid": os.getpid(), "pgid": pid,
                 "creationSeconds": str(900 + index), "creationMicroseconds": str(70 + index)}
                for index, pid in enumerate(native.proc.pids)]
        by_pid = {row["pid"]: row for row in rows}
        seen = []
        def identity(pid):
            seen.append(pid)
            return by_pid[pid]
        native.identity = identity
        self.assertEqual(native.snapshot(), rows)
        self.assertEqual(seen, native.proc.pids)
        self.assertEqual(native.proc.calls, [(4, os.getuid(), ctypes.sizeof(ctypes.c_int) * 4096)])

    def test_invalid_or_full_byte_count_remains_fail_closed(self):
        for value in (0, -1, 2, ctypes.sizeof(ctypes.c_int) * 4096):
            with self.subTest(value=value):
                native = self.fake_native(value)
                native.identity = lambda pid: {"pid": pid, "uid": os.getuid()}
                with self.assertRaisesRegex(RuntimeError, "OWN UID process snapshot"):
                    native.snapshot()

    def test_unreadable_own_identity_keeps_errno_and_rejects(self):
        native = self.fake_native()
        with self.assertRaises(RuntimeError) as caught:
            native.identity(31337)
        for fragment in ("process identity unreadable", "pid=31337", "errno=" + str(errno.EPERM),
                         "flavor=3", "requestedBytes=136", "returned=0"):
            self.assertIn(fragment, str(caught.exception))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checker", required=True)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("source_admitted_checker_fixture", args.checker)
    MODULE = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MODULE)  # Target import only in a separately granted PURE run.
    unittest.main(argv=[sys.argv[0]])
