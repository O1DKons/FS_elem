"""Prepared narrow offline Mac fixtures only; imports/tests await Root actual scope."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("offline_mac_candidate", ROOT / "scripts/macos-first-run.py")
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)


class OfflineModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="FS_elem offline-model ")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.app, self.user = self.base/"app", self.base/"user"
        self.app.mkdir();self.user.mkdir()
        self.rows=[]
        for role in ["flight","family","nominal","yolox","rtmw"]:
            body=(role+" fixture bytes").encode()
            name="assets/models/"+role+".bin";path=self.app/name
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
            self.rows.append(dict(id=role,path=name,origin="app",sizeBytes=len(body),
                sha256=hashlib.sha256(body).hexdigest(),url="https://example.invalid/"+role))
        self.binding=dict(app=self.app,user=self.user,canonicalApp=self.app.resolve(),canonicalUser=self.user.resolve())
        models=patch.object(candidate,"MODEL_ROWS",self.rows);models.start();self.addCleanup(models.stop)
        network=patch.object(urllib.request,"urlopen",side_effect=AssertionError("No end-user HTTP"));network.start();self.addCleanup(network.stop)

    def test_complete_five_models_are_verified_from_immutable_app_only(self):
        actual=candidate.verify_offline_models(self.binding,lambda row:None,threading.Event())
        self.assertEqual(set(actual),{"flight","family","nominal","yolox","rtmw"})
        for row in self.rows:
            value=actual[row["id"]]
            self.assertEqual(value["absolutePath"],str(self.app/row["path"]))
            self.assertEqual(value["origin"],"app")
            self.assertEqual(value["sha256"],row["sha256"])
        self.assertEqual(list(self.user.iterdir()),[])

    def test_missing_app_model_cannot_be_repaired_from_legacy_cache(self):
        row=self.rows[-1];body=(self.app/row["path"]).read_bytes()
        cached=self.user/"model-cache"/row["path"];cached.parent.mkdir(parents=True);cached.write_bytes(body)
        (self.app/row["path"]).unlink()
        with self.assertRaises((OSError,ValueError)):
            candidate.verify_offline_models(self.binding,lambda value:None,threading.Event())
        self.assertFalse((self.app/row["path"]).exists())
        self.assertEqual(cached.read_bytes(),body)

    def test_corrupt_local_model_is_rejected_and_left_untouched(self):
        row=self.rows[-1];file=self.app/row["path"];bad=b"x"*row["sizeBytes"];file.write_bytes(bad)
        with self.assertRaisesRegex(ValueError,"checksum"):
            candidate.verify_offline_models(self.binding,lambda value:None,threading.Event())
        self.assertEqual(file.read_bytes(),bad)


class RootRecipeTests(unittest.TestCase):
    def fixture(self,path="runtime/pipeline/support.py"):
        key="../"+path
        expected={}
        refs={}
        for role,name,digest,size in [
            ("parent","configs/axel-release-offline-macos-arm64-parent-v026.json","1"*64,1),
            ("derived","configs/axel-release-ort4-macos-app.json","2"*64,2),
            ("modelManifest","assets/models/manifest-offline-macos-v026.json","3"*64,3)]:
            refs[role]=dict(path=name,sha256=digest,bytes=size);expected[name]=refs[role]
        row=dict(path=path,key=key,bytes=4,sha256="4"*64);expected[path]=row
        rule=dict(status="source-accepted",sourceUpdates=[row],packagingProvenance={"scope":"fixture"},**refs)
        original=dict(inputSha256={key:"0"*64},backendSourceProvenance={"runtimeHashes":{key:"0"*64},"runtimeBytes":{key:9}},
                      sampleFps=8.333333,ortThreads={"intraOpNumThreads":4,"interOpNumThreads":1},models={"flight":{"sha256":"a"*64}})
        return original,rule,expected

    def test_root_source_rebind_preserves_every_scientific_field(self):
        original,rule,expected=self.fixture();before=copy.deepcopy(original)
        candidate.validate_recipe_binding(rule,expected)
        derived=candidate.expected_derived_recipe(original,rule)
        candidate.validate_derived_recipe(original,derived,rule)
        self.assertEqual(original,before)
        for name in ["sampleFps","ortThreads","models"]:
            self.assertEqual(derived[name],before[name])
        for name,value in [("sampleFps",25),("models",{"flight":{"sha256":"b"*64}})]:
            bad=copy.deepcopy(derived);bad[name]=value
            with self.assertRaises(ValueError):
                candidate.validate_derived_recipe(original,bad,rule)

    def test_only_exact_main_owner_additions_may_extend_source_maps(self):
        original,rule,expected=self.fixture("scripts/macos-bundle.mjs")
        for table in [original["inputSha256"],original["backendSourceProvenance"]["runtimeHashes"],original["backendSourceProvenance"]["runtimeBytes"]]:
            table.clear()
        candidate.validate_recipe_binding(rule,expected)
        derived=candidate.expected_derived_recipe(original,rule)
        self.assertEqual(derived["inputSha256"]["../scripts/macos-bundle.mjs"],"4"*64)
        row=rule["sourceUpdates"][0];row["path"]="scripts/unlisted.py";row["key"]="../scripts/unlisted.py"
        expected[row["path"]]=row
        candidate.validate_recipe_binding(rule,expected)
        with self.assertRaisesRegex(ValueError,"source maps"):
            candidate.expected_derived_recipe(original,rule)


if __name__=="__main__":
    unittest.main()
