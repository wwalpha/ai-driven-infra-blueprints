"""Validate one reviewed whole-target snapshot and atomically replace its reports."""

import json

import model.sources as model_sources
from task_contract_core import (
    issues_save_only,
    paths_in,
    safe_path,
    section,
    status,
    task_read_scope,
    task_snapshot,
)
from utils.file_operations import atomic_files
from utils.json_format import strict_json
from validation_scope import active_scope

from .artifact import validate_artifact
from .integrity import whole_target
from .reports import iac_report, ordinary_report
from .review import human_confirmations, review_snapshot, target_identity


@task_read_scope
def save_authority(root, environment, directory, services, filenames):
    snapshot = task_snapshot(root)
    text = snapshot.text
    scope = active_scope(root)
    selected = {(environment, directory, service) for service in services}
    if status(text) != "running" or not scope or not selected <= scope:
        raise ValueError(
            "report save requires a running report-only migration with explicit service scope"
        )
    allowed = paths_in(text, "## Allowed paths")
    if not issues_save_only(root, scope=scope, text=text):
        raise ValueError(
            "save-only exception does not permit model/IaC/unscoped outputs"
        )
    if any(name not in {"issues.md", "iac-issues.md"} for name in filenames):
        raise ValueError("report authority permits only issues.md/iac-issues.md")
    paths = [
        safe_path(root, f"issues/{environment}/{directory}/{name}")
        for name in filenames
    ]
    if any(
        path.relative_to(root).as_posix() not in allowed
        or path.relative_to(root).as_posix() not in paths_in(text, "## Modified files")
        for path in paths
    ):
        raise ValueError("report is outside Allowed paths or Modified files")
    return paths


def require_cleanup_authority(root, data, cleanup):
    entries = section(
        task_snapshot(root).text, "## Human-requested confirmation cleanup"
    )
    requested = []
    fields = {"environment", "target", "confirmation_id", "record_id"}
    for line in entries:
        entry = strict_json(line.removeprefix("- "))
        if (
            not line.startswith("- ")
            or not isinstance(entry, dict)
            or set(entry) != fields
        ):
            raise ValueError("invalid Human-requested confirmation cleanup entry")
        requested.append(entry)
    for confirmation, record, *_ in cleanup:
        if (
            dict(
                environment=data["environment"],
                target=data["target"],
                confirmation_id=confirmation,
                record_id=record,
            )
            not in requested
        ):
            raise ValueError("cleanup requires an explicit Human request in the Task")


def render_snapshot(root, snapshot):
    data = json.loads(snapshot.data)
    return (
        ordinary_report(root, data),
        iac_report(
            data["environment"],
            data["target"],
            data["services"],
            data["iac"],
            data.get("iac_display"),
            stamp=data["executed_at"],
            artifact=data,
        ),
    )


def save_scan(root, artifact, review):
    if artifact.get("root") != str(root):
        raise ValueError("invalid scan artifact/root")
    validate_artifact(artifact)
    whole_target(artifact)
    snapshot = review_snapshot(artifact, review)
    data = json.loads(snapshot.data)
    reports = render_snapshot(root, snapshot)
    with model_sources.publication_lock(root, read_only=True):
        paths = save_authority(
            root,
            data["environment"],
            data["target"],
            data["services"],
            ["issues.md", "iac-issues.md"],
        )
        contents = dict(zip(paths[:2], reports, strict=True))
        if snapshot.cleanup:
            require_cleanup_authority(root, data, snapshot.cleanup)
            paths.append(
                safe_path(
                    root,
                    f"issues/{data['environment']}/{data['target']}/human-confirmations.yaml",
                )
            )
            # Apply only reviewed record removals to the current file, retaining raw Human facts.
            human = human_confirmations(root, data["environment"], data["target"])
            pending = {item[:2]: item[2:] for item in snapshot.cleanup}
            for confirmation in human["confirmations"]:
                records = []
                for record in confirmation["related_issues"]:
                    key = (confirmation["id"], record["id"])
                    if key in pending:
                        if target_identity(
                            dict(record, service=confirmation["service"])
                        ) != pending.pop(key):
                            raise ValueError(
                                "current Human related record does not match the reviewed target/rule"
                            )
                    else:
                        records.append(record)
                confirmation["related_issues"] = records
            if pending:
                raise ValueError("reviewed Human related record is no longer present")
            contents[paths[2]] = json.dumps(human, ensure_ascii=False, indent=2) + "\n"
        atomic_files(contents)
    return paths, snapshot
