"""Repeat the delivered toolkit's local acceptance, preserving actual commands."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF
from ontology_tools.core import RUN
from ontology_tools.io import OT, code_digest, file_set, new_output, parse_rdf, sha256, write_graph, write_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = new_output(args.output, ROOT / "examples", ROOT / "ontology_tools", ROOT / "tests")
    checks = [("unit-tests", ["-m", "unittest", "discover", "-s", "tests", "-v"], 0)]
    for example in ("tagging", "family", "projection", "calculation"):
        package = f"examples/{example}"
        for operation in ("inspect", "validate", "infer", "test"):
            checks.append((f"{example}-{operation}", ["-m", "ontology_tools", operation, "--package", package, "--output", str(out / f"{example}-{operation}")], 0))
        query = "ancestors.rq" if example == "family" else "check-result.rq"
        checks.append((f"{example}-query", ["-m", "ontology_tools", "query", "--graph", str(out / f"{example}-infer/closure.ttl"), "--query", f"{package}/queries/{query}", "--output", str(out / f"{example}-query")], 0))
        checks.append((f"{example}-replay", ["-m", "ontology_tools", "replay", "--run", str(out / f"{example}-infer"), "--output", str(out / f"{example}-replay")], 0))
    checks.append(("invalid-input", ["-m", "ontology_tools", "infer", "--package", "examples/tagging", "--facts", "examples/tagging/tests/inputs/invalid.ttl", "--output", str(out / "invalid-input")], 3))
    for operation in ("owl-dl", "owl-infer"):
        checks.append((operation, ["-m", "ontology_tools", operation,
                                   "--ontology", "examples/projection/ontology.ttl",
                                   "--facts", "examples/projection/inputs/facts.ttl",
                                   "--output", str(out / operation)], 0))
        checks.append((operation + "-replay", ["-m", "ontology_tools", "replay",
                                              "--run", str(out / operation),
                                              "--output", str(out / (operation + "-replay"))], 0))
    report = Graph()
    report.add((RUN, OT.startedAt, Literal(datetime.now(timezone.utc).isoformat())))
    report.add((RUN, OT.engineDigest, Literal(code_digest())))
    rows = []
    all_passed = True
    unit_count = "unknown"
    skipped_count = 0
    for name, arguments, expected in checks:
        command = [sys.executable, "-B", "-X", "utf8", *arguments]
        log = out / f"{name}.txt"
        with log.open("w", encoding="utf-8") as stream:
            try:
                completed = subprocess.run(command, cwd=ROOT, stdout=stream,
                                           stderr=subprocess.STDOUT,
                                           timeout=900 if name == "unit-tests" else 300)
                actual = completed.returncode
            except subprocess.TimeoutExpired:
                actual = 124
                stream.write("\nAcceptance command timed out; incomplete tests are not passed.\n")
        log_text = log.read_text(encoding="utf-8", errors="replace")
        command_text = subprocess.list2cmdline(command)
        node = URIRef("urn:ontology-tools:acceptance:" + name)
        passed = actual == expected
        if name == "unit-tests":
            skipped = re.search(r"skipped=(\d+)", log_text)
            skipped_count = int(skipped.group(1)) if skipped else 0
            matches = re.findall(r"Ran (\d+) tests", log_text)
            unit_count = matches[-1] if matches else "unknown"
            passed = passed and skipped_count == 0 and bool(matches) and int(unit_count) > 0
        all_passed &= passed
        for predicate, value in ((OT.command, command_text), (OT.expectedExit, expected), (OT.actualExit, actual), (OT.status, "passed" if passed else "failed"), (OT.log, log.name)):
            report.add((node, predicate, Literal(value)))
        report.add((node, RDF.type, OT.CommandCheck))
        report.add((RUN, OT.check, node))
        rows.append(f"| {name} | {expected} | {actual} | {'passed' if passed else 'failed'} |")
        print(f"{name}: {'passed' if passed else 'failed'} (exit {actual}, expected {expected})", flush=True)
    report.add((RUN, OT.status, Literal("passed" if all_passed else "failed")))
    report.add((RUN, OT.finishedAt, Literal(datetime.now(timezone.utc).isoformat())))
    report.add((RUN, OT.skippedTests, Literal(skipped_count)))
    write_graph(report, out / "acceptance.ttl")
    source_lines = []
    for relative, path in file_set(ROOT).items():
        if not relative.startswith("outputs/"):
            source_lines.append(f"{sha256(path)}  {relative}\n")
    (out / "source-files.sha256").write_text("".join(source_lines), encoding="utf-8")
    summary = f"# 通用工具验收\n\n状态：{'passed' if all_passed else 'failed'}。单元与集成测试：{unit_count} 项。\n\n| 命令 | 预期退出码 | 实际退出码 | 状态 |\n|---|---:|---:|---|\n" + "\n".join(rows)
    summary += f"\n\n跳过测试：{skipped_count}；必检测试跳过时不记为整体验收通过。实际命令、退出码、UTC时间和日志索引见 acceptance.ttl。日志保存 stdout 与 stderr。源文件指纹见 source-files.sha256，整个证据目录指纹见 manifest.sha256。\n\n验收有限规则、独立 OWL DL 检查、命名事实投影、有限 OWL/SWRL 协同、标量计算与新值反馈及统一重放。OWL DL 执行要求本地 Java 和随包依赖；固定候选域与计算扩张候选域的协同都不是完整 OWL DL + SWRL 联合推理。这些合成案例不替代真实业务本体、制度、数据和黄金预期验收。\n"
    (out / "acceptance.md").write_text(summary, encoding="utf-8")
    write_manifest(out)
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
