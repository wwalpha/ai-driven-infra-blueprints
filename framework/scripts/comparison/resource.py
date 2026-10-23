"""Explicit resource/inline-child correspondence and inactive-resource evidence."""

import re
from functools import partial as _bind_framework_callback

from cloudformation_inputs import Blocked as Blocked
from cloudformation_inputs import output_value, resolve_value
from iac_values import cfn_resource_identity
from utils.layout_schema import GROUPED


def correspondence(resource, stacks):
    if not resource.get('cfn-logicalId'):
        raise Blocked('explicit cfn-logicalId is required; Model logicalId cannot establish CFn correspondence')
    name, logical = cfn_resource_identity(resource['cfn-logicalId'])
    if name not in stacks:
        raise Blocked(f'cfn-logicalId stack is not declared: {name}')
    return name, logical, stacks[name]


def inline_owner(kind, rowkind, logical, definition, document, parameters, pseudo, childtype):
    if rowkind == kind:
        return definition, None
    rule = GROUPED.get(rowkind)
    if not rule or rule['parent'] != kind or rule['identityProperty'] is not None:
        return None, ('uncompared', 'row ownership requires an explicit child mapping')
    children, unresolved = [], []
    for child in document.get('Resources', {}).values():
        if child.get('Type') != childtype:
            continue
        try:
            parent = output_value(document, parameters, pseudo, child.get('Properties', {}).get(rule['parentProperty']))
            if not isinstance(parent, dict) or set(parent) != {'Ref'}:
                raise Blocked('inline child parent requires an unambiguous local Ref')
            if parent == {'Ref': logical}:
                children.append(child)
        except (Blocked, ValueError, KeyError, TypeError) as error:
            unresolved.append(str(error))
    if unresolved or len(children) > 1:
        return None, ('uncompared', f'inline child correspondence matches={len(children)}; ' + '; '.join(unresolved))
    if not children:
        return None, ('difference', 'inline CREATE child missing')
    return children[0], None

def _recursive_inactive_evidence_visit(conditions, directory, document, environment, inputs, parameter_path, parameters, path, pseudo, redact, source_lookup, stack_id, supplied, target, /, value):
    if isinstance(value, list):
        for child in value:
            _recursive_inactive_evidence_visit(conditions, directory, document, environment, inputs, parameter_path, parameters, path, pseudo, redact, source_lookup, stack_id, supplied, target, child)
    elif isinstance(value, dict):
        if 'Condition' in value:
            key = value['Condition']
            if key not in conditions:
                expression = document['Conditions'][key]
                result = resolve_value({'Condition': key}, parameters, pseudo, conditions=document['Conditions'])
                conditions[key] = {'result': result, 'expression': expression,
                                   'source': {'path': path, 'key': f'Conditions.{key}'}}
                _recursive_inactive_evidence_visit(conditions, directory, document, environment, inputs, parameter_path, parameters, path, pseudo, redact, source_lookup, stack_id, supplied, target, expression)
        elif 'Fn::If' in value:
            key, yes, no = value['Fn::If']
            _recursive_inactive_evidence_visit(conditions, directory, document, environment, inputs, parameter_path, parameters, path, pseudo, redact, source_lookup, stack_id, supplied, target, {'Condition': key})
            _recursive_inactive_evidence_visit(conditions, directory, document, environment, inputs, parameter_path, parameters, path, pseudo, redact, source_lookup, stack_id, supplied, target, yes if conditions[key]['result'] else no)
        elif 'Fn::Sub' in value:
            argument = value['Fn::Sub']
            text, variables = (argument, {}) if isinstance(argument, str) else argument
            _recursive_inactive_evidence_visit(conditions, directory, document, environment, inputs, parameter_path, parameters, path, pseudo, redact, source_lookup, stack_id, supplied, target, list(variables.values()))
            for key in re.findall(r'\$\{([^}]+)\}', text):
                if not key.startswith('!') and key not in variables:
                    _recursive_inactive_evidence_visit(conditions, directory, document, environment, inputs, parameter_path, parameters, path, pseudo, redact, source_lookup, stack_id, supplied, target, {'Ref': key})
        elif 'Ref' in value:
            key = value['Ref']
            if key in parameters:
                declaration = document['Parameters'][key]
                input_source = ({'kind': 'parameter-file', 'path': parameter_path,
                           'key': f'ParameterKey={key}'} if key in supplied else
                          {'kind': 'template-default', 'path': path, 'key': f'Parameters.{key}.Default'})
                # NoEcho must also mask typed numeric/list parameters.
                shown = '<masked sensitive parameter>' if declaration.get('NoEcho') else redact(parameters[key], key)
            else:
                if key == 'AWS::StackName':
                    input_source = source_lookup('cloudformation-stacks', f'desired.stack.{stack_id}.name')
                elif key in {'AWS::Region', 'AWS::AccountId'}:
                    field = ('awsRegion' if key == 'AWS::Region' else
                             'awsExecutionAccountId' if 'awsExecutionAccountId' in target else 'awsAccountId')
                    input_source = {'kind': 'project-target', 'path': 'project.json', 'key': field,
                              'environment': environment, 'target': directory}
                else:
                    input_source = {'kind': 'botocore-endpoints' if key == 'AWS::Partition' else 'cloudformation-pseudo',
                              'region': pseudo['AWS::Region'], 'key': key}
                shown = pseudo[key]
            inputs[key] = {'name': key, 'value': shown, 'source': input_source}
        else:
            for child in value.values():
                _recursive_inactive_evidence_visit(conditions, directory, document, environment, inputs, parameter_path, parameters, path, pseudo, redact, source_lookup, stack_id, supplied, target, child)


def inactive_evidence(name, logical, definition, document, parameters, pseudo, *, path, parameter_path, supplied, stack_id, target, environment, directory, marks, source_lookup, redact):
    condition = definition['Condition']
    location = {'path': path, 'key': f'Resources.{logical}.Condition'}
    if line := marks.get('Condition', marks.get(None)):
        location['line'] = line
    inputs, conditions = {}, {}

    visit = _bind_framework_callback(_recursive_inactive_evidence_visit, conditions, directory, document, environment, inputs, parameter_path, parameters, path, pseudo, redact, source_lookup, stack_id, supplied, target)

    visit({'Condition': condition})
    return location, {'kind': 'condition-disabled', 'path': path, 'stack': name, 'logical': logical,
                      'condition': condition, 'result': False, 'relationship': 'direct',
                      'conditions': conditions, 'inputs': list(inputs.values())}
