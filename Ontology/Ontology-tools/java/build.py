"""Compile/check the offline Java bridge using only the sibling vendored JARs."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess


HERE = Path(__file__).resolve().parent
VENDOR = HERE.parent / "vendor" / "owl-dl"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root: Path, exact: bool = True) -> None:
    manifest = root / "manifest.sha256"
    expected = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        sha, relative = line.split("  ", 1)
        path = (root / relative).resolve()
        path.relative_to(root.resolve())
        if relative in expected or not path.is_file() or digest(path) != sha:
            raise SystemExit(f"Fingerprint mismatch: {root.name}/{relative}")
        expected.add(relative)
    if exact:
        actual = {p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and p != manifest and "__pycache__" not in p.parts}
        if actual != expected:
            raise SystemExit(f"Unexpected or missing dependency files: {sorted(actual ^ expected)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify existing files without compiling")
    args = parser.parse_args()
    verify(VENDOR)
    if args.check:
        verify(HERE)
        print("Verified Java bridge and offline dependency fingerprints")
        return
    compiler = shutil.which("javac")
    if not compiler:
        raise SystemExit("javac is required to rebuild the bridge (JDK 11+ recommended)")
    classes = HERE / "classes"
    classes.mkdir(exist_ok=True)
    unexpected_classes = [p for p in classes.rglob("*.class")
                          if p.parent != classes or not (
                              p.name == "OwlDlCheck.class" or p.name.startswith("OwlDlCheck$"))]
    if unexpected_classes:
        raise SystemExit(f"Unexpected bridge classes: {unexpected_classes}")
    subprocess.run([compiler, "--release", "8", "-Xlint:-options", "-encoding", "UTF-8",
                    "-classpath", str(VENDOR / "lib" / "*"), "-d", str(classes),
                    str(HERE / "OwlDlCheck.java")], check=True)
    files = sorted(p for p in HERE.rglob("*") if p.is_file()
                   and p.name != "manifest.sha256" and "__pycache__" not in p.parts)
    (HERE / "manifest.sha256").write_text(
        "".join(f"{digest(p)}  {p.relative_to(HERE).as_posix()}\n" for p in files), encoding="utf-8")
    print("Built OwlDlCheck (Java 8 bytecode) and refreshed bridge fingerprints")


if __name__ == "__main__":
    main()
