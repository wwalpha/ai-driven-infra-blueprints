#!/usr/bin/env python3
"""Bundle service designs into one PDF with working internal links."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


ANCHOR = re.compile(r'<a\s+id="([^"]+)"\s*></a>')
LINK = re.compile(r'(?<!!)\[([^\]]+)\]\(([^)]+)\)')
HEADING = re.compile(r'^(#{1,5}) (.+)$')
FENCE = re.compile(r'^\s*(`{3,}|~{3,})')


def design_files(root: Path) -> list[Path]:
    base = root / "docs" / "designs"
    files = sorted(base.rglob("*.md"))
    if not files:
        raise ValueError(f"no detailed-design Markdown in {base}")
    for path in files:
        if len(path.relative_to(base).parts) != 3:
            raise ValueError(f"design Markdown must be <environment>/<target>/<service>.md: {path}")
    return files


def source_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def prose_lines(lines: list[str]):
    fence = ""
    for line in lines:
        match = FENCE.match(line)
        if match:
            marker = match.group(1)
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = ""
            yield line, False
        else:
            yield line, not fence


def number_overviews(lines: list[str]) -> list[str]:
    numbered_lines = []
    overview = False
    table_row = 0
    add_number = False
    for line, prose in prose_lines(lines):
        if prose and line == "## リソース一覧":
            overview = True
        elif prose and line == "## リソース詳細":
            overview = False
        if prose and overview and line.startswith("|") and line.endswith("|"):
            if table_row == 0:
                add_number = line.split("|", 2)[1].strip() != "No."
            if add_number:
                number = "No." if table_row == 0 else "---:" if table_row == 1 else str(table_row - 1)
                line = f"| {number} |{line[1:]}"
            table_row += 1
        else:
            table_row = 0
        numbered_lines.append(line)
    return numbered_lines


def bundle(root: Path) -> tuple[str, dict[str, int]]:
    root = root.resolve()
    base = root / "docs" / "designs"
    files = design_files(root)
    file_set = set(files)
    anchors: dict[tuple[Path, str], str] = {}
    used_ids: set[str] = set()
    service_ids: dict[Path, str] = {}

    for path in files:
        environment, target, service = path.relative_to(base).parts
        service_id = f"service-{environment}-{target}-{Path(service).stem}"
        if service_id in used_ids:
            raise ValueError(f"duplicate PDF anchor: {service_id}")
        service_ids[path] = service_id
        used_ids.add(service_id)
        for line, prose in prose_lines(source_lines(path)):
            if not prose:
                continue
            for old in ANCHOR.findall(line):
                new = f"{environment}-{target}-{old}"
                if (path, old) in anchors or new in used_ids:
                    raise ValueError(f"duplicate design anchor: {path}#{old}")
                anchors[path, old] = new
                used_ids.add(new)

    artifacts: dict[Path, str] = {}
    expected_links: dict[str, int] = {}

    def rewrite_link(source: Path, match: re.Match[str]) -> str:
        label, raw = match.groups()
        if raw.startswith(("http://", "https://", "mailto:")):
            return match.group(0)
        target_text, separator, fragment = raw.partition("#")
        destination = (source.parent / target_text).resolve() if target_text else source
        if destination in file_set:
            if separator:
                key = (destination, fragment)
                if key not in anchors:
                    raise ValueError(f"missing PDF link target: {source}: {raw}")
                pdf_id = anchors[key]
            else:
                pdf_id = service_ids[destination]
        elif destination.suffix == ".json" and destination.is_file():
            if separator:
                raise ValueError(f"JSON fragment cannot be included in PDF: {source}: {raw}")
            relative = destination.relative_to(base) if destination.is_relative_to(base) else None
            if relative is None or len(relative.parts) != 4:
                raise ValueError(f"JSON artifact is outside service designs: {source}: {raw}")
            if destination not in artifacts:
                appendix_id = "appendix-" + "-".join(relative.with_suffix("").parts)
                if appendix_id in used_ids:
                    raise ValueError(f"duplicate PDF anchor: {appendix_id}")
                artifacts[destination] = appendix_id
                used_ids.add(appendix_id)
            pdf_id = artifacts[destination]
        else:
            raise ValueError(f"link target is not included in PDF: {source}: {raw}")
        expected_links[pdf_id] = expected_links.get(pdf_id, 0) + 1
        return f"[{label}](#{pdf_id})"

    parts = []
    previous_target = None
    for path in files:
        environment, target, _ = path.relative_to(base).parts
        target_key = (environment, target)
        if target_key != previous_target:
            first_target = " .first-target" if previous_target is None else ""
            parts.extend([f"# {environment} / {target} {{#target-{environment}-{target} .target-title{first_target}}}", ""])
            previous_target = target_key
            first_service = True
        for line, prose in prose_lines(number_overviews(source_lines(path))):
            if prose:
                line = ANCHOR.sub(lambda match: f'<a id="{anchors[path, match.group(1)]}"></a>', line)
                line = LINK.sub(lambda match: rewrite_link(path, match), line)
                heading = HEADING.fullmatch(line)
                if heading:
                    level, text = heading.groups()
                    line = f"{level}# {text}"
                    if len(level) == 1:
                        first = " .first-service" if first_service else ""
                        line += f" {{#{service_ids[path]} .service-title{first}}}"
                        first_service = False
            parts.append(line)
            if prose and ANCHOR.fullmatch(line):
                parts.append("")  # Pandoc needs a blank line before the following Markdown heading.
        parts.append("")

    if artifacts:
        parts.extend(["# JSON付録 {#json-appendix}", ""])
        for path, appendix_id in sorted(artifacts.items()):
            value = json.loads(path.read_text(encoding="utf-8"))
            parts.extend([
                f"## {path.name} {{#{appendix_id}}}",
                "",
                "~~~json",
                json.dumps(value, ensure_ascii=False, indent=2),
                "~~~",
                "",
            ])
    return "\n".join(parts) + "\n", expected_links


def verify_pdf(path: Path, expected_links: dict[str, int]) -> None:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise RuntimeError("pypdf is required to check PDF links") from error

    reader = PdfReader(path)
    if not reader.pages:
        raise ValueError("PDF has no pages")
    named = reader.named_destinations
    found: dict[str, int] = {}
    for page in reader.pages:
        for reference in page.get("/Annots", []):
            annotation = reference.get_object()
            if annotation.get("/Subtype") != "/Link":
                continue
            action = annotation.get("/A")
            destination = annotation.get("/Dest")
            if action:
                action = action.get_object()
                kind = action.get("/S")
                if kind == "/GoTo":
                    destination = action.get("/D")
                elif kind == "/GoToR":
                    raise ValueError("PDF contains a link to another document")
                elif kind == "/URI" and str(action.get("/URI", "")).startswith("file:"):
                    raise ValueError("PDF contains a file link")
            if destination is not None:
                if isinstance(destination, str):
                    name = str(destination)
                    if name not in named:
                        raise ValueError(f"PDF link destination is missing: {name}")
                    page_number = reader.get_destination_page_number(named[name])
                    if not 0 <= page_number < len(reader.pages):
                        raise ValueError(f"PDF link destination has no page: {name}")
                    found[name] = found.get(name, 0) + 1
    for name, count in expected_links.items():
        if found.get(name, 0) < count:
            raise ValueError(f"PDF internal link is missing: {name} ({found.get(name, 0)}/{count})")


def export(root: Path, output: Path) -> None:
    markdown, expected_links = bundle(root)
    for program in ("pandoc", "weasyprint"):
        if shutil.which(program) is None:
            raise RuntimeError(f"{program} is required for HTML-to-PDF conversion")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="design-pdf-", dir=output.parent) as temporary:
        temp = Path(temporary)
        merged = temp / "detailed-design.md"
        style = temp / "print.css"
        pdf = temp / "detailed-design.pdf"
        merged.write_text(markdown, encoding="utf-8")
        style.write_text(
            "#title-block-header, #TOC { break-after: page; }\n"
            ".target-title:not(.first-target), .service-title:not(.first-service), #json-appendix { break-before: page; }\n"
            ".service-title { border-bottom: 1px solid #555; padding-bottom: .3em; }\n"
            "pre { white-space: pre-wrap; overflow-wrap: anywhere; }\n"
            "table { border-collapse: collapse; }\n"
            "td, th { border: 1px solid #555; padding: .2em .35em; overflow-wrap: anywhere; }\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "pandoc", str(merged), "--from=markdown", "--to=html5", "--standalone",
                "--toc", "--toc-depth=4", "--metadata=title:詳細設計書", "--metadata=toc-title:目次",
                "--pdf-engine=weasyprint", f"--css={style}",
                f"--output={pdf}",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"pandoc failed ({result.returncode})")
        verify_pdf(pdf, expected_links)
        os.replace(pdf, output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        export(args.repository_root.resolve(), args.output.resolve())
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f"{error}\n")
    print(f"Detailed-design PDF: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
