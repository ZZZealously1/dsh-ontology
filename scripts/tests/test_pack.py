"""Archive fidelity, deterministic metadata and output boundary contracts."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "pack.py"


class PackTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("pack_plugin", SCRIPT)
        self.pack = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.pack)
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("ONTOLOGY_TEST_OUTPUT"))
        self.base = Path(self.temp.name)
        self.root = self.base / "plugin"
        self.root.mkdir()
        self.write("package.json", json.dumps({"files": ["Ontology", "source-manifest.sha256"]}).encode())
        self.write("README.md", b"documentation")
        native = {"Ontology-tools/.gitignore": b"__pycache__/\r\n", "model.ttl": b"@prefix : <urn:test:> .\n"}
        for name, content in native.items():
            self.write("Ontology/" + name, content)
        self.write("source-manifest.sha256", "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in native.items()).encode())

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, data):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def test_archive_preserves_dotfile_and_has_reproducible_metadata(self):
        self.write("Ontology/__pycache__/excluded.pyc", b"cache")
        resources = self.pack.collect(self.root)
        self.pack.verify_native(resources)
        first = self.pack.archive_bytes(resources)
        self.assertEqual(first, self.pack.archive_bytes(resources))
        with tarfile.open(fileobj=io.BytesIO(first), mode="r:gz") as archive:
            self.assertEqual(set(archive.getnames()), {"package/" + name for name in resources})
            self.assertEqual(archive.extractfile("package/Ontology/Ontology-tools/.gitignore").read(), b"__pycache__/\r\n")
            for member in archive:
                self.assertEqual((member.mtime, member.uid, member.gid, member.mode), (0, 0, 0, 0o644))

    def test_native_tampering_is_rejected(self):
        resources = self.pack.collect(self.root)
        resources["Ontology/model.ttl"] = b"modified"
        with self.assertRaisesRegex(ValueError, "hashes differ"):
            self.pack.verify_native(resources)

    def test_unsafe_allowlist_is_rejected(self):
        for name in ("../private", "C:/private", "nested\\private", "*", "/absolute"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.pack.checked_path(self.root, name)

    def test_output_must_be_new_and_outside_repository(self):
        with patch.object(self.pack.subprocess, "run") as command:
            with self.assertRaisesRegex(ValueError, "outside"):
                self.pack.pack(self.root, self.root / "output.tgz")
            output = self.base / "new.tgz"
            self.pack.pack(self.root, output)
            command.assert_called_once()
            before = output.read_bytes()
            with self.assertRaisesRegex(ValueError, "already exists"):
                self.pack.pack(self.root, output)
            self.assertEqual(before, output.read_bytes())

    def test_prerequisite_failure_creates_no_archive(self):
        output = self.base / "never.tgz"
        with patch.object(self.pack.subprocess, "run", side_effect=OSError("verification unavailable")):
            with self.assertRaises(OSError):
                self.pack.pack(self.root, output)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
