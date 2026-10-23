"""Collect only unambiguously mapped CloudFormation identifiers, then use model sync."""

import argparse
import hashlib
from functools import partial as _bind_framework_callback
from pathlib import Path

import sync_runtime as _imports_sync_runtime
from cloudformation_inputs import (
    Blocked,
    condition_active,
    load_target,
    load_template_inputs,
    output_value,
    resolve_value,
)
from design_catalog import DesignSchemaCatalog
from iac_values import cfn_resource_identity
from issue_gate import require_target_no_issues as require_target_no_issues
from task_contract_core import matches as matches
from task_contract_core import paths_in as paths_in
from task_contract_core import section as section
from task_contract_core import task_path as task_path
from utils.aws_catalogs import catalog_outputs
from utils.input_cache import input_scope
from utils.layout_schema import CODEBUILD_FORMAL_VARIABLE, GROUPED, HIDDEN_PROPERTIES
from utils.source_reads import FileReads
from validation_scope import active_scope

import model.observed as _imports_model_observed
import model.projection as _imports_model_projection
from model import projection as model_projection
from model.core import entries, properties, stack_model
from model.files import read_model, resource_row_index
from model.identity import Resolver, parse_reference, resource_link
from model.sources import (
    design_source_digest,
    input_snapshot,
    model_exists,
    model_paths,
    raw_model,
    scope_for,
)
from model.sources import (
    load_model as load_model,
)


def reference_key(value, path, resolver=None):
    scope = scope_for(path)
    producer, number, resource = (resolver or Resolver(scope.root)).resolve(value, scope)
    return (producer.scope.environment, producer.scope.target, producer.scope.service, resource['logicalId'])


def own_key(path, resource):
    scope = scope_for(path)
    return (scope.environment, scope.target, scope.service, resource['logicalId'])




def ambiguous(detail):
    raise ValueError("AMBIGUOUS_OBSERVED_MAPPING: " + detail)


class MappingError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("AMBIGUOUS_OBSERVED_MAPPING: " + "\n".join(
            detail for details in errors.values() for detail in details))


def models(root, environment, directory):
    return {path: properties(read_model(path)) for path in model_paths(root, environment, directory)
            if path.stem != "cloudformation-stacks"}


def resource_index(loaded, catalog):
    direct = {}
    for path, values in loaded.items():
        for identity, resource in entries(values, "desired.resource."):
            try:
                cfn_type = catalog.cloudformation_type(resource["resourceType"])
            except (KeyError, ValueError):
                cfn_type = None
            entry = (path, identity, resource, cfn_type)
            if "cfn-logicalId" in resource:
                direct.setdefault(cfn_resource_identity(resource["cfn-logicalId"]), []).append(entry)
    return direct


def validate_mapping_targets(root, environment, directory, values, *, definitions_root=None):
    """Validate resource-owned stack identities before templates exist."""
    bound_stack_names = _imports_model_projection.bound_stack_names
    stack_model(values)
    names = set(bound_stack_names(root / 'model' / environment / directory / 'cloudformation-stacks.properties')) or {
        stack['name'] for _, stack in entries(values, 'desired.stack.')}
    loaded = models(root, environment, directory)
    direct = resource_index(loaded, DesignSchemaCatalog(definitions_root or root))
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


def mapped_resource(direct, name, logical, cfn_type):
    candidates = direct.get((name, logical), [])
    if len(candidates) != 1:
        raise ValueError(f"cfn-logicalId matches={len(candidates)}; explicit mapping required")
    entry = candidates[0]
    if entry[2].get("resourceMode", "CREATE") != "CREATE":
        raise ValueError("cfn-logicalId requires CREATE")
    if entry[3] != cfn_type:
        raise ValueError(f"formal CFn type mismatch: {cfn_type} != {entry[3]}")
    return entry


def _recursive_static_export_handle_independent(document, parameters, pseudo, /, value):
    if isinstance(value, list):
        return all(_recursive_static_export_handle_independent(document, parameters, pseudo, item) for item in value)
    if not isinstance(value, dict):
        return True
    if "DependsOn" in value:
        return False
    # Check every branch/map value, including expressions unused by If/Sub.
    if not all(_recursive_static_export_handle_independent(document, parameters, pseudo, item) for item in value.values()):
        return False
    if any(key in {"Ref", "Condition"} or key.startswith("Fn::") for key in value):
        resolve_value(value, parameters, pseudo, conditions=document.get("Conditions", {}))
    return True


def static_export_handle(document, logical, parameters, pseudo):
    """Prove a Type-only scaffold has no resource-dependent template expressions."""
    if (document.get("Resources") != {logical: {"Type": "AWS::CloudFormation::WaitConditionHandle"}}
            or "Transform" in document):
        return False
    declarations, outputs = document.get("Parameters"), document.get("Outputs")
    if (not isinstance(declarations, dict) or logical in declarations
            or not isinstance(outputs, dict) or not outputs):
        return False
    if not all(isinstance(item, dict) and isinstance(item.get("Type"), str) for item in declarations.values()):
        return False
    parameters = {key: value for key, value in parameters.items() if key in declarations}
    for output in outputs.values():
        if not isinstance(output, dict):
            return False
        value, export = output.get("Value"), output.get("Export")
        if (not isinstance(value, dict) or set(value) != {"Ref"}
                or not isinstance(value["Ref"], str) or value["Ref"] not in declarations
                or not isinstance(export, dict) or set(export) != {"Name"}):
            return False

    independent = _bind_framework_callback(_recursive_static_export_handle_independent, document, parameters, pseudo)

    try:
        return independent(document) and all(
            isinstance(name := resolve_value(output["Export"]["Name"], parameters, pseudo), str) and bool(name)
            for output in outputs.values())
    except (Blocked, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return False


def require_fixed_stack_names(source, selected):
    bound_stack_names = _imports_model_projection.bound_stack_names
    bound = bound_stack_names(source)
    for fixed, desired in bound.items():
        if desired in selected and fixed != desired:
            ambiguous(f'{desired}: renamed stack requires explicit placement reconciliation; fixed StackName={fixed}')
    return bound


@input_scope
def _mappings(root, environment, directory, templates, units, removed=None, target=None, *, implementation=False, loaded=None, selection=None, identifiers=True):
    """Shared read-only implement/deploy validation; resource-owned IDs never fall back."""
    loaded = models(root, environment, directory) if loaded is None else loaded
    catalog = DesignSchemaCatalog(root) if loaded else None
    direct = resource_index(loaded, catalog)
    import_only = set()
    if implementation:
        modes = {}
        for values in loaded.values():
            for _, resource in entries(values, "desired.resource."):
                try:
                    cfn_type = catalog.cloudformation_type(resource["resourceType"])
                except (KeyError, ValueError):
                    continue
                mode = "mapped" if "cfn-logicalId" in resource else resource.get("resourceMode", "CREATE")
                modes.setdefault(cfn_type, set()).add(mode)
        import_only = {kind for kind, modes in modes.items() if kind and modes == {"IMPORT"}}
    integrated = {catalog.cloudformation_type(kind): (kind, rule) for kind, rule in GROUPED.items()
                  if rule["identityProperty"] is None} if catalog else {}
    source = root / "model" / environment / directory / "cloudformation-stacks.properties"
    values = properties(read_model(source)) if model_exists(source) else {}
    bound = require_fixed_stack_names(source, {unit['name'] for unit in units})
    if values:
        stack_model(values)
    target = target or (load_target(root, environment, directory) if (root / "project.json").is_file() else {})
    result, owners, errors = {}, {}, {}
    row_indexes = {}
    if values and selection is None:
        names = set(bound) or {stack["name"] for _, stack in entries(values, "desired.stack.")}
        for name, logical in direct:
            if name not in names:
                errors.setdefault(name, []).append(f"{name}/{logical}: cfn-logicalId references an undeclared stack")
    scope = active_scope(root)
    for unit in units:
        name = unit["name"]
        document, parameters = templates[name]
        pseudo = {"AWS::StackName": name} | {"AWS::" + key: target[value] for key, value in
                 (("AccountId", "awsAccountId"), ("Region", "awsRegion")) if value in target}
        if "awsExecutionAccountId" in target:
            pseudo["AWS::AccountId"] = target["awsExecutionAccountId"]
        result[name] = {}
        definitions = document.get("Resources", {}) | (removed or {}).get(name, {})
        try:
            output_values = active_outputs(document, parameters, pseudo) if identifiers else {}
        except (ValueError, Blocked) as error:
            errors.setdefault(name, []).append(f"{name}/Outputs: {error}")
            output_values = {}
        for logical, definition in definitions.items():
            if selection is not None and logical not in selection.get(name, set()):
                continue
            deleting = logical in (removed or {}).get(name, {})
            try:
                if (not deleting and (name, logical) not in direct
                        and static_export_handle(document, logical, parameters, pseudo)):
                    continue
                if not deleting and not condition_active(document, parameters, pseudo, definition):
                    continue
                if not deleting and definition["Type"] in import_only:
                    continue
                kind, rule = integrated.get(definition["Type"], (None, None))
                if rule:
                    reference = output_value(document, parameters, pseudo,
                                             definition.get("Properties", {}).get(rule["parentProperty"]))
                    if not isinstance(reference, dict) or set(reference) != {"Ref"} or not isinstance(reference["Ref"], str):
                        raise ValueError("integrated child requires an unambiguous local parent Ref")
                    parent_logical = reference["Ref"]
                    parent = definitions.get(parent_logical, {})
                    parent_type = catalog.cloudformation_type(rule["parent"])
                    if parent.get("Type") != parent_type or (not deleting and not condition_active(document, parameters, pseudo, parent)):
                        raise ValueError("integrated child parent missing, inactive or formal CFn type mismatch")
                    if not deleting and parent_type in import_only:
                        continue
                    entry = mapped_resource(direct, name, parent_logical, parent_type)
                else:
                    entry = mapped_resource(direct, name, logical, definition["Type"])
                path, identity, resource, _ = entry
                service = tuple(path.relative_to(root / "model").with_suffix("").parts)
                if scope is not None and service not in scope:
                    raise ValueError(f"task scope violation: stack resource outside Validation scope: {'/'.join(service)}")
                owner = (path, identity, kind or resource["resourceType"])
                if owner in owners:
                    previous = owners[owner]
                    errors.setdefault(previous[0], []).append(f"{previous[0]}/{previous[1]}: model resource also owned by {name}/{logical}")
                    raise ValueError(f"model resource also owned by {previous[0]}/{previous[1]}")
                owners[owner] = (name, logical)
                outputs = set() if rule else catalog_outputs(root, resource["resourceType"]) - HIDDEN_PROPERTIES
                if path not in row_indexes:
                    row_indexes[path] = resource_row_index(loaded[path])
                rows = [(rid, dict(row)) for rid, row in row_indexes[path].get(identity, ())]
                if rule:
                    rows = [(rid, row) for rid, row in rows if row["property"].startswith(kind + ".")]
                    if not rows:
                        raise ValueError(f"integrated child settings missing from parent model: {kind}")
                for prop in outputs if identifiers else ():
                    selected = [(rid, row) for rid, row in rows if row["property"] == prop]
                    link = resource_link(selected[0][1]["value"]) if len(selected) == 1 else None
                    if not link:
                        errors.setdefault(name, []).append(f"{name}/{logical}: identifier row missing/ambiguous: {prop}")
                    elif reference_key(link[0], path) != own_key(path, resource):
                        errors.setdefault(name, []).append(f"{name}/{logical}: identifier must reference its own Resource reference: {prop}")
                    primary, keys = identifier_source(catalog, resource, outputs, logical, prop, output_values)
                    if not deleting and not primary and not keys:
                        errors.setdefault(name, []).append(f"{name}/{logical}: required GetAtt Output missing: {prop}")
                result[name][logical] = (path, identity, resource, rows, outputs)
            except (ValueError, Blocked) as error:
                errors.setdefault(name, []).append(f"{name}/{logical}: {error}")
    if errors:
        raise MappingError(errors)
    return loaded, result


@input_scope
def mappings(root, environment, directory, templates, units, removed=None, target=None, *, implementation=False):
    return _mappings(root, environment, directory, templates, units, removed, target, implementation=implementation)


def resolve_resources(root, environment, directory, templates, units, selected, removed=None, target=None, *, identifiers=True):
    """Discover explicit ownership from raw metadata, validate only requested identities.

    Unrelated authorities are not expanded or diagnosed. No naming inference is used.
    """
    wanted = set()
    target = target or (load_target(root, environment, directory) if (root / 'project.json').is_file() else {})
    catalog = DesignSchemaCatalog(root)
    for unit in units:
        document, parameters = templates[unit['name']]
        pseudo = {'AWS::StackName': unit['name']} | {
            'AWS::' + key: target[value] for key, value in
            (('AccountId', 'awsAccountId'), ('Region', 'awsRegion')) if value in target}
        if 'awsExecutionAccountId' in target:
            pseudo['AWS::AccountId'] = target['awsExecutionAccountId']
        definitions = document.get('Resources', {}) | (removed or {}).get(unit['name'], {})
        for logical in selected.get(unit['name'], ()):
            definition = definitions.get(logical, {})
            deleting = logical in (removed or {}).get(unit['name'], {})
            if not deleting and not condition_active(document, parameters, pseudo, definition):
                continue
            wanted.add((unit['name'], logical))
            rules = [rule for kind, rule in GROUPED.items()
                     if rule['identityProperty'] is None and catalog.cloudformation_type(kind) == definition.get('Type')]
            if rules:
                parent = output_value(document, parameters, pseudo,
                    definition.get('Properties', {}).get(rules[0]['parentProperty']))
                if not isinstance(parent, dict) or set(parent) != {'Ref'} or not isinstance(parent['Ref'], str):
                    ambiguous(f"{unit['name']}/{logical}: integrated child parent evidence unavailable")
                parent_definition = definitions.get(parent['Ref'], {})
                if (parent_definition.get('Type') != catalog.cloudformation_type(rules[0]['parent'])
                        or not deleting and not condition_active(document, parameters, pseudo, parent_definition)):
                    ambiguous(f"{unit['name']}/{logical}: integrated child parent missing, inactive or formal CFn type mismatch")
                wanted.add((unit['name'], parent['Ref']))
    wanted = {name + '-' + logical for name, logical in wanted}
    loaded, reads = {}, FileReads()
    for path in model_paths(root, environment, directory, reads):
        if path.stem == 'cloudformation-stacks':
            continue
        raw = raw_model(path, reads)
        owners = any(key.startswith('desired.resource.') and key.endswith('.cfn-logicalId')
                     and value in wanted
                     for key, value in raw.authoritative.items())
        if owners:
            loaded[path] = properties(read_model(path))
    return _mappings(root, environment, directory, templates, units, removed, target,
                     loaded=loaded, selection=selected, identifiers=identifiers)


def propagate_references(root, loaded, changes, identifiers, by_identifier=None):
    """Discover incoming links mechanically; both deploy and destroy use this scanner."""
    # Read out-of-target models only if a raw incoming link reaches an updated identifier.
    # This is link discovery, not validation of unrelated prod/service designs.
    resolver = Resolver(root)
    incoming = {(*own_key(path, resource)[:3], resource.get('anchor'))
                for path, values in loaded.items() for _, resource in entries(values, 'desired.resource.')
                if own_key(path, resource) in identifiers}
    reads = FileReads()
    for path in model_paths(root, read_context=reads) if identifiers else []:
        if path in loaded or path.stem == "cloudformation-stacks":
            continue
        _ = (root / "docs/designs" / path.relative_to(root / "model")).with_suffix(".md")
        linked = False
        values = raw_model(path, reads).authoritative
        for key, value in values.items():
            link = resource_link(value) if key.startswith("desired.row.") and key.endswith(".value") else None
            if link:
                linked |= parse_reference(link[0], scope_for(path)) in incoming
        if linked:
            loaded[path] = properties(read_model(path))
    # Include every incoming reference, including out-of-scope ones; reject before any write.
    for path, values in loaded.items():
        _ = (root / "docs/designs" / path.relative_to(root / "model")).with_suffix(".md")
        for rid, row in entries(values, "desired.row."):
            link = resource_link(row["value"])
            if not link or row["property"] == CODEBUILD_FORMAL_VARIABLE + "Value":
                continue
            target = reference_key(link[0], path, resolver)
            if target in identifiers:
                changes.setdefault(path, {}).setdefault(f"observed.row.{rid}.value", identifiers[target])
                if by_identifier is not None:
                    by_identifier.setdefault(target, {}).setdefault(path, {})[f"observed.row.{rid}.value"] = identifiers[target]


def observed_destinations(root, environment, directory, loaded, changes, check_scope=True):
    """Plan exact model parts/views before writes, preserving desired/display bytes."""
    sync = _imports_sync_runtime
    scope = active_scope(root) if check_scope else None
    destinations = {}
    for path, updates in changes.items():
        service = tuple(path.relative_to(root / "model").with_suffix("").parts)
        if scope is not None and service not in scope or service[:2] != (environment, directory):
            raise ValueError(f"task scope violation: observed reference requires {'/'.join(service)}")
        observed_outputs = _imports_model_observed.observed_outputs
        projected = observed_outputs(path, {**loaded[path], **updates})
        if projected is None:
            raise ValueError(f'properties Model sources missing for observed update: {path}')
        destinations.update(projected)
    views = set()
    for path in changes:
        design = (root / "docs/designs" / path.relative_to(root / "model")).with_suffix(".md")
        views.add(design)
        for _, row in entries(loaded[path], "desired.row."):
            if match := model_projection.JSON_LINK.fullmatch(row["value"]):
                views.add((design.parent / match.group(1)).resolve())
    if not check_scope:
        return destinations, views, sync
    prompt = task_path(root)
    contract = prompt.read_text(encoding="utf-8")
    allowed = paths_in(contract, "## Allowed paths")
    if any(not any(matches(path.relative_to(root).as_posix(), p) for p in allowed) for path in set(destinations) | views):
        raise ValueError("task scope violation: observed model/view output outside Allowed paths")
    return destinations, views, sync


def destroy_plan(root, environment, directory, stack_names, check_scope=True):
    """Resolve ownership/identifier propagation without templates, parameters or AWS.

    Stack ownership requires explicit metadata.
    Unmapped designs without observed identifiers are reported, never synchronized.
    The returned plan is JSON serializable and remains stable after observed sync.
    """
    require_fixed_stack_names(root / 'model' / environment / directory / 'cloudformation-stacks.properties', stack_names)
    loaded = models(root, environment, directory)
    catalog = DesignSchemaCatalog(root) if loaded else None
    direct = resource_index(loaded, catalog)
    scope = active_scope(root) if check_scope else None
    for (name, logical), candidates in direct.items():
        if name in stack_names and any(resource.get("resourceMode", "CREATE") != "CREATE" or not formal
                                     for _, _, resource, formal in candidates):
            ambiguous(f"{name}/{logical}: destroy ownership requires CREATE and formal CloudFormation type")
    changes_by_stack = {name: {} for name in stack_names}
    anchors = {name: {} for name in stack_names}
    owners = {name: [] for name in stack_names}
    unmapped = []
    for path, values in loaded.items():
        rows = resource_row_index(values)
        for identity, resource in entries(values, "desired.resource."):
            if resource.get("resourceMode", "CREATE") != "CREATE":
                continue
            try:
                formal = catalog.cloudformation_type(resource["resourceType"])
            except (KeyError, ValueError):
                formal = None
            if not formal:
                continue
            outputs = catalog_outputs(root, resource["resourceType"]) - HIDDEN_PROPERTIES
            if not resource.get("cfn-logicalId"):
                for rid, row in rows[identity]:
                    if row["property"] in outputs and values.get(f"observed.row.{rid}.value") not in {
                            None, "PENDING_DEPLOY", "`PENDING_DEPLOY`"}:
                        ambiguous(f"{path.name}/{identity}: observed identifier requires explicit cfn-logicalId ownership")
                unmapped.append({"model": path.relative_to(root).as_posix(), "resource": identity,
                                 "logicalId": resource.get("logicalId"), "reason": "no cfn-logicalId; no observed identifier"})
                continue
            name, logical = cfn_resource_identity(resource["cfn-logicalId"])
            if name not in changes_by_stack:
                continue
            if len(direct[name, logical]) != 1:
                ambiguous(f"{name}/{logical}: duplicate ownership")
            service = tuple(path.relative_to(root / "model").with_suffix("").parts)
            if check_scope and service not in (scope or set()):
                raise ValueError(f"task scope violation: destroy ownership requires {'/'.join(service)}")
            owners[name].append({"model": path.relative_to(root).as_posix(), "resource": identity,
                                 "logicalId": logical})
            _ = (root / "docs/designs" / path.relative_to(root / "model")).with_suffix(".md")
            for prop in outputs:
                selected = [(rid, row) for rid, row in rows[identity] if row["property"] == prop]
                if len(selected) != 1:
                    ambiguous(f"{name}/{logical}: identifier row missing/ambiguous: {prop}")
                rid, row = selected[0]
                link = resource_link(row["value"])
                if not link or reference_key(link[0], path) != own_key(path, resource):
                    ambiguous(f"{name}/{logical}: identifier must reference its own Resource reference")
                changes_by_stack[name].setdefault(path, {})[f"observed.row.{rid}.value"] = "`PENDING_DEPLOY`"
                anchors[name][own_key(path, resource)] = "PENDING_DEPLOY"
    result, paths, services, inputs = {}, set(), set(), {}
    all_anchors = {}
    for name in stack_names:
        if all_anchors.keys() & anchors[name].keys():
            ambiguous("identifier Resource owned by multiple stacks")
        all_anchors.update(anchors[name])
    references = {}
    propagate_references(root, loaded, {}, all_anchors, references)
    for name in stack_names:
        services.update(tuple(Path(owner["model"]).relative_to("model").with_suffix("").parts) for owner in owners[name])
    for name in stack_names:
        changes = changes_by_stack[name]
        for anchor in anchors[name]:
            for path, updates in references.get(anchor, {}).items():
                for key, value in updates.items():
                    changes.setdefault(path, {}).setdefault(key, value)
        if changes:
            destinations, views, _ = observed_destinations(root, environment, directory, loaded, changes, check_scope)
            paths.update(destinations)
            paths.update(views)
        result[name] = {path.relative_to(root).as_posix(): updates for path, updates in changes.items()}
        for path in changes:
            services.add(tuple(path.relative_to(root / "model").with_suffix("").parts))
            # Intended inputs remain immutable, observed transitions are idempotent on resume.
            inputs[path.relative_to(root).as_posix()] = hashlib.sha256(
                (repr(sorted((key, value) for key, value in loaded[path].items()
                            if not key.startswith("observed."))) + design_source_digest(path)).encode()).hexdigest()
    return {"updates": result, "owners": owners, "paths": sorted(path.relative_to(root).as_posix() for path in paths),
            "services": sorted("/".join(service) for service in services), "inputs": inputs,
            "unmappedResources": unmapped}


def sync_destroyed(backend, states, plan):
    """Batch only proven deletions using the write plan established before mutation."""
    root, environment, directory = backend.root, backend.environment, backend.directory
    completed = [name for name, state in states.items()
                 if state["status"] == "DELETE_COMPLETE" and not state.get("observedSynced")]
    if not completed:
        return
    if any(not states[name].get("StackId") or not states[name].get("deleteObserved") for name in completed):
        raise ValueError("destroy observed sync requires pinned StackId and deletion evidence")
    loaded, changes = {}, {}
    for name in completed:
        for relative, updates in plan["updates"][name].items():
            path = root / relative
            values = properties(read_model(path))
            current = hashlib.sha256((repr(sorted((key, value) for key, value in values.items()
                                               if not key.startswith("observed."))) + design_source_digest(path)).encode()).hexdigest()
            if current != plan["inputs"][relative]:
                raise ValueError(f"destroy observed inputs changed: {relative}; resume after restoring inputs")
            loaded[path] = values
            changes.setdefault(path, {}).update(updates)
    if changes:
        destinations, views, sync = observed_destinations(root, environment, directory, loaded, changes)
        if {path.relative_to(root).as_posix() for path in set(destinations) | views} - set(plan["paths"]):
            raise ValueError("destroy observed output differs from pre-mutation output plan")
        publish_observed(root, destinations, {p: data for source in changes for p, data in input_snapshot(source).items()})
        if sync.sync(root, True, environment, directory, services=sorted({path.stem for path in changes})):
            raise ValueError("destroy observed sync failed; resume same session")
    for name in completed:
        states[name]["observedSynced"] = True


@input_scope
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
        plan = mappings(root, environment, directory, templates, [u for u in units if u["name"] in templates],
                        target=target, implementation=True)
    except MappingError as error:
        errors.update(error.errors)
    if errors:
        raise MappingError(errors)
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only local CloudFormation resource/identifier preflight; no AWS calls")
    parser.add_argument("--environment", required=True)
    parser.add_argument("--target-directory", required=True)
    parser.add_argument("--stack", action="append", required=True)
    args = parser.parse_args(argv)
    try:
        _, mapped = preflight(Path.cwd(), args.environment, args.target_directory, args.stack)
        print(f"CloudFormation mapping preflight: PASS ({len(mapped)} stacks)")
    except (OSError, ValueError, Blocked) as error:
        print(f"CloudFormation mapping preflight: FAIL ({error})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def publish_observed(root, destinations, inputs=None):
    publish_observed_candidates = _imports_model_observed.publish_observed_candidates
    publish_observed_candidates(root, destinations, inputs)
