"""Debug-only aggregation of agent-recorded source lines; never opens source files."""

import argparse
import json
from pathlib import PurePosixPath
import sys


def report(events):
    if not isinstance(events, list):
        raise ValueError("events must be a JSON array")
    files = {}
    for event in events:
        if not isinstance(event, dict) or set(event) != {"file", "lines"}:
            raise ValueError("each event must contain file and lines only")
        name, lines = event["file"], event["lines"]
        if (not isinstance(name, str) or not name or "\\" in name
                or PurePosixPath(name).is_absolute() or ".." in name.split("/")
                or PurePosixPath(name).as_posix() != name
                or name == "." or ":" in name or any(ord(c) < 32 for c in name)):
            raise ValueError("file must be a repository-relative POSIX path")
        if not isinstance(lines, list) or any(type(n) is not int or n < 1 for n in lines):
            raise ValueError("lines must be a list of positive source line numbers")
        if not lines:
            continue
        reads, unique, cumulative = files.get(name, (0, set(), 0))
        files[name] = reads + 1, unique.union(lines), cumulative + len(lines)
    output = ["## Debug: LLM read report", "",
              "| File | Reads | Unique lines | Cumulative lines |",
              "|---|---:|---:|---:|"]
    for name in sorted(files, key=lambda name: (-files[name][2], name)):
        reads, unique, cumulative = files[name]
        label = name.replace("|", "&#124;").replace("<", "&lt;").replace(">", "&gt;")
        output.append(f"| {label} | {reads} | {len(unique)} | {cumulative} |")
    output.extend(["", "Total:", f"- Files: {len(files)}",
                   f"- Unique lines: {sum(len(row[1]) for row in files.values())}",
                   f"- Cumulative lines: {sum(row[2] for row in files.values())}"])
    return "\n".join(output)


def self_test():
    # ponytail: capture depends on agent records; runtime tool hooks if available later.
    import io
    import subprocess
    import tempfile
    from contextlib import redirect_stdout
    from pathlib import Path
    from unittest.mock import patch

    if not __debug__:
        raise ValueError("self-test requires assertions; run without -O")
    with patch("sys.stdin", None), redirect_stdout(io.StringIO()) as output:
        assert main([]) == 0 and output.getvalue() == ""  # Case 1: no stdin/read/report.
    def event(file, lines):
        return {"file": file, "lines": list(lines)}
    assert "| full | 1 | 100 | 100 |" in report([event("full", range(1, 101))])
    assert "| partial | 1 | 50 | 50 |" in report([event("partial", range(100, 150))])
    assert "| overlap | 2 | 60 | 70 |" in report([
        event("overlap", range(100, 150)), event("overlap", range(140, 160))])
    # Case 5: the real extractor parses five 600-line parts; only part-003 is returned.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        model = root / "kms.properties"
        parts = root / "kms"
        parts.mkdir()
        selected = ["desired.resource.003.resourceType=KMS.Key",
                    "desired.resource.003.logicalId=Selected",
                    "desired.resource.003.anchor=kms-selected",
                    "desired.resource.003.resourceMode=CREATE"]
        for number in range(1, 13):
            prefix = f"desired.row.003-{number:03d}"
            selected += [f"{prefix}.property=KMS.Key.Description",
                         f"{prefix}.value=test", f"{prefix}.comment=test"]
        for number in range(1, 6):
            lines = ["# padding"] * 600
            if number == 3:
                lines[119:159] = selected
            (parts / f"part-{number:03d}.properties").write_text("\n".join(lines) + "\n", encoding="utf-8")
        model.write_text("# model-index: 1\n" + "".join(
            f"# part: kms/part-{n:03d}.properties\n" for n in range(1, 6)), encoding="utf-8")
        script = Path(__file__).with_name("model_files.py")
        events = []
        for flag, selector in (("--find", "Selected"), ("--resource", "003")):
            result = subprocess.run([sys.executable, "-B", str(script), str(model), flag, selector],
                                    capture_output=True, text=True, encoding="utf-8", check=True)
            grouped = {}
            for line in result.stdout.splitlines():
                location, _ = line.split(": ", 1)
                filename, number = location.rsplit(":", 1)
                grouped.setdefault(Path(filename).relative_to(root).as_posix(), []).append(int(number))
            events.extend(event(name, lines) for name, lines in grouped.items())
        result = report(events)
        assert "| kms/part-003.properties | 2 | 40 | 41 |" in result
        assert "- Files: 1" in result
    assert "| a | 1 | 2 | 2 |" in report([event("a", [20, 35])])
    search = report([event("a", [20, 35]), event("b", [1, 4, 8, 12]), event("c", [10])])
    assert all(row in search for row in ("| a | 1 | 2 | 2 |", "| b | 1 | 4 | 4 |", "| c | 1 | 1 | 1 |"))
    assert search.index("| b |") < search.index("| a |") < search.index("| c |")
    assert "| empty |" not in report([event("empty", [])])
    assert "| duplicate | 1 | 1 | 2 |" in report([event("duplicate", [5, 5])])
    for bad in (event("../escape", [1]), event("/absolute", [1]), event("a", [True]), event("a", [0])):
        try:
            report([bad])
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid event: {bad}")
    print("LLM read report: 6 cases PASS (record aggregation; capture is agent-reported)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--debug", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
    elif args.debug:
        print(report(json.load(sys.stdin)))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, TypeError) as error:
        print(f"LLM read report: FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
