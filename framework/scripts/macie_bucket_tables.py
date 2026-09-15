"""Read fixed Macie Job bucket mappings from detailed-design Markdown."""

from __future__ import annotations

import json
import re
from pathlib import Path


JOB = re.compile(r"^### Macie\.ClassificationJob: ([A-Za-z0-9][A-Za-z0-9_.-]*)$")
SCOPE = re.compile(r"^\|\s*\d+\s*\|\s*Macie\.ClassificationJob\.s3JobDefinition\s*\|\s*\[[^\]]+\]\(([^)#]+\.json)\)\s*\|")
BUCKET_LINK = re.compile(r"^\[([^\]]+)\]\(([^)#]+#[^)]+)\)$")
HEADER = "| Job | AWS account ID | Bucket |"
ALIGNMENT = "| --- | --- | --- |"
HEADING = "#### 対象S3 bucket"


def job_bucket_tables(path: Path) -> dict[str, tuple[Path, list[dict]]]:
    """Return each Job's JSON artifact and bucketDefinitions in table order."""
    lines = path.read_text(encoding="utf-8").splitlines()
    artifacts: dict[str, Path] = {}
    mappings: dict[str, list[dict]] = {}
    current = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        if match := JOB.fullmatch(line):
            current = match.group(1)
        elif line.startswith("### "):
            current = ""
        if current and (match := SCOPE.match(line)):
            artifact = (path.parent / match.group(1)).resolve()
            if artifact.parent != path.with_suffix("").resolve():
                raise ValueError(f"Macie Job JSON artifact must belong to the service: {current}")
            artifacts[current] = artifact
        if line != HEADING:
            index += 1
            continue
        if not current or current in mappings:
            raise ValueError("Macie bucket table must belong to exactly one Job")
        index += 1
        while index < len(lines) and not lines[index]:
            index += 1
        if lines[index:index + 2] != [HEADER, ALIGNMENT]:
            raise ValueError(f"invalid Macie bucket table header: {current}")
        index += 2
        groups: dict[str, list[str]] = {}
        seen: set[str] = set()
        last_account = ""
        while index < len(lines) and lines[index].startswith("|"):
            cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
            if len(cells) != 3 or cells[0] != f"[{current}](#macie-{current.lower()})" or not re.fullmatch(r"`[0-9]{12}`", cells[1]):
                raise ValueError(f"invalid Macie Job/account mapping row: {current}")
            bucket = cells[2][1:-1] if cells[2].startswith("`") and cells[2].endswith("`") else ""
            if match := BUCKET_LINK.fullmatch(cells[2]):
                bucket = match.group(1)
                target_text, anchor = match.group(2).split("#", 1)
                target = (path.parent / target_text).resolve()
                if target.parent != path.parent.resolve() or not target.is_file():
                    raise ValueError(f"Macie bucket link must resolve in the same target: {current}: {bucket}")
                target_lines = target.read_text(encoding="utf-8").splitlines()
                anchor_line = f'<a id="{anchor}"></a>'
                if anchor_line not in target_lines:
                    raise ValueError(f"Macie bucket link lacks an S3 Bucket anchor: {current}: {bucket}")
                position = target_lines.index(anchor_line) + 1
                while position < len(target_lines) and not target_lines[position].strip():
                    position += 1
                if target_lines[position:position + 1] != [f"### S3.Bucket: {bucket}"]:
                    raise ValueError(f"Macie bucket link label must match its S3 Bucket: {current}: {bucket}")
            if not bucket or bucket in seen:
                raise ValueError(f"missing or duplicate Macie bucket: {current}: {bucket}")
            seen.add(bucket)
            account = cells[1][1:-1]
            if account in groups and account != last_account:
                raise ValueError(f"Macie account rows must be contiguous: {current}: {account}")
            groups.setdefault(account, []).append(bucket)
            last_account = account
            index += 1
        if not groups:
            raise ValueError(f"Macie bucket table is empty: {current}")
        mappings[current] = [{"accountId": account, "buckets": buckets} for account, buckets in groups.items()]
    for job in mappings:
        if job not in artifacts:
            raise ValueError(f"Macie bucket table requires a linked s3JobDefinition JSON artifact: {job}")
    return {job: (artifacts[job], definitions) for job, definitions in mappings.items()}


def write_job_bucket_definitions(path: Path) -> None:
    """Update only bucketDefinitions; keep optional JSON scoping settings."""
    for job, (artifact, definitions) in job_bucket_tables(path).items():
        value = json.loads(artifact.read_text(encoding="utf-8")) if artifact.is_file() else {}
        if not isinstance(value, dict) or "bucketCriteria" in value:
            raise ValueError(f"Macie bucket table conflicts with bucketCriteria: {job}")
        if value.get("bucketDefinitions") == definitions:
            continue
        value["bucketDefinitions"] = definitions
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
