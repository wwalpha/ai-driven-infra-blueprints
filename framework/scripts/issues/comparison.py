"""Target-batched, local desired → CloudFormation comparison. No AWS/provider calls."""
from __future__ import annotations

import re

from cloudformation_inputs import Blocked, condition_active, load_target, resolve_value, output_value
from design_catalog import DesignSchemaCatalog
from design_layout import GROUPED, HIDDEN_PROPERTIES, resource_mode
from iac_values import cfn_resource_identity
from model.projection import catalog_outputs
from model.files import load_model
from policy_tables import literal


from comparison_rows import Unresolved, cloudtrail_rows, put_row, select
from service_rows import pipeline_rows
from array_display import indexed_rows
from iac_values import ResourceReference, Expression, safe_value, same, selected_same, unordered_same
from utils.json_format import policy_json as strict_json


from .references import KMS_COMPARISON_FORMS, REF_ATTRIBUTES

from model.core import ReferenceResolutionError
from model.sources import _invocation_reads

from . import inputs, references, records

class Comparison:
    def __init__(self, root, environment, directory, services, *, catalog=None):
        self.root, self.environment, self.directory = root, environment, directory
        self.services = sorted(set(services))
        self.target = load_target(root, environment, directory)
        self.catalog = catalog or DesignSchemaCatalog(root)
        self.models, self.rows, self.resources = {}, {}, {}
        self.documents, self.stack_inputs = {}, {}
        self.template_locations = {}
        self._index, self.symbols = None, {}
        self.local_comparison, self.reference_models_loaded = False, False
        self.exports = None
        self.export_failures, self.stack_errors = [], {}
        self._templates, self.reference_formats = None, {}
        self.read_hashes, self.sensitive_values = {}, set()
        self.model_reads = _invocation_reads(root)
        self.unreadable_inputs = False
        self.view_errors = {}
        self.load_errors = []
        self.warnings = []
        self.reference_unavailable = {}
        self.inputs = {root / 'project.json'}
        self.results = []
        self.display_differences = {}
        self.metrics = {'model_loads': 0, 'model_parses': 0, 'template_decodes': 0, 'stack_evaluations': 0}
        for service in self.services:
            try:
                self.model(service)
            except ReferenceResolutionError as error:
                self.warnings.append({**error.diagnostic, 'service': service})
                self.reference_unavailable[service] = str(error)
                from model.sources import load_model
                analysis = load_model(root / 'model' / environment / directory / (service + '.properties'), self.model_reads)
                self.inputs.update(analysis.files)
                inputs.retain_reads(self)
                self.warnings.extend(analysis.warnings)
                self.resources[service], self.rows[service] = {}, {}
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.load_errors.append((service, str(error)))
                self.resources[service], self.rows[service] = {}, {}


    def model(self, service):
        return inputs.model(self, service)

    def source(self, service, key):
        return inputs.source(self, service, key)

    def track(self, path):
        return inputs.track(self, path)

    def redacted(self, value, prop=''):
        return records.redacted(self, value, prop)


    def record(self, category, service, identity, prop, reason, desired=None, actual=None, stack=None, source=None, template=None, cause=None):
        return records.record(self, category, service, identity, prop, reason, desired, actual, stack, source, template, cause)


    def record_inactive(self, service, identity, prop, name, logical, template, definition):
        document, parameters, pseudo = self.stack_inputs[name]
        condition = definition['Condition']
        path = template.relative_to(self.root).as_posix()
        location = {'path': path, 'key': f'Resources.{logical}.Condition'}
        marks = self.template_locations.get(id(definition), {})
        if line := marks.get('Condition', marks.get(None)):
            location['line'] = line
        stack_id, unit = next((stack_id, unit) for stack_id, unit in self.templates() if unit['name'] == name)
        parameter_path = self.root / 'infra/cloudformation/parameters' / self.environment / self.directory / unit['parameters']
        supplied = {item['ParameterKey'] for item in strict_json(parameter_path.read_text(encoding='utf-8'))}
        inputs, conditions = {}, {}

        def visit(value):
            if isinstance(value, list):
                for child in value:
                    visit(child)
            elif isinstance(value, dict):
                if 'Condition' in value:
                    key = value['Condition']
                    if key not in conditions:
                        expression = document['Conditions'][key]
                        result = resolve_value({'Condition': key}, parameters, pseudo, conditions=document['Conditions'])
                        conditions[key] = {'result': result, 'expression': expression,
                                           'source': {'path': path, 'key': f'Conditions.{key}'}}
                        visit(expression)
                elif 'Fn::If' in value:
                    key, yes, no = value['Fn::If']
                    visit({'Condition': key})
                    visit(yes if conditions[key]['result'] else no)
                elif 'Fn::Sub' in value:
                    argument = value['Fn::Sub']
                    text, variables = (argument, {}) if isinstance(argument, str) else argument
                    visit(list(variables.values()))
                    for key in re.findall(r'\$\{([^}]+)\}', text):
                        if not key.startswith('!') and key not in variables:
                            visit({'Ref': key})
                elif 'Ref' in value:
                    key = value['Ref']
                    if key in parameters:
                        declaration = document['Parameters'][key]
                        source = ({'kind': 'parameter-file', 'path': parameter_path.relative_to(self.root).as_posix(),
                                   'key': f'ParameterKey={key}'} if key in supplied else
                                  {'kind': 'template-default', 'path': path, 'key': f'Parameters.{key}.Default'})
                        # NoEcho must also mask typed numeric/list parameters.
                        shown = '<masked sensitive parameter>' if declaration.get('NoEcho') else self.redacted(parameters[key], key)
                    else:
                        if key == 'AWS::StackName':
                            source = self.source('cloudformation-stacks', f'desired.stack.{stack_id}.name')
                        elif key in {'AWS::Region', 'AWS::AccountId'}:
                            field = ('awsRegion' if key == 'AWS::Region' else
                                     'awsExecutionAccountId' if 'awsExecutionAccountId' in self.target else 'awsAccountId')
                            source = {'kind': 'project-target', 'path': 'project.json', 'key': field,
                                      'environment': self.environment, 'target': self.directory}
                        else:
                            source = {'kind': 'botocore-endpoints' if key == 'AWS::Partition' else 'cloudformation-pseudo',
                                      'region': pseudo['AWS::Region'], 'key': key}
                        shown = pseudo[key]
                    inputs[key] = {'name': key, 'value': shown, 'source': source}
                else:
                    for child in value.values():
                        visit(child)

        visit({'Condition': condition})
        self.record('difference', service, identity, prop, 'CREATE resource is inactive under confirmed parameters',
                    stack=name, template=location,
                    cause={'kind': 'condition-disabled', 'path': path, 'stack': name, 'logical': logical,
                           'condition': condition, 'result': False, 'relationship': 'direct',
                           'conditions': conditions, 'inputs': list(inputs.values())})


    def reference(self, service, value, expected_attribute=None, *, consumer_property=None):
        return references.reference(self, service, value, expected_attribute, consumer_property=consumer_property)

    def index(self):
        return inputs.index(self)

    def symbol(self, stack, logical, attribute=None):
        return references.symbol(self, stack, logical, attribute)

    def import_value(self, stack, argument, seen):
        return references.import_value(self, stack, argument, seen)

    def evaluate(self, stack, value, seen=frozenset()):
        return references.evaluate(self, stack, value, seen)

    def reference_forms(self, kind, path):
        return references.reference_forms(self, kind, path)

    def reference_diagnostic(self, left, right, kind, path, reason):
        return references.reference_diagnostic(self, left, right, kind, path, reason)

    def reference_literal(self, value):
        return references.reference_literal(self, value)

    def kms_format(self, value):
        return references.kms_format(self, value)

    def reference_same(self, left, right, kind, path, diagnostics=None):
        return references.reference_same(self, left, right, kind, path, diagnostics)

    def desired_reference(self, service, value, kind, path, attribute=None, context=None):
        return references.desired_reference(self, service, value, kind, path, attribute, context)

    def desired_value(self, service, row, kind, *, stack=None, context=None):
        return references.desired_value(self, service, row, kind, stack=stack, context=context)

    def templates(self):
        return inputs.templates(self)

    def stack(self, unit):
        return inputs.stack(self, unit)

    def stack_input(self, unit):
        return inputs.stack_input(self, unit)

    def run(self):
        self.local_comparison = True
        self.symbols.clear()
        for service, message in self.reference_unavailable.items():
            self.record('uncompared', service, '*', '*', message, cause={'kind': 'reference-unresolved'})
        for service, error in self.load_errors:
            self.record('error', service, '*', '*', error)
        if self.target['iacEngine'] != 'cloudformation':
            for service in self.services:
                self.record('uncompared', service, '*', '*', 'Terraform: no existing local resource correspondence/evaluator; no init/plan/provider calls')
            return self.results
        stacks = dict((unit['name'], unit) for _, unit in self.templates())
        # Load/evaluate only stacks explicitly assigned to selected resources.
        for service in self.services:
            for identity, resource in self.resources[service].items():
                mode = resource_mode(resource)
                if mode == 'IMPORT':
                    self.record('excluded', service, identity, '*', 'IMPORT is outside IaC generation')
                    continue
                try:
                    kind = resource.get('resourceType')
                    if not isinstance(kind, str) or not kind:
                        raise ValueError('resourceType is missing or malformed')
                    if kind in self.catalog.api_schemas:
                        self.record('uncompared', service, identity, '*',
                                    'CloudFormation unsupported; outside CFn comparison; API implementation status unverified',
                                    cause={'kind': 'cloudformation-unsupported', 'resource_type': kind,
                                           'implementation_status': 'unverified'})
                        continue
                    if self.catalog.canonical_type(kind) not in self.catalog.resource_types:
                        raise ValueError(f'unknown resource type: {kind}')
                    cfn_type = self.catalog.cloudformation_type(kind)
                    if resource.get('cfn-logicalId'):
                        name, logical = cfn_resource_identity(resource['cfn-logicalId'])
                        if name not in stacks:
                            raise Blocked(f'cfn-logicalId stack is not declared: {name}')
                        unit = stacks[name]
                        template = self.root / 'infra/cloudformation/templates' / self.target.get('alias', '') / unit['template']
                        self.inputs.add(template)
                        if not template.is_file():
                            self.record('difference', service, identity, '*', 'モデルに対応するtemplateが存在しない（CREATE未実装）', desired={'resourceType': kind, 'logical': logical}, stack=name, template={'path': template.relative_to(self.root).as_posix()},
                                        cause={'kind': 'template-missing', 'path': template.relative_to(self.root).as_posix(),
                                               'stack': name, 'relationship': 'direct'})
                            continue
                        template, (document, parameters, pseudo) = self.stack(unit)
                        definition = document.get('Resources', {}).get(logical)
                        # Explicit identity is authoritative even if the template resource is missing.
                        direct = self.index()
                        if len(direct.get((name, logical), [])) != 1:
                            raise Blocked(f'duplicate resource correspondence: {name}/{logical}')
                    else:
                        raise Blocked('explicit cfn-logicalId is required; Model logicalId cannot establish CFn correspondence')
                    if document.get('Transform'):
                        raise Blocked('Transform requires external evaluation')
                    if definition is None:
                        self.record('difference', service, identity, '*', 'resource missing', desired={'resourceType': kind, 'logical': logical}, stack=name,
                                    template={'path': template.relative_to(self.root).as_posix()})
                        continue
                    if definition.get('Type') != cfn_type:
                        raise Blocked(f'formal resource type mismatch: {definition.get("Type")} != {cfn_type}')
                    if not condition_active(document, parameters, pseudo, definition):
                        self.record_inactive(service, identity, '*', name, logical, template, definition)
                        continue
                    self.compare_rows(service, identity, resource, name, logical, template, definition, document)
                except (Blocked, KeyError) as error:
                    self.record('uncompared', service, identity, '*', str(error), cause=getattr(error, 'iac_cause', None))
                except ReferenceResolutionError as error:
                    self.warnings.append({**error.diagnostic, 'service': service, 'resource': identity})
                    self.record('uncompared', service, identity, '*', str(error), cause={'kind': 'reference-unresolved'})
                except (OSError, ValueError, ImportError, TypeError) as error:
                    self.record('error', service, identity, '*', str(error))
        return self.results


    def managed_policy_roles(self, service, identity, stack, direct):
        """Combine direct Roles with proven same-stack active Role attachments."""
        roles = self.evaluate(stack, direct)
        if not isinstance(roles, list):
            raise Blocked('ManagedPolicy Roles is not a proven list')
        roles = list(roles)
        policy = ResourceReference({'$resource': [service, identity], '$attribute': 'PolicyArn'})
        # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-iam-role.html#cfn-iam-role-managedpolicyarns
        document, parameters, pseudo = self.stack_inputs[stack]
        for logical, definition in document.get('Resources', {}).items():
            if definition.get('Type') != 'AWS::IAM::Role' or not condition_active(document, parameters, pseudo, definition):
                continue
            attachments = self.evaluate(stack, definition.get('Properties', {}).get('ManagedPolicyArns', []))
            if not isinstance(attachments, list):
                raise Blocked('role ManagedPolicyArns is not a proven list')
            matches = [False if isinstance(item, str) and re.fullmatch(r'arn:aws[a-z-]*:iam::aws:policy/.+', item) else
                       self.reference_same(policy, item, 'IAM.Role', 'ManagedPolicyArns[]') for item in attachments]
            if any(result is None for result in matches) and not any(result is True for result in matches):
                raise Blocked('inverse role attachment identity is unproven')
            if any(result is True for result in matches):
                role = self.symbol(stack, logical)
                if not any(self.reference_same(role, item, 'IAM.ManagedPolicy', 'Roles[]') is True for item in roles):
                    roles.append(role)
        return roles


    def compare_rows(self, service, identity, resource, name, logical, template, definition, document):
        kind = resource['resourceType']
        def unverified(value, pointer=''):
            if isinstance(value, Expression) and value.operation == 'Unverified':
                yield pointer
            elif isinstance(value, dict):
                for key, child in value.items():
                    yield from unverified(child, pointer + '/' + key.replace('~', '~0').replace('/', '~1'))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    yield from unverified(child, pointer + '/' + str(index))
        grouped = {}
        all_rows = list(self.rows[service][identity])
        if resource.get('parentReference') and resource.get('parentProperty') and not any(row['property'] == resource['parentProperty'] for _, row in all_rows):
            all_rows.append(('@parent', {'property': resource['parentProperty'], 'value': resource['parentReference'], 'comment': 'grouped parent identity'}))
        for rid, row in all_rows:
            prop = row['property']
            rowkind = '.'.join(prop.split('.')[:2])
            grouped.setdefault(rowkind, []).append((rid, row))
        # Independent children have their own mode; inline children inherit this resource's mode.
        for rowkind, rows in grouped.items():
            if rowkind == 'CloudTrail.Trail':
                try:
                    rows = cloudtrail_rows(rows, self.root)
                except Unresolved as error:
                    self.record('uncompared', service, identity, rowkind + '.EventSelectors', str(error), stack=name,
                                source=self.source(service, f'desired.row.{rows[0][0]}.property'))
                    rows = [(rid, row) for rid, row in rows if not row['property'].startswith(rowkind + '.EventSelectors')]
            if rowkind == 'CodePipeline.Pipeline' and any('Stages[].' in row['property'] for _, row in rows):
                original = dict(rows)
                displayed = pipeline_rows([[rid, row['property'].removeprefix(rowkind + '.'),
                                           row['value'], row.get('comment', '')] for rid, row in rows])
                rows, configurations = [], set()
                for rid, prop, value, _ in indexed_rows(displayed, rowkind, self.root):
                    row = original[rid]
                    if row['property'].endswith('.Configuration'):
                        if rid in configurations:
                            continue
                        configurations.add(rid)
                        prop = prop.split('.Configuration.', 1)[0] + '.Configuration'
                        value = row['value']
                    rows.append((rid, dict(row, property=rowkind + '.' + prop, value=value)))
            unresolved = {}
            for rid, row in rows:
                short = row['property'].removeprefix(rowkind + '.')
                setting = re.sub(r'\[(?:\d*)\]', '', short.split('.', 1)[0])
                try:
                    put_row({}, short, None)
                except Unresolved as error:
                    unresolved.setdefault(setting, (rid, str(error)))
            for setting, (rid, reason) in unresolved.items():
                self.record('uncompared', service, identity, rowkind + '.' + setting, reason, stack=name,
                            source=self.source(service, f'desired.row.{rid}.property'))
            rows = [(rid, row) for rid, row in rows if re.sub(r'\[(?:\d*)\]', '',
                    row['property'].removeprefix(rowkind + '.').split('.', 1)[0]) not in unresolved]
            contexts = {}
            if self.local_comparison and rowkind == 'EC2.FlowLog':
                types = [literal(row['value']) for _, row in rows if row['property'] == 'EC2.FlowLog.ResourceType']
                if len(types) == 1:
                    contexts['ResourceId'] = {'ResourceType': types[0]}
            if self.local_comparison and rowkind in {'CloudTrail.Trail', 'CodePipeline.Pipeline'}:
                # Only explicit indexes bind sibling conditions; row order cannot prove action membership.
                for _, row in rows:
                    prop = row['property'].removeprefix(rowkind + '.')
                    action = re.fullmatch(r'(.*\.Actions\[\d+\])\.ActionTypeId\.(Category|Owner|Provider|Version)', prop)
                    data = re.fullmatch(r'(.*\.DataResources\[\d+\])\.Type', prop)
                    if action:
                        put_row(contexts.setdefault(action[1], {}), 'ActionTypeId.' + action[2], literal(row['value']))
                    elif data:
                        put_row(contexts.setdefault(data[1], {}), 'Type', literal(row['value']))
            if self.local_comparison and rowkind == 'CodeBuild.Project':
                variables = {}
                for rid, row in rows:
                    short = row['property'].removeprefix(rowkind + '.')
                    if re.fullmatch(r'Environment.EnvironmentVariables\[\d*\]\.(Name|Type|Value)', short):
                        put_row(variables, short, rid if short.endswith('.Value') else literal(row['value']))
                for variable in variables.get('Environment', {}).get('EnvironmentVariables', []):
                    if 'Value' in variable:
                        contexts[variable['Value']] = variable
            owner = definition
            if rowkind != kind:
                rule = GROUPED.get(rowkind)
                if not rule or rule['parent'] != kind or rule['identityProperty'] is not None:
                    self.record('uncompared', service, identity, rowkind, 'row ownership requires an explicit child mapping')
                    continue
                childtype = self.catalog.cloudformation_type(rowkind)
                children, unresolved = [], []
                _, parameters, pseudo = self.stack_inputs[name]
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
                    self.record('uncompared', service, identity, rowkind, f'inline child correspondence matches={len(children)}; ' + '; '.join(unresolved))
                    continue
                if not children:
                    self.record('difference', service, identity, rowkind, 'inline CREATE child missing', desired={'resourceType': rowkind}, stack=name,
                                source=self.source(service, f'desired.row.{rows[0][0]}.property'), template={'path': template.relative_to(self.root).as_posix()})
                    continue
                owner = children[0]
                _, parameters, pseudo = self.stack_inputs[name]
                if not condition_active(document, parameters, pseudo, owner):
                    child_logical = next(key for key, child in document['Resources'].items() if child is owner)
                    self.record_inactive(service, identity, rowkind, name, child_logical, template, owner)
                    continue
            desired, sources, incomplete, exact = {}, {}, {}, set()
            outputs = catalog_outputs(self.root, rowkind) | HIDDEN_PROPERTIES
            for rid, row in rows:
                prop = row['property']
                short = prop.removeprefix(rowkind + '.')
                source = self.source(service, f'desired.resource.{identity}.parentReference' if rid == '@parent' else f'desired.row.{rid}.document' if 'document' in row else f'desired.row.{rid}.value')
                if prop in outputs or prop == 'S3.Bucket.Region':
                    self.record('excluded', service, identity, prop, 'identifier output/design-only metadata', source=source)
                    continue
                if short == 'Name' and rowkind in {'EC2.VPC', 'EC2.Subnet', 'EC2.RouteTable', 'EC2.FlowLog'}:
                    short = 'Tags[]'
                    value = {'Key': 'Name', 'Value': literal(row['value'])}
                else:
                    try:
                        parent = re.split(r'\.(?:Configuration|Values)(?:\[|\.|$)', short)[0]
                        value = self.desired_value(service, row, rowkind, stack=name, context=contexts.get(rid, contexts.get(parent)))
                    except (Blocked, KeyError) as error:
                        self.record('uncompared', service, identity, prop, str(error), source=source)
                        if hasattr(error, 'reference_detail'):
                            symbol, field = error.reference_detail
                            try:
                                actual = self.evaluate(name, select(owner.get('Properties', {}), field))
                                reason = 'Model attribute is outside allowed property forms; comparison remains deferred'
                            except (Blocked, KeyError, ValueError, TypeError, IndexError) as actual_error:
                                actual = {'unresolved': self.redacted(str(actual_error))}
                                reason = 'Model attribute is outside allowed property forms; IaC reference evaluation also failed'
                            self.results[-1]['reference_diagnostics'] = [self.reference_diagnostic(symbol, actual, rowkind, field, reason)]
                            self.results[-1]['stack'] = name
                            self.results[-1]['iac'] = {'path': template.relative_to(self.root).as_posix()}
                        incomplete.setdefault(re.sub(r'\[\d*\]', '', short.split('.', 1)[0]), []).append(self.redacted(self.results[-1]))
                        continue
                    except (ValueError, TypeError) as error:
                        self.record('error', service, identity, prop, str(error), source=source)
                        incomplete.setdefault(re.sub(r'\[\d*\]', '', short.split('.', 1)[0]), []).append(self.redacted(self.results[-1]))
                        continue
                if '.' not in short and not short.endswith('[]'):
                    exact.add(short)
                put_row(desired, short, value)
                sources.setdefault(re.sub(r'\[\d*\]', '', short.split('.', 1)[0]), []).append(source)
            for key, value in desired.items():
                prop = rowkind + '.' + key
                if key in incomplete:
                    self.record('uncompared', service, identity, prop, 'incomplete nested input; whole setting comparison deferred',
                                stack=name, source=sources[key][0], template={'path': template.relative_to(self.root).as_posix()})
                    self.results[-1]['deferred_children'] = incomplete[key]
                    self.results[-1]['reference_diagnostics'] = [diagnostic for child in incomplete[key]
                                                               for diagnostic in child.get('reference_diagnostics', [])]
                    continue
                iac_source = {'path': template.relative_to(self.root).as_posix()}
                marks = self.template_locations.get(id(owner.get('Properties', {})), {})
                if line := marks.get(key, self.template_locations.get(id(owner), {}).get(None)):
                    iac_source['line'] = line
                actual = owner.get('Properties', {}).get(key)
                inverse_roles = self.local_comparison and rowkind == 'IAM.ManagedPolicy' and key == 'Roles'
                if key not in owner.get('Properties', {}) and not inverse_roles:
                    self.record('difference', service, identity, prop, 'property missing', desired=value, stack=name,
                                source=sources[key][0], template=iac_source)
                    self.results[-1]['model_sources'] = sources[key]
                    continue
                actual_error = None
                try:
                    if inverse_roles:
                        actual = self.managed_policy_roles(service, identity, name, owner.get('Properties', {}).get(key, []))
                    else:
                        try:
                            actual = self.evaluate(name, actual)
                        except (Blocked, KeyError) as error:
                            actual_error = error
                            from json_intrinsics import project_document
                            if not self.local_comparison:
                                raise
                            actual = project_document(actual, evaluate=lambda value: self.evaluate(name, value),
                                unresolved=lambda value: Expression('Unverified', [value]), template=True,
                                warnings=self.warnings, property_name=prop, model_path=template)
                except (Blocked, KeyError) as error:
                    self.record('uncompared', service, identity, prop, str(error), source=sources[key][0], template=iac_source, cause=getattr(error, 'iac_cause', None))
                    continue
                except (ValueError, TypeError, IndexError) as error:
                    self.record('error', service, identity, prop, str(error), source=sources[key][0], template=iac_source, cause=getattr(error, 'iac_cause', None))
                    continue
                if actual == {'$noValue': True}:
                    self.record('difference', service, identity, prop, 'property omitted by AWS::NoValue', value, None, name, sources[key][0], iac_source)
                    continue
                self.reference_equivalent = False
                diagnostics = []
                reference = (lambda left, right, path: self.reference_same(left, right, rowkind, path, diagnostics)) if self.local_comparison else None
                equal = (unordered_same(value, actual, reference=reference, path=key) if inverse_roles else
                         same(value, actual, reference=reference, path=key) if key in exact else
                         selected_same(value, actual, key, reference=reference, path=key))
                if equal is None:
                    self.record('uncompared', service, identity, prop,
                                str(actual_error) if actual_error is not None else 'reference identity or property format is unproven',
                                stack=None if actual_error is not None else name, source=sources[key][0], template=iac_source,
                                cause=getattr(actual_error, 'iac_cause', None))
                    self.results[-1]['reference_diagnostics'] = diagnostics
                elif not equal:
                    self.record('difference', service, identity, prop, 'value mismatch', value, actual, name, sources[key][0], iac_source)
                    if diagnostics:
                        self.results[-1]['reference_diagnostics'] = list(diagnostics)
                        format_errors = [item['reason'] for item in diagnostics if item['reason'].startswith('KMS format') and item['reason'] != 'KMS format is unproven']
                        if format_errors:
                            self.results[-1]['reason'] = '; '.join(dict.fromkeys(format_errors))
                    self.results[-1]['model_sources'] = sources[key]
                    # Preserve original records; capture display evidence before redaction loses it.
                    from .records import identifier, value_differences
                    self.display_differences[identifier(self.results[-1])] = value_differences(
                        value, actual, prop, exact=key in exact, redact=self.redacted, reference=reference)
                    for pointer in sorted(set(unverified(value)) | set(unverified(actual))):
                        self.record('uncompared', service, identity, prop + '#' + pointer,
                                    'unresolved/unverified intrinsic; JSON Pointer=' + repr(pointer),
                                    stack=name, source=sources[key][0], template=iac_source)
                else:
                    reason = 'reference expression equivalent' if self.reference_equivalent else 'equal'
                    self.record('matched', service, identity, prop, reason, stack=name, source=sources[key][0], template=iac_source)


