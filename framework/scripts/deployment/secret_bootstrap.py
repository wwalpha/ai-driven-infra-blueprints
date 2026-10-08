"""Proven CREATE Secret initialization with metadata-only reads and stable intent/token."""
import json
import re
import uuid

from cloudformation_inputs import Blocked, resolve_value, condition_active, output_value
from task_contract import task_path
from validation_scope import active_scope as validation_scope
from deployment.aws_adapter import SECRET_METADATA_QUERY, secret_value_missing
from deployment.change_sets import import_names
from deployment.scheduler import SUCCESS

BOOTSTRAP_STAGES = {'BOOTSTRAP_INTENT', 'VALUE_CHECKED_MISSING', 'PUT_SUBMITTED', 'BOOTSTRAP_CONFIRMED'}


def bootstrap_plan(root, environment, directory, target, templates, states, mapping_plan, mapping_units, aws,
        check_secret_arn, unit, state):
    """Resolve consumer references and CREATE ownership through existing mappings."""
    scope = validation_scope(root)
    owned = mapping_plan[1]
    document, parameters = templates[unit['name']]
    pseudo = {'AWS::AccountId': target.get('awsExecutionAccountId', target['awsAccountId']),
              'AWS::Region': target['awsRegion'], 'AWS::StackName': unit['name']}
    failed = [event for event in state.get('failureEvents', [])
              if event.get('ResourceType') != 'AWS::CloudFormation::Stack'
              and event.get('ResourceStatus', '').endswith('_FAILED')
              and 'cancel' not in (event.get('ResourceStatusReason') or '').lower()]
    if not failed or not all(secret_value_missing(e.get('ResourceStatusReason')) for e in failed):
        raise Blocked('runtime bootstrap requires only confirmed missing-current-value failures')
    for event in failed:
        logical = event['LogicalResourceId']
        mapping = owned.get(unit['name'], {}).get(logical)
        definition = document.get('Resources', {}).get(logical, {})
        if (not mapping or definition.get('Type') != event['ResourceType'] or not scope
                or (environment, directory, mapping[0].stem) not in scope
                or mapping[2].get('resourceMode', 'CREATE') != 'CREATE'):
            raise Blocked('consumer resource ownership/scope unknown')
    names = import_names(document, parameters, pseudo)
    entries = aws('list-exports').get('Exports', []) if names else []
    exports = {e['Name']: e['Value'] for e in entries}
    if len(exports) != len(entries) or names - exports.keys():
        raise Blocked('consumer Export resolution ambiguous/missing')
    local_secrets = {logical for logical, definition in document.get('Resources', {}).items()
                     if definition['Type'] == 'AWS::SecretsManager::Secret'
                     and condition_active(document, parameters, pseudo, definition)}
    if local_secrets:
        actuals = aws('list-stack-resources', '--stack-name', state['stackId'])['StackResourceSummaries']
        for logical in local_secrets:
            matches = [r for r in actuals if r.get('LogicalResourceId') == logical
                       and r.get('ResourceType') == 'AWS::SecretsManager::Secret']
            if len(matches) != 1 or not matches[0].get('PhysicalResourceId'):
                raise Blocked('local Secret Ref ownership unknown')
            pseudo[logical] = pseudo[logical + '.Id'] = matches[0]['PhysicalResourceId']

    references = []
    # These slots consume scalar credentials. Opaque JSON/rotation/application schemas are Human-only.
    scalar_slots = {'AWS::QuickSight::DataSource': {('Credentials', 'CredentialPair', 'Username'),
                                                   ('Credentials', 'CredentialPair', 'Password')},
                    'AWS::RDS::DBInstance': {('MasterUserPassword',)},
                    'AWS::RDS::DBCluster': {('MasterUserPassword',)},
                    'AWS::Glue::Connection': {('ConnectionInput', 'ConnectionProperties', 'USERNAME'),
                                              ('ConnectionInput', 'ConnectionProperties', 'PASSWORD')}}

    def visit(value, logical, kind, path=(), used_exports=frozenset()):
        value = output_value(document, parameters, pseudo, value)
        if isinstance(value, dict) and len(value) == 1 and next(iter(value)) in {'Ref', 'Fn::Sub', 'Fn::Join', 'Fn::ImportValue', 'Fn::GetAtt'}:
            marked = 'resolve:secretsmanager:' in json.dumps(value)
            used_exports |= import_names({'Conditions': document.get('Conditions', {}),
                                          'Resources': {'Value': {'Properties': value}}}, parameters, pseudo)
            try:
                if 'Fn::GetAtt' in value:
                    argument = value['Fn::GetAtt']
                    logical_id, attribute = argument.split('.', 1) if isinstance(argument, str) else argument
                    if attribute != 'Id' or logical_id not in local_secrets:
                        raise Blocked('unsupported Secret attribute')
                    value = pseudo[logical_id]
                else:
                    value = resolve_value(value, parameters, pseudo, exports, document.get('Conditions', {}))
            except Blocked:
                if marked:
                    raise Blocked('consumer Secret expression cannot be uniquely resolved') from None
                return
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, logical, kind, path + (key,), used_exports)
        elif isinstance(value, list):
            for child in value:
                visit(child, logical, kind, path + ('[]',), used_exports)
        elif isinstance(value, str) and 'resolve:secretsmanager:' in value:
            match = re.fullmatch(r'\{\{resolve:secretsmanager:(.+?):SecretString(?::([^:]*))?(?::([^:]*))?(?::([^:]*))?\}\}', value)
            if (not match or match[3] not in (None, '', 'AWSCURRENT') or match[4] not in (None, '')
                    or path not in scalar_slots.get(kind, set())):
                raise Blocked('consumer Secret schema/version selector unsupported or ambiguous')
            references.append((logical, match[1], match[2] or '', used_exports))
    for logical, definition in document.get('Resources', {}).items():
        if condition_active(document, parameters, pseudo, definition):
            visit(definition.get('Properties', {}), logical, definition['Type'])
    affected = {e['LogicalResourceId'] for e in failed}
    identifiers = {r[1] for r in references if r[0] in affected}
    if len(identifiers) != 1:
        raise Blocked('failed consumer Secret reference missing/ambiguous')
    identifier = identifiers.pop()
    if identifier.startswith('arn:'):
        check_secret_arn(identifier)
    metadata = aws('describe-secret', '--secret-id', identifier, service='secretsmanager')
    arn = metadata.get('ARN')
    check_secret_arn(arn)
    if identifier not in {arn, metadata.get('Name')}:
        raise Blocked('consumer Secret identifier does not match canonical identity')
    owners = []
    units = {u['name']: u for u in mapping_units}
    for name, resources in owned.items():
        owner_state = states.get(name, {})
        if owner_state.get('status') != 'SUCCESS' and not (
                name == unit['name'] and owner_state.get('stackStatus') == 'UPDATE_ROLLBACK_COMPLETE'):
            continue  # Uncreated later producers are not identity evidence for this consumer.
        candidates = [(logical, mapping) for logical, mapping in resources.items()
                      if mapping[2]['resourceType'] == 'SecretsManager.Secret']
        if not candidates:
            continue
        summaries = aws('list-stack-resources', '--stack-name', name)['StackResourceSummaries']
        if len({r['LogicalResourceId'] for r in summaries}) != len(summaries):
            raise Blocked('Secret stack resource mapping ambiguous')
        for logical, mapping in candidates:
            matches = [r for r in summaries if r.get('LogicalResourceId') == logical and r.get('PhysicalResourceId') == arn
                       and r.get('ResourceType') == 'AWS::SecretsManager::Secret'
                       and r.get('ResourceStatus') in {'CREATE_COMPLETE', 'UPDATE_COMPLETE'}]
            if matches:
                owners.append((name, logical, mapping))
    if len(owners) != 1:
        raise Blocked('Secret CREATE owner is unknown/external/ambiguous')
    name, logical, mapping = owners[0]
    source, identity, resource = mapping[:3]
    if (resource.get('resourceMode', 'CREATE') != 'CREATE' or resource.get('cfn-logicalId') != name + '-' + logical
            or (environment, directory, source.stem) not in scope or name not in units):
        raise Blocked('Secret is IMPORT or outside CREATE deployment ownership/scope')
    current = aws('describe-stacks', '--stack-name', name)['Stacks'][0]
    stack_id = current.get('StackId')
    if (stack_id != states[name].get('stackId') or not isinstance(stack_id, str)
            or stack_id.split(':', 5)[2:5] != ['cloudformation', target['awsRegion'], pseudo['AWS::AccountId']]
            or current.get('ParentId') or current.get('RootId')
            or current.get('StackStatus') not in SUCCESS | {'UPDATE_ROLLBACK_COMPLETE'}):
        raise Blocked('Secret owner StackId/account/region/state unconfirmed')
    actual = aws('get-template', '--stack-name', stack_id)['TemplateBody']
    if isinstance(actual, str):
        from cfnlint.decode import decode_str
        actual, errors = decode_str(actual)
        if errors:
            raise Blocked('Secret owner template unreadable')
    if not isinstance(actual, dict) or actual.get('Transform'):
        raise Blocked('Secret owner template dynamically generated/unknown')
    local, params = templates[name]
    actual_params = {key: str(value['Default']) for key, value in actual.get('Parameters', {}).items() if 'Default' in value}
    actual_params.update({p['ParameterKey']: p['ParameterValue'] for p in current.get('Parameters', [])})
    owner_pseudo = pseudo | {'AWS::StackName': name}
    for template, inputs in ((local, params), (actual, actual_params)):
        definition = template.get('Resources', {}).get(logical, {})
        if (definition.get('Type') != 'AWS::SecretsManager::Secret' or not condition_active(template, inputs, owner_pseudo, definition)
                or any(k in definition.get('Properties', {}) for k in ('SecretString', 'SecretBinary', 'GenerateSecretString'))):
            raise Blocked('Secret bootstrap differs from CREATE template ownership/initial-value design')
        expected_name = definition.get('Properties', {}).get('Name')
        if expected_name is not None and resolve_value(expected_name, inputs, owner_pseudo,
                conditions=template.get('Conditions', {})) != metadata.get('Name'):
            raise Blocked('Secret name differs from owning template')
        for export in {e for r in references if r[1] == identifier for e in r[3]}:
            entries_for_export = [e for e in entries if e['Name'] == export and e.get('ExportingStackId') == stack_id and e['Value'] == arn]
            outputs = [o for o in template.get('Outputs', {}).values() if 'Export' in o
                       and condition_active(template, inputs, owner_pseudo, o)
                       and resolve_value(o['Export']['Name'], inputs, owner_pseudo, conditions=template.get('Conditions', {})) == export
                       and output_value(template, inputs, owner_pseudo, o.get('Value')) in ({'Ref': logical}, {'Fn::GetAtt': [logical, 'Id']})]
            if len(entries_for_export) != 1 or len(outputs) != 1:
                raise Blocked('Secret Export owner/value expression unconfirmed')
    keys = {r[2] for r in references if r[1] in {arn, metadata.get('Name')}}
    if not keys or '' in keys and len(keys) > 1:
        raise Blocked('mixed/unknown Secret string and JSON schema')
    return {'bootstrapType': 'SECRETS_MANAGER_INITIAL_VALUE', 'consumerStack': unit['name'],
            'failureClass': '|'.join(sorted(logical + ':SecretCurrentValue' for logical in affected)),
            'secretId': arn, 'secretName': metadata['Name'], 'account': pseudo['AWS::AccountId'], 'region': target['awsRegion'],
            'owner': {'stack': name, 'stackId': stack_id, 'logicalId': logical, 'model': source.relative_to(root).as_posix(), 'resource': identity},
            'requiredJsonKeys': sorted(keys - {''}), 'valueType': 'JSON' if keys != {''} else 'STRING'}


def check_secret_arn(target, arn):
    match = re.fullmatch(r'arn:(aws|aws-cn|aws-us-gov):secretsmanager:([^:]+):(\d{12}):secret:([^:]+)', arn or '')
    partition = ('aws-cn' if target['awsRegion'].startswith('cn-') else
                 'aws-us-gov' if target['awsRegion'].startswith('us-gov-') else 'aws')
    if (not match or match[2] != target['awsRegion']
            or match[1] != partition or match[3] != target.get('awsExecutionAccountId', target['awsAccountId'])):
        raise Blocked('Secret account/region/identity mismatch')


def bootstrap_current(aws, entry):
    """Retrieve metadata only. Never return/log/persist SecretString or SecretBinary."""
    arn, token = entry['secretId'], entry['clientRequestToken']
    metadata = aws('describe-secret', '--secret-id', arn, service='secretsmanager')
    if (metadata.get('ARN') != arn or metadata.get('Name') != entry['secretName']
            or metadata.get('DeletedDate') or metadata.get('OwningService') or metadata.get('RotationEnabled')
            or metadata.get('ReplicationStatus') or metadata.get('PrimaryRegion') not in (None, entry['region'])):
        raise Blocked('Secret runtime identity/deletion/rotation/service ownership unsafe')
    response = aws('list-secret-version-ids', '--secret-id', arn, '--include-deprecated', service='secretsmanager')
    versions = response.get('Versions')
    if not isinstance(versions, list) or response.get('NextToken') or response.get('ARN') != arn:
        raise Blocked('Secret version inventory incomplete/ambiguous')
    if not all(isinstance(v, dict) for v in versions):
        raise Blocked('Secret version inventory invalid')
    stages = {v.get('VersionId'): v.get('VersionStages') for v in versions}
    summary = metadata.get('VersionIdsToStages', {})
    if (len(stages) != len(versions) or not all(isinstance(k, str) and isinstance(v, list)
            and all(isinstance(s, str) for s in v) and len(set(v)) == len(v) for k, v in stages.items())
            or not isinstance(summary, dict) or not all(isinstance(v, list) and all(isinstance(s, str) for s in v)
                                                      and len(set(v)) == len(v) for v in summary.values())
            or {k: sorted(v) for k, v in summary.items()} != {k: sorted(v) for k, v in stages.items() if v}):
        raise Blocked('Secret version metadata ambiguous/inconsistent')
    try:
        current = aws('get-secret-value', '--secret-id', arn, '--version-stage', 'AWSCURRENT',
                           '--query', SECRET_METADATA_QUERY, service='secretsmanager')
    except Blocked as error:
        if not getattr(error, 'current_missing', False) or any('AWSCURRENT' in v for v in stages.values()):
            raise Blocked('Secret current-value check denied/failed/ambiguous') from None
        if set(stages) - {token}:
            raise Blocked('Secret has existing noncurrent versions; initial bootstrap unsafe')
        if token in stages and (entry['stage'] != 'PUT_SUBMITTED'
                or stages[token] != ['BLUEPRINT_BOOTSTRAP_' + token]):
            raise Blocked('Secret bootstrap version no longer in submitted initial state')
        return False, token in stages
    labels = current.get('VersionStages')
    if (current.get('ARN') != arn or current.get('HasValue') is not True or not isinstance(labels, list)
            or not all(isinstance(s, str) for s in labels) or len(set(labels)) != len(labels)
            or sorted(labels) != sorted(stages.get(current.get('VersionId'), [])) or 'AWSCURRENT' not in labels):
        raise Blocked('Secret current-value response ambiguous')
    if current.get('VersionId') != token or entry['stage'] not in {'PUT_SUBMITTED', 'BOOTSTRAP_CONFIRMED'}:
        raise Blocked('Secret already has a current value; never overwrite')
    return True, True


def bootstrap(root, states, guard, save, aws, bootstrap_plan, bootstrap_current, finish_repair, unit, state,
        entry=None):
    contract = task_path(root).read_text(encoding='utf-8')
    if any(line not in contract.splitlines() for line in ('- AWS API execution: `allowed`', '- Deploy/apply: `allowed`')):
        raise Blocked('runtime bootstrap requires existing deploy mutation authorization')
    plan = bootstrap_plan(unit, state)
    if entry is None:
        if any(e.get('classification') == 'RUNTIME_BOOTSTRAP' and e.get('secretId') == plan['secretId']
               for s in states.values() for e in s.get('repairs', [])):
            raise Blocked('same Secret bootstrap already attempted; no second dummy PUT')
        if sum(e.get('failureClass') == plan['failureClass'] for e in state['repairs']) >= 3:
            raise Blocked('runtime bootstrap repair iteration limit')
        entry = plan | {'classification': 'RUNTIME_BOOTSTRAP', 'clientRequestToken': uuid.uuid4().hex, 'stage': 'BOOTSTRAP_INTENT'}
        state['repairs'].append(entry)
        state['failureClassification'] = 'RUNTIME_BOOTSTRAP'
        save()  # Intent and stable token MUST be durable before any Secrets Manager mutation.
    elif any(entry.get(k) != value for k, value in plan.items()) or not re.fullmatch(r'[0-9a-f]{32}', entry.get('clientRequestToken', '')):
        raise Blocked('persisted bootstrap ownership/schema/identity changed')
    state['failureClassification'] = 'RUNTIME_BOOTSTRAP'
    guard()
    confirmed, submitted = bootstrap_current(entry)
    if not confirmed:
        if not submitted:
            entry['stage'] = 'VALUE_CHECKED_MISSING'
            save()
            guard()
            # Recheck after intent persistence, immediately before submission.
            confirmed, submitted = bootstrap_current(entry)
            if not confirmed and not submitted:
                entry['stage'] = 'PUT_SUBMITTED'
                save()
                value = (json.dumps({k: 'DUMMY_DEPLOY_ONLY' for k in entry['requiredJsonKeys']}, sort_keys=True)
                         if entry['valueType'] == 'JSON' else 'DUMMY_DEPLOY_ONLY')
                # Explicit private stage avoids moving an existing AWSCURRENT during a concurrent write.
                aws('put-secret-value', '--secret-id', entry['secretId'], '--secret-string', value,
                         '--client-request-token', entry['clientRequestToken'],
                         '--version-stages', 'BLUEPRINT_BOOTSTRAP_' + entry['clientRequestToken'], service='secretsmanager')
        confirmed, submitted = bootstrap_current(entry)
        if not confirmed:
            if not submitted:
                raise Blocked('bootstrap PUT not confirmed; resume same intent/token')
            # No RemoveFromVersionId: AWS refuses to move another version's AWSCURRENT.
            aws('update-secret-version-stage', '--secret-id', entry['secretId'], '--version-stage', 'AWSCURRENT',
                     '--move-to-version-id', entry['clientRequestToken'], service='secretsmanager')
            confirmed, _ = bootstrap_current(entry)
            if not confirmed:
                raise Blocked('bootstrap current version not confirmed')
    entry['stage'] = 'BOOTSTRAP_CONFIRMED'
    save()
    finish_repair(unit, state, entry)
    return True


