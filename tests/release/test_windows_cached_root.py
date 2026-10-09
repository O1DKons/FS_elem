"""Prepared Source only; apply to a complete approved candidate before execution."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
import test_windows_first_run as fixture
SCRIPTS = fixture.SCRIPTS
first = fixture.first

class CachedRootTests(unittest.TestCase):
    setUp = fixture.FirstRunTests.setUp

    def root_alias(self):
        temporary = tempfile.TemporaryDirectory(prefix='FS_elem supplied root ')
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        alias = directory / 'installed'
        outside = directory / 'outside'
        outside.mkdir()
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest('Actual symlink fixture prohibited by host: ' + str(error))
        return alias, outside

    def test_valid_alias_then_model_mutation(self):
        first.bootstrap(self.root, self.events.append)
        alias, _ = self.root_alias()
        self.assertTrue(first.cached_ready(alias))
        (self.root / self.model['path']).write_bytes(b'changed')
        self.assertFalse(first.cached_ready(alias))

    def test_supplied_root_swap_during_fingerprint_rejected(self):
        first.bootstrap(self.root, self.events.append)
        alias, outside = self.root_alias()
        original = first.fingerprint
        swapped = []
        def fingerprint_then_swap(path):
            value = original(path)
            if not swapped:
                alias.unlink()
                alias.symlink_to(outside, target_is_directory=True)
                swapped.append(True)
            return value
        with mock.patch.object(first, 'fingerprint', side_effect=fingerprint_then_swap):
            self.assertFalse(first.cached_ready(alias))
        self.assertEqual(swapped, [True])

    def test_path_through_outside_parent_alias_rejected(self):
        _, outside = self.root_alias()
        (outside / 'file.txt').write_bytes(b'outside')
        parent = self.root / 'outside-parent'
        parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(first.setup.SetupError):
            first.relative_file(self.root, 'outside-parent/file.txt', self.root.resolve())

    def test_node_supplied_root_swap_after_receipt_read_rejected(self):
        node = os.environ.get('FS_ELEM_TEST_NODE') or shutil.which('node')
        if not node:
            self.skipTest('Explicit Node executable unavailable')
        first.bootstrap(self.root, self.events.append)
        alias, outside = self.root_alias()
        first_inventory_path = self.bundle['files'][0]['path']
        outside_file = outside / first_inventory_path
        outside_file.parent.mkdir(parents=True, exist_ok=True)
        outside_file.write_bytes((self.root / first_inventory_path).read_bytes())
        program = """
import fs from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
import {join} from 'node:path';
const [root,outside,checker]=process.argv.slice(1);
const original=fs.readFileSync;
const modelFile=join(root,'assets/models/manifest-release-v1.json');
let swapped=false;
let modelReads=0;
fs.readFileSync=function(file,...args){
  const body=original.call(this,file,...args);
  if (String(file)===modelFile) {
    modelReads+=1;
    // First read parses the manifest. Second returns its final preliminary hash body.
    if (modelReads===2 && !swapped) {
      fs.unlinkSync(root);
      fs.symlinkSync(outside,root,'dir');
      swapped=true;
    }
  }
  return body;
};
syncBuiltinESMExports();
const {requireDesktopReady}=await import(checker);
let message=null;
try {requireDesktopReady(root);} catch(error) {message=String(error.message);}
const expected='Bundle file escapes installed application';
const accepted=swapped && modelReads===2 && message!==null && message.includes(expected);
console.log(JSON.stringify({swapped,modelReads,message,accepted}));
if (!accepted) process.exitCode=1;
"""
        result = subprocess.run([node, '--input-type=module', '-e', program,
            str(alias), str(outside), (SCRIPTS / 'windows-bundle.mjs').as_uri()],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        observation = json.loads(result.stdout)
        self.assertTrue(observation['swapped'])
        self.assertEqual(observation['modelReads'], 2)
        self.assertIn('Bundle file escapes installed application', observation['message'])


if __name__ == '__main__':
    unittest.main()
