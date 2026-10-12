#!/usr/bin/env python3
"""Prepared fake-stat Source cases. Separate Root grant required for import/tests; no native API."""
import argparse
import importlib.util
import io
import pathlib
import stat
import sys
import types
import unittest
from unittest.mock import patch


class FakePath:
    def __init__(self, name, payload=b"", size=None, linked=False):
        self.name, self.payload, self.linked = name, payload, linked
        self.info = types.SimpleNamespace(st_dev=1, st_ino=2, st_mode=(stat.S_IFLNK if linked else stat.S_IFREG) | 0o644,
            st_size=len(payload) if size is None else size, st_mtime_ns=100, st_ctime_ns=101)
        self.target, self.reads = self, []
    def __str__(self): return self.name
    def __eq__(self, other): return self.name == str(other)
    def __truediv__(self, name): return FakePath(str(pathlib.PurePosixPath(self.name) / name))
    @property
    def parts(self): return pathlib.PurePosixPath(self.name).parts
    def is_absolute(self): return pathlib.PurePosixPath(self.name).is_absolute()
    def is_relative_to(self, root): return pathlib.PurePosixPath(self.name).is_relative_to(pathlib.PurePosixPath(str(root)))
    def resolve(self, strict=False): return self.target
    def lstat(self): return types.SimpleNamespace(**vars(self.info))
    def is_symlink(self): return self.linked
    def open(self, mode):
        outer = self
        class Reader(io.BytesIO):
            def read(self, size=-1):
                outer.reads.append(size)
                return super().read(size)
        return Reader(self.payload)


class SelectedSwiftInputTests(unittest.TestCase):
    def pair(self):
        developer = FakePath("/Applications/Xcode_Test.app/Contents/Developer")
        alias = FakePath(str(developer) + "/Toolchains/XcodeDefault.xctoolchain/usr/bin/swiftc", linked=True, size=14)
        target = FakePath(str(developer) + "/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift-frontend", size=700000000)
        alias.target = target
        return developer, alias, target

    def test_selected_alias_keeps_argv_path_and_only_target_gets_one_gib(self):
        developer, alias, target = self.pair()
        seen = []
        def pinned(path, end, maximum):
            seen.append((path, end, maximum))
            return {"path": str(path), "bytes": path.info.st_size, "sha256": "a"*64}
        with patch.object(MODULE, "before", lambda end: None), patch.object(MODULE, "file_pin", pinned), patch.object(MODULE.os, "readlink", lambda path: "swift-frontend"):
            value = MODULE.selected_swift_pin(alias, developer, 123)
        self.assertEqual(seen, [(target, 123, 1024**3)])
        self.assertEqual(value["path"], str(alias))
        self.assertEqual(value["resolvedTargetPath"], str(target))
        self.assertEqual(value["bytes"], 700000000)
        self.assertTrue(value["invocationAlias"]["symbolicLink"])

    def test_outside_target_and_changed_alias_remain_rejected(self):
        developer, alias, target = self.pair()
        alias.target = FakePath("/outside/swiftc")
        with patch.object(MODULE, "before", lambda end: None), patch.object(MODULE, "file_pin") as pin, patch.object(MODULE.os, "readlink", lambda path: "swift-frontend"):
            with self.assertRaisesRegex(RuntimeError, "target escaped"):
                MODULE.selected_swift_pin(alias, developer, 123)
            pin.assert_not_called()
        alias.target = target
        def changed(path, end, maximum):
            alias.info.st_ino += 1
            return {"path": str(path), "bytes": path.info.st_size, "sha256": "a"*64}
        with patch.object(MODULE, "before", lambda end: None), patch.object(MODULE, "file_pin", changed), patch.object(MODULE.os, "readlink", lambda path: "swift-frontend"):
            with self.assertRaisesRegex(RuntimeError, "alias changed"):
                MODULE.selected_swift_pin(alias, developer, 123)

    def test_generic_input_cap_is_unchanged_and_rejection_is_numeric(self):
        path = FakePath("/generic/input", size=256*1024**2 + 1)
        with patch.object(MODULE, "before", lambda end: None):
            with self.assertRaises(RuntimeError) as caught:
                MODULE.file_pin(path, 123)
        for part in ("path=/generic/input", "mode=0o100644", "regular=True", "symlink=False", "actualBytes=268435457", "capBytes=268435456"):
            self.assertIn(part, str(caught.exception))
        self.assertEqual(path.reads, [])

    def test_streamed_hash_checks_original_deadline_before_each_one_mib_read(self):
        path = FakePath("/generic/small", payload=b"x"*(2*1024**2))
        calls = []
        def horizon(end):
            calls.append(end)
            if len(calls) == 3:
                raise RuntimeError("original horizon expired")
        with patch.object(MODULE, "before", horizon):
            with self.assertRaisesRegex(RuntimeError, "original horizon expired"):
                MODULE.file_pin(path, 123)
        self.assertEqual(calls, [123, 123, 123])
        self.assertEqual(path.reads, [1024**2])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("source_admitted_host_fixture", args.host)
    MODULE = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MODULE)
    unittest.main(argv=[sys.argv[0]])
