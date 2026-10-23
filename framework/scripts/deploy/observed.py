"""Post-success synchronization and execution-bound deletion evidence."""
from pathlib import Path
import re
from cloudformation_inputs import Blocked
from design_catalog import DesignSchemaCatalog
from model.adapters.observed import (ambiguous, resolve_resources, active_outputs, identifier_source,
    reference_key, own_key, propagate_references, observed_destinations, publish_observed)
from model.identity import resource_link
from model.sources import input_snapshot
from issue_gate import require_target_no_issues


def removed_resources(units, states):
    result = {}
    for unit in units:
        state = states[unit['name']]
        evidence = state.get('executionEvidence')
        changes = evidence.get('resources', []) if evidence else state.get('changes', [])
        removed = {}
        for change in changes:
            if change['Action'] != 'Remove':
                continue
            definition = {'Type': change['ResourceType'], 'PolicyAction': change.get('PolicyAction'),
                          'PhysicalResourceId': change.get('PhysicalResourceId')}
            if change.get('parentLogicalId'):
                definition['Properties'] = {change['parentProperty']: {'Ref': change['parentLogicalId']}}
            removed[change['LogicalResourceId']] = definition
        result[unit['name']] = removed
    return result


def collect_successful(backend, units, states, *, generated_views=None):
    """Resolve exact candidates from fresh successful Stack reads without writing."""
    root, environment, directory = backend.root, backend.environment, backend.directory
    require_target_no_issues(root, (environment, directory))
    removed = removed_resources(units, states)
    selected = {}
    from design_layout import GROUPED
    grouped = {DesignSchemaCatalog(root).cloudformation_type(kind) for kind, rule in GROUPED.items() if rule['identityProperty'] is None}
    from cloudformation_inputs import condition_active
    for unit in units:
        name = unit['name']
        document, parameters = backend.templates[name]
        pseudo = {'AWS::StackName': name, 'AWS::Region': backend.target['awsRegion'],
                  'AWS::AccountId': backend.target.get('awsExecutionAccountId', backend.target['awsAccountId'])}
        selected[name] = {logical for logical, definition in document.get('Resources', {}).items()
                          if condition_active(document, parameters, pseudo, definition)} | {logical for logical, definition in removed[name].items() if definition['Type'] not in grouped}
    loaded, mapped = resolve_resources(root, environment, directory, backend.templates, units, selected, removed, target=backend.target)
    catalog = DesignSchemaCatalog(root) if loaded else None
    changes, identifiers = {}, {}
    for unit in units:
        name = unit["name"]
        document, parameters = backend.templates[name]
        if not mapped[name]:
            continue
        stack = backend.aws("describe_stacks", StackName=name)["Stacks"][0]
        planned = getattr(backend, 'session', {}).get('pendingObserved', {}).get('evidence', {}).get(name)
        if planned and (stack.get('StackId') != planned['stackId'] or stack.get('StackStatus') != planned['stackStatus']):
            ambiguous(f'{name}: saved successful Stack identity/status changed')
        if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}:
            ambiguous(f"{name}: stack no longer terminal success")
        outputs = {item["OutputKey"]: item["OutputValue"] for item in stack.get("Outputs", [])}
        actuals = backend.aws("list_stack_resources", StackName=name).get("StackResourceSummaries", [])
        by_logical = {}
        for actual in actuals:
            logical = actual["LogicalResourceId"]
            if logical in by_logical:
                ambiguous(f"{name}/{logical}: duplicate actual resource")
            by_logical[logical] = actual
        for logical, (path, identity, resource, rows, selected_outputs) in mapped[name].items():
            if logical in removed.get(name, {}):
                if not selected_outputs:
                    continue  # Integrated children have no independent identifier to reset.
                if not deleted_resource(backend, name, logical, removed[name][logical], states[name], by_logical):
                    continue
                for rid, row in rows:
                    if row["property"] in selected_outputs:
                        changes.setdefault(path, {})[f"observed.row.{rid}.value"] = "`PENDING_DEPLOY`"
                        design = (root / "docs/designs" / path.relative_to(root / "model")).with_suffix(".md")
                        identifiers[own_key(path, resource)] = "PENDING_DEPLOY"
                continue
            definition = document["Resources"][logical]
            actual = by_logical.get(logical)
            if not actual or actual["ResourceType"] != definition["Type"]:
                ambiguous(f"{name}/{logical}: actual resource missing/type mismatch")
            for rid, row in rows:
                prop = row["property"]
                if prop not in selected_outputs:
                    continue
                pseudo = {"AWS::StackName": name, "AWS::AccountId": backend.target.get("awsExecutionAccountId", backend.target["awsAccountId"]), "AWS::Region": backend.target["awsRegion"]}
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
                link = resource_link(row["value"])
                design = (root / "docs/designs" / path.relative_to(root / "model")).with_suffix(".md")
                if not link or reference_key(link[0], path) != own_key(path, resource):
                    ambiguous(f"{name}/{logical}: identifier must reference its own Resource reference")
                anchor_key = own_key(path, resource)
                if anchor_key in identifiers and identifiers[anchor_key] != value:
                    ambiguous(f"{name}/{logical}: multiple identifiers for one Resource")
                identifiers[anchor_key] = value
                changes.setdefault(path, {})[f"observed.row.{rid}.value"] = f"`{value}`"
    propagate_references(root, loaded, changes, identifiers)
    if not changes:
        return {}, [], None
    destinations, views, sync = observed_destinations(root, environment, directory, loaded, changes)
    if generated_views is not None:
        generated_views.update(views)
    return destinations, sorted({path.stem for path in changes}), sync


def sync_successful(backend, units, states):
    """Keep successful AWS state while the Model and generated views cross their barrier."""
    from deploy.observed_resume import prepare, finish
    if getattr(backend, 'session', {}).get('pendingObserved'):
        destinations = finish(backend, units)
        names = backend.session['pendingObserved']['evidence']
    else:
        views = set()
        destinations, services, sync = collect_successful(backend, units, states, generated_views=views)
        names = [unit['name'] for unit in units]
        if services:
            if getattr(backend, 'session', {}).get('modelInputManifest') is not None:
                prepare(backend, units, destinations, services, views)
                finish(backend, units)
            else:
                root = backend.root
                publish_observed(root, destinations, {path: raw for service in services
                    for path, raw in input_snapshot(root / 'model' / backend.environment / backend.directory / (service + '.properties')).items()})
                if sync.sync(root, True, backend.environment, backend.directory, services=services):
                    raise ValueError("observed model sync/validation failed; resume same session after resolving blocker")
    for name in names:
        states[name]['observedSynced'] = True
    return destinations or None




def deleted_resource(runtime, name, logical, removal, state, actuals):
    """A Remove is intent. Only execution-bound physical destruction resets an identifier."""
    if removal['PolicyAction'] in {'Retain', 'RetainExceptOnCreate'}:
        return False
    evidence = state.get('executionEvidence', {})
    if any(evidence.get(key) != state.get(field) for key, field in (
            ('StackId', 'stackId'), ('ChangeSetId', 'changeSetId'), ('changeDigest', 'changeDigest'),
            ('clientToken', 'clientToken'))):
        ambiguous(f'{name}/{logical}: original execution evidence missing or changed')
    if not evidence or not removal.get('PhysicalResourceId'):
        ambiguous(f'{name}/{logical}: physical deletion identity unknown')
    if removal['PolicyAction'] not in {'Delete', 'Snapshot'}:
        ambiguous(f'{name}/{logical}: removal policy is unknown')
    actual = actuals.get(logical)
    if actual and actual.get('ResourceStatus') == 'DELETE_SKIPPED':
        return False
    if actual and actual.get('ResourceStatus') == 'DELETE_COMPLETE' and all(
            actual.get(key) == removal.get(key if key != 'ResourceType' else 'Type')
            for key in ('PhysicalResourceId', 'ResourceType')):
        return True
    events = runtime.aws('describe_stack_events', StackName=evidence['StackId'])['StackEvents']
    matched = [event for event in events if event.get('LogicalResourceId') == logical
               and event.get('ResourceType') == removal['Type']
               and event.get('PhysicalResourceId') == removal['PhysicalResourceId']
               and event.get('ClientRequestToken') == evidence['clientToken']
               and event.get('StackId') == evidence['StackId']]
    if any(event.get('ResourceStatus') == 'DELETE_SKIPPED' for event in matched):
        return False
    if not any(event.get('ResourceStatus') == 'DELETE_COMPLETE' for event in matched):
        ambiguous(f'{name}/{logical}: physical destruction is unconfirmed')
    return True
