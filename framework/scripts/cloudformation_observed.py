"""Collect only unambiguously mapped CloudFormation identifiers, then use model sync."""
from pathlib import Path
import importlib.util
import re

from design_catalog import DesignSchemaCatalog
from model_design import properties, entries, catalog_outputs, LINK
from model_files import read_model, model_parts, model_file_contents, MAX_LINES
from task_contract import require_writable, task_path, paths_in, matches
from validation_scope import active_scope
from issue_gate import require_target_no_issues
from design_layout import CODEBUILD_FORMAL_VARIABLE


def ambiguous(detail):
    raise ValueError("AMBIGUOUS_OBSERVED_MAPPING: " + detail)


def cfn_identity(logical):
    # The documented PascalCase conversion is mechanical; collisions never pick a winner.
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", logical) if part)


def models(root, environment, directory):
    return {path: properties(read_model(path)) for path in sorted((root / "model" / environment / directory).glob("*.properties"))
            if path.stem != "cloudformation-stacks"}


def mappings(root, environment, directory, templates, units, removed=None):
    """Map type + existing logical identity, never names, file order or old physical IDs."""
    loaded = models(root, environment, directory)
    catalog = DesignSchemaCatalog(root) if loaded else None
    resources = []
    for path, values in loaded.items():
        if path.parent != root / "model" / environment / directory:
            continue
        for identity, resource in entries(values, "desired.resource."):
            if resource.get("resourceMode", "CREATE") != "CREATE":
                continue
            try:
                cfn_type = catalog.cloudformation_type(resource["resourceType"])
            except (KeyError, ValueError):
                continue  # API-only resources never become stack resources.
            resources.append((path, identity, resource, cfn_type))
    result, owners = {}, {}
    scope = active_scope(root)
    for unit in units:
        document, _ = templates[unit["name"]]
        result[unit["name"]] = {}
        definitions = document.get("Resources", {}) | (removed or {}).get(unit["name"], {})
        for logical, definition in definitions.items():
            candidates = [item for item in resources if item[3] == definition["Type"]
                          and logical in {item[2]["logicalId"], cfn_identity(item[2]["logicalId"])}]
            if len(candidates) != 1:
                ambiguous(f"{unit['name']}/{logical}: model resource matches={len(candidates)}")
            path, identity, resource, _ = candidates[0]
            service = tuple(path.relative_to(root / "model").with_suffix("").parts)
            if scope is not None and service not in scope:
                raise ValueError(f"task scope violation: stack resource outside Validation scope: {'/'.join(service)}")
            owner = (path, identity)
            if owner in owners:
                ambiguous(f"{unit['name']}/{logical}: model resource also owned by {owners[owner]}")
            owners[owner] = unit["name"]
            outputs = catalog_outputs(root, resource["resourceType"])
            rows = [(rid, row) for rid, row in entries(loaded[path], "desired.row.") if rid.startswith(identity + "-")]
            for prop in outputs:
                selected = [(rid, row) for rid, row in rows if row["property"] == prop]
                if len(selected) != 1 or not LINK.fullmatch(selected[0][1]["value"]):
                    ambiguous(f"{unit['name']}/{logical}: identifier row missing/ambiguous: {prop}")
            result[unit["name"]][logical] = (path, identity, resource, rows, outputs)
    return loaded, result


def sync_successful(backend, units, states):
    """Plan every update before writing; success markers are saved only after generation passes."""
    root, environment, directory = backend.root, backend.environment, backend.directory
    require_target_no_issues(root, (environment, directory))
    loaded, mapped = mappings(root, environment, directory, backend.templates, units)
    catalog = DesignSchemaCatalog(root) if loaded else None
    changes, identifiers = {}, {}
    removed = {u["name"]: {c["LogicalResourceId"]: {"Type": c["ResourceType"], "PolicyAction": c.get("PolicyAction")}
                           for c in states[u["name"]].get("changes", []) if c["Action"] == "Remove"}
               for u in units} if loaded else {}
    if any(removed.values()):
        loaded, mapped = mappings(root, environment, directory, backend.templates, units, removed)
    for unit in units:
        name = unit["name"]
        document, parameters = backend.templates[name]
        if not mapped[name]:
            continue
        stack = backend.aws("describe-stacks", "--stack-name", name)["Stacks"][0]
        if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}:
            ambiguous(f"{name}: stack no longer terminal success")
        outputs = {item["OutputKey"]: item["OutputValue"] for item in stack.get("Outputs", [])}
        actuals = backend.aws("list-stack-resources", "--stack-name", name).get("StackResourceSummaries", [])
        by_logical = {}
        for actual in actuals:
            logical = actual["LogicalResourceId"]
            if logical in by_logical:
                ambiguous(f"{name}/{logical}: duplicate actual resource")
            by_logical[logical] = actual
        for logical, (path, identity, resource, rows, selected_outputs) in mapped[name].items():
            if logical in removed.get(name, {}):
                # Only a confirmed deletion resets IDs. Retention/unknown policy cannot prove destruction.
                actual = by_logical.get(logical)
                if removed[name][logical]["PolicyAction"] not in {"Delete", "Snapshot"} or (actual and actual.get("ResourceStatus") != "DELETE_COMPLETE"):
                    ambiguous(f"{name}/{logical}: removal does not prove physical destruction")
                for rid, row in rows:
                    if row["property"] in selected_outputs:
                        changes.setdefault(path, {})[f"observed.row.{rid}.value"] = "`PENDING_DEPLOY`"
                        design = (root / "docs/designs" / path.relative_to(root / "model")).with_suffix(".md")
                        identifiers[design.resolve(), resource["anchor"]] = "PENDING_DEPLOY"
                continue
            definition = document["Resources"][logical]
            if "Condition" in definition:
                # The controller's evaluator is passed by the backend; do not duplicate intrinsics.
                if not backend.resolve_condition(document, parameters, definition["Condition"], name):
                    continue
            actual = by_logical.get(logical)
            if not actual or actual["ResourceType"] != definition["Type"]:
                ambiguous(f"{name}/{logical}: actual resource missing/type mismatch")
            for rid, row in rows:
                prop = row["property"]
                if prop not in selected_outputs:
                    continue
                attribute = prop.removeprefix(resource["resourceType"] + ".")
                schema = catalog.schema(resource["resourceType"])
                primary = ("/properties/" + attribute in schema.get("primaryIdentifier", [])
                           and len(selected_outputs) == 1)
                values = []
                for key, output in document.get("Outputs", {}).items():
                    if "Condition" in output and not backend.resolve_condition(document, parameters, output["Condition"], name):
                        continue
                    value = output.get("Value")
                    getatt = value.get("Fn::GetAtt") if isinstance(value, dict) else None
                    if isinstance(getatt, str):
                        getatt = getatt.split(".", 1)
                    if (value == {"Ref": logical} and primary) or getatt == [logical, attribute]:
                        if key not in outputs:
                            ambiguous(f"{name}/{logical}: required Output absent: {key}")
                        values.append(outputs[key])
                physical = actual.get("PhysicalResourceId") if primary else None
                if values and (len(set(values)) != 1 or physical is not None and physical != values[0]):
                    ambiguous(f"{name}/{logical}: Outputs/physical identifier disagree: {prop}")
                value = values[0] if values else physical
                if not isinstance(value, str) or not value or re.search(r"\barn:aws[a-z-]*:", value, re.I) or any(c in value for c in "\r\n`"):
                    ambiguous(f"{name}/{logical}: non-ARN identifier unavailable: {prop}")
                link = LINK.fullmatch(row["value"])
                design = (root / "docs/designs" / path.relative_to(root / "model")).with_suffix(".md")
                target = (design.parent / link.group(2)).resolve() if link.group(2) else design.resolve()
                if target != design.resolve() or link.group(3) != resource["anchor"]:
                    ambiguous(f"{name}/{logical}: identifier must reference its own resource anchor")
                anchor_key = (design.resolve(), resource["anchor"])
                if anchor_key in identifiers and identifiers[anchor_key] != value:
                    ambiguous(f"{name}/{logical}: multiple identifiers for one anchor")
                identifiers[anchor_key] = value
                changes.setdefault(path, {})[f"observed.row.{rid}.value"] = f"`{value}`"
    # Read out-of-target models only if a raw incoming link reaches an updated identifier.
    # This is link discovery, not validation of unrelated prod/service designs.
    for path in sorted((root / "model").glob("*/*/*.properties")) if identifiers else []:
        if path in loaded or path.stem == "cloudformation-stacks":
            continue
        design = (root / "docs/designs" / path.relative_to(root / "model")).with_suffix(".md")
        linked = False
        for part in model_parts(path):
            for line in part.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition("=")
                link = LINK.fullmatch(value) if key.startswith("desired.row.") and key.endswith(".value") else None
                if link:
                    target = (design.parent / link.group(2)).resolve() if link.group(2) else design.resolve()
                    linked |= (target, link.group(3)) in identifiers
        if linked:
            loaded[path] = properties(read_model(path))
    # Include every incoming reference, including out-of-scope ones; reject before any write.
    for path, values in loaded.items():
        design = (root / "docs/designs" / path.relative_to(root / "model")).with_suffix(".md")
        for rid, row in entries(values, "desired.row."):
            link = LINK.fullmatch(row["value"])
            if not link or row["property"] == CODEBUILD_FORMAL_VARIABLE + "Value":
                continue
            target = (design.parent / link.group(2)).resolve() if link.group(2) else design.resolve()
            if (target, link.group(3)) in identifiers:
                changes.setdefault(path, {}).setdefault(f"observed.row.{rid}.value", identifiers[target, link.group(3)])
    if not changes:
        for unit in units:
            states[unit["name"]]["observedSynced"] = True
        return
    scope = active_scope(root)
    destinations = {}
    for path, updates in changes.items():
        service = tuple(path.relative_to(root / "model").with_suffix("").parts)
        if scope is not None and service not in scope or service[:2] != (environment, directory):
            raise ValueError(f"task scope violation: observed reference requires {'/'.join(service)}")
        for key in list(updates):
            rid = key.removeprefix("observed.row.").removesuffix(".value")
            for field in ("property", "comment"):
                observed = f"observed.row.{rid}.{field}"
                if observed not in loaded[path]:
                    updates[observed] = loaded[path][f"desired.row.{rid}.{field}"]
        # Preserve existing comments/order/parts and all desired/display inputs.
        parts = model_parts(path)
        remaining = dict(updates)
        rewritten = {}
        for part in parts:
            lines = []
            for line in part.read_text(encoding="utf-8").splitlines():
                key = line.partition("=")[0]
                lines.append(key + "=" + remaining.pop(key) if key in remaining else line)
            rewritten[part] = lines
        rewritten[parts[-1]].extend(key + "=" + value for key, value in remaining.items())
        if all(len(lines) <= MAX_LINES for lines in rewritten.values()):
            destinations.update({part: "\n".join(lines) + "\n" for part, lines in rewritten.items()})
        else:
            output = model_file_contents(path, "".join("\n".join(lines) + "\n" for lines in rewritten.values()))
            if set(parts) - output.keys():
                raise ValueError("task scope violation: observed update requires model part repartition")
            destinations.update(output)
    spec = importlib.util.spec_from_file_location("observed_sync", Path(__file__).with_name("sync-model.py"))
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    views = set()
    for path in changes:
        design = (root / "docs/designs" / path.relative_to(root / "model")).with_suffix(".md")
        views.add(design)
        for _, row in entries(loaded[path], "desired.row."):
            if match := sync.JSON_LINK.fullmatch(row["value"]):
                views.add((design.parent / match.group(1)).resolve())
    require_writable(root, set(destinations) | views)
    contract = task_path(root).read_text(encoding="utf-8")
    allowed = paths_in(contract, "## Allowed paths")
    if any(not any(matches(path.relative_to(root).as_posix(), p) for p in allowed) for path in set(destinations) | views):
        raise ValueError("task scope violation: observed model/view output outside Allowed paths")
    sync.save_files(destinations)
    if changes and sync.sync(root, True, environment, directory, services=sorted({path.stem for path in changes})):
        raise ValueError("observed model sync/validation failed; resume same session after resolving blocker")
    for unit in units:
        states[unit["name"]]["observedSynced"] = True
