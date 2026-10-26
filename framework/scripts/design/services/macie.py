"""Read fixed Macie Job bucket mappings from detailed-design Markdown."""

from __future__ import annotations

import json
import re
from pathlib import Path

from design.services.definitions.macie import ALIGNMENT as ALIGNMENT
from design.services.definitions.macie import BUCKET_LINK as BUCKET_LINK
from design.services.definitions.macie import HEADER as HEADER
from design.services.definitions.macie import HEADING as HEADING
from design.services.definitions.macie import JOB as JOB
from design.services.definitions.macie import SCOPE as SCOPE


def job_bucket_tables(path: Path) -> dict[str, tuple[Path, list[dict]]]:
    """Return each Job's JSON artifact and bucketDefinitions in table order."""
    lines = path.read_text(encoding="utf-8").splitlines()
    artifacts: dict[str, Path] = {}
    mappings: dict[str, list[dict]] = {}
    current = anchor = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        if marker := re.fullmatch(r'<a id="([^"]+)"></a>', line):
            anchor = marker.group(1)
        if match := JOB.fullmatch(line):
            current = match.group(1)
        elif line.startswith("### "):
            current = ""
        if current and (match := SCOPE.match(line)):
            artifact = (path.parent / match.group(1)).resolve()
            if artifact.parent != path.with_suffix("").resolve():
                raise ValueError(
                    f"Macie Job JSON artifact must belong to the service: {current}"
                )
            artifacts[current] = artifact
        if line != HEADING:
            index += 1
            continue
        if not current or current in mappings:
            raise ValueError("Macie bucket table must belong to exactly one Job")
        index += 1
        while index < len(lines) and not lines[index]:
            index += 1
        if lines[index : index + 2] != [HEADER, ALIGNMENT]:
            raise ValueError(f"invalid Macie bucket table header: {current}")
        index += 2
        groups: dict[str, list[str]] = {}
        seen: set[str] = set()
        last_account = ""
        while index < len(lines) and lines[index].startswith("|"):
            cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
            if (
                len(cells) != 3
                or cells[0] != f"[{current}](#{anchor})"
                or not re.fullmatch(r"`[0-9]{12}`", cells[1])
            ):
                raise ValueError(f"invalid Macie Job/account mapping row: {current}")
            bucket = (
                cells[2][1:-1]
                if cells[2].startswith("`") and cells[2].endswith("`")
                else ""
            )
            if match := BUCKET_LINK.fullmatch(cells[2]):
                bucket = match.group(1)
                target_text, anchor = match.group(2).split("#", 1)
                target = (path.parent / target_text).resolve()
                if target.parent != path.parent.resolve() or not target.is_file():
                    raise ValueError(
                        f"Macie bucket link must resolve in the same target: {current}: {bucket}"
                    )
                target_lines = target.read_text(encoding="utf-8").splitlines()
                anchor_line = f'<a id="{anchor}"></a>'
                if anchor_line not in target_lines:
                    raise ValueError(
                        f"Macie bucket link lacks an S3 Bucket anchor: {current}: {bucket}"
                    )
                position = target_lines.index(anchor_line) + 1
                while (
                    position < len(target_lines) and not target_lines[position].strip()
                ):
                    position += 1
                if target_lines[position : position + 1] != [
                    f"### S3.Bucket: {bucket}"
                ]:
                    raise ValueError(
                        f"Macie bucket link label must match its S3 Bucket: {current}: {bucket}"
                    )
            if not bucket or bucket in seen:
                raise ValueError(
                    f"missing or duplicate Macie bucket: {current}: {bucket}"
                )
            seen.add(bucket)
            account = cells[1][1:-1]
            if account in groups and account != last_account:
                raise ValueError(
                    f"Macie account rows must be contiguous: {current}: {account}"
                )
            groups.setdefault(account, []).append(bucket)
            last_account = account
            index += 1
        if not groups:
            raise ValueError(f"Macie bucket table is empty: {current}")
        mappings[current] = [
            {"accountId": account, "buckets": buckets}
            for account, buckets in groups.items()
        ]
    for job in mappings:
        if job not in artifacts:
            raise ValueError(
                f"Macie bucket table requires a linked s3JobDefinition JSON artifact: {job}"
            )
    return {job: (artifacts[job], definitions) for job, definitions in mappings.items()}


def write_job_bucket_definitions(path: Path) -> None:
    """Update only bucketDefinitions; keep optional JSON scoping settings."""
    for job, (artifact, definitions) in job_bucket_tables(path).items():
        value = (
            json.loads(artifact.read_text(encoding="utf-8"))
            if artifact.is_file()
            else {}
        )
        if not isinstance(value, dict) or "bucketCriteria" in value:
            raise ValueError(f"Macie bucket table conflicts with bucketCriteria: {job}")
        if value.get("bucketDefinitions") == definitions:
            continue
        value["bucketDefinitions"] = definitions
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


JOB_INPUT_GROUPS = (
    {"jobType", "scheduleFrequency", "initialRun"},
    {
        "managedDataIdentifierSelector",
        "managedDataIdentifierIds",
        "customDataIdentifierIds",
    },
    {"s3JobDefinition"},
)


def job_rule_inputs(self, changed=None):
    return set().union(
        *(group for group in JOB_INPUT_GROUPS if changed is None or group & changed)
    )


def job_errors(self, values: dict, *, changed=None) -> list[str]:
    """Cross-property API constraints; call after typed value validation."""
    errors = []
    scheduling = changed is None or bool(JOB_INPUT_GROUPS[0] & changed)
    selection = changed is None or bool(JOB_INPUT_GROUPS[1] & changed)
    if (
        scheduling
        and values.get("jobType") == "SCHEDULED"
        and "scheduleFrequency" not in values
    ):
        errors.append("SCHEDULED requires scheduleFrequency")
    if scheduling and values.get("jobType") == "ONE_TIME":
        for prop in ("scheduleFrequency", "initialRun"):
            if prop in values:
                errors.append(f"ONE_TIME must omit {prop}")
    selector = values.get("managedDataIdentifierSelector", "RECOMMENDED")
    if (
        selection
        and selector in {"INCLUDE", "EXCLUDE"}
        and not values.get("managedDataIdentifierIds")
    ):
        errors.append(f"{selector} requires managedDataIdentifierIds")
    if (
        selection
        and selector in {"ALL", "NONE", "RECOMMENDED"}
        and "managedDataIdentifierIds" in values
    ):
        errors.append(f"{selector} must omit managedDataIdentifierIds")
    if selection and selector == "NONE" and not values.get("customDataIdentifierIds"):
        errors.append("NONE requires customDataIdentifierIds")
    scoping = (
        values.get("s3JobDefinition", {}).get("scoping", {})
        if changed is None or "s3JobDefinition" in changed
        else {}
    )
    for block in scoping.values():
        for term in block.get("and", []):
            simple = term.get("simpleScopeTerm", {})
            key = simple.get("key")
            if key:
                operators = {
                    "OBJECT_EXTENSION": {"EQ", "NE"},
                    "OBJECT_KEY": {"STARTS_WITH"},
                }.get(key, {"EQ", "NE", "GT", "GTE", "LT", "LTE"})
                if simple.get("comparator") not in operators:
                    errors.append(f"{key}: invalid comparator")
                if (
                    key in {"OBJECT_SIZE", "OBJECT_LAST_MODIFIED_DATE"}
                    and len(simple.get("values", [])) != 1
                ):
                    errors.append(f"{key}: requires exactly one value")
    return errors
