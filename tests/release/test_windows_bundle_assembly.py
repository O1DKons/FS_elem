import importlib.util
import pathlib
import shutil
import tempfile
import unittest
import zipfile

SOURCE = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "prepare-windows-bundle.py"


class BundleAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        try:
            spec = importlib.util.spec_from_file_location("windows_bundle_assembly", SOURCE)
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        except FileNotFoundError:
            self.fail("Portable Windows bundle assembly is not implemented yet")

    def archive(self, values):
        p = self.root / "runtime.zip"
        with zipfile.ZipFile(p, "w") as z:
            for name, data in values.items():
                z.writestr(name, data)
        return p

    def test_archive_cannot_write_outside_payload(self):
        archive = self.archive({"../escape.exe": b"bad"})
        with self.assertRaises(ValueError):
            self.module.extract_zip(archive, self.root / "payload")
        self.assertFalse((self.root / "escape.exe").exists())

    def test_existing_payload_file_is_not_overwritten(self):
        dest = self.root / "payload"
        dest.mkdir()
        (dest / "python.exe").write_bytes(b"original")
        archive = self.archive({"python.exe": b"replacement"})
        with self.assertRaises(ValueError):
            self.module.extract_zip(archive, dest)
        self.assertEqual((dest / "python.exe").read_bytes(), b"original")

    def test_embedded_python_keeps_all_search_paths_after_relocation(self):
        archive = self.archive({"python.exe": b"PE-fixture",
                                "python312.dll": b"DLL-fixture",
                                "python312.zip": b"stdlib-fixture",
                                "python312._pth": b"builder-specific-path"})
        app = self.root / "old" / "app"
        (app / "scripts").mkdir(parents=True)
        site = self.root / "site"
        site.mkdir()
        (site / "package.py").write_text("value = 1")
        env = app / ".runtime" / "venv-science"
        self.module.assemble_python(archive, site, env, "3.12")
        shutil.move(str(app), str(self.root / "relocated"))
        relocated = self.root / "relocated"
        scripts = relocated / ".runtime" / "venv-science" / "Scripts"
        entries = (scripts / "python312._pth").read_text().splitlines()
        paths = [line for line in entries if line and not line.startswith("#") and not line.startswith("import ")]
        self.assertTrue(paths)
        for value in paths:
            self.assertFalse(pathlib.Path(value).is_absolute())
            self.assertTrue((scripts / value).exists(), value)
        self.assertTrue((scripts / "../Lib/site-packages/package.py").is_file())
        self.assertFalse((scripts.parent / "pyvenv.cfg").exists())

    def test_inventory_rejects_external_symlink(self):
        app = self.root / "app"
        app.mkdir()
        external = self.root / "external"
        external.write_bytes(b"secret")
        (app / "leak").symlink_to(external)
        with self.assertRaises(ValueError):
            self.module.inventory(app)


if __name__ == "__main__":
    unittest.main()

