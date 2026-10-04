#!/usr/bin/env python3
"""Read-only desired comparison: dev/stg and stg/prod, for cde and non-cde."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from model_design import entries, properties, stack_model
from design_layout import resource_mode
from model_files import model_parts, read_model
from policy_tables import invalid_constant, unique_object

PAIRS = [(left, right, target) for target in ("cde", "non-cde")
         for left, right in (("dev", "stg"), ("stg", "prod"))]
REFERENCE = re.compile(r"\[([^\]]+)\]\(([^)]*?)#([^)]+)\)")


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
        resource_mode(resource)  # Missing mode is CREATE; unknown values must not bypass comparison.
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


def evidence(field: dict | None) -> dict | None:
    return {key: value for key, value in field.items() if key != "normalized"} if field else None


def align_resources(sides: list[dict], mappings: list[dict], service: str, absent_service: bool) -> tuple:
    resources = [{key[1:3] for key in side if key[0] == "resource"} for side in sides]
    translations = [{}, {}]
    matches = []
    for item in mappings:
        if (not isinstance(item, dict) or set(item) != {"service", "resourceType", "left", "right", "reason"}
                or not all(isinstance(item[key], str) and item[key].strip()
                           for key in ("service", "resourceType", "reason"))
                or not all(item[key] is None or isinstance(item[key], str) and item[key].strip()
                           for key in ("left", "right")) or (item["left"] is None and item["right"] is None)):
            raise ValueError("resource map requires service, resourceType, left/right IDs (or null), and reason")
        if item["service"] != service:
            continue
        identities = [(item["resourceType"], item[side]) if item[side] is not None else None
                      for side in ("left", "right")]
        canonical = identities[0] or (*identities[1], "right")
        for index, identity in enumerate(identities):
            if identity is not None:
                if identity not in resources[index] or identity in translations[index]:
                    raise ValueError(f"missing or duplicate mapped resource on {('left', 'right')[index]}: {identity}")
                translations[index][identity] = canonical
        matches.append({**item, "basis": "confirmed"})
    for identity in sorted(resources[0] & resources[1]):
        if all(identity not in side for side in translations):
            for side in translations:
                side[identity] = identity
            matches.append({"service": service, "resourceType": identity[0],
                            "left": identity[1], "right": identity[1], "basis": "same_logical_id"})
    imported = [{identity for identity in identities
                 if sides[index].get(("resource", *identity, "resourceMode"), {}).get("value") == "IMPORT"}
                for index, identities in enumerate(resources)]
    excluded_pairs = {translations[index][identity] for index, identities in enumerate(imported)
                      for identity in identities if identity in translations[index]}
    excluded = [identities | {identity for identity, canonical in translations[index].items()
                             if canonical in excluded_pairs}
                for index, identities in enumerate(imported)]
    exclusions = []
    for index, identities in enumerate(excluded):
        for identity in sorted(identities):
            mode = sides[index].get(("resource", *identity, "resourceMode"))
            exclusions.append({"service": service, "side": ("left", "right")[index],
                               "resourceType": identity[0], "logicalId": identity[1],
                               "resourceMode": mode["value"] if mode else "CREATE",
                               "reason": "IMPORT" if identity in imported[index] else "corresponding resource is IMPORT",
                               "evidence": evidence(mode or sides[index][("resource", *identity, "logicalId")])})
    for match in matches:
        match["excluded"] = any((match["resourceType"], match[side]) in excluded[index]
                                for index, side in enumerate(("left", "right")))
    unconfirmed = []
    for index, identities in enumerate(resources):
        for identity in sorted(identities - translations[index].keys() - excluded[index]):
            if absent_service:
                translations[index][identity] = identity
            else:
                unconfirmed.append({"service": service, "side": ("left", "right")[index],
                                    "resourceType": identity[0], "logicalId": identity[1],
                                    "reason": "resource correspondence is unconfirmed; not an addition/removal",
                                    "fields": [evidence(field) for key, field in sorted(sides[index].items())
                                               if key[0] in {"resource", "row"} and key[1:3] == identity]})
    return translations, matches, unconfirmed, exclusions


def reference_value(value: str, service: str, references: dict) -> str:
    def replace(match):
        _, path, anchor = match.groups()
        if path and (len(Path(path).parts) != 1 or not path.endswith(".md")):
            return match.group(0)  # Do not reinterpret external or cross-target links.
        target = Path(path).stem if path else service
        resolved = references.get((target, anchor))
        if resolved is None:
            return match.group(0)
        return json.dumps(["reference", target, *resolved], ensure_ascii=False)
    return REFERENCE.sub(replace, value)


def comparison_fields(fields: dict, translations: dict, service: str, references: dict, excluded: set) -> dict:
    def normalize(value):
        if isinstance(value, str):
            return reference_value(value, service, references)
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {name: normalize(item) for name, item in value.items()}
        return value

    result = {}
    for key, field in fields.items():
        if key[0] in {"resource", "row"} and key[1:3] in excluded:
            continue
        if key[0] == "row" and key[-1] == "artifactSha256" and (document := fields.get((*key[:-1], "document"))):
            if field["value"] != hashlib.sha256(document["normalized"].encode("utf-8")).hexdigest():
                raise ValueError(f"artifactSha256 differs from document: {field['path']}:{field['line']}")
            continue  # Derived document digest, not an independent setting.
        if key[0] in {"resource", "row"}:
            identity = translations.get(key[1:3])
            if identity is None or key[0] == "resource" and key[-1] in {"logicalId", "anchor", "resourceMode"}:
                continue
            key = (key[0], *identity, *key[3:])
        # Preserve literals, names and artifact paths; only resolved Markdown references
        # are compared by destination rather than their label or generated anchor.
        normalized = field["normalized"]
        if key[0] == "row" and key[-1] == "document":
            normalized = json.dumps(normalize(json.loads(normalized)), ensure_ascii=False,
                                    sort_keys=True, separators=(",", ":"))
        elif (key[0] == "row" and key[-1] == "value") or (key[0] == "resource" and key[-1] == "parentReference"):
            normalized = reference_value(normalized, service, references)
        result[key] = {**field, "normalized": normalized}
    return result


def exclude_environment_differences(result: dict, approvals: list[dict], services: list[str]) -> None:
    """Exclude only confirmed differences whose identity and original values still match."""
    differences = {(item["service"], tuple(item["identity"])): item for item in result["differences"]}
    confirmed = {}
    for item in approvals:
        if (not isinstance(item, dict) or set(item) != {"service", "identity", "left", "right", "reason"}
                or not all(isinstance(item[key], str) and item[key].strip() for key in ("service", "reason"))
                or item["service"] not in services
                or not isinstance(item["identity"], list) or not item["identity"]
                or not all(isinstance(key, str) and key for key in item["identity"])
                or not all(isinstance(item[key], str) for key in ("left", "right"))):
            raise ValueError("environment difference requires selected service, identity, left/right values and reason")
        key = (item["service"], tuple(item["identity"]))
        difference = differences.get(key)
        if key in confirmed:
            raise ValueError(f"duplicate confirmed environment difference: {key}")
        if (difference is None or difference["kind"] != "changed"
                or any(difference[side]["value"] != item[side] for side in ("left", "right"))):
            raise ValueError(f"confirmed environment difference is missing, unconfirmed or stale: {key}")
        confirmed[key] = item["reason"]
    # Apply only after every approval passes, so invalid input never partially hides differences.
    result["environment_differences"] = [
        {**item, "reason": confirmed[item["service"], tuple(item["identity"])]}
        for item in result["differences"] if (item["service"], tuple(item["identity"])) in confirmed]
    result["differences"] = [item for item in result["differences"]
                             if (item["service"], tuple(item["identity"])) not in confirmed]


def compare_pair(root: Path, left: str, right: str, target: str, services: list[str], resource_map: Path | None = None,
                 *, field_cache: dict[Path, dict] | None = None) -> dict:
    # The caller owns the invocation lifetime; standalone calls start fresh.
    if field_cache is None:
        field_cache = {}
    result = {"left": left, "right": right, "target": target,
              "status": "complete", "services": [], "differences": [], "errors": [],
              "resource_matches": [], "unconfirmed": [], "excluded": [],
              "environment_differences": [], "difference_count": 0}
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
        mappings = []
        environment_differences = []
        if resource_map is not None:
            document = json.loads(resource_map.read_text(encoding="utf-8"),
                                  object_pairs_hook=unique_object, parse_constant=invalid_constant)
            if (not isinstance(document, dict) or not {"left", "right", "target", "resources"} <= set(document)
                    or set(document) - {"left", "right", "target", "resources", "environment_differences"}
                    or (document["left"], document["right"], document["target"]) != (left, right, target)
                    or not isinstance(document["resources"], list)
                    or not isinstance(document.get("environment_differences", []), list)):
                raise ValueError("resource map must specify this left/right/target, resources and optional environment_differences arrays")
            mappings = document["resources"]
            environment_differences = document.get("environment_differences", [])
            if any(not isinstance(item, dict) or item.get("service") not in selected for item in mappings):
                raise ValueError("resource map contains an invalid or unselected service")
        prepared = {}
        references = [{}, {}]
        for service in selected:
            try:
                if not any(service in model for model in models):
                    raise ValueError(f"service missing on both sides: {service}")
                sides = []
                for model in models:
                    if service not in model:
                        sides.append({})
                        continue
                    path = model[service]
                    if path not in field_cache:
                        field_cache[path] = desired_fields(path, root)
                    sides.append(field_cache[path])
                translations, matches, unconfirmed, exclusions = align_resources(
                    sides, mappings, service, any(service not in model for model in models))
                prepared[service] = (sides, translations, matches, unconfirmed, exclusions)
                for index, fields in enumerate(sides):
                    for key, field in fields.items():
                        if key[0] == "resource" and key[-1] == "anchor" and key[1:3] in translations[index]:
                            reference = (service, field["value"])
                            if reference in references[index]:
                                raise ValueError(f"duplicate resource anchor: {service}#{field['value']}")
                            references[index][reference] = translations[index][key[1:3]]
            except (OSError, ValueError, KeyError) as error:
                prepared.pop(service, None)
                for side in references:
                    for key in [key for key in side if key[0] == service]:
                        del side[key]
                result["errors"].append({"service": service, "message": str(error)})
        for service, (fields, translations, matches, unconfirmed, exclusions) in prepared.items():
            try:
                excluded = [{(item["resourceType"], item["logicalId"]) for item in exclusions
                             if item["side"] == side} for side in ("left", "right")]
                sides = [comparison_fields(fields[index], translations[index], service, references[index], excluded[index])
                         for index in range(2)]
                if exclusions:
                    only_imported = all({key[1:3] for key in fields[index] if key[0] == "resource"} <= excluded[index]
                                        for index in range(2))
                    # Derived service coverage must not reintroduce excluded resource differences.
                    sides = [{key: field for key, field in side.items()
                              if key != (f"desired.service.{service}.ownedCatalogResourceTypes",)
                              and not (only_imported and key[0].startswith(f"desired.service.{service}."))}
                             for side in sides]
                result["services"].append(service)
                result["resource_matches"].extend(matches)
                result["unconfirmed"].extend(unconfirmed)
                result["excluded"].extend(exclusions)
                for identity in sorted(sides[0].keys() | sides[1].keys()):
                    before, after = (side.get(identity) for side in sides)
                    if before is not None and after is not None and before["normalized"] == after["normalized"]:
                        continue
                    result["differences"].append({
                        "service": service, "identity": list(identity),
                        "kind": "only_right" if before is None else "only_left" if after is None else "changed",
                        "left": evidence(before), "right": evidence(after),
                    })
            except (OSError, ValueError, KeyError) as error:
                result["errors"].append({"service": service, "message": str(error)})
        exclude_environment_differences(result, environment_differences, selected)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result["errors"].append({"service": None, "message": str(error)})
    result["difference_count"] = len(result["differences"])
    if result["errors"]:
        result["status"] = "incomplete"
    elif result["unconfirmed"]:
        result["status"] = "unconfirmed"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--pair", choices=("dev-stg", "stg-prod"), help="Compare only this environment pair")
    parser.add_argument("--target", choices=("cde", "non-cde"), help="Compare only this target")
    parser.add_argument("--service", action="append", default=[], help="Limit to named service IDs; repeatable")
    parser.add_argument("--resource-map", type=Path,
                        help="JSON with confirmed resource correspondence and optional environment differences for one pair/target")
    args = parser.parse_args()
    if args.resource_map is not None and (args.pair is None or args.target is None):
        parser.error("--resource-map requires --pair and --target")
    pairs = [(left, right, target) for left, right, target in PAIRS
             if (args.pair is None or args.pair == f"{left}-{right}")
             and (args.target is None or args.target == target)]
    field_cache = {}
    results = [compare_pair(args.repository_root.resolve(), *pair, args.service, args.resource_map,
                            field_cache=field_cache) for pair in pairs]
    print(json.dumps({"namespace": "desired", "comparisons": results}, ensure_ascii=False, indent=2))
    return int(any(result["status"] != "complete" for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
