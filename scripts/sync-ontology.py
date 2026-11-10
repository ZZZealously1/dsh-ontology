"""Import or verify the bundled, byte-preserved Ontology snapshot.

Default: verify the existing copy and its source-manifest.sha256. --source also
compares a local upstream library. --import requires --source and a new target;
it never refreshes an existing snapshot or changes its recorded fingerprints.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "Ontology"
MANIFEST = ROOT / "source-manifest.sha256"
EXCLUDED_DIRECTORIES = {
    "__pycache__", ".venv", "venv", "node_modules", ".git", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "outputs", "output", "ontology-runs",
    "archive", "archives", "history", "历史资料", "归档",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
# npm always omits .gitignore. It is VCS metadata, not a runtime input.
# Only filter it at the upstream boundary; unexpected installed files still fail.
SOURCE_ONLY_FILES = {"Ontology-tools/.gitignore"}
REQUIRED = {
    "AGENTS.md", "README.md", "CONTRACT.md", "common_rules.md",
    "skills/ontology-builder/SKILL.md", "Ontology-tools/requirements.lock.txt",
    "Ontology-tools/ontology_tools/__init__.py",
    "Ontology-tools/java/manifest.sha256", "Ontology-tools/vendor/owl-dl/manifest.sha256",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(root: Path, *, source_filter: bool = True) -> dict[str, tuple[Path, str]]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"A real local Ontology directory is required: {root}")
    result = {}
    for parent, directories, names in os.walk(root, followlinks=False):
        parent = Path(parent)
        excluded = EXCLUDED_DIRECTORIES if source_filter else {"__pycache__"}
        directories[:] = sorted(d for d in directories if d.casefold() not in excluded)
        for name in directories:
            directory = parent / name
            if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)():
                raise ValueError(f"Linked directories cannot enter the distribution: {directory}")
        for name in sorted(names):
            path = parent / name
            if path.suffix.lower() in EXCLUDED_SUFFIXES:
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Nonregular source file: {path}")
            relative = path.relative_to(root).as_posix()
            if source_filter and relative in SOURCE_ONLY_FILES:
                continue
            if "\n" in relative or "\r" in relative:
                raise ValueError("Line breaks are not supported in manifest paths")
            result[relative] = (path, sha256(path))
    missing = REQUIRED - result.keys()
    if missing:
        raise ValueError(f"Incomplete Ontology library: {sorted(missing)}")
    return result


def recorded() -> dict[str, str]:
    result = {}
    for row in MANIFEST.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", row)
        if not match:
            raise ValueError("Malformed source manifest")
        digest, name = match.groups()
        path = PurePosixPath(name)
        if (path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
                or path.as_posix() != name or name in result):
            raise ValueError(f"Invalid or duplicate source manifest path: {name}")
        result[name] = digest
    if not result:
        raise ValueError("Empty source manifest")
    return result


def compare(expected: dict[str, str], actual: dict[str, str], label: str) -> None:
    changed = sorted(p for p in expected.keys() & actual.keys() if expected[p] != actual[p])
    added, missing = sorted(actual.keys() - expected.keys()), sorted(expected.keys() - actual.keys())
    if changed or added or missing:
        raise ValueError(f"{label} differs: changed={changed}, added={added}, missing={missing}. "
                         "No files were replaced. Prepare and review a new snapshot version.")


def import_once(source: Path) -> None:
    # Every mutation target is fixed beneath this repository, never a user path.
    if TARGET.exists() or TARGET.is_symlink() or MANIFEST.exists() or MANIFEST.is_symlink():
        raise ValueError("Snapshot or manifest already exists. Import only into a new checkout.")
    source = source.resolve(strict=True)
    if source == ROOT or ROOT.is_relative_to(source) or source.is_relative_to(ROOT):
        raise ValueError("Import source must be separate from this repository")
    rows = inventory(source)
    expected = {name: digest for name, (_, digest) in rows.items()}
    stage = Path(tempfile.mkdtemp(prefix=".ontology-import-", dir=ROOT)).resolve()
    try:
        for relative, (path, _) in rows.items():
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
        compare(expected, {p: h for p, (_, h) in inventory(stage, source_filter=False).items()}, "Copied library")
        compare(expected, {p: h for p, (_, h) in inventory(source).items()}, "Source during import")
        # Resolved move stays in the repository and cannot overwrite an old copy.
        stage.relative_to(ROOT.resolve())
        TARGET.resolve().relative_to(ROOT.resolve())
        if TARGET.exists():
            raise ValueError("Snapshot appeared during import; refusing to replace it")
        stage.rename(TARGET)
        with MANIFEST.open("x", encoding="utf-8", newline="\n") as stream:
            stream.writelines(f"{digest}  {name}\n" for name, digest in sorted(expected.items()))
    finally:
        if stage.exists():
            # stage was created by this invocation, checked before recursive cleanup.
            stage.relative_to(ROOT.resolve())
            if not stage.name.startswith(".ontology-import-") or stage.is_symlink():
                raise ValueError("Unsafe temporary cleanup target")
            shutil.rmtree(stage)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Explicit existing Ontology source directory")
    parser.add_argument("--import", dest="import_source", action="store_true", help="Import once; refuses existing snapshot")
    args = parser.parse_args()
    if args.import_source:
        if args.source is None:
            parser.error("--import requires --source")
        import_once(args.source)
    expected = recorded()
    actual = inventory(TARGET, source_filter=False)
    compare(expected, {p: h for p, (_, h) in actual.items()}, "Bundled library")
    if args.source is not None:
        source = inventory(args.source.resolve(strict=True))
        compare(expected, {p: h for p, (_, h) in source.items()}, "Supplied source library")
    size = sum(path.stat().st_size for path, _ in actual.values())
    print(f"Verified {len(actual)} files; {size} bytes; original library bytes retained")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error))
