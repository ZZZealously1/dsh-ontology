"""Source-snapshot preservation and refusal contracts; no ontology execution."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "sync-ontology.py"


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("sync_ontology", SCRIPT)
        self.sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sync)
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("ONTOLOGY_TEST_OUTPUT"))
        self.root = Path(self.temp.name)
        self.sync.ROOT = self.root / "plugin"
        self.sync.ROOT.mkdir()
        self.sync.TARGET = self.sync.ROOT / "Ontology"
        self.sync.MANIFEST = self.sync.ROOT / "source-manifest.sha256"
        self.source = self.root / "upstream" / "Ontology"
        for relative in self.sync.REQUIRED:
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("source: " + relative).encode())

    def tearDown(self):
        self.temp.cleanup()

    def digests(self, path, **options):
        return {p: digest for p, (_, digest) in self.sync.inventory(path, **options).items()}

    def test_import_preserves_bytes_and_excludes_runtime_history(self):
        for relative in ("__pycache__/cache.pyc", ".venv/runtime.txt", "outputs/run.txt", "history/old.txt"):
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"not a distribution input")
        self.sync.import_once(self.source)
        self.assertEqual(self.sync.recorded(), self.digests(self.source))
        self.assertEqual(self.sync.recorded(), self.digests(self.sync.TARGET, source_filter=False))
        self.assertFalse((self.sync.TARGET / "outputs").exists())
        self.assertFalse((self.sync.TARGET / "__pycache__").exists())

    def test_existing_copy_is_never_overwritten(self):
        self.sync.import_once(self.source)
        target = self.sync.TARGET / "README.md"
        target.write_bytes(b"user modification")
        manifest = self.sync.MANIFEST.read_bytes()
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.sync.import_once(self.source)
        self.assertEqual(target.read_bytes(), b"user modification")
        self.assertEqual(self.sync.MANIFEST.read_bytes(), manifest)

    def test_changed_source_and_copy_are_detected_without_rewriting(self):
        self.sync.import_once(self.source)
        original_manifest = self.sync.MANIFEST.read_bytes()
        (self.source / "README.md").write_bytes(b"new upstream content")
        with self.assertRaisesRegex(ValueError, "differs"):
            self.sync.compare(self.sync.recorded(), self.digests(self.source), "Upstream")
        (self.sync.TARGET / "README.md").write_bytes(b"copy modification")
        with self.assertRaisesRegex(ValueError, "differs"):
            self.sync.compare(self.sync.recorded(), self.digests(self.sync.TARGET), "Copy")
        self.assertEqual(self.sync.MANIFEST.read_bytes(), original_manifest)

    def test_bundled_outputs_are_detected_as_unexpected_files(self):
        self.sync.import_once(self.source)
        output = self.sync.TARGET / "outputs" / "private-run.txt"
        output.parent.mkdir()
        output.write_text("must not ship", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "added=.*outputs/private-run.txt"):
            self.sync.compare(self.sync.recorded(), self.digests(self.sync.TARGET, source_filter=False), "Copy")

    def test_invalid_or_duplicate_manifest_paths_are_rejected(self):
        for name in ("../outside", "C:/outside", "a\\b", "/absolute", "a/./b"):
            self.sync.MANIFEST.write_text("a" * 64 + "  " + name + "\n", encoding="utf-8")
            with self.subTest(path=name), self.assertRaises(ValueError):
                self.sync.recorded()
        row = "a" * 64 + "  README.md\n"
        self.sync.MANIFEST.write_text(row + row, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.sync.recorded()


if __name__ == "__main__":
    unittest.main()
