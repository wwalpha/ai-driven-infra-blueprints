"""Task-local Human exclusions of evidenced, unchanged Model failures."""

import json

import worktree_state
from task_contract_core import (
    atomic_files,
    invalidate_task_reads,
    section,
    set_status,
    task_snapshot,
    verify_snapshot,
)
from utils.json_format import document_sha256
from utils.source_reads import FileReads

from model import change_plan, references, sources

HEADING = "## Out-of-task FAIL approvals"


def approvals(text):
    body = "\n".join(section(text, HEADING)).strip()
    if not body:
        return []
    records = json.loads(body)
    if not isinstance(records, list):
        raise ValueError("out-of-task FAIL approvals must be a JSON list")
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("invalid out-of-task FAIL approval")
        for key in (
            "task",
            "diagnostic_id",
            "reason",
            "check_id",
            "source_path",
            "candidate",
            "scope",
            "assessment",
            "human_approval",
            "dependencies",
        ):
            if not record.get(key):
                raise ValueError("out-of-task FAIL approval missing " + key)
        if (
            any(
                not isinstance(record[key], str) or not record[key].strip()
                for key in (
                    "task",
                    "diagnostic_id",
                    "reason",
                    "check_id",
                    "source_path",
                    "candidate",
                )
            )
            or not isinstance(record["scope"], list)
            or any(
                not isinstance(entry, list)
                or len(entry) != 3
                or any(not isinstance(part, str) or not part for part in entry)
                for entry in record["scope"]
            )
        ):
            raise ValueError("invalid approval identity or scope")
        if not isinstance(record["dependencies"], list) or any(
            not isinstance(path, str) for path in record["dependencies"]
        ):
            raise ValueError("invalid approval dependencies")
        assessment = record["assessment"]
        if not isinstance(assessment, dict) or not isinstance(
            record["human_approval"], dict
        ):
            raise ValueError(
                "LLM assessment and explicit Human approval must be objects"
            )
        for key in (
            "task_relevance",
            "before_after",
            "producer_consumer",
            "regression",
            "why_outside_task",
            "risk",
        ):
            if not isinstance(assessment.get(key), str) or not assessment[key].strip():
                raise ValueError("LLM assessment missing " + key)
        human = record["human_approval"]
        if (
            human.get("decision") != "exclude_this_task_only"
            or human.get("diagnostic_id") != record["diagnostic_id"]
            or human.get("reason") != record["reason"]
            or not isinstance(human.get("statement"), str)
            or record["diagnostic_id"] not in human.get("statement", "")
        ):
            raise ValueError(
                "explicit Human exclusion of this diagnostic and reason required"
            )
        if record["diagnostic_id"] in seen:
            raise ValueError("duplicate out-of-task FAIL approval")
        seen.add(record["diagnostic_id"])
    return records


def contract_body(text):
    lines = text.splitlines()
    result, ignored = [], False
    for line in lines:
        if line.startswith("## "):
            ignored = line in {HEADING, "## Suspension reason"}
        if not ignored:
            result.append(line)
    return set_status("\n".join(result).rstrip() + "\n", "running")


def candidate(task, dependencies):
    """Bind the review to exact changed bytes, contract, baseline and dependencies."""
    task.fix_baseline()
    changed = task.final_paths()
    paths = (changed - {task.contract_file}) | set(dependencies)
    files = {}
    for name in sorted(paths):
        path = task.root / name
        if path.is_symlink() or not path.resolve().is_relative_to(task.root.resolve()):
            raise ValueError("unsafe approval input: " + name)
        files[name] = (
            document_sha256(path.read_bytes().hex()) if path.is_file() else None
        )
    return document_sha256(
        dict(
            base=task.baseline, contract=contract_body(task.contract_text), files=files
        )
    )


def unchanged_model_evidence(task, failure):
    """Prove unchanged source/context; the LLM still owns the relevance judgment."""
    source = failure.get("source_path") or ""
    if (
        failure.get("cause_kind") != "input_invalid"
        or not source.startswith("model/")
        or not source.endswith(".properties")
        or failure["check_id"].startswith("change.")
    ):
        raise ValueError("only existing Model input failures are eligible")
    changed = task.final_paths()
    if any(name.startswith("framework/") for name in changed):
        raise ValueError(
            "changed Framework rules require regression repair, not exclusion"
        )
    plan = change_plan.task_plan(
        task.root, changed, base=task.baseline, contract_file=task.contract_file
    )
    model_scope = sources.source_scope(task.root, task.root / source)
    source_scope = model_scope.environment, model_scope.target, model_scope.service
    affected = set(plan.services) | set(plan.contracts)
    if (
        source_scope in affected
        or model_scope.path in plan.dependencies
        or model_scope.path in plan.reads.contents
    ):
        raise ValueError(
            "changed Model or affected reference contract cannot be excluded"
        )
    reads = FileReads()
    pending, visited = [model_scope.path], set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        snapshot = sources.raw_model(path, reads)
        references.diagnose(snapshot, reads, errors=[])
        pending.extend(
            sources.source_scope(task.root, p).path
            for p in reads.contents
            if p.is_relative_to(task.root / "model")
            and p.suffix == ".properties"
            and sources.source_scope(task.root, p).path not in visited
        )
    dependencies = {
        p.relative_to(task.root).as_posix()
        for p in reads.contents
        if p.is_relative_to(task.root)
    }
    dependencies.add(source)
    # Context (account, region, topology) is part of the reference contract too.
    dependencies.add("project.json")
    if not task.baseline:
        raise ValueError("baseline is required to prove an existing Model failure")
    for name in sorted(dependencies):
        path = task.root / name
        previous = worktree_state.git(
            task.root, "show", f"{task.baseline}:{name}", check=False
        )
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if (
            previous.stdout if previous.returncode == 0 else None
        ) != current or name in changed:
            raise ValueError("Model failure input/dependency changed: " + name)
    reads.verify()
    return sorted(dependencies)


def assess(task):
    raw = task.findings.failures()
    try:
        records = approvals(task.contract_text or "")
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        return dict(
            status="FAIL",
            validation_status=task.findings.status,
            approved=[],
            unapproved=raw,
            invalid=[str(error)],
        )
    approved, blocked, invalid = [], [], []
    indexed = {r["diagnostic_id"]: r for r in records}
    for failure in raw:
        record = indexed.get(failure["diagnostic_id"])
        if record is None:
            blocked.append(failure)
            continue
        try:
            if record["task"] != task.contract_file or any(
                record[key] != failure.get(key)
                for key in ("reason", "check_id", "source_path", "scope")
            ):
                raise ValueError("approval does not match the current Task/FAIL")
            dependencies = unchanged_model_evidence(task, failure)
            if record["dependencies"] != dependencies or record[
                "candidate"
            ] != candidate(task, dependencies):
                raise ValueError(
                    "candidate or dependency evidence changed; renewed review and Human approval required"
                )
        except (OSError, ValueError, KeyError, TypeError) as error:
            blocked.append(failure)
            invalid.append(str(error))
        else:
            approved.append(failure)
    # Change Validation need not rerun unrelated quality checks. Retain their
    # reviewed FAILs while exact baseline/dependency evidence is still current.
    current_ids = {failure["diagnostic_id"] for failure in raw}
    for record in records:
        if record["diagnostic_id"] in current_ids:
            continue
        try:
            dependencies = unchanged_model_evidence(
                task, dict(record, cause_kind="input_invalid")
            )
            current = (
                record["task"] == task.contract_file
                and record["dependencies"] == dependencies
                and record["candidate"] == candidate(task, dependencies)
            )
        except (OSError, ValueError, KeyError, TypeError):
            current = False
        if current:
            approved.append(dict(record, status="FAIL", retained=True))
    return dict(
        status="FAIL"
        if blocked or task.findings.status == "FAIL" and not raw
        else "PASS",
        validation_status="FAIL" if approved else task.findings.status,
        approved=approved,
        unapproved=blocked,
        invalid=invalid,
    )


def approve(task, payload):
    """Persist only explicit, diagnostic-specific Human decisions in this Task."""
    root, name = task.root, task.contract_file
    snapshot = task_snapshot(root, name, executable=False, live=True)
    if snapshot.status == "completed":
        raise ValueError("completed Task cannot receive new approvals")
    before = len(task.findings.errors)
    task.check_task_scope()
    if len(task.findings.errors) != before:
        raise ValueError("Task scope must be valid before recording approval")
    existing = approvals(snapshot.text)
    text = contract_body(snapshot.text)
    if not isinstance(payload, list) or len(
        {record["diagnostic_id"] for record in payload}
    ) != len(payload):
        raise ValueError("approval must list unique explicit diagnostic decisions")
    # Existing approvals survive partial approvals; never replace them implicitly.
    combined = list({r["diagnostic_id"]: r for r in [*existing, *payload]}.values())
    encoded = json.dumps(combined, ensure_ascii=False, indent=2)
    approvals(text + "\n" + HEADING + "\n" + encoded)
    for record in payload:
        if record["task"] != name:
            raise ValueError("approval belongs to another Task")
        dependencies = unchanged_model_evidence(
            task, dict(record, cause_kind="input_invalid")
        )
        if record["dependencies"] != dependencies or record["candidate"] != candidate(
            task, dependencies
        ):
            raise ValueError("approval evidence is stale")
    # Preserve suspension: approval does not itself resume or complete a Task.
    lines, ignored = [], False
    for line in snapshot.text.splitlines():
        if line.startswith("## "):
            ignored = line == HEADING
        if not ignored:
            lines.append(line)
    original = "\n".join(lines).rstrip()
    verify_snapshot(snapshot)
    atomic_files(
        {snapshot.path: original + "\n\n" + HEADING + "\n" + encoded + "\n"},
        staging_directory=root,
    )
    invalidate_task_reads(root)
