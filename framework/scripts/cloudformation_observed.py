"""Collect only unambiguously mapped CloudFormation identifiers, then use model sync."""
from pathlib import Path
import importlib.util
import re

from design_catalog import DesignSchemaCatalog
from model_design import properties, entries, catalog_outputs, stack_model, cfn_resource_identity, LINK
from cloudformation_inputs import Blocked, condition_active, output_value, load_template_inputs, load_target
from model_files import read_model, model_parts, model_file_contents, MAX_LINES
from task_contract import require_writable, task_path, paths_in, matches
from validation_scope import active_scope
from issue_gate import require_target_no_issues
from design_layout import CODEBUILD_FORMAL_VARIABLE


def ambiguous(detail):
    raise ValueError("AMBIGUOUS_OBSERVED_MAPPING: " + detail)


class MappingError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("AMBIGUOUS_OBSERVED_MAPPING: " + "\n".join(
            detail for details in errors.values() for detail in details))


def cfn_identity(logical):
    # The documented PascalCase conversion is mechanical; collisions never pick a winner.
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", logical) if part)


def models(root, environment, directory):
    return {path: properties(read_model(path)) for path in sorted((root / "model" / environment / directory).glob("*.properties"))
            if path.stem != "cloudformation-stacks"}


def resource_index(loaded, catalog):
    direct, legacy = {}, {}
    for path, values in loaded.items():
        for identity, resource in entries(values, "desired.resource."):
            try:
                cfn_type = catalog.cloudformation_type(resource["resourceType"])
            except (KeyError, ValueError):
                cfn_type = None
            entry = (path, identity, resource, cfn_type)
            if "cfn-logicalId" in resource:
                direct.setdefault(cfn_resource_identity(resource["cfn-logicalId"]), []).append(entry)
            elif cfn_type and resource.get("resourceMode", "CREATE") == "CREATE" and f"desired.resource.{identity}.logicalId" in values:
                # Read-only transition support for pre-existing models, never for new identities.
                for logical in {resource["logicalId"], cfn_identity(resource["logicalId"])}:
                    legacy.setdefault((cfn_type, logical), []).append(entry)
    return direct, legacy


def validate_mapping_targets(root, environment, directory, values):
    """Validate resource-owned stack identities before templates exist."""
    stack_model(values)
    names = {stack["name"] for _, stack in entries(values, "desired.stack.")}
    loaded = models(root, environment, directory)
    direct, _ = resource_index(loaded, DesignSchemaCatalog(root))
    errors = {}
    for (name, logical), candidates in direct.items():
        if name not in names:
            errors.setdefault(name, []).append(f"{name}/{logical}: cfn-logicalId references an undeclared stack")
        if len(candidates) != 1:
            errors.setdefault(name, []).append(f"{name}/{logical}: duplicate cfn-logicalId")
        for path, identity, resource, cfn_type in candidates:
            if resource.get("resourceMode", "CREATE") != "CREATE" or not cfn_type:
                errors.setdefault(name, []).append(f"{path.name}/{identity}: cfn-logicalId requires CREATE with a formal CFn type")
    if errors:
        raise MappingError(errors)


def active_outputs(document, parameters, pseudo):
    return {key: output_value(document, parameters, pseudo, output.get("Value"))
            for key, output in document.get("Outputs", {}).items()
            if condition_active(document, parameters, pseudo, output)}


def identifier_source(catalog, resource, outputs, logical, prop, values):
    attribute = prop.removeprefix(resource["resourceType"] + ".")
    primary = ("/properties/" + attribute in catalog.schema(resource["resourceType"]).get("primaryIdentifier", [])
               and len(outputs) == 1)
    keys = []
    for key, value in values.items():
        getatt = value.get("Fn::GetAtt") if isinstance(value, dict) else None
        if isinstance(getatt, str):
            getatt = getatt.split(".", 1)
        if (value == {"Ref": logical} and primary) or getatt == [logical, attribute]:
            keys.append(key)
    return primary, keys


def mappings(root, environment, directory, templates, units, removed=None, target=None):
    """Shared read-only implement/deploy validation; resource-owned IDs never fall back."""
    loaded = models(root, environment, directory)
    catalog = DesignSchemaCatalog(root) if loaded else None
    direct, legacy = resource_index(loaded, catalog)
    source = root / "model" / environment / directory / "cloudformation-stacks.properties"
    values = properties(read_model(source)) if source.is_file() else {}
    if values:
        stack_model(values)
    target = target or (load_target(root, environment, directory) if (root / "project.json").is_file() else {})
    result, owners, errors = {}, {}, {}
    if values:
        names = {stack["name"] for _, stack in entries(values, "desired.stack.")}
        for name, logical in direct:
            if name not in names:
                errors.setdefault(name, []).append(f"{name}/{logical}: cfn-logicalId references an undeclared stack")
    scope = active_scope(root)
    for unit in units:
        name = unit["name"]
        document, parameters = templates[name]
        pseudo = {"AWS::StackName": name} | {"AWS::" + key: target[value] for key, value in
                 (("AccountId", "awsAccountId"), ("Region", "awsRegion")) if value in target}
        result[name] = {}
        definitions = document.get("Resources", {}) | (removed or {}).get(name, {})
        explicit = any(stack == name for stack, _ in direct)
        try:
            output_values = active_outputs(document, parameters, pseudo)
        except (ValueError, Blocked) as error:
            errors.setdefault(name, []).append(f"{name}/Outputs: {error}")
            output_values = {}
        for logical, definition in definitions.items():
            deleting = logical in (removed or {}).get(name, {})
            try:
                if not deleting and not condition_active(document, parameters, pseudo, definition):
                    continue
                candidates = direct.get((name, logical), [])
                if candidates or explicit:
                    if len(candidates) != 1:
                        raise ValueError(f"cfn-logicalId matches={len(candidates)}; legacy fallback forbidden")
                    entry = candidates[0]
                    if entry[2].get("resourceMode", "CREATE") != "CREATE":
                        raise ValueError("cfn-logicalId requires CREATE")
                    if entry[3] != definition["Type"]:
                        raise ValueError(f"formal CFn type mismatch: {definition['Type']} != {entry[3]}")
                else:
                    candidates = legacy.get((definition["Type"], logical), [])
                    if len(candidates) != 1:
                        raise ValueError(f"model resource matches={len(candidates)}; cfn-logicalId required")
                    entry = candidates[0]
                path, identity, resource, _ = entry
                service = tuple(path.relative_to(root / "model").with_suffix("").parts)
                if scope is not None and service not in scope:
                    raise ValueError(f"task scope violation: stack resource outside Validation scope: {'/'.join(service)}")
                owner = (path, identity)
                if owner in owners:
                    previous = owners[owner]
                    errors.setdefault(previous[0], []).append(f"{previous[0]}/{previous[1]}: model resource also owned by {name}/{logical}")
                    raise ValueError(f"model resource also owned by {previous[0]}/{previous[1]}")
                owners[owner] = (name, logical)
                outputs = catalog_outputs(root, resource["resourceType"])
                rows = [(rid, row) for rid, row in entries(loaded[path], "desired.row.") if rid.startswith(identity + "-")]
                for prop in outputs:
                    selected = [(rid, row) for rid, row in rows if row["property"] == prop]
                    link = LINK.fullmatch(selected[0][1]["value"]) if len(selected) == 1 else None
                    if not link:
                        errors.setdefault(name, []).append(f"{name}/{logical}: identifier row missing/ambiguous: {prop}")
                    elif link.group(2) not in {"", path.stem + ".md"} or link.group(3) != resource["anchor"]:
                        errors.setdefault(name, []).append(f"{name}/{logical}: identifier must reference its own resource anchor: {prop}")
                    primary, keys = identifier_source(catalog, resource, outputs, logical, prop, output_values)
                    if not deleting and not primary and not keys:
                        errors.setdefault(name, []).append(f"{name}/{logical}: required GetAtt Output missing: {prop}")
                result[name][logical] = (path, identity, resource, rows, outputs)
            except (ValueError, Blocked) as error:
                errors.setdefault(name, []).append(f"{name}/{logical}: {error}")
    if errors:
        raise MappingError(errors)
    return loaded, result


def removed_resources(units, states):
    return {unit["name"]: {change["LogicalResourceId"]: {"Type": change["ResourceType"], "PolicyAction": change.get("PolicyAction")}
                            for change in states[unit["name"]].get("changes", []) if change["Action"] == "Remove"}
            for unit in units}


def sync_successful(backend, units, states):
    """Plan every update before writing; success markers are saved only after generation passes."""
    root, environment, directory = backend.root, backend.environment, backend.directory
    require_target_no_issues(root, (environment, directory))
    removed = removed_resources(units, states)
    plan = getattr(backend, "mapping_plan", None)
    if plan is None:
        # Direct read-only synchronization callers also pass through the same validator.
        plan = mappings(root, environment, directory, backend.templates, units, removed, target=backend.target)
    _, mapped = plan
    if any(set(removed[name]) - mapped.get(name, {}).keys() for name in removed):
        ambiguous("removed resource has no mapping validated before execution")
    loaded = models(root, environment, directory)
    catalog = DesignSchemaCatalog(root) if loaded else None
    changes, identifiers = {}, {}
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
            actual = by_logical.get(logical)
            if not actual or actual["ResourceType"] != definition["Type"]:
                ambiguous(f"{name}/{logical}: actual resource missing/type mismatch")
            for rid, row in rows:
                prop = row["property"]
                if prop not in selected_outputs:
                    continue
                pseudo = {"AWS::StackName": name, "AWS::AccountId": backend.target["awsAccountId"], "AWS::Region": backend.target["awsRegion"]}
                primary, keys = identifier_source(catalog, resource, selected_outputs, logical, prop,
                                                 active_outputs(document, parameters, pseudo))
                values = []
                for key in keys:
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


def preflight(root, environment, directory, stack_names):
    """Local inputs only: same mapping validator as the deploy controller."""
    target = load_target(root, environment, directory)
    if target["iacEngine"] != "cloudformation":
        raise ValueError("mapping preflight requires CloudFormation target")
    values = properties(read_model(root / "model" / environment / directory / "cloudformation-stacks.properties"))
    _, stacks = stack_model(values)
    names = {stack["name"] for _, stack in stacks}
    if not stack_names or len(set(stack_names)) != len(stack_names) or set(stack_names) - names:
        raise ValueError("scope must contain unique designed StackName values")
    units = [stack for _, stack in stacks if stack["name"] in stack_names]
    templates, errors = {}, {}
    for unit in units:
        try:
            template = root / "infra/cloudformation/templates" / target.get("alias", "") / unit["template"]
            parameters = root / "infra/cloudformation/parameters" / environment / directory / unit["parameters"]
            templates[unit["name"]] = load_template_inputs(template, parameters)
        except (OSError, ValueError, Blocked) as error:
            errors.setdefault(unit["name"], []).append(f"{unit['name']}: input unavailable: {error}")
    try:
        plan = mappings(root, environment, directory, templates, [u for u in units if u["name"] in templates], target=target)
    except MappingError as error:
        errors.update(error.errors)
    if errors:
        raise MappingError(errors)
    return plan


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Read-only local CloudFormation resource/identifier preflight; no AWS calls")
    parser.add_argument("--environment", required=True)
    parser.add_argument("--target-directory", required=True)
    parser.add_argument("--stack", action="append", required=True)
    args = parser.parse_args()
    try:
        _, mapped = preflight(Path(__file__).resolve().parents[2], args.environment, args.target_directory, args.stack)
        print(f"CloudFormation mapping preflight: PASS ({len(mapped)} stacks)")
    except (OSError, ValueError, Blocked) as error:
        print(f"CloudFormation mapping preflight: FAIL ({error})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
