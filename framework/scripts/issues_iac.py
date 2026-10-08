"""Target-batched, local desired → CloudFormation comparison. No AWS/provider calls."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from cloudformation_inputs import Blocked, condition_active, load_target, load_template_inputs, resolve_value, output_value
from cloudformation_observed import resource_index, mapped_resource
from design_catalog import DesignSchemaCatalog
from design_layout import GROUPED, HIDDEN_PROPERTIES, resource_mode
from model_design import cfn_resource_identity
from model_references import catalog_outputs
from model_core import LINK, entries, stack_model
from model_files import load_model, resource_row_index, MAX_LINES
from policy_tables import literal


from iac_evaluation import Evaluation
from comparison_rows import put_row
from iac_values import ResourceReference, Expression, safe_value, same, selected_same, strict_json


# Documented identifier formats absent from the provider schema's string pattern.
# Each entry is a property contract, not permission to erase reference attributes.
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-kms-alias.html
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-cloudtrail-trail.html
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-athena-workgroup-encryptionconfiguration.html
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-ecr-repository-encryptionconfiguration.html
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-s3-bucket-serversideencryptionbydefault.html
REFERENCE_FORMS = {
    'KMS.Alias.TargetKeyId': {'KeyId', 'Arn'},
    'CloudTrail.Trail.KMSKeyId': {'KeyId', 'Arn', 'AliasName'},
    'Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey': {'KeyId', 'Arn'},
    'ECR.Repository.EncryptionConfiguration.KmsKey': {'KeyId', 'Arn', 'AliasName'},
    'S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID': {'KeyId', 'Arn', 'AliasName'},
}


class Comparison:
    def __init__(self, root, environment, directory, services, *, catalog=None):
        self.root, self.environment, self.directory = root, environment, directory
        self.services = sorted(set(services))
        self.target = load_target(root, environment, directory)
        self.catalog = catalog or DesignSchemaCatalog(root)
        self.models, self.rows, self.resources = {}, {}, {}
        self.documents, self.stack_inputs = {}, {}
        self._index, self.symbols = None, {}
        self.local_comparison, self.reference_models_loaded = False, False
        self.exports = None
        self.export_failures, self.stack_errors = [], {}
        self._templates, self.reference_formats = None, {}
        self.read_hashes, self.sensitive_values = {}, set()
        self.load_errors = []
        self.inputs = {root / 'project.json'}
        self.results = []
        self.display_differences = {}
        self.metrics = {'model_loads': 0, 'model_parses': 0, 'template_decodes': 0, 'stack_evaluations': 0}
        for service in self.services:
            try:
                self.model(service)
            except (OSError, ValueError) as error:
                self.load_errors.append((service, str(error)))
                self.resources[service], self.rows[service] = {}, {}

    def model(self, service):
        if not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', service):
            raise ValueError('invalid reference service')
        if service not in self.models:
            path = self.root / 'model' / self.environment / self.directory / (service + '.properties')
            self.inputs.add(path)
            loaded = load_model(path)
            if any(len(text.splitlines()) > MAX_LINES for text in loaded.files.values()):
                raise ValueError(f'model file exceeds {MAX_LINES} lines: {path}; split service model')
            if service != 'cloudformation-stacks' and loaded.values.get(f'desired.service.{service}.serviceId') != service:
                raise ValueError(f'mismatched service ID: {path}')
            self.models[service] = loaded
            self._index = None
            self.symbols.clear()
            self.inputs.update(loaded.files)
            self.read_hashes.update({file: hashlib.sha256(text.encode('utf-8')).hexdigest() for file, text in loaded.files.items()})
            self.metrics['model_loads'] += 1
            self.metrics['model_parses'] += 1
            self.resources[service] = dict(entries(loaded.values, 'desired.resource.'))
            self.rows[service] = resource_row_index(loaded.values)
            for rows in self.rows[service].values():
                for _, row in rows:
                    if re.search(r'password|secretstring|secretbinary|token|credential|privatekey', '.'.join(row.get('property', '').split('.')[2:]), re.I):
                        raw = row.get('document', row.get('value', ''))
                        self.sensitive_values.update((raw, literal(raw)))
        return self.models[service]

    def source(self, service, key):
        location = self.models[service].locations.get(key) if service in self.models else None
        return {'path': location[0].relative_to(self.root).as_posix(), 'line': location[1], 'key': key} if location else None

    def track(self, path):
        self.inputs.add(path)
        if path not in self.read_hashes:
            self.read_hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

    def redacted(self, value, prop=''):
        value = safe_value(value, prop)
        if isinstance(value, str) and any(secret in value for secret in self.sensitive_values if secret):
            return '<masked sensitive parameter>'
        if isinstance(value, dict):
            return {key: self.redacted(item, key) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redacted(item, prop) for item in value]
        return value

    def record(self, category, service, identity, prop, reason, desired=None, actual=None, stack=None, source=None, template=None, cause=None):
        self.results.append({'category': category, 'service': service, 'resource': identity,
                             'property': prop, 'reason': reason, 'desired': self.redacted(desired, prop),
                             'actual': self.redacted(actual, prop), 'stack': stack,
                             'model': source or self.source(service, f'desired.resource.{identity}.resourceType'),
                             'iac': template})
        if cause:
            self.results[-1]['cause'] = self.redacted(cause)

    def reference(self, service, value, expected_attribute=None):
        link = LINK.fullmatch(value)
        if not link:
            raise Blocked('not a logical model reference')
        refservice = Path(link.group(2)).stem if link.group(2) else service
        if link.group(2) not in {'', refservice + '.md'}:
            raise Blocked('reference must stay in the same target')
        self.model(refservice)
        candidates = [(identity, resource) for identity, resource in self.resources[refservice].items()
                      if resource.get('anchor') == link.group(3)]
        if len(candidates) != 1:
            raise Blocked(f'reference mapping matches={len(candidates)}: {refservice}#{link.group(3)}')
        identity, resource = candidates[0]
        if resource_mode(resource) == 'IMPORT':
            raise Blocked('IMPORT reference requires approved handoff; no physical ID inference')
        attributes = {row['property'].removeprefix(resource['resourceType'] + '.')
                      for _, row in self.rows[refservice][identity]
                      if row['property'] in catalog_outputs(self.root, resource['resourceType'])}
        primary = self.catalog.schema(resource['resourceType']).get('primaryIdentifier', [])
        if expected_attribute is None:
            if len(primary) != 1:
                raise Blocked('reference attribute is ambiguous')
            expected_attribute = primary[0].removeprefix('/properties/').replace('/', '.')
        # The link label is never a physical ID, including PENDING_DEPLOY.
        readonly = self.catalog.schema(resource['resourceType']).get('readOnlyProperties', [])
        if expected_attribute not in attributes and '/properties/' + expected_attribute not in primary + readonly:
            raise Blocked(f'reference attribute not confirmed: {expected_attribute}')
        return ResourceReference({'$resource': [refservice, identity], '$attribute': expected_attribute})

    def index(self):
        if self._index is None:
            loaded = {self.root / 'model' / self.environment / self.directory / (service + '.properties'): model.values
                      for service, model in self.models.items() if service != 'cloudformation-stacks'}
            self._index = resource_index(loaded, self.catalog)
        return self._index

    def symbol(self, stack, logical, attribute=None):
        attribute = str(attribute) if isinstance(attribute, str) else attribute
        cachekey = stack, logical, attribute
        if cachekey in self.symbols:
            return self.symbols[cachekey]
        document, parameters, pseudo = self.stack_inputs[stack]
        definition = document.get('Resources', {}).get(logical)
        if not definition or not condition_active(document, parameters, pseudo, definition):
            raise Blocked(f'local resource reference missing/inactive: {stack}/{logical}')
        if self.local_comparison and not self.reference_models_loaded:
            # Same-target model identities establish uniqueness, never physical values.
            for path in sorted((self.root / 'model' / self.environment / self.directory).glob('*.properties')):
                if path.stem != 'cloudformation-stacks':
                    self.model(path.stem)
            self.reference_models_loaded = True
        direct, legacy = self.index()
        try:
            entry = mapped_resource(direct, legacy, stack, logical, definition['Type'], any(name == stack for name, _ in direct))
        except ValueError as error:
            if self.local_comparison:
                raise Blocked(f'unproven resource correspondence: {stack}/{logical}: {error}') from error
            raise
        path, identity, resource, _ = entry
        if attribute is None:
            primary = self.catalog.schema(resource['resourceType']).get('primaryIdentifier', [])
            if len(primary) != 1:
                raise Blocked('Ref attribute is ambiguous')
            attribute = primary[0].removeprefix('/properties/').replace('/', '.')
        else:
            try:
                self.catalog.property_schema(resource['resourceType'], attribute)
            except ValueError as error:
                if self.local_comparison:
                    raise Blocked(f'unproven resource attribute: {logical}.{attribute}') from error
                raise
        result = ResourceReference({'$resource': [path.stem, identity], '$attribute': attribute})
        self.symbols[cachekey] = result
        return result

    def import_value(self, stack, argument, seen):
        name = self.evaluate(stack, argument, seen)
        if not isinstance(name, str):
            raise Blocked('ImportValue name is not a local string')
        token = ('import', stack, name)
        if token in seen:
            raise Blocked(f'cyclic ImportValue: {name}')
        if self.exports is None:
            # Cache the partial index and failures too: one broken stack is not a
            # reason to discard proven exports or retry the entire search per row.
            self.exports = {}
            for _, unit in self.templates():
                try:
                    _, (document, parameters, pseudo) = self.stack(unit)
                    if document.get('Transform'):
                        raise Blocked('Transform requires external evaluation')
                except (Blocked, ValueError, KeyError, TypeError, OSError) as error:
                    self.export_failures.append(error)
                    continue
                for output in document.get('Outputs', {}).values():
                    try:
                        if 'Export' not in output or not condition_active(document, parameters, pseudo, output):
                            continue
                        export = self.evaluate(unit['name'], output['Export']['Name'], frozenset({('export-name',)}))
                        if not isinstance(export, str):
                            raise Blocked('Export name is not a local string')
                        self.exports.setdefault(export, []).append((unit['name'], output.get('Value')))
                    except (Blocked, ValueError, KeyError, TypeError, OSError) as error:
                        self.export_failures.append(error)
        candidates = self.exports.get(name, [])
        if not candidates and self.export_failures:
            error = self.export_failures[0]
            blocked = Blocked(f'ImportValue handoff search incomplete: {error}')
            causes = [getattr(failure, 'iac_cause', None) for failure in self.export_failures]
            if all(causes) and len({(cause['kind'], cause['path']) for cause in causes}) == 1:
                blocked.iac_cause = dict(causes[0], relationship='export-search-incomplete', consumer_stack=stack)
            else:
                blocked.iac_cause = {'kind': 'import-unresolved', 'export': name, 'relationship': 'import', 'consumer_stack': stack}
            raise blocked from error
        if len(candidates) != 1 or candidates[0][0] == stack:
            blocked = Blocked(f'ImportValue handoff matches={len(candidates)} or same-stack export: {name}')
            blocked.iac_cause = {'kind': 'import-unresolved', 'export': name, 'relationship': 'import', 'consumer_stack': stack}
            raise blocked
        producer, value = candidates[0]
        try:
            return self.evaluate(producer, value, seen | {token})
        except Blocked as error:
            if not getattr(error, 'iac_cause', None):
                error.iac_cause = {'kind': 'import-unresolved', 'export': name, 'relationship': 'import', 'consumer_stack': stack}
            raise

    def evaluate(self, stack, value, seen=frozenset()):
        return Evaluation(self.stack_inputs, self.resources, self.catalog.property_schema,
                          self.symbol, self.import_value, self.local_comparison).evaluate(stack, value, seen)

    def reference_forms(self, kind, path):
        key = kind + '.' + path
        if key not in self.reference_formats:
            try:
                node = self.catalog.property_schema(kind, path)
            except KeyError:
                # Policy document members and open JSON fields have no typed schema.
                node = {}
            self.reference_formats[key] = ({'Arn'} if node.get('pattern', '').startswith('^arn:') or
                                           path.lower().endswith(('arn', 'arns')) else REFERENCE_FORMS.get(key))
        return self.reference_formats[key]

    def reference_same(self, left, right, kind, path):
        """Compare proven identities under a property contract, retaining form/alias intent."""
        if isinstance(left, Expression) or isinstance(right, Expression):
            return True if same(left, right) else None
        symbols = [value for value in (left, right) if isinstance(value, ResourceReference)]
        if not symbols or not any(self.resources[value['$resource'][0]][value['$resource'][1]]['resourceType']
                                  in {'KMS.Key', 'KMS.Alias'} for value in symbols):
            return NotImplemented
        if len(symbols) != 2:
            # No observed/AWS values: a literal cannot prove this symbolic identity.
            return None
        if left['$resource'] != right['$resource']:
            # Aliases retain their own identity; a mutable alias is not a direct key.
            return False
        forms = self.reference_forms(kind, path)
        if forms is not None:
            if left['$attribute'] == right['$attribute'] and left['$attribute'] not in forms:
                return None
            equal = left['$attribute'] in forms and right['$attribute'] in forms
            if equal and left['$attribute'] != right['$attribute']:
                self.reference_equivalent = True
            return equal
        return True if left['$attribute'] == right['$attribute'] else None

    def desired_reference(self, service, value, kind, path, attribute=None):
        symbol = self.reference(service, value, attribute)
        if self.local_comparison and attribute is None:
            refservice, identity = symbol['$resource']
            refkind = self.resources[refservice][identity]['resourceType']
            if refkind == 'KMS.Key' and self.reference_forms(kind, path) == {'Arn'}:
                symbol = self.reference(service, value, 'Arn')
        return symbol

    def desired_value(self, service, row, kind, *, stack=None):
        raw = row.get('document', row['value'])
        if 'document' in row:
            value = strict_json(raw)
        elif LINK.fullmatch(raw):
            prop = row['property'].removeprefix(kind + '.')
            # A schema-typed ARN property selects the referenced Arn, never a current ARN.
            attribute = 'Arn' if row['property'] == 'CodeBuild.Project.ServiceRole' or prop.lower().endswith(('arn', 'arns')) else None
            symbol = self.desired_reference(service, raw, kind, prop, attribute)
            node = self.catalog.property_schema(kind, prop)
            return [symbol] if node.get('type') == 'array' else symbol
        else:
            value = literal(raw)
            if value in {'UNSET', 'PENDING_DEPLOY', 'TBD', 'TODO', '未確定'}:
                raise Blocked('desired value is unresolved')
            node = self.catalog.property_schema(kind, row['property'].removeprefix(kind + '.'))
            schema_type = node.get('type')
            if schema_type != 'string':
                if schema_type is None:
                    raise Blocked('property type is not uniquely determined')
                value = strict_json(value)
        policy = row['property'].rsplit('.', 1)[-1] in {'PolicyDocument', 'AssumeRolePolicyDocument', 'KeyPolicy', 'Policy'}
        def references(item, field='', operands=False, path=''):
            if isinstance(item, str) and LINK.fullmatch(item):
                attribute = 'Arn' if field.lower().endswith(('arn', 'arns')) or policy and field in {'Resource', 'NotResource', 'AWS'} else None
                return self.desired_reference(service, item, kind, path, attribute)
            if isinstance(item, list):
                return [references(child, field, operands, path + '[]') for child in item]
            if isinstance(item, dict):
                if self.local_comparison:
                    intrinsic = next((key for key in item if key == 'Ref' or key.startswith('Fn::')), None)
                    if intrinsic:
                        if intrinsic not in {'Fn::Split', 'Fn::Select', 'Fn::Join', 'Fn::Sub'} or len(item) != 1 or stack is None:
                            raise Blocked(f'unproven model intrinsic reference: {intrinsic} {item[intrinsic]}; no confirmed template/target binding')
                        argument = references(item[intrinsic], field, True, path)
                        if intrinsic == 'Fn::Sub':
                            text, variables = (argument, {}) if isinstance(argument, str) else argument if isinstance(argument, list) and len(argument) == 2 else (None, None)
                            if not isinstance(text, str) or not isinstance(variables, dict):
                                raise ValueError('invalid Fn::Sub')
                            if any(not key.startswith('!') and key not in variables for key in re.findall(r'\$\{([^}]+)\}', text)):
                                raise Blocked('unproven model Sub variable; explicit bindings required')
                        # Only literals and confirmed model links reach the existing evaluator.
                        return self.evaluate(stack, {intrinsic: argument})
                return {key: references(child, field if operands else key, operands, path + '.' + key) for key, child in item.items()}
            return item
        return references(value, path=row['property'].removeprefix(kind + '.'))

    def templates(self):
        if self._templates is not None:
            return self._templates
        stackpath = self.root / 'model' / self.environment / self.directory / 'cloudformation-stacks.properties'
        self.inputs.add(stackpath)
        if not stackpath.is_file():
            self._templates = []
            return self._templates
        _, stacks = stack_model(self.model('cloudformation-stacks').values)
        self._templates = stacks
        return self._templates

    def stack(self, unit):
        name = unit['name']
        if name in self.stack_errors:
            raise self.stack_errors[name].with_traceback(None)
        try:
            return self.stack_input(unit)
        except (Blocked, ValueError, KeyError, TypeError, OSError) as error:
            self.stack_errors[name] = error
            raise

    def stack_input(self, unit):
        name = unit['name']
        template = self.root / 'infra/cloudformation/templates' / self.target.get('alias', '') / unit['template']
        parameters_path = self.root / 'infra/cloudformation/parameters' / self.environment / self.directory / unit['parameters']
        self.track(template)
        self.track(parameters_path)
        if name in self.stack_inputs:
            return template, self.stack_inputs[name]
        for path in (template, parameters_path):
            if not path.is_file():
                blocked = Blocked(f'stack input missing: {path.relative_to(self.root).as_posix()}')
                blocked.iac_cause = {'kind': 'template-missing' if path == template else 'parameters-missing',
                                     'path': path.relative_to(self.root).as_posix(), 'stack': name,
                                     'relationship': 'stack-input'}
                raise blocked
        if template not in self.documents:
            from cfnlint.decode import decode
            document, errors = decode(str(template))
            self.metrics['template_decodes'] += 1
            if errors or not isinstance(document, dict):
                raise ValueError(f'invalid template: {template}')
            self.documents[template] = document
        document = self.documents[template]
        _, values = load_template_inputs(template, parameters_path, strict_parameters=True, document=document)
        definitions = document.get('Parameters', {})
        for key, definition in definitions.items():
            if definition.get('NoEcho') or re.search(r'password|secret|token|credential', key, re.I):
                value = values[key]
                self.sensitive_values.update(str(item) for item in (value if isinstance(value, list) else [value]))
        pseudo = {'AWS::StackName': name, 'AWS::AccountId': self.target.get('awsExecutionAccountId', self.target['awsAccountId']),
                  'AWS::Region': self.target['awsRegion'], 'AWS::NoValue': {'$noValue': True}}
        if not hasattr(self, 'partition'):
            from botocore.loaders import Loader
            self.partition = next((part['partition'] for part in Loader().load_data('endpoints')['partitions']
                                   if self.target['awsRegion'] in part['regions']), None)
        if self.partition is not None:
            pseudo['AWS::Partition'] = self.partition
        self.stack_inputs[name] = document, values, pseudo
        self.metrics['stack_evaluations'] += 1
        return template, self.stack_inputs[name]

    def run(self):
        self.local_comparison = True
        self.symbols.clear()
        for service, error in self.load_errors:
            self.record('error', service, '*', '*', error)
        if self.target['iacEngine'] != 'cloudformation':
            for service in self.services:
                self.record('uncompared', service, '*', '*', 'Terraform: no existing local resource correspondence/evaluator; no init/plan/provider calls')
            return self.results
        stacks = dict((unit['name'], unit) for _, unit in self.templates())
        # Load/evaluate only stacks assigned to selected resources (legacy candidates need all declared stacks).
        for service in self.services:
            for identity, resource in self.resources[service].items():
                mode = resource_mode(resource)
                if mode == 'IMPORT':
                    self.record('excluded', service, identity, '*', 'IMPORT is outside IaC generation')
                    continue
                try:
                    kind = resource['resourceType']
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
                        direct, _ = self.index()
                        if len(direct.get((name, logical), [])) != 1:
                            raise Blocked(f'duplicate resource correspondence: {name}/{logical}')
                    else:
                        candidates, unresolved, causes = [], [], []
                        for name, unit in stacks.items():
                            try:
                                template, (document, parameters, pseudo) = self.stack(unit)
                            except Blocked as error:
                                unresolved.append(f'{name}: {error}')
                                causes.append(getattr(error, 'iac_cause', None))
                                continue
                            direct, legacy = self.index()
                            for logical, definition in document.get('Resources', {}).items():
                                if definition.get('Type') != cfn_type:
                                    continue
                                try:
                                    entry = mapped_resource(direct, legacy, name, logical, cfn_type, any(n == name for n, _ in direct))
                                except ValueError as error:
                                    unresolved.append(f'{name}/{logical}: {error}')
                                    causes.append(None)
                                    continue
                                if entry[0].stem == service and entry[1] == identity:
                                    candidates.append((name, template, document, parameters, pseudo, logical, definition))
                        if unresolved:
                            blocked = Blocked('incomplete legacy candidate search; ' + '; '.join(unresolved))
                            if all(causes) and len({(cause['kind'], cause['path']) for cause in causes}) == 1:
                                blocked.iac_cause = dict(causes[0], relationship='legacy-search-incomplete')
                            raise blocked
                        if len(candidates) != 1:
                            raise Blocked(f'legacy correspondence matches={len(candidates)}; explicit cfn-logicalId required')
                        name, template, document, parameters, pseudo, logical, definition = candidates[0]
                    if document.get('Transform'):
                        raise Blocked('Transform requires external evaluation')
                    if definition is None:
                        self.record('difference', service, identity, '*', 'resource missing', desired={'resourceType': kind, 'logical': logical}, stack=name,
                                    template={'path': template.relative_to(self.root).as_posix()})
                        continue
                    if definition.get('Type') != cfn_type:
                        raise Blocked(f'formal resource type mismatch: {definition.get("Type")} != {cfn_type}')
                    if not condition_active(document, parameters, pseudo, definition):
                        self.record('difference', service, identity, '*', 'CREATE resource is inactive under confirmed parameters', stack=name)
                        continue
                    self.compare_rows(service, identity, resource, name, logical, template, definition, document)
                except (Blocked, KeyError) as error:
                    self.record('uncompared', service, identity, '*', str(error), cause=getattr(error, 'iac_cause', None))
                except (OSError, ValueError, ImportError, TypeError) as error:
                    self.record('error', service, identity, '*', str(error))
        return self.results

    def compare_rows(self, service, identity, resource, name, logical, template, definition, document):
        kind = resource['resourceType']
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
                    self.record('difference', service, identity, rowkind, 'inline CREATE child is inactive', stack=name)
                    continue
            desired, sources, incomplete, exact = {}, {}, set(), set()
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
                        value = self.desired_value(service, row, rowkind, stack=name)
                    except (Blocked, KeyError) as error:
                        self.record('uncompared', service, identity, prop, str(error), source=source)
                        incomplete.add(short.split('.', 1)[0].removesuffix('[]'))
                        continue
                    except (ValueError, TypeError) as error:
                        self.record('error', service, identity, prop, str(error), source=source)
                        incomplete.add(short.split('.', 1)[0].removesuffix('[]'))
                        continue
                if '.' not in short and not short.endswith('[]'):
                    exact.add(short)
                put_row(desired, short, value)
                sources.setdefault(short.split('.', 1)[0].removesuffix('[]'), []).append(source)
            for key, value in desired.items():
                prop = rowkind + '.' + key
                if key in incomplete:
                    self.record('uncompared', service, identity, prop, 'incomplete nested input; whole setting comparison deferred')
                    continue
                iac_source = {'path': template.relative_to(self.root).as_posix()}
                property_key = next((entry for entry in owner.get('Properties', {}) if entry == key), None)
                mark = getattr(property_key, 'start_mark', None) or getattr(owner, 'start_mark', None)
                if mark is not None:
                    iac_source['line'] = mark.line + 1
                actual = owner.get('Properties', {}).get(key)
                if key not in owner.get('Properties', {}):
                    self.record('difference', service, identity, prop, 'property missing', desired=value, stack=name,
                                source=sources[key][0], template=iac_source)
                    self.results[-1]['model_sources'] = sources[key]
                    continue
                try:
                    actual = self.evaluate(name, actual)
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
                reference = (lambda left, right, path: self.reference_same(left, right, rowkind, path)) if self.local_comparison else None
                equal = (same(value, actual, reference=reference, path=key) if key in exact else
                         selected_same(value, actual, key, reference=reference, path=key))
                if equal is None:
                    self.record('uncompared', service, identity, prop, 'reference identity or property format is unproven',
                                stack=name, source=sources[key][0], template=iac_source)
                elif not equal:
                    self.record('difference', service, identity, prop, 'value mismatch', value, actual, name, sources[key][0], iac_source)
                    self.results[-1]['model_sources'] = sources[key]
                    # Preserve original records; capture display evidence before redaction loses it.
                    from issues_reports import identifier, value_differences
                    self.display_differences[identifier(self.results[-1])] = value_differences(
                        value, actual, prop, exact=key in exact, redact=self.redacted, reference=reference)
                else:
                    reason = 'reference expression equivalent' if self.reference_equivalent else 'equal'
                    self.record('matched', service, identity, prop, reason, stack=name, source=sources[key][0], template=iac_source)
