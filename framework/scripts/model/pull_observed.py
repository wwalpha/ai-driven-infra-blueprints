"""Offline publication of confirmed CREATE identifiers from the AWS pull workflow."""

import hashlib
import re

from contracts.model import MODEL_PENDING_DEPLOY, MODEL_UNSET
from services.reference_engine import REFERENCES
from task_contract_core import section, selected_task, task_reads, task_snapshot
from utils.aws_catalogs import catalog_outputs
from utils.json_format import strict_json
from utils.source_reads import FileReads

from model.format import owner
from model.observed import observed_outputs, publish_observed_candidates
from model.reference_nodes import parse
from model.sources import load_model, scope_for


def capture(snapshot):
    root = snapshot.scope.root
    inputs = {
        path: raw
        for path, raw in snapshot.dependencies.items()
        if path.is_relative_to(root)
    }
    inputs.update({path: text.encode("utf-8") for path, text in snapshot.files.items()})
    return inputs, {
        "model": str(snapshot.scope.path),
        "inputs": {
            str(path.relative_to(root)): None
            if raw is None
            else hashlib.sha256(raw).hexdigest()
            for path, raw in inputs.items()
        },
    }


def proposed_values(snapshot, observations):
    if not isinstance(observations, list):
        raise ValueError(
            "AWS pull observations must be a list of confirmed acquisition results"
        )
    values = dict(snapshot.values)
    old = snapshot.authoritative
    scope = snapshot.scope
    target = (scope.environment, scope.target, scope.service)
    seen = set()
    for item in observations:
        if (
            not isinstance(item, dict)
            or item.get("status") != "identifier"
            or tuple(item.get(field) for field in ("environment", "target", "service"))
            != target
        ):
            raise ValueError(
                "AWS pull needs an identifier result for the selected service"
            )
        key = item.get("observationKey", "")
        if not isinstance(key, str) or key in seen:
            raise ValueError("AWS pull observation keys must be strings and unique")
        seen.add(key)
        match = re.fullmatch(r"observed\.row\.([A-Za-z0-9_-]+)\.value", key)
        if match is None:
            raise ValueError(
                "AWS pull observation requires an observed Row value: " + key
            )
        _, number = owner(key, old)
        resource = f"desired.resource.{number}."
        row = f"desired.row.{match[1]}."
        kind = old[resource + "resourceType"]
        prop = old.get(row + "property")
        logical = old.get(resource + "logicalId")
        if (
            old.get(resource + "resourceMode", "CREATE") != "CREATE"
            or (
                item.get("resource"),
                item.get("resourceType"),
                item.get("propertiesKey"),
            )
            != (logical, kind, prop)
            or prop not in catalog_outputs(scope.root, kind)
            or row + "value" not in old
        ):
            raise ValueError(
                "AWS pull observation requires an existing CREATE identifier Row: "
                + key
            )
        node = parse(old[row + "value"])
        attribute = prop.removeprefix(kind + ".")
        if node.logical_id != logical or REFERENCES.formal_attribute(
            kind, node.attribute
        ) != REFERENCES.formal_attribute(kind, attribute):
            raise ValueError(
                "AWS pull identifier Row must refer to its own Resource attribute: "
                + key
            )
        value = item.get("awsValue")
        if (
            not isinstance(value, str)
            or not value.strip()
            or value in {MODEL_PENDING_DEPLOY, MODEL_UNSET, "UNKNOWN", "[REDACTED]"}
            or re.search(r"[\x00-\x1f\x7f`]|\barn:aws[a-z-]*:", value, re.IGNORECASE)
        ):
            raise ValueError(
                "AWS pull observation requires a confirmed non-ARN identifier: " + key
            )
        values[key] = f"`{value}`"
    return values


def execute(args):
    scope = scope_for(args.model)
    if args.snapshot is None and args.observations is None and args.task_file is None:
        return capture(load_model(scope, FileReads()))[1]
    if args.snapshot is None or args.observations is None:
        raise ValueError(
            "AWS pull observation requires both --snapshot and --observations"
        )
    expected = strict_json(args.snapshot.read_text(encoding="utf-8"))
    observations = strict_json(args.observations.read_text(encoding="utf-8"))
    with selected_task(scope.root, args.task_file), task_reads(scope.root, live=True):
        snapshot = load_model(scope, FileReads())
        inputs, current = capture(snapshot)
        if current != expected:
            raise ValueError("AWS pull inputs changed since acquisition")
        outputs = observed_outputs(scope.path, proposed_values(snapshot, observations))
        if args.task_file is None:
            return {
                "status": "planned",
                "paths": [str(path) for path in sorted(outputs)],
            }
        task = task_snapshot(scope.root, args.task_file)
        required = {
            "- Task type: `design`",
            "- Workflow: `update`",
            "- AWS API execution: `forbidden`",
            "- deploy/apply: `forbidden`",
        }
        if not required <= set(section(task.text, "## Task contract")):
            raise ValueError("AWS pull observations require a Model-only update Task")
        paths = publish_observed_candidates(scope.root, outputs, inputs)
    return {
        "status": "saved" if paths else "unchanged",
        "paths": [str(path) for path in paths],
    }
