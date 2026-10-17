#!/usr/bin/env python3
"""Read-only parameters.yaml comparison between project.json targets."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from model_parameter_inputs import yaml_read
from validation.findings import Findings
from validation.project import check_project_topology


def validate_value(value, ancestors=None):
    """Reject YAML values that cannot be represented faithfully in JSON."""
    if ancestors is None:
        ancestors = set()
    if type(value) in (dict, list):
        if id(value) in ancestors:
            raise ValueError("cyclic parameters YAML")
        ancestors.add(id(value))
        for item in (value.values() if type(value) is dict else value):
            validate_value(item, ancestors)
        ancestors.remove(id(value))
    elif type(value) not in (str, int, float, bool, type(None)) or (
            type(value) is float and not math.isfinite(value)):
        raise ValueError(f"unsupported parameters YAML value: {type(value).__name__}")


def value_differences(left, right, path=""):
    if type(left) is type(right) is dict:
        for key in sorted(left.keys() | right.keys()):
            child = f"{path}.{key}" if path else key
            if key not in left or key not in right:
                yield child, "only_left" if key in left else "only_right", left.get(key), right.get(key), key in left, key in right
            else:
                yield from value_differences(left[key], right[key], child)
    elif type(left) is type(right) is list:
        for index in range(max(len(left), len(right))):
            child = f"{path}[{index}]"
            before, after = index < len(left), index < len(right)
            if not before or not after:
                yield child, "only_left" if before else "only_right", left[index] if before else None, right[index] if after else None, before, after
            else:
                yield from value_differences(left[index], right[index], child)
    elif type(left) is not type(right) or left != right:
        yield path, "changed", left, right, True, True


def compare(root: Path, pairs: list[tuple], services: list[str]) -> list[dict]:
    """Compare explicit (from-env, to-env, from-target, to-target) selections."""
    base = root / "model/parameters"
    inputs = {}
    directories = {}
    accounts = {}
    findings = Findings(root)
    try:
        check_project_topology(accounts, findings, root, template_mode=False, scope_import=False)
        project_error = "; ".join(findings.errors)
    except (OSError, ValueError, KeyError, TypeError) as error:
        project_error = f"invalid project.json: {error}"
    resolved = {}
    for left, right, left_selector, right_selector in pairs:
        for environment, selector in ((left, left_selector), (right, right_selector)):
            key = environment, selector
            if key in directories:
                continue
            target = selector
            try:
                if project_error:
                    raise ValueError(project_error)
                candidates = [directory for env, directory in accounts if env == environment]
                if not candidates:
                    raise ValueError(f"unregistered environment: {environment}")
                if selector is None:
                    if len(candidates) != 1:
                        raise ValueError(f"multiple targets in {environment}; specify target: {', '.join(candidates)}")
                    target, = candidates
                elif selector not in candidates:
                    raise ValueError(f"unregistered target: {environment}/{selector}; available: {', '.join(candidates)}")
                directory = base / environment / target
                if not directory.is_dir():
                    raise ValueError(f"parameters environment/target directory missing: {environment}/{target}")
                available = {path.parent.name for path in directory.glob("*/parameters.yaml")}
                directories[key] = available, None
                selected = sorted(set(services) if services else available)
                for service in selected:
                    path = directory / service / "parameters.yaml"
                    if path in inputs:
                        continue
                    try:
                        value = yaml_read(path.read_text(encoding="utf-8"))
                        if type(value) is not dict:
                            raise ValueError("parameters YAML root must be an object")
                        validate_value(value)
                        inputs[path] = True, value, None
                    except FileNotFoundError:
                        inputs[path] = False, None, None
                    except (OSError, ValueError, RecursionError) as error:
                        inputs[path] = True, None, str(error)
            except (OSError, ValueError) as error:
                directories[key] = set(), str(error)
            resolved[key] = target
    results = []
    for left, right, left_selector, right_selector in pairs:
        keys = ((left, left_selector), (right, right_selector))
        left_target, right_target = (resolved[key] for key in keys)
        placements = ((left, left_target), (right, right_target))
        target = left_target if left_target == right_target else None
        available = [directories[key] for key in keys]
        selected = sorted(set(services) if services else available[0][0] | available[1][0])
        result = {"left": left, "right": right, "target": target, "left_target": left_target, "right_target": right_target, "status": "complete",
                  "services": selected, "differences": [], "difference_count": 0, "errors": []}

        def record(service, path, kind, before, after, left_exists, right_exists):
            paths = [f"model/parameters/{env}" + (f"/{directory}" if directory is not None else "")
                     + (f"/{service}/parameters.yaml" if service else "") for env, directory in placements]
            result["differences"].append({"pair": f"{left}-{right}", "alias": target, "left_target": left_target,
                                          "right_target": right_target, "service": service,
                                          "key_path": path, "kind": kind, "left": before, "right": after,
                                          "left_exists": left_exists, "right_exists": right_exists,
                                          "source_paths": {"left": paths[0], "right": paths[1]}})

        if any(error for _, error in available):
            for (environment, directory), (_, error) in zip(placements, available):
                if error:
                    result["errors"].append({"service": None, "path": f"model/parameters/{environment}" + (f"/{directory}" if directory is not None else ""), "message": error})
            record(None, "", "incomplete", None, None, available[0][1] is None, available[1][1] is None)
        elif not selected:
            result["errors"].append({"service": None, "message": "no parameters YAML inputs on either side"})
            record(None, "", "incomplete", None, None, True, True)
        else:
            for service in selected:
                sides = [inputs.get(base / env / directory / service / "parameters.yaml", (False, None, None)) for env, directory in placements]
                before, after = sides
                for (environment, directory), (_, _, error) in zip(placements, sides):
                    if error:
                        result["errors"].append({"service": service, "path": f"model/parameters/{environment}/{directory}/{service}/parameters.yaml", "message": error})
                if any(side[2] for side in sides) or not (before[0] or after[0]):
                    if not (before[0] or after[0]):
                        result["errors"].append({"service": service, "message": "parameters YAML missing on both sides"})
                    record(service, "", "incomplete", None, None, before[0], after[0])
                elif not (before[0] and after[0]):
                    record(service, "", "only_left" if before[0] else "only_right", None, None, before[0], after[0])
                else:
                    for difference in value_differences(before[1], after[1]):
                        record(service, *difference)
        result["difference_count"] = len(result["differences"])
        if result["errors"]:
            result["status"] = "incomplete"
        results.append(result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--from-env", required=True)
    parser.add_argument("--from-target")
    parser.add_argument("--to-env", required=True)
    parser.add_argument("--to-target")
    parser.add_argument("--service", action="append", default=[])
    args = parser.parse_args()
    if any(not service or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in service)
           for service in args.service):
        parser.error("--service must be a lowercase service ID")
    pairs = [(args.from_env, args.to_env, args.from_target, args.to_target)]
    results = compare(args.repository_root.resolve(), pairs, args.service)
    print(json.dumps({"namespace": "parameters", "comparisons": results}, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return int(any(result["status"] != "complete" for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
