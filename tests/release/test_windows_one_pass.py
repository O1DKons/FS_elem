"""Prepared affected cases only; no execution authorized by Source preparation."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest import mock
import test_windows_first_run as fixture

first = fixture.first
SCRIPTS = fixture.SCRIPTS


class OnePassAdmissionTests(unittest.TestCase):
    setUp = fixture.FirstRunTests.setUp

    def prepared(self):
        first.bootstrap(self.root, self.events.append)
        return json.loads((self.root / first.RECEIPT).read_text('utf-8'))

    def write_state(self, state):
        (self.root / first.RECEIPT).write_text(json.dumps(state), encoding='utf-8')

    def node_observation(self, expected_names):
        node = os.environ.get('FS_ELEM_TEST_NODE') or shutil.which('node')
        if not node:
            self.skipTest('Explicit Node test executable unavailable')
        program = """
import fs from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
import {resolve} from 'node:path';
const [root,checker,namesJson]=process.argv.slice(1);
const paths=new Map(JSON.parse(namesJson).map(name=>[resolve(root,name),name]));
const original=fs.realpathSync;
const scanned=[];
function observed(file,...args){
  const value=original.call(this,file,...args);
  if (paths.has(String(file))) scanned.push(paths.get(String(file)));
  return value;
}
observed.native=original.native;
fs.realpathSync=observed;
syncBuiltinESMExports();
const {requireDesktopReady}=await import(checker);
let accepted=false,message=null;
try {requireDesktopReady(root);accepted=true;} catch(error) {message=String(error.message);}
console.log(JSON.stringify({accepted,message,scanned}));
"""
        result = subprocess.run([node, '--input-type=module', '-e', program, str(self.root),
            (SCRIPTS / 'windows-bundle.mjs').as_uri(), json.dumps(expected_names)],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def malformed_states(self, state):
        variants = {}
        bad = copy.deepcopy(state)
        bad['files'][0]['path'] = 'unknown-file.bin'
        variants['same_count_unknown'] = bad
        bad = copy.deepcopy(state)
        bad['files'].pop()
        variants['missing_expected'] = bad
        bad = copy.deepcopy(state)
        bad['files'][-1] = copy.deepcopy(bad['files'][0])
        variants['exact_duplicate'] = bad
        bad = copy.deepcopy(state)
        bad['files'][-1] = copy.deepcopy(bad['files'][0])
        bad['files'][-1]['path'] = bad['files'][-1]['path'].upper()
        variants['casefold_duplicate'] = bad
        bad = copy.deepcopy(state)
        bad['files'][0]['sha256'] = '0' * 64
        variants['wrong_digest'] = bad
        bad = copy.deepcopy(state)
        bad['files'][0].pop('sha256')
        variants['absent_digest'] = bad
        bad = copy.deepcopy(state)
        bad['bundleSha256'] = '0' * 64
        variants['wrong_bundle_binding'] = bad
        return variants

    def test_valid_inventory_has_one_complete_fresh_scan_per_process(self):
        state = self.prepared()
        names = [row['path'] for row in state['files']]
        scanned = []
        original = first.relative_file
        def observe(root, name, *args, **kwargs):
            value = original(root, name, *args, **kwargs)
            scanned.append(name)
            return value
        with mock.patch.object(first, 'relative_file', side_effect=observe):
            self.assertTrue(first.cached_ready(self.root))
        self.assertCountEqual(scanned, names)
        self.assertEqual(len(scanned), len(names))
        node = self.node_observation(names)
        self.assertTrue(node['accepted'], node['message'])
        self.assertCountEqual(node['scanned'], names)
        self.assertEqual(len(node['scanned']), len(names))

    def test_bad_receipt_composition_rejected_before_python_physical_scan(self):
        state = self.prepared()
        for label, bad in self.malformed_states(state).items():
            with self.subTest(label=label):
                self.write_state(bad)
                with mock.patch.object(first, 'relative_file', wraps=first.relative_file) as path_scan, \
                        mock.patch.object(first, 'fingerprint', wraps=first.fingerprint) as stat_scan:
                    self.assertFalse(first.cached_ready(self.root))
                    path_scan.assert_not_called()
                    stat_scan.assert_not_called()

    def test_bad_receipt_composition_rejected_before_node_physical_scan(self):
        state = self.prepared()
        names = [row['path'] for row in state['files']]
        for label, bad in self.malformed_states(state).items():
            with self.subTest(label=label):
                self.write_state(bad)
                node = self.node_observation(names)
                self.assertFalse(node['accepted'])
                self.assertEqual(node['scanned'], [])
                expected = ('Desktop bundle/ready binding changed' if label == 'wrong_bundle_binding'
                    else 'Changed ready checksum binding' if label in ('wrong_digest', 'absent_digest')
                    else 'Incomplete ready receipt')
                self.assertIn(expected, node['message'])

    def test_authoritative_inventory_digest_cannot_be_replaced_by_current_receipt(self):
        state = self.prepared()
        names = [row['path'] for row in state['files']]
        bundle = copy.deepcopy(self.bundle)
        bundle['files'][0]['sha256'] = '0' * 64
        body = json.dumps(bundle).encode('utf-8')
        (self.root / first.BUNDLE).write_bytes(body)
        state['bundleSha256'] = fixture.digest(body)
        self.write_state(state)
        with mock.patch.object(first, 'relative_file', wraps=first.relative_file) as scan:
            self.assertFalse(first.cached_ready(self.root))
            scan.assert_not_called()
        node = self.node_observation(names)
        self.assertFalse(node['accepted'])
        self.assertEqual(node['scanned'], [])
        self.assertIn('Changed ready checksum binding', node['message'])

    def test_node_rejects_model_mutation_after_python_admission(self):
        state = self.prepared()
        names = [row['path'] for row in state['files']]
        self.assertTrue(first.cached_ready(self.root))
        (self.root / self.model['path']).write_bytes(b'changed')
        node = self.node_observation(names)
        self.assertFalse(node['accepted'])
        self.assertIn('Ready file changed: ' + self.model['path'], node['message'])


if __name__ == '__main__':
    unittest.main()
