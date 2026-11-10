"""Build a deterministic npm-compatible archive with native hash verification.

The package.json files list is a literal allowlist (no glob syntax). Native
Ontology bytes and source-manifest.sha256 are preserved. Standard pnpm/npm
packing is also supported by the public snapshot's explicit VCS exclusion.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", "node_modules", "__pycache__", ".venv", ".pytest_cache",
            ".mypy_cache", ".ruff_cache", "outputs", "output", "ontology-runs"}


def checked_path(root: Path, name: str) -> Path:
    pure = PurePosixPath(name)
    if (not name or name == "." or pure.is_absolute() or ".." in pure.parts
            or pure.as_posix() != name or any(c in name for c in "\\:*?[]\r\n\0")):
        raise ValueError(f"Unsafe or nonliteral package path: {name!r}")
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise ValueError(f"Links cannot enter the archive: {name}")
    if not current.resolve(strict=True).is_relative_to(root.resolve()):
        raise ValueError(f"Package path escapes repository: {name}")
    return current


def collect(root: Path) -> dict[str, bytes]:
    metadata = checked_path(root, "package.json").read_bytes()
    declared = json.loads(metadata).get("files")
    if not isinstance(declared, list) or any(not isinstance(v, str) for v in declared):
        raise ValueError("package.json must contain a literal files allowlist")
    result: dict[str, bytes] = {}

    def visit(name: str):
        path = checked_path(root, name)
        if any(part.casefold() in EXCLUDED for part in PurePosixPath(name).parts):
            return
        if path.is_dir():
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                visit(f"{name}/{child.name}")
        elif path.is_file():
            if path.suffix.lower() not in {".pyc", ".pyo"}:
                result[name] = path.read_bytes()
        else:
            raise ValueError(f"Nonregular package resource: {name}")

    for name in [*declared, "package.json", "README.md"]:
        visit(name)
    if result["package.json"] != metadata:
        raise ValueError("package.json changed while packing")
    return result


def verify_native(resources: dict[str, bytes]):
    expected = {}
    for line in resources["source-manifest.sha256"].decode("utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if name in expected or len(digest) != 64:
            raise ValueError("Invalid native source manifest")
        expected[name] = digest
    actual = {name.removeprefix("Ontology/"): hashlib.sha256(data).hexdigest()
              for name, data in resources.items() if name.startswith("Ontology/")}
    if not expected or expected != actual:
        raise ValueError("Archived Ontology file set or hashes differ from the native source manifest")


def archive_bytes(resources: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=output, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name, data in sorted(resources.items()):
                info = tarfile.TarInfo("package/" + name)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                archive.addfile(info, io.BytesIO(data))
    return output.getvalue()


def pack(root: Path, output: Path, *, node: str = "node") -> tuple[int, str]:
    root = root.resolve(strict=True)
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("Archive already exists; choose a new output file")
    parent = output.parent.resolve(strict=True)
    target = parent / output.name
    if target.is_relative_to(root) or target.suffix.lower() != ".tgz":
        raise ValueError("Archive must be a .tgz file outside the repository")
    subprocess.run([node, str(root / "scripts/verify-package.mjs"), str(root)],
                   cwd=root, check=True)
    resources = collect(root)
    verify_native(resources)
    content = archive_bytes(resources)
    # Exclusive creation: never replace an artifact produced by another run.
    with target.open("xb") as stream:
        stream.write(content)
    return len(resources), hashlib.sha256(content).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path,
                        help="New .tgz file in an existing directory outside the repository")
    parser.add_argument("--node", default="node", help="Trusted Node executable for prerequisite validation")
    args = parser.parse_args()
    count, digest = pack(ROOT, args.output, node=args.node)
    print(f"Packed {count} files: {args.output.resolve()}\nSHA256 {digest}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
