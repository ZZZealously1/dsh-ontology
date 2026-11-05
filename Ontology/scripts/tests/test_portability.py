"""Exercise current-library checks on isolated, minimal fixtures."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "check_portability.py"
SPEC = importlib.util.spec_from_file_location("check_portability", SCRIPT)
PORTABILITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PORTABILITY)
SKILL = "---\nname: example\ndescription: Model an example ontology.\n---\n"


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ontology-current-library-")
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name)
        self.root = self.parent / "Ontology"
        for relative in PORTABILITY.REQUIRED_FILES:
            self.write(relative, SKILL if relative.endswith("SKILL.md") else "")
        for name in PORTABILITY.ACTIVE_SKILLS:
            self.write(f"skills/{name}/SKILL.md", SKILL.replace("example", name, 1))

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def failures(self):
        return [row for row in PORTABILITY.check(self.root) if row[2] == "failed"]

    def assert_failed(self, kind, detail=None):
        failures = [row for row in self.failures() if row[0] == kind
                    and (detail is None or detail in row[3])]
        self.assertTrue(failures, f"Expected rejection: {kind}, {detail}")

    def test_self_contained_library_needs_no_external_material(self):
        self.write("README.md", "[rules](common_rules.md#section)\n")
        self.assertEqual([], self.failures())
        # Neighboring files, even invalid ones, are outside this check's scope.
        (self.parent / "old_notes.py").write_text("invalid python {", encoding="utf-8")
        self.assertEqual([], self.failures())

    def test_missing_and_extra_method_entrypoints(self):
        (self.root / "skills/ontology-execution/SKILL.md").unlink()
        self.assert_failed("active-methods", "ontology-execution")
        self.write("skills/ontology-execution/SKILL.md", SKILL)
        self.write("skills/extra/SKILL.md", SKILL)
        self.assert_failed("active-methods", "extra")

    def test_missing_required_runtime(self):
        (self.root / "Ontology-tools/ontology_tools/__main__.py").unlink()
        self.assert_failed("required-file")

    def test_valid_link_forms_and_code_examples(self):
        self.write("references/a (b).md", "")
        self.write("README.md", """
[ordinary](common_rules.md "title")
![asset](references/a%20%28b%29.md)
[angle](<references/a (b).md>)
[parentheses](references/a%20(b).md)
[reference][rules]
[rules]: common_rules.md
[external](https://example.org/missing.md)
[anchor](#within-this-document)
`[example](missing.md)`
```markdown
[example](missing.md)
```
""")
        self.assertEqual([], self.failures())

    def test_missing_inline_and_reference_targets(self):
        for content in ("[missing](absent.md)", "[reference]: absent.md"):
            with self.subTest(content=content):
                self.write("README.md", content)
                self.assert_failed("local-link")

    def test_external_local_links_are_rejected(self):
        (self.parent / "outside.md").write_text("outside", encoding="utf-8")
        for link in ("../outside.md", "%2e%2e/outside.md", "/outside.md",
                     "C:/outside.md", "file:///C:/outside.md", "%2Foutside.md",
                     "references\\outside.md"):
            with self.subTest(link=link):
                self.write("README.md", f"[outside]({link})")
                self.assert_failed("local-link")

    def test_broken_markdown_link_is_reported(self):
        self.write("README.md", "[broken](unfinished")
        self.assert_failed("markdown", "Unclosed Markdown link")

    def test_directory_link_cannot_make_the_check_scan_external_files(self):
        outside = self.parent / "external"
        outside.mkdir()
        (outside / "bad.py").write_text("not python {", encoding="utf-8")
        try:
            (self.root / "external").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Directory symlink unavailable: {error}")
        failures = self.failures()
        self.assertTrue(any(row[0] == "local-files" for row in failures))
        self.assertFalse(any(row[0] == "python-syntax" for row in failures))

    def test_invalid_skill_frontmatter_is_reported(self):
        for content in ("# No metadata", "---\nname: bad name\ndescription: d\n---\n",
                        "---\nname: valid\n---\n",
                        '---\nname: valid\ndescription: ""\n---\n',
                        "---\nname: valid\ndescription: |\n---\n"):
            with self.subTest(content=content):
                self.write("skills/ontology-builder/SKILL.md", content)
                self.assert_failed("markdown")

    def test_multiline_description(self):
        self.write("skills/ontology-builder/SKILL.md",
                   "---\nname: ontology-builder\ndescription: >\n"
                   "  Build an ontology from supplied business material.\n---\n")
        self.assertEqual([], self.failures())

    def test_invalid_python_is_reported_without_execution(self):
        self.write("scripts/invalid.py", "def missing_colon()\n    pass\n")
        self.assert_failed("python-syntax")
        self.write("scripts/invalid.py", "raise RuntimeError('must not execute')\n")
        self.assertEqual([], self.failures())

    def test_json_is_rejected(self):
        self.write("nested/unwanted.JSON", "{}")
        self.assert_failed("format", "unwanted.JSON")

    def test_report_must_be_new_and_outside_library(self):
        for path in (self.root / "report.tsv", self.root / "README.md"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                PORTABILITY.report_path(self.root, path)
        existing = self.parent / "existing.tsv"
        existing.write_text("keep", encoding="utf-8")
        with self.assertRaises(ValueError):
            PORTABILITY.report_path(self.root, existing)
        self.assertEqual("keep", existing.read_text(encoding="utf-8"))
        fresh = self.parent / "fresh.tsv"
        self.assertEqual(fresh, PORTABILITY.report_path(self.root, fresh))
        self.assertFalse(fresh.exists())


if __name__ == "__main__":
    unittest.main()
