"""Model-derived repair evidence, exact candidate application and pinned CREATE cleanup."""
import copy
import hashlib
import json
import re
import time
import uuid
from pathlib import Path

from iac_values import cfn_resource_identity
from comparison_rows import put_row
from issues_iac import Comparison
from iac_values import same, fingerprint
from cloudformation_inputs import Blocked, resolve_value, condition_active, output_value
from task_contract import require_writable
from validation_scope import active_scope as validation_scope
from deployment.scheduler import SUCCESS


def repair_template(text, logical, prop, value):
    """Change one property using source spans, preserving all other YAML bytes."""
    import yaml
    value = json.loads(json.dumps(value))
    if text.lstrip().startswith('{'):
        document = json.loads(text)
        document['Resources'][logical].setdefault('Properties', {})[prop] = value
        return json.dumps(document, ensure_ascii=False, indent=2) + '\n'
    class Dumper(yaml.SafeDumper):
        pass
    def intrinsic(dumper, item):
        if len(item) == 1:
            key, argument = next(iter(item.items()))
            if key == 'Ref' or key.startswith('Fn::'):
                tag = '!' + key.removeprefix('Fn::')
                if isinstance(argument, list):
                    return dumper.represent_sequence(tag, argument, flow_style=True)
                if isinstance(argument, dict):
                    return dumper.represent_mapping(tag, argument, flow_style=True)
                return dumper.represent_scalar(tag, str(argument))
        return dumper.represent_dict(item)
    Dumper.add_representer(dict, intrinsic)
    node = yaml.compose(text)
    def child(node, key):
        found = [value for name, value in node.value if name.value == key]
        if len(found) != 1:
            raise Blocked('missing/ambiguous YAML mapping: ' + key)
        return found[0]
    resource = child(child(node, 'Resources'), logical)
    properties_nodes = [val for key, val in resource.value if key.value == 'Properties']
    missing_properties = not properties_nodes
    properties_node = child(resource, 'Properties') if properties_nodes else resource
    rendered = yaml.dump({prop: value}, Dumper=Dumper, allow_unicode=True, sort_keys=False).rstrip()
    found = [(key, val) for key, val in properties_node.value if key.value == prop]
    if len(found) > 1:
        raise Blocked('duplicate YAML property')
    if missing_properties:
        found = []
    if properties_node.flow_style:
        mapping = {'Properties': {prop: value}} if missing_properties else {prop: value}
        flow = yaml.dump(mapping, Dumper=Dumper, allow_unicode=True, sort_keys=False,
                         default_flow_style=True, width=1000000).strip()[1:-1]
        if found:
            key, val = found[0]
            start, end = key.start_mark.index, val.end_mark.index
        else:
            start = end = properties_node.end_mark.index - 1
            flow = (', ' if properties_node.value else '') + flow
        result = text[:start] + flow + text[end:]
    elif found:
        key, val = found[0]
        start = text.rfind('\n', 0, key.start_mark.index) + 1
        end = val.end_mark.index
        # A block node ends at the next key's indentation; do not consume that key.
        end = text.rfind('\n', 0, end) + 1 if not text[text.rfind('\n', 0, end)+1:end].strip() else end
        if end < len(text) and text[end] == '\n':
            end += 1
        indent = key.start_mark.column
    elif not properties_node.flow_style:
        start = end = properties_node.end_mark.index
        if not text[text.rfind('\n', 0, end)+1:end].strip():
            start = end = text.rfind('\n', 0, end) + 1
        indent = properties_node.start_mark.column
    if not properties_node.flow_style:
        if missing_properties:
            rendered = 'Properties:\n' + '\n'.join('  ' + line for line in rendered.splitlines())
        replacement = '\n'.join(' ' * indent + line for line in rendered.splitlines()) + '\n'
        result = text[:start] + replacement + text[end:]
    # Fail closed if the source-span edit touched anything except the selected property.
    from cfnlint.decode import decode_str as loads
    before, errors = loads(text)
    after, later = loads(result)
    expected = copy.deepcopy(before)
    expected['Resources'][logical].setdefault('Properties', {})[prop] = value
    if errors or later or not same(json.loads(json.dumps(expected)), json.loads(json.dumps(after))):
        raise Blocked('repair source edit changed unrelated template content')
    return result


def merge_selected(actual, desired, prop=""):
    if isinstance(actual, dict) and isinstance(desired, dict):
        return dict(actual) | {key: merge_selected(actual.get(key), val, key) for key, val in desired.items()}
    if isinstance(actual, list) and isinstance(desired, list) and prop in {'Tags', 'HostedZoneTags'}:
        if not all(isinstance(item, dict) and 'Key' in item for item in actual + desired):
            raise Blocked('ambiguous keyed tag setting')
        replacements = {item['Key']: item for item in desired}
        if len(replacements) != len(desired) or len({item['Key'] for item in actual}) != len(actual):
            raise Blocked('duplicate tag identities')
        result = [merge_selected(item, replacements.pop(item['Key'])) if item['Key'] in replacements else item for item in actual]
        return result + list(replacements.values())
    if isinstance(actual, list) and isinstance(desired, list) and len(actual) != len(desired) and any(isinstance(item, dict) for item in actual + desired):
        raise Blocked('partial object-array membership cannot be changed without complete design')
    if isinstance(actual, list) and isinstance(desired, list) and len(actual) == len(desired):
        return [merge_selected(a, b) for a, b in zip(actual, desired)]
    return desired


def repair_plan(root, environment, directory, target, mapping_plan, paths, aws, unit, state):
    """Use the existing typed model projection; error text selects scope, never values."""
    scope = validation_scope(root)
    if not scope:
        raise Blocked('repair needs explicit service Validation scope')
    owned = mapping_plan[1].get(unit['name'], {})
    affected = {owned[event['LogicalResourceId']][0].stem for event in state.get('failureEvents', [])
                if event.get('LogicalResourceId') in owned}
    comparison = Comparison(root, environment, directory,
                            sorted(affected) or [service for env, directory, service in scope
                             if (env, directory) == (environment, directory) and service != 'cloudformation-stacks'])
    if comparison.load_errors:
        raise Blocked('authoritative repair model cannot be loaded')
    path, (document, _, _) = comparison.stack(unit)
    failed = [event for event in state.get('failureEvents', [])
              if event['ResourceType'] != 'AWS::CloudFormation::Stack' and event['ResourceStatus'].endswith('_FAILED')
              and 'cancel' not in (event.get('ResourceStatusReason') or '').lower()]
    if not failed:
        raise Blocked('no resource failure diagnostics tied to this execution')
    direct, legacy = comparison.index()
    from cloudformation_observed import mapped_resource
    from model_references import catalog_outputs
    edits, classes, export_snapshot, producer_snapshots = [], [], {}, {}
    for event in failed:
        logical = event['LogicalResourceId']
        definition = document.get('Resources', {}).get(logical)
        if not definition or definition['Type'] != event['ResourceType']:
            raise Blocked('failed resource outside authoritative template ownership')
        source, identity, resource, _ = mapped_resource(direct, legacy, unit['name'], logical, definition['Type'], True)
        if (environment, directory, source.stem) not in scope:
            raise Blocked('failure outside service task scope')
        comparison.results = []
        comparison.compare_rows(source.stem, identity, resource, unit['name'], logical, path, definition, document)
        differences = [item for item in comparison.results if item['category'] == 'difference']
        reason = (event.get('ResourceStatusReason') or '').lower()
        kind = resource['resourceType']
        # Stable classes ignore request IDs and changing physical IDs.
        selector = ('VpcConfig' if kind == 'Lambda.Function' and 'subnet' in reason else
                    'CatalogId' if kind.startswith('Glue.') and ('catalog' in reason or 'accessdenied' in reason or 'access denied' in reason) else
                    next((key for key in ('KmsKeyId', 'KmsKeyArn', 'TargetKeyId', 'KeyPolicy')
                          if any(item['property'] == kind + '.' + key for item in differences)), None)
                    if 'kms' in reason or kind.startswith('KMS.') else None)
        selected = [item for item in differences if selector and item['property'] == kind + '.' + selector
                    or not selector and item['property'].rsplit('.', 1)[-1].lower() in reason]
        if not selected:
            def mentioned(item):
                if isinstance(item, dict):
                    return any(mentioned(value) for value in item.values())
                if isinstance(item, list):
                    return any(mentioned(value) for value in item)
                return isinstance(item, str) and len(item) >= 8 and item.lower() in reason
            selected = [item for item in differences if mentioned(definition.get('Properties', {}).get(
                item['property'].removeprefix(kind + '.')))]
        if len(selected) != 1:
            raise Blocked('failure has no unique model-derived property correction')
        prop = selected[0]['property'].removeprefix(kind + '.')
        if '.' in prop or prop in catalog_outputs(root, kind):
            raise Blocked('repair needs explicit property ownership')
        desired, exact = {}, False
        for _, row in comparison.rows[source.stem][identity]:
            short = row['property'].removeprefix(kind + '.')
            if short == 'Name' and kind in {'EC2.VPC', 'EC2.Subnet', 'EC2.RouteTable', 'EC2.FlowLog'} and prop == 'Tags':
                from policy_tables import literal
                put_row(desired, 'Tags[]', {'Key': 'Name', 'Value': literal(row['value'])})
            elif row['property'].startswith(kind + '.') and short.split('.', 1)[0].removesuffix('[]') == prop:
                put_row(desired, short, comparison.desired_value(source.stem, row, kind))
                exact |= short == prop
        if prop not in desired:
            raise Blocked('repair projection incomplete')
        def render(value):
            if isinstance(value, dict) and '$resource' in value:
                service, rid = value['$resource']
                referenced = comparison.resources[service][rid]
                name, ref = cfn_resource_identity(referenced['cfn-logicalId'])
                attr = value['$attribute']
                primary = comparison.catalog.schema(referenced['resourceType']).get('primaryIdentifier', [])
                expression = {'Ref': ref} if primary == ['/properties/' + attr] else {'Fn::GetAtt': [ref, attr]}
                if name != unit['name']:
                    # Never invent an export or alter a producer during consumer repair.
                    producer = next((u for _, u in comparison.templates() if u['name'] == name), None)
                    if not producer:
                        raise Blocked('reference producer unknown')
                    comparison.stack(producer)
                    producer_doc, params, pseudo = comparison.stack_inputs[name]
                    candidates = [resolve_value(output['Export']['Name'], params, pseudo, conditions=producer_doc.get('Conditions', {}))
                                  for output in producer_doc.get('Outputs', {}).values()
                                  if condition_active(producer_doc, params, pseudo, output)
                                  and output_value(producer_doc, params, pseudo, output.get('Value')) == expression and 'Export' in output]
                    if len(candidates) != 1:
                        raise Blocked('reference export ambiguous/missing')
                    if 'exports' not in export_snapshot:
                        export_snapshot['exports'] = aws('list-exports').get('Exports', [])
                    exports = export_snapshot['exports']
                    owners = [entry for entry in exports if entry['Name'] == candidates[0]
                              and entry.get('ExportingStackId', '').split(':stack/')[-1].split('/')[0] == name]
                    if len(owners) != 1:
                        raise Blocked('reference export current owner not confirmed')
                    if name not in producer_snapshots:
                        producer_snapshots[name] = (aws('describe-stacks', '--stack-name', name)['Stacks'][0],
                                                    aws('get-template', '--stack-name', name)['TemplateBody'])
                    current, actual = producer_snapshots[name]
                    if current['StackStatus'] not in SUCCESS:
                        raise Blocked('reference producer is not terminal success')
                    if isinstance(actual, str):
                        from cfnlint.decode import decode_str
                        actual, errors = decode_str(actual)
                        if errors:
                            raise Blocked('reference producer template unreadable')
                    if actual.get('Resources', {}).get(ref, {}).get('Type') != comparison.catalog.cloudformation_type(referenced['resourceType']):
                        raise Blocked('reference producer actual resource ownership differs')
                    current_params = {key: str(val['Default']) for key, val in actual.get('Parameters', {}).items() if 'Default' in val}
                    current_params.update({item['ParameterKey']: item['ParameterValue'] for item in current.get('Parameters', [])})
                    actual_exports = [out for out in actual.get('Outputs', {}).values()
                        if condition_active(actual, current_params, pseudo, out) and 'Export' in out
                        and resolve_value(out['Export']['Name'], current_params, pseudo, conditions=actual.get('Conditions', {})) == candidates[0]
                        and output_value(actual, current_params, pseudo, out.get('Value')) == expression]
                    if len(actual_exports) != 1:
                        raise Blocked('reference export actual value expression differs from approved model')
                    return {'Fn::ImportValue': candidates[0]}
                return expression
            if isinstance(value, dict):
                return {key: render(val) for key, val in value.items()}
            if isinstance(value, list):
                return [render(val) for val in value]
            return value
        value = render(desired[prop])
        if prop == 'CatalogId' and value == target.get('awsExecutionAccountId', target['awsAccountId']):
            value = {'Ref': 'AWS::AccountId'}
        # Retain unspecified nested settings, including security/policy statements.
        actual = definition.get('Properties', {}).get(prop)
        if not exact:
            if isinstance(actual, dict) and any(key.startswith('Fn::') or key == 'Ref' for key in actual):
                raise Blocked('partial setting behind intrinsic is ambiguous')
            value = merge_selected(actual, value, prop)
        if len(failed) == 1 and isinstance(actual, dict) and set(actual) == {'Ref'} and actual['Ref'] in document.get('Parameters', {}) and isinstance(value, (str, bool, int, float)):
            parameter = actual['Ref']
            def uses(item):
                if isinstance(item, dict):
                    return int(item == {'Ref': parameter}) + sum(uses(child) for child in item.values()) + sum(
                        str(child).count('${' + parameter + '}') for key, child in item.items() if key == 'Fn::Sub')
                return sum(uses(child) for child in item) if isinstance(item, list) else 0
            if uses(document) != 1:
                raise Blocked('parameter has other consumers; repair value is not proven for every use')
            parameter_path = paths(unit)[1]
            inputs = json.loads(parameter_path.read_text(encoding='utf-8'))
            matches = [item for item in inputs if item.get('ParameterKey') == parameter]
            if len(matches) != 1:
                raise Blocked('repair parameter explicit value missing/ambiguous')
            matches[0]['ParameterValue'] = str(value).lower() if isinstance(value, bool) else str(value)
            require_writable(root, [parameter_path])
            return parameter_path, json.dumps(inputs, ensure_ascii=False, indent=2) + '\n', logical + ':' + prop
        edits.append((logical, prop, value))
        classes.append(logical + ':' + prop)
    # A template repair cannot silently affect any other designed stack instance.
    for _, other in comparison.templates():
        if other['name'] != unit['name'] and other['template'] == unit['template']:
            raise Blocked('shared template affects another stack; scope decision required')
    text = path.read_text(encoding='utf-8')
    for logical, prop, value in edits:
        text = repair_template(text, logical, prop, value)
    if text == path.read_text(encoding='utf-8'):
        raise Blocked('no material repair progress')
    require_writable(root, [path])
    return path, text, '|'.join(sorted(set(classes)))


def cleanup_failed_create(templates, aws, save, wait_cleanup, unit, state, *, empty_only=False):
    if state.get('stackStatus') == 'PRE_EXECUTION':
        return
    if state.get('stackStatus') != 'ROLLBACK_COMPLETE':
        if state.get('stackStatus') != 'UPDATE_ROLLBACK_COMPLETE':
            raise Blocked('rollback recovery cannot be proven safe; no delete/ResourcesToSkip')
        return
    if not state.get('stackId'):
        raise Blocked('failed CREATE StackId missing; never delete by name')
    if state.get('cleanupStatus') == 'DELETE_COMPLETE' and state.get('cleanupStackId') == state['stackId']:
        return True
    if state.get('cleanupStatus') == 'DELETE_INTENT':
        try:
            current = aws('describe-stacks', '--stack-name', state['stackId'])['Stacks'][0]
        except Blocked as error:
            if 'does not exist' not in str(error):
                raise
            state['cleanupStatus'] = 'DELETE_COMPLETE'
            save()
            return True
        if current['StackId'] != state['stackId']:
            raise Blocked('interrupted cleanup stack identity changed')
        if current['StackStatus'] in {'DELETE_IN_PROGRESS', 'DELETE_COMPLETE'}:
            wait_cleanup(state)
            return True
        if current['StackStatus'] != 'ROLLBACK_COMPLETE':
            raise Blocked('interrupted cleanup state unsafe')
    document, _ = templates[unit['name']]
    stack = aws('describe-stacks', '--stack-name', state['stackId'])['Stacks'][0]
    if (stack['StackId'] != state['stackId'] or stack['StackStatus'] != 'ROLLBACK_COMPLETE'
            or stack.get('EnableTerminationProtection') or stack.get('ParentId') or stack.get('RootId')):
        raise Blocked('failed CREATE identity/state changed or protected')
    actuals = aws('list-stack-resources', '--stack-name', state['stackId'])['StackResourceSummaries']
    empty = all(item.get('ResourceStatus') == 'DELETE_COMPLETE' for item in actuals)
    if empty_only and not empty:
        return False
    if not empty:
        if (state.get('operationType') != 'CREATE' or not state.get('absentBeforeCreate')
                or state.get('operationStackId') != state['stackId']):
            raise Blocked('failed CREATE session provenance missing; never delete by name')
        if any(resource.get('DeletionPolicy', 'Delete') != 'Delete'
               or resource.get('UpdateReplacePolicy', 'Delete') != 'Delete'
               or resource['Type'].startswith(('Custom::', 'AWS::CloudFormation::'))
               for resource in document.get('Resources', {}).values()) or any(
                   event['ResourceStatus'] == 'DELETE_SKIPPED' for event in state.get('failureEvents', [])):
            raise Blocked('failed CREATE contains retained/custom resources; cleanup requires human')
    if not empty and any(item['ResourceStatus'] not in {'DELETE_COMPLETE', 'CREATE_FAILED'}
           or item['ResourceStatus'] == 'CREATE_FAILED' and item.get('PhysicalResourceId')
           or item.get('LogicalResourceId') not in document.get('Resources', {})
           or item.get('ResourceType') != document['Resources'][item['LogicalResourceId']]['Type']
           for item in actuals):
        raise Blocked('failed CREATE still owns resources; cleanup requires human')
    state.update(cleanupStatus='DELETE_INTENT', cleanupStackId=state['stackId'])
    save()
    aws('delete-stack', '--stack-name', state['stackId'])
    wait_cleanup(state)
    return True


def wait_cleanup(aws, save, state):
    for _ in range(120):
        try:
            current = aws('describe-stacks', '--stack-name', state['stackId'])['Stacks'][0]['StackStatus']
        except Blocked as error:
            if 'does not exist' not in str(error):
                raise
            current = 'DELETE_COMPLETE'
        if current == 'DELETE_COMPLETE':
            state['cleanupStatus'] = 'DELETE_COMPLETE'
            save()
            return
        if current != 'DELETE_IN_PROGRESS':
            raise Blocked('failed CREATE cleanup stopped: ' + current)
        time.sleep(5)
    raise Blocked('failed CREATE cleanup timeout; inspect same StackId before resuming')


def reset_after_cleanup(save, state):
    retained = {key: state[key] for key in ('repairs', 'cleanupStatus', 'cleanupStackId', 'emptyStackRecreated') if key in state}
    state.clear()
    state.update(retained, status='NOT_STARTED')
    save()


def finish_repair(refresh_validation, save, cleanup_failed_create, reset_after_cleanup, unit, state, entry):
    refresh_validation(unit)
    runtime = entry.get('classification') == 'RUNTIME_BOOTSTRAP'
    entry['stage'] = 'BOOTSTRAP_CONFIRMED' if runtime else 'VALIDATED'
    save()
    cleanup_failed_create(unit, state)
    if runtime:
        # Persist RETRY_READY and reset together; an interruption must not look like a new failure.
        entry['stage'] = 'RETRY_READY'
    reset_after_cleanup(state)
    entry['stage'] = 'RETRY_READY'
    save()


def resume_candidate(root, workdir, file_digest, input_digest, expected_digests, infra_manifest, save,
        finish_repair, unit, state, entry):
    path = root / entry['path']
    require_writable(root, [path])
    candidate_path = Path(entry['candidatePath']).resolve()
    if not candidate_path.is_relative_to(workdir.resolve()) or file_digest(candidate_path, fresh=True) != entry['newFileDigest']:
        raise Blocked('pending repair recovery copy missing/changed')
    if file_digest(path, fresh=True) == entry['oldFileDigest']:
        path.write_bytes(candidate_path.read_bytes())
    if file_digest(path, fresh=True) != entry['newFileDigest'] or input_digest(unit, fresh=True) != entry['newDigest']:
        raise Blocked('pending repair bytes changed')
    expected_digests[unit['name']] = entry['newDigest']
    infra_manifest[entry['path']] = entry['newFileDigest']
    entry['stage'] = 'VALIDATING'
    save()
    finish_repair(unit, state, entry)
    return True


def apply_candidate(root, workdir, file_digest, input_digest, deployment_input_paths, expected_digests,
        infra_manifest, save, finish_repair, unit, state, history, path, text, failure_class):
    logical_classes = set(failure_class.split('|'))
    attempts = [entry for entry in history if entry.get('classification', 'AUTO_REPAIRABLE') == 'AUTO_REPAIRABLE'
                and logical_classes & set(entry['failureClass'].split('|'))]
    candidate = hashlib.sha256(text.encode()).hexdigest()
    if any(sum(logical in entry['failureClass'].split('|') for entry in attempts) >= 3
           for logical in logical_classes) or any(entry['newFileDigest'] == candidate for entry in attempts):
        raise Blocked('repair iteration limit/no material progress for logical failure class')
    entry = {'classification': 'AUTO_REPAIRABLE', 'failureClass': failure_class,
             'path': path.relative_to(root).as_posix(), 'oldFileDigest': file_digest(path, fresh=True),
             'newFileDigest': candidate, 'oldDigest': input_digest(unit, fresh=True),
             'stage': 'REPAIR_INTENT', 'changeSetId': state.get('changeSetId')}
    workdir.mkdir(parents=True, exist_ok=True)
    candidate_path = workdir / ('repair-' + uuid.uuid4().hex + path.suffix)
    candidate_path.write_text(text, encoding='utf-8')
    entry['candidatePath'] = str(candidate_path)
    entry['newDigest'] = fingerprint([candidate if p == path else file_digest(p, fresh=True)
        for p in deployment_input_paths([unit])])
    history.append(entry)
    state['failureClassification'] = 'AUTO_REPAIRABLE'
    save()  # Persist authorized exact bytes before modifying IaC.
    path.write_text(text, encoding='utf-8')
    if input_digest(unit, fresh=True) != entry['newDigest']:
        raise Blocked('repair inputs changed outside the exact authorized candidate')
    expected_digests[unit['name']] = entry['newDigest']
    infra_manifest[entry['path']] = candidate
    entry['stage'] = 'VALIDATING'
    save()
    finish_repair(unit, state, entry)
    return True


