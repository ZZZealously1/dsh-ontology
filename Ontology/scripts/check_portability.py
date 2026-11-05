"""Check the current library's local files and links, without running inference."""
from __future__ import annotations

import argparse
import ast
import csv
import io
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_SKILLS = (
    "ontology-builder", "business-ontology-design", "ontology-construction",
    "ontology-inference-design", "ontology-validation", "ontology-execution",
    "gbt-ontology-modeling", "ontology-fusion", "ontology-migration",
)
REQUIRED_FILES = (
    "README.md", "AGENTS.md", "common_rules.md", "CONTRACT.md",
    "references/modeling-principles.md", "references/domain-organization.md",
    "references/owl-swrl/index.md",
    "Ontology-tools/SKILL.md", "Ontology-tools/README.md",
    "Ontology-tools/PROFILE.md", "Ontology-tools/OWL-DL.md",
    "Ontology-tools/requirements.txt", "Ontology-tools/requirements.lock.txt",
    "Ontology-tools/ontology_tools/__main__.py",
    "Ontology-tools/ontology_tools/core.py", "Ontology-tools/ontology_tools/backend.py",
    "Ontology-tools/ontology_tools/owl_dl.py", "Ontology-tools/java/build.py",
    "Ontology-tools/java/manifest.sha256", "Ontology-tools/vendor/owl-dl/manifest.sha256",
    "templates/README.md", "templates/project-design.md",
    "templates/domain-doc.md", "templates/runtime-SKILL.md", "templates/acceptance.md",
    "templates/ontology/README.md", "templates/ontology/integration/load-plan.ttl",
    "templates/ontology/scripts/build_integration.py",
    "templates/rag-build/README.md", "templates/rag-build/scripts/build_ontology.py",
    "templates/rag-build/scripts/prepare_rule_tests.py",
    "skills/ontology-builder/references/document-route.md",
    "skills/ontology-builder/references/rag-route.md",
    "skills/ontology-builder/references/full-domain-document.md",
    "skills/ontology-fusion/scripts/fuse_local.py",
    "skills/ontology-migration/scripts/local_graph.py",
)
FORBIDDEN_SUFFIXES = {".json", ".json5", ".jsonl", ".ndjson"}
INLINE_LINK = re.compile(r"(?<!\\)\[[^\]\n]*\]\(")
REFERENCE_LINK = re.compile(r"^ {0,3}\[[^\]\n]+\]:[ \t]*(.+)$", re.MULTILINE)


def prose_only(text: str) -> str:
    """Mask code examples while preserving line numbers for diagnostics."""
    output, fence = [], None
    for line in text.splitlines(keepends=True):
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence:
            if re.match(r"^ {0,3}" + re.escape(fence[0]) + "{" + str(len(fence))
                        + r",}\s*$", line):
                fence = None
            output.append("".join("\n" if char == "\n" else " " for char in line))
        elif opening:
            fence = opening.group(1)
            output.append("".join("\n" if char == "\n" else " " for char in line))
        else:
            output.append(line)
    return re.sub(r"(`+)(.+?)\1", lambda match: " " * len(match.group()),
                  "".join(output))


def destination(raw: str) -> str:
    """Read an angle-delimited or bare Markdown destination (optional title)."""
    raw = raw.lstrip()
    if raw.startswith("<"):
        end = raw.find(">")
        if end < 0:
            raise ValueError("Unclosed angle-delimited link")
        return raw[1:end]
    return re.split(r"\s", raw, maxsplit=1)[0]


def markdown_links(text: str):
    """Yield inline/image and reference-definition destinations, with line numbers.

    This is a local file-link check, not a full Markdown renderer. URL requests
    and heading-anchor validation are deliberately outside its scope.
    """
    prose = prose_only(text)
    for match in INLINE_LINK.finditer(prose):
        start, index, depth = match.end(), match.end(), 1
        angled = index < len(prose) and prose[index] == "<"
        while index < len(prose) and depth:
            char = prose[index]
            if char == "\\":
                index += 2
                continue
            if angled:
                angled = char != ">"
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            index += 1
        if depth:
            raise ValueError(f"Unclosed Markdown link at line "
                             f"{prose.count(chr(10), 0, match.start()) + 1}")
        yield prose.count("\n", 0, match.start()) + 1, destination(prose[start:index - 1])
    for match in REFERENCE_LINK.finditer(prose):
        yield prose.count("\n", 0, match.start()) + 1, destination(match.group(1))


def local_target(root: Path, document: Path, link: str) -> Path | None:
    """Resolve local links without visiting any target outside this library."""
    if re.match(r"^[A-Za-z]:", link) or link.startswith(("/", "\\")):
        raise ValueError(f"Absolute local link is not portable: {link}")
    parsed = urlsplit(link)
    if parsed.scheme:
        if parsed.scheme.lower() == "file":
            raise ValueError(f"Absolute local link is not portable: {link}")
        return None  # External URL; never request it.
    relative = unquote(parsed.path)
    if not relative:
        return None  # Same-document fragment; anchors are not checked.
    if (relative.startswith(("/", "\\")) or "\\" in relative
            or re.match(r"^[A-Za-z]:", relative)):
        raise ValueError(f"Nonportable local path: {link}")
    path = (document.parent / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Local link leaves the library: {link}")
    return path


def skill_metadata(text: str) -> str:
    """Check required simple frontmatter fields without a YAML dependency."""
    match = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|$)", text, re.DOTALL)
    if not match:
        raise ValueError("Missing YAML frontmatter")
    header = match.group(1)
    name = re.search(r"^name:\s*([a-z0-9-]{1,64})\s*$", header, re.MULTILINE)
    if not name:
        raise ValueError("Missing or invalid skill name")
    description = re.search(r"^description:[ \t]*(.*)$", header, re.MULTILINE)
    if not description or not description.group(1).strip(" \t'\""):
        raise ValueError("Missing skill description")
    if description.group(1).strip() in {"|", ">", "|-", ">-"}:
        if not re.match(r"\n[ \t]+\S", header[description.end():]):
            raise ValueError("Empty multiline skill description")
    return name.group(1)


def check(root: Path = ROOT):
    root = root.resolve()
    results = []

    def record(kind, item, ok, detail):
        results.append((kind, item, "passed" if ok else "failed", detail))

    files = []
    for directory, children, names in os.walk(root, followlinks=False):
        # Prune escaped directory links/junctions before os.walk visits them.
        for name in children[:]:
            path = Path(directory) / name
            is_link = path.is_symlink() or getattr(path, "is_junction", lambda: False)()
            if is_link or not path.resolve().is_relative_to(root):
                children.remove(name)
                record("local-files", path.relative_to(root).as_posix(), False,
                       "Directory links/junctions are not portable library files")
        for name in names:
            path = Path(directory) / name
            if not path.resolve().is_relative_to(root):
                record("local-files", path.relative_to(root).as_posix(), False,
                       "Path resolves outside the library")
            elif path.is_file():
                files.append(path)
    files.sort()

    current_skills = {path.parent.relative_to(root / "skills").as_posix()
                      for path in files if path.name == "SKILL.md"
                      and path.is_relative_to(root / "skills")}
    expected_skills = set(ACTIVE_SKILLS)
    record("active-methods", "skill-entrypoints", current_skills == expected_skills,
           f"count={len(current_skills)}; missing={sorted(expected_skills-current_skills)}; "
           f"extra={sorted(current_skills-expected_skills)}")
    for relative in REQUIRED_FILES:
        path = root / relative
        record("required-file", relative,
               path.resolve().is_relative_to(root) and path.is_file(),
               "required current entrypoint or asset")

    link_count = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() == ".md":
            try:
                content = path.read_text(encoding="utf-8-sig")
                for line, link in markdown_links(content):
                    try:
                        target = local_target(root, path, link)
                        if target is not None:
                            link_count += 1
                            record("local-link", f"{relative}:{line}", target.exists(), link)
                    except (OSError, ValueError) as error:
                        record("local-link", f"{relative}:{line}", False, str(error))
                if path.name == "SKILL.md":
                    name = skill_metadata(content)
                    record("skill-metadata", relative, True, name)
            except (OSError, UnicodeError, ValueError) as error:
                record("markdown", relative, False, str(error))
        elif path.suffix.lower() == ".py":
            try:
                ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
                record("python-syntax", relative, True, "parsed; not executed")
            except (OSError, UnicodeError, SyntaxError) as error:
                record("python-syntax", relative, False, str(error))
    forbidden = [path.relative_to(root).as_posix() for path in files
                 if path.suffix.lower() in FORBIDDEN_SUFFIXES]
    record("format", "no-json-files", not forbidden, ";".join(forbidden) or "none")
    record("scope", "current-library-only", True,
           f"files={len(files)}; local_links={link_count}; "
           "checks file presence, local links and syntax only; "
           "does not validate ontology semantics, business rules or inference")
    return results


def report_path(root: Path, requested: Path) -> Path:
    output = requested.resolve()
    if output.is_relative_to(root.resolve()) or output.exists() or requested.is_symlink():
        raise ValueError("Report must be a new file outside Ontology")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="New TSV report outside Ontology; never overwrites")
    args = parser.parse_args()
    if args.report:
        try:
            output = report_path(ROOT, args.report)
        except ValueError as error:
            parser.error(str(error))
    result = check()
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
    writer.writerow(("check", "item", "status", "detail"))
    writer.writerows(result)
    if args.report:
        with output.open("x", encoding="utf-8", newline="") as file:
            file.write(stream.getvalue())
    failures = [row for row in result if row[2] == "failed"]
    for row in failures:
        print(" | ".join(row), file=sys.stderr)
    print(f"checks={len(result)}; passed={len(result)-len(failures)}; failed={len(failures)}; "
          "scope=current-library-maintenance; inference=not-run")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
