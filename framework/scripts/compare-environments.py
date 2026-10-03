#!/usr/bin/env python3
"""Read-only desired comparison: dev/stg and stg/prod, for cde and non-cde."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from model_design import entries, properties, stack_model
from model_files import model_parts, read_model
from policy_tables import invalid_constant, unique_object

PAIRS = [(left, right, target) for target in ("cde", "non-cde")
         for left, right in (("dev", "stg"), ("stg", "prod"))]


def desired_fields(path: Path, root: Path) -> dict[tuple[str, ...], dict]:
    values = properties(read_model(path))
    if path.stem == "cloudformation-stacks":
        stack_model(values)
    elif values.get(f"desired.service.{path.stem}.serviceId") != path.stem:
        raise ValueError(f"missing or mismatched service ID: {path.relative_to(root)}")
    locations = {}
    for part in model_parts(path):
        for line, text in enumerate(part.read_text(encoding="utf-8").splitlines(), 1):
            if text.startswith("desired."):
                locations[text.partition("=")[0]] = (part.relative_to(root).as_posix(), line)
    resources = {}
    identities = set()
    for number, resource in entries(values, "desired.resource."):
        identity = (resource.get("resourceType", ""), resource.get("logicalId", ""))
        if not all(identity) or identity in identities:
            raise ValueError(f"missing or duplicate resource identity: {path.relative_to(root)}: {number}")
        identities.add(identity)
        resources[number] = identity
    rows = {}
    occurrences = Counter()
    for number, row in entries(values, "desired.row."):
        resource = number.partition("-")[0]
        if resource not in resources or not row.get("property") or "value" not in row:
            raise ValueError(f"orphan or incomplete desired row: {path.relative_to(root)}: {number}")
        identity = (*resources[resource], row["property"])
        occurrences[identity] += 1
        rows[number] = (*identity, str(occurrences[identity]))
    result = {}
    for key, value in values.items():
        if not key.startswith("desired."):
            continue
        pieces = key.split(".", 3)
        if key.startswith("desired.resource."):
            _, _, number, field = pieces
            semantic = ("resource", *resources[number], field)
        elif key.startswith("desired.row."):
            _, _, number, field = pieces
            semantic = ("row", *rows[number], field)
        else:
            semantic = (key,)
        normalized = value
        if key.startswith("desired.row.") and pieces[-1] == "document":
            document = json.loads(value, object_pairs_hook=unique_object, parse_constant=invalid_constant)
            if not isinstance(document, dict):
                raise ValueError(f"document must be a JSON object: {key}")
            normalized = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        filename, line = locations[key]
        result[semantic] = {"value": value, "path": filename, "line": line, "key": key,
                            "normalized": normalized}
    return result


def compare_pair(root: Path, left: str, right: str, target: str, services: list[str]) -> dict:
    result = {"left": left, "right": right, "target": target,
              "status": "complete", "services": [], "differences": [], "errors": []}
    try:
        project = json.loads((root / "project.json").read_text(encoding="utf-8"))
        targets = project["targets"]
        if not isinstance(targets, list) or not all(isinstance(item, dict) for item in targets):
            raise ValueError("project.json targets must be an array of objects")
        directories = []
        for environment in (left, right):
            matches = [item for item in targets if item.get("environment") == environment
                       and item.get("alias") == target]
            if len(matches) != 1:
                raise ValueError(f"project.json requires exactly one confirmed target: {environment}/{target}")
            directory = root / "model" / environment / target
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError(f"missing or unsafe model directory: model/{environment}/{target}")
            directories.append(directory)
        models = [{path.stem: path for path in directory.glob("*.properties")} for directory in directories]
        if not all(models):
            raise ValueError("target has no service model entrances; comparison is unconfirmed")
        selected = sorted(set(services) if services else models[0].keys() | models[1].keys())
        for service in selected:
            try:
                if not any(service in model for model in models):
                    raise ValueError(f"service missing on both sides: {service}")
                sides = [desired_fields(model[service], root) if service in model else {} for model in models]
                result["services"].append(service)
                for identity in sorted(sides[0].keys() | sides[1].keys()):
                    before, after = (side.get(identity) for side in sides)
                    if before is not None and after is not None and before["normalized"] == after["normalized"]:
                        continue
                    result["differences"].append({
                        "service": service, "identity": list(identity),
                        "kind": "only_right" if before is None else "only_left" if after is None else "changed",
                        "left": {key: value for key, value in before.items() if key != "normalized"} if before else None,
                        "right": {key: value for key, value in after.items() if key != "normalized"} if after else None,
                    })
            except (OSError, ValueError, KeyError) as error:
                result["errors"].append({"service": service, "message": str(error)})
    except (OSError, ValueError, KeyError, TypeError) as error:
        result["errors"].append({"service": None, "message": str(error)})
    if result["errors"]:
        result["status"] = "incomplete"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--service", action="append", default=[], help="Limit to named service IDs; repeatable")
    args = parser.parse_args()
    results = [compare_pair(args.repository_root.resolve(), *pair, args.service) for pair in PAIRS]
    print(json.dumps({"namespace": "desired", "comparisons": results}, ensure_ascii=False, indent=2))
    return int(any(result["status"] != "complete" for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
