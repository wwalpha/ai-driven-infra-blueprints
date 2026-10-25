"""Validate one reviewed whole-target snapshot and atomically replace its reports."""

import json

import model.sources as model_sources
from task_contract_core import (
    issues_save_only,
    paths_in,
    safe_path,
    status,
    task_read_scope,
    task_snapshot,
)
from utils.file_operations import atomic_files
from validation_scope import active_scope

from .artifact import validate_artifact
from .integrity import whole_target
from .reports import iac_report, ordinary_report
from .review import human_confirmations, review_snapshot


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
    names = ["issues.md", "iac-issues.md"]
    if snapshot.cleanup:
        names.append("human-confirmations.yaml")
    with model_sources.publication_lock(root, read_only=True):
        paths = save_authority(
            root, data["environment"], data["target"], data["services"], names
        )
        contents = dict(zip(paths[:2], reports, strict=True))
        if snapshot.cleanup:
            # Apply only reviewed record removals to the current file, retaining raw Human facts.
            human = human_confirmations(root, data["environment"], data["target"])
            pending = set(snapshot.cleanup)
            for confirmation in human["confirmations"]:
                records = []
                for record in confirmation["related_issues"]:
                    key = (confirmation["id"], record["id"])
                    if key in pending:
                        pending.remove(key)
                    else:
                        records.append(record)
                confirmation["related_issues"] = records
            if pending:
                raise ValueError("reviewed Human related record is no longer present")
            contents[paths[2]] = json.dumps(human, ensure_ascii=False, indent=2) + "\n"
        atomic_files(contents)
    return paths, snapshot
