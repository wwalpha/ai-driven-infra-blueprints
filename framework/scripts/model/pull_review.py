"""Offline AWS pull Review integrity; conversational consent belongs to the LLM.

The ordinary editor has no approved-key boundary. Keep this opt-in check beside
that editor, reusing its validation, input snapshot and publication transaction.
"""

import hashlib
import json
import re

from task_contract_core import section

from model.format import owner, patch

MARKER = "- Model source: `aws-pull`"


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprints(snapshot):
    return {
        str(path.relative_to(snapshot.scope.root)): digest(text)
        for path, text in snapshot.files.items()
    }


def build(before, after, task_file, evidence):
    """Bind exact serialized Model values, never normalized comparator values."""
    if (before.scope.environment, before.scope.target, before.scope.service) != (
        after.scope.environment,
        after.scope.target,
        after.scope.service,
    ):
        raise ValueError("AWS pull scope changed")
    old, new = before.authoritative, after.authoritative
    if (
        old.keys() != new.keys()
        or fingerprints(before).keys() != fingerprints(after).keys()
    ):
        raise ValueError("AWS pull cannot add/remove Model keys or files")
    changes = []
    for key in sorted(old):
        if old[key] == new[key]:
            continue
        kind, rid = owner(key, old)
        prefix = "desired.resource." + rid + "."
        if (
            kind != "resource"
            or not key.startswith("desired.row.")
            or not key.endswith((".value", ".document"))
            or old.get(prefix + "resourceMode", "CREATE") != "CREATE"
        ):
            raise ValueError("AWS pull requires an existing CREATE property: " + key)
        source = evidence.get(key)
        if not isinstance(source, str) or not source.strip():
            raise ValueError("AWS pull requires confirmed retrieval evidence: " + key)
        changes.append(
            {
                "key": key,
                "resource": rid,
                "identity": {k: v for k, v in old.items() if k.startswith(prefix)},
                "before": old[key],
                "after": new[key],
                "evidence": source,
            }
        )
    if set(evidence) != {item["key"] for item in changes}:
        raise ValueError("AWS pull evidence must name exactly the changed keys")
    approved = {item["key"]: item["after"] for item in changes}
    expected = dict(before.files)
    for path, document in before.documents.items():
        updates = {key: value for key, value in approved.items() if key in document.values}
        if updates:
            expected[path] = patch(document, updates)
    if {
        path.relative_to(before.scope.root): text for path, text in expected.items()
    } != {
        path.relative_to(after.scope.root): text for path, text in after.files.items()
    }:
        raise ValueError("AWS pull candidate contains unapproved raw Model changes")
    return {
        "version": 1,
        "worktree": str(before.scope.root.resolve()),
        "task": task_file,
        "scope": [before.scope.environment, before.scope.target, before.scope.service],
        "sources": fingerprints(before),
        "candidate": fingerprints(after),
        "inputs": {
            str(path.relative_to(before.scope.root)): None
            if raw is None
            else hashlib.sha256(raw).hexdigest()
            for path, raw in before.dependencies.items()
            if path.is_relative_to(before.scope.root) and path not in before.files
        },
        "changes": changes,
    }


def read_review(text):
    review = json.loads("\n".join(section(text, "## AWS pull review")))
    scope = review.get("scope") if isinstance(review, dict) else None
    if not isinstance(scope, list) or len(scope) != 3 or any(
        not isinstance(item, str) or re.fullmatch(r"[A-Za-z0-9_-]+", item) is None
        for item in scope
    ):
        raise ValueError("AWS pull Review requires one safe environment/target/service scope")
    return review


def verify(before, after, task_file, text, *, worktree=None):
    """Called inside the existing snapshot-backed publication context."""
    if MARKER not in section(text, "## Task contract"):
        return
    lines = set(section(text, "## Task contract"))
    required = {
        "- Task type: `design`",
        "- Workflow: `update`",
        "- AWS API execution: `forbidden`",
        "- deploy/apply: `forbidden`",
    }
    if not required <= lines:
        raise ValueError("AWS pull requires a Model-only update Task")
    try:
        review = read_review(text)
        evidence = {item["key"]: item["evidence"] for item in review["changes"]}
        expected = build(before, after, task_file, evidence)
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError("AWS pull Review is missing, stale or invalid") from error
    if worktree is not None:
        expected["worktree"] = str(worktree.resolve())
    if review != expected:
        raise ValueError("AWS pull candidate differs from the approved Review")
