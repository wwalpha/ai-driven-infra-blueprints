"""Target-batched, local desired → CloudFormation comparison. No AWS/provider calls."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from cloudformation_inputs import Blocked, condition_active, load_target, load_template_inputs, resolve_value, output_value
from model.adapters.observed import resource_index, mapped_resource
from design_catalog import DesignSchemaCatalog
from design_layout import GROUPED, HIDDEN_PROPERTIES, resource_mode
from iac_values import cfn_resource_identity
from model.projection import catalog_outputs, reference_attribute
from model.core import LINK, entries, stack_model
from model.sources import model_paths, model_exists
from model.files import load_model, resource_row_index, MAX_LINES
from policy_tables import literal, POLICY_FORMATS


from iac_evaluation import Evaluation
from comparison_rows import Unresolved, cloudtrail_rows, put_row, select
from service_rows import pipeline_rows
from array_display import indexed_rows
from iac_values import ResourceReference, Expression, safe_value, same, selected_same, unordered_same
from utils.json_format import policy_json as strict_json


from reference_contracts import REFERENCE_FORMS, REFERENCE_PROPERTIES

# Local policy for the currently failing KMS consumers; other contracts stay unchanged.
KMS_COMPARISON_FORMS = {
    'Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey': {'KeyArn'},
    # CloudFormation KmsKeyId accepts key/alias ARNs; their forms remain distinct.
    'Logs.LogGroup.KmsKeyId': {'KeyArn', 'AliasArn'},
    'Glue.SecurityConfiguration.EncryptionConfiguration.S3Encryptions[].KmsKeyArn': {'AliasArn'},
    'Glue.SecurityConfiguration.EncryptionConfiguration.CloudWatchEncryption.KmsKeyArn': {'AliasArn'},
    'CodePipeline.Pipeline.ArtifactStore.EncryptionKey.Id': {'AliasArn'},
}

# Documented Ref returns, independent of provider primaryIdentifier.
# https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-<service>-<resource>.html#aws-resource-<service>-<resource>-return-values
REF_ATTRIBUTES = {
    'S3.Bucket': 'BucketName', 'Logs.LogGroup': 'LogGroupName',
    'SQS.Queue': 'QueueUrl', 'KMS.Key': 'KeyId', 'KMS.Alias': 'AliasName',
    'IAM.Role': 'RoleName', 'EC2.Subnet': 'SubnetId', 'EC2.VPC': 'VpcId',
    'CodeBuild.Project': 'Name', 'Lambda.Function': 'FunctionName',
    'CodeCommit.Repository': 'RepositoryId',
    'EC2.RouteTable': 'RouteTableId', 'IAM.InstanceProfile': 'InstanceProfileName',
    'Route53.HostedZone': 'Id',
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-glue-connection.html
    'Glue.Connection': 'Name',
    # https://docs.aws.amazon.com/controltower/latest/controlreference/glue-rules.html
    'Glue.SecurityConfiguration': 'Name',
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-athena-workgroup.html
    'Athena.WorkGroup': 'Name',
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-iam-managedpolicy.html
    'IAM.ManagedPolicy': 'PolicyArn',
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-secretsmanager-secret.html
    'SecretsManager.Secret': 'Id',
}


from model.core import ReferenceResolutionError
from model.identity import URI

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
                analysis = load_model(root / 'model' / environment / directory / (service + '.properties'))
                self.inputs.update(analysis.files)
                self.read_hashes.update({file: hashlib.sha256(text.encode('utf-8')).hexdigest() for file, text in analysis.files.items()})
                self.warnings.extend(analysis.warnings)
                self.resources[service], self.rows[service] = {}, {}
            except (OSError, ValueError) as error:
                self.load_errors.append((service, str(error)))
                self.resources[service], self.rows[service] = {}, {}

    def model(self, service):
        if not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', service):
            raise ValueError('invalid reference service')
        if service not in self.models:
            path = self.root / 'model' / self.environment / self.directory / (service + '.properties')
            loaded = load_model(path)
            self.warnings.extend(getattr(loaded, "warnings", ()))
            if service != 'cloudformation-stacks' and loaded.values.get(f'desired.service.{service}.serviceId') != service:
                raise ValueError(f'mismatched service ID: {path}')
            self.models[service] = loaded
            self._index = None
            self.symbols.clear()
            self.inputs.update(loaded.dependencies)
            self.read_hashes.update({file: None if raw is None else hashlib.sha256(raw).hexdigest() for file, raw in loaded.dependencies.items()})
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

    def record_inactive(self, service, identity, prop, name, logical, template, definition):
        document, parameters, pseudo = self.stack_inputs[name]
        condition = definition['Condition']
        path = template.relative_to(self.root).as_posix()
        location = {'path': path, 'key': f'Resources.{logical}.Condition'}
        mark = getattr(next(key for key in definition if key == 'Condition'), 'start_mark', None) or getattr(definition, 'start_mark', None)
        if mark is not None:
            location['line'] = mark.line + 1
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

    def reference(self, service, value, expected_attribute=None):
        from model.identity import parse_reference, Resolver
        environment, directory, refservice, logical = parse_reference(value)
        if (environment, directory) != (self.environment, self.directory):
            Resolver(self.root).resolve(value)
            raise Blocked('cross-target IaC reference requires a proven handoff')
        self.model(refservice)
        candidates = [(identity, resource) for identity, resource in self.resources[refservice].items()
                      if resource['logicalId'] == logical]
        if len(candidates) != 1:
            raise Blocked(f'reference mapping matches={len(candidates)}: {value}')
        identity, resource = candidates[0]
        attributes = {row['property'].removeprefix(resource['resourceType'] + '.')
                      for _, row in self.rows[refservice][identity]
                      if row['property'] in catalog_outputs(self.root, resource['resourceType'])}
        primary = self.catalog.schema(resource['resourceType']).get('primaryIdentifier', [])
        if expected_attribute is None:
            expected_attribute = REF_ATTRIBUTES.get(resource['resourceType'])
            if expected_attribute is None:
                raise Blocked(f'reference attribute is unproven: {resource["resourceType"]}; explicit property contract required')
        expected_attribute = reference_attribute(resource['resourceType'], expected_attribute)
        # The link label is never a physical ID, including PENDING_DEPLOY.
        readonly = self.catalog.schema(resource['resourceType']).get('readOnlyProperties', [])
        alias_arn = resource['resourceType'] == 'KMS.Alias' and expected_attribute == 'AliasArn'
        if not alias_arn and expected_attribute not in attributes and '/properties/' + expected_attribute not in primary + readonly:
            raise Blocked(f'reference attribute not confirmed: {expected_attribute}')
        if resource_mode(resource) == 'IMPORT':
            observed = [literal(self.models[refservice].values.get(f'observed.row.{rid}.value', 'PENDING_DEPLOY'))
                        for rid, row in self.rows[refservice][identity]
                        if row['property'] == resource['resourceType'] + '.' + expected_attribute]
            if not observed or all(value == 'PENDING_DEPLOY' for value in observed):
                raise Blocked('IMPORT reference is PENDING_DEPLOY (not imported/unobserved); comparison deferred until approved handoff; no physical ID inference')
            raise Blocked('IMPORT reference requires approved handoff; no physical ID inference')
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
            if self.symbols[cachekey] is None:
                raise Blocked(f'cyclic resource reference: {stack}/{logical}')
            return self.symbols[cachekey]
        document, parameters, pseudo = self.stack_inputs[stack]
        definition = document.get('Resources', {}).get(logical)
        if not definition or not condition_active(document, parameters, pseudo, definition):
            raise Blocked(f'local resource reference missing/inactive: {stack}/{logical}')
        if self.local_comparison and not self.reference_models_loaded:
            # Same-target model identities establish uniqueness, never physical values.
            for path in model_paths(self.root, self.environment, self.directory):
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
            if self.local_comparison and resource['resourceType'] == 'EC2.SecurityGroup':
                # Ref is a group ID only when VpcId is specified; GetAtt GroupId is unconditional.
                # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ec2-securitygroup.html
                self.symbols[cachekey] = None
                try:
                    vpc = self.evaluate(stack, definition.get('Properties', {}).get('VpcId'))
                finally:
                    self.symbols.pop(cachekey, None)
                if isinstance(vpc, ResourceReference):
                    service, rid = vpc['$resource']
                    confirmed = self.resources[service][rid]['resourceType'] == 'EC2.VPC' and vpc['$attribute'] == 'VpcId'
                else:
                    confirmed = isinstance(vpc, str) and re.fullmatch(r'vpc-[0-9a-f]+', vpc)
                if not confirmed:
                    raise Blocked('SecurityGroup Ref requires a proven explicit VpcId; group name is not a group ID')
                attribute = 'GroupId'
            else:
                attribute = REF_ATTRIBUTES.get(resource['resourceType'])
            if attribute is None:
                raise Blocked(f'Ref return attribute is unproven: {resource["resourceType"]}')
        else:
            try:
                self.catalog.property_schema(resource['resourceType'], attribute)
            except ValueError as error:
                if self.local_comparison:
                    raise Blocked(f'unproven resource attribute: {logical}.{attribute}') from error
                raise
            if self.local_comparison and '/properties/' + attribute.replace('.', '/') not in self.catalog.schema(resource['resourceType']).get('readOnlyProperties', []):
                raise Blocked(f'unproven GetAtt return attribute: {logical}.{attribute}')
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
        if self.local_comparison and key in KMS_COMPARISON_FORMS:
            return KMS_COMPARISON_FORMS[key]
        if key not in self.reference_formats:
            try:
                node = self.catalog.property_schema(kind, path)
            except KeyError:
                # Policy document members and open JSON fields have no typed schema.
                node = {}
            contract = REFERENCE_PROPERTIES.get(key)
            forms = REFERENCE_FORMS.get(key)
            if forms is None and contract and contract[1]:
                forms = {contract[1]}
            self.reference_formats[key] = ({'Arn'} if node.get('pattern', '').startswith('^arn:') or
                                           node.get('type') == 'string' and path.removesuffix('[]').lower().endswith(('arn', 'arns')) else forms)
        return self.reference_formats[key]

    def reference_diagnostic(self, left, right, kind, path, reason):
        forms = self.reference_forms(kind, path)
        symbols = all(isinstance(value, ResourceReference) for value in (left, right))
        identity = ('same' if left['$resource'] == right['$resource'] else 'different') if symbols else 'unproven'
        def format_status(value):
            if self.local_comparison and kind + '.' + path in KMS_COMPARISON_FORMS:
                form = self.kms_format(value)
                return 'unproven' if form is None else 'allowed' if form in forms else 'outside allowed forms'
            if forms is None or not isinstance(value, ResourceReference):
                return 'unproven'
            service, identity = value['$resource']
            refkind = self.resources[service][identity]['resourceType']
            return 'allowed' if value['$attribute'] in {reference_attribute(refkind, form) for form in forms} else 'outside allowed forms'
        return self.redacted(dict(path=kind + '.' + path, model=self.redacted(left, path),
                                  iac=self.redacted(right, path), identity=identity,
                                  allowed_forms=sorted(forms) if forms is not None else None,
                                  format=dict(model=format_status(left), iac=format_status(right)), reason=reason))

    def reference_literal(self, value):
        """Resolve explicit names/ARNs and supported expressions, never generated IDs."""
        if isinstance(value, Expression):
            if value.operation in {'Split', 'Select'}:
                first, source = value.operands
                if isinstance(source, (ResourceReference, Expression)):
                    source = self.reference_literal(source)
                if value.operation == 'Split' and isinstance(first, str) and first and isinstance(source, str):
                    return source.split(first)
                if value.operation == 'Select' and isinstance(source, list) and re.fullmatch(r'\d+', str(first)) and int(first) < len(source):
                    return source[int(first)]
                raise Blocked('Split/Select requires concrete operands and an in-bounds index')
            if value.operation != 'Sub':
                raise Blocked('expression has no local literal comparison contract')
            text, variables = value.operands
            def replace(match):
                key = match.group(1)
                if key.startswith('!'):
                    return '${' + key[1:] + '}'
                child = variables[key]
                if isinstance(child, str):
                    return child
                if isinstance(child, ResourceReference):
                    service, identity = child['$resource']
                    if self.resources[service][identity]['resourceType'] in {'S3.Bucket', 'Logs.LogGroup', 'CodeBuild.Project', 'Events.Rule'} and child['$attribute'] == 'Arn':
                        return self.reference_literal(child)
                if isinstance(child, Expression):
                    resolved = self.reference_literal(child)
                    if isinstance(resolved, str):
                        return resolved
                raise Blocked('Sub variable requires a proven S3 ARN or string')
            return re.sub(r'\$\{([^}]+)\}', replace, text)
        service, identity = value['$resource']
        resource = self.resources[service][identity]
        name, logical = cfn_resource_identity(resource['cfn-logicalId'])
        units = [unit for _, unit in self.templates() if unit['name'] == name]
        if len(units) != 1:
            raise Blocked('reference stack correspondence is unproven')
        self.stack(units[0])
        attribute = value['$attribute']
        alias_arn = resource['resourceType'] == 'KMS.Alias' and attribute == 'AliasArn'
        if alias_arn:
            alias = self.reference_literal(ResourceReference(dict(value, **{'$attribute': 'AliasName'})))
            if self.kms_format(alias) != 'AliasName':
                raise Blocked('alias ARN requires a valid explicit AliasName')
            pseudo = self.stack_inputs[name][2]
            return f"arn:{pseudo['AWS::Partition']}:kms:{pseudo['AWS::Region']}:{pseudo['AWS::AccountId']}:{alias}"
        secret_name = resource['resourceType'] == 'SecretsManager.Secret' and attribute == 'Name'
        bound = self.symbol(name, logical, None if secret_name or attribute == REF_ATTRIBUTES.get(resource['resourceType']) else attribute)
        if secret_name:
            bound = ResourceReference(dict(bound, **{'$attribute': 'Name'}))
        if not same(bound, value):
            raise Blocked('reference resource correspondence is unproven')
        document, _, pseudo = self.stack_inputs[name]
        if document.get('Transform'):
            raise Blocked('Transform requires external evaluation')
        evaluator = Evaluation(self.stack_inputs, self.resources, self.catalog.property_schema,
                               self.symbol, self.import_value, self.local_comparison)
        properties = document['Resources'][logical].get('Properties', {})
        if resource['resourceType'] == 'Glue.Connection' and attribute == 'Name':
            properties = properties.get('ConnectionInput', {})
        if resource['resourceType'] == 'Lambda.Function' and attribute == 'Arn':
            # AWS::Lambda::Function Arn is unqualified; aliases/versions retain separate identities.
            if 'FunctionName' not in properties:
                raise Blocked('Lambda ARN requires explicit FunctionName')
            function = evaluator.substitution(name, ResourceReference(dict(value, **{'$attribute': 'FunctionName'})), frozenset())
            if not isinstance(function, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', function):
                raise Blocked('Lambda FunctionName is not a proven unqualified name')
            return f"arn:{pseudo['AWS::Partition']}:lambda:{pseudo['AWS::Region']}:{pseudo['AWS::AccountId']}:function:{function}"
        if resource['resourceType'] == 'S3.Bucket' and attribute == 'Arn':
            # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-s3-bucket.html#aws-resource-s3-bucket-return-values
            if resource_mode(resource) == 'IMPORT':
                raise Blocked('S3 ARN requires a CREATE resource with an explicit BucketName')
            bucket = self.reference_literal(ResourceReference(dict(value, **{'$attribute': 'BucketName'})))
            if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket):
                raise Blocked('S3 ARN requires a proven bucket name without a path or wildcard')
            return f"arn:{pseudo['AWS::Partition']}:s3:::{bucket}"
        named_arns = {'Logs.LogGroup': ('LogGroupName', r'[.\-_/#A-Za-z0-9]{1,512}', 'logs', 'log-group:', ':*'),
                      'CodeBuild.Project': ('Name', r'[A-Za-z0-9][A-Za-z0-9_-]{1,254}', 'codebuild', 'project/', ''),
                      'Events.Rule': ('Name', r'[.\-_A-Za-z0-9]{1,64}', 'events', 'rule/', '')}
        if attribute == 'Arn' and resource['resourceType'] in named_arns:
            field, pattern, service, prefix, suffix = named_arns[resource['resourceType']]
            explicit = evaluator.evaluate(name, properties.get(field))
            if not isinstance(explicit, str) or not re.fullmatch(pattern, explicit):
                raise Blocked('ARN requires a valid explicit resource name')
            if resource['resourceType'] == 'Events.Rule' and evaluator.evaluate(name, properties.get('EventBusName', 'default')) != 'default':
                raise Blocked('rule ARN requires a confirmed default event bus')
            return f"arn:{pseudo['AWS::Partition']}:{service}:{pseudo['AWS::Region']}:{pseudo['AWS::AccountId']}:{prefix}{explicit}{suffix}"
        if (attribute != REF_ATTRIBUTES.get(resource['resourceType']) and not secret_name) or attribute not in properties:
            raise Blocked('reference has no explicit name property contract')
        result = evaluator.substitution(name, value, frozenset())
        if not isinstance(result, str):
            raise Blocked('reference name remains symbolic')
        if not result or result in {'UNSET', 'PENDING_DEPLOY', 'TBD', 'TODO', '未確定'}:
            raise Blocked('reference name is unresolved')
        return result

    def kms_format(self, value):
        if isinstance(value, ResourceReference):
            service, identity = value['$resource']
            kind = self.resources[service][identity]['resourceType']
            return {('KMS.Key', 'KeyId'): 'KeyId', ('KMS.Key', 'Arn'): 'KeyArn',
                    ('KMS.Alias', 'AliasName'): 'AliasName', ('KMS.Alias', 'AliasArn'): 'AliasArn'}.get((kind, value['$attribute']), 'invalid')
        if isinstance(value, Expression):
            return None
        if not isinstance(value, str):
            return 'invalid'
        if '{{resolve:' in value or '${' in value:
            return None
        key = r'(?:[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}|mrk-[a-fA-F0-9]{32})'
        alias = r'alias/[A-Za-z0-9:/_-]+'
        arn = r'arn:[a-z0-9-]+:kms:[a-z0-9-]+:\d{12}:'
        for form, pattern in [('KeyId', key), ('KeyArn', arn + 'key/' + key), ('AliasName', alias), ('AliasArn', arn + alias)]:
            if re.fullmatch(pattern, value):
                return form
        return 'invalid'

    def reference_same(self, left, right, kind, path, diagnostics=None):
        """Compare proven identities under a property contract, retaining form/alias intent."""
        if (self.local_comparison and kind == 'CodeBuild.Project' and
                path == 'Environment.EnvironmentVariables[].Value'):
            if isinstance(left, Expression) or isinstance(right, Expression):
                try:
                    values = [self.reference_literal(value) if isinstance(value, (Expression, ResourceReference)) else value
                              for value in (left, right)]
                    return same(*values)
                except (Blocked, ValueError, KeyError, TypeError, OSError):
                    return None
            if isinstance(left, ResourceReference) and isinstance(right, ResourceReference):
                return same(left, right)
            if isinstance(left, ResourceReference) != isinstance(right, ResourceReference):
                symbol, other = (left, right) if isinstance(left, ResourceReference) else (right, left)
                if isinstance(other, str):
                    forms = self.kms_format(symbol), self.kms_format(other)
                    if all(form not in {None, 'invalid'} for form in forms) and forms[0] != forms[1]:
                        return False
                    try:
                        return same(self.reference_literal(symbol), other)
                    except (Blocked, ValueError, KeyError, TypeError, OSError):
                        return None
        allowed = KMS_COMPARISON_FORMS.get(kind + '.' + path) if self.local_comparison else None
        if allowed:
            forms = self.kms_format(left), self.kms_format(right)
            reason = None
            if any(form is not None and form not in allowed for form in forms):
                result, reason = False, f'KMS format outside allowed forms: model={forms[0]}, iac={forms[1]}'
            elif None in forms:
                result, reason = None, 'KMS format is unproven'
            elif forms[0] != forms[1]:
                result, reason = False, f'KMS format mismatch: model={forms[0]}, iac={forms[1]}'
            elif isinstance(left, ResourceReference) and isinstance(right, ResourceReference):
                result = same(left, right)
            else:
                try:
                    values = [self.reference_literal(value) if isinstance(value, ResourceReference) else value for value in (left, right)]
                    result = same(*values)
                except (Blocked, ValueError, KeyError, TypeError, OSError):
                    result, reason = None, 'same KMS format; physical value is unproven'
            if reason and diagnostics is not None:
                diagnostics.append(self.reference_diagnostic(left, right, kind, path, reason))
            return result
        if (kind.startswith('IAM.') and path.endswith('.Statement') and
                isinstance(left, list) and isinstance(right, list) and
                POLICY_FORMATS.get(kind + '.' + path.removesuffix('.Statement')) == 'statement'):
            return unordered_same(left, right, path=path,
                                  reference=lambda a, b, p: self.reference_same(a, b, kind, p, diagnostics))
        # https://docs.aws.amazon.com/codebuild/latest/userguide/build-spec-ref.html#build-spec.env.secrets-manager
        if (kind == 'CodeBuild.Project' and path.endswith('EnvironmentVariables[]') and
                isinstance(left, dict) and isinstance(right, dict) and
                left.get('Type') == right.get('Type') == 'SECRETS_MANAGER'):
            def secret_value(a, b, p):
                if p == path:
                    return NotImplemented
                if p.endswith('.Value') and isinstance(a, ResourceReference) != isinstance(b, ResourceReference):
                    symbol, text = (a, b) if isinstance(a, ResourceReference) else (b, a)
                    service, identity = symbol['$resource']
                    if (self.resources[service][identity]['resourceType'] == 'SecretsManager.Secret' and
                            isinstance(text, str) and not text.startswith('arn:')):
                        try:
                            name = self.reference_literal(ResourceReference(dict(symbol, **{'$attribute': 'Name'})))
                        except (Blocked, ValueError, KeyError, TypeError, OSError):
                            return None
                        return same(name, text)
                return self.reference_same(a, b, kind, p, diagnostics)
            return same(left, right, reference=secret_value, path=path)
        # IAM permits a single Action with or without array brackets; other JSON stays typed.
        # https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_grammar.html
        if (kind.startswith('IAM.') and path.endswith('.Statement[].Action') and
                POLICY_FORMATS.get(kind + '.' + path.removesuffix('.Statement[].Action')) == 'statement' and
                (isinstance(left, str) and isinstance(right, list) or isinstance(left, list) and isinstance(right, str))):
            return same([left] if isinstance(left, str) else left, [right] if isinstance(right, str) else right)

        def unproven(reason):
            if diagnostics is not None:
                diagnostics.append(self.reference_diagnostic(left, right, kind, path, reason))
            return None

        if isinstance(left, Expression) or isinstance(right, Expression):
            if same(left, right):
                return True
            expression, other = (left, right) if isinstance(left, Expression) else (right, left)
            if not isinstance(other, str):
                return unproven('unresolved expression; reference identity and format cannot be proven')
            try:
                equal = same(self.reference_literal(expression), other)
            except (Blocked, ValueError, KeyError, TypeError, OSError) as error:
                return unproven(str(error))
            if equal:
                self.reference_equivalent = True
            return equal
        symbols = [value for value in (left, right) if isinstance(value, ResourceReference)]
        if not symbols:
            return NotImplemented
        if not any(self.resources[value['$resource'][0]][value['$resource'][1]]['resourceType']
                   in {'KMS.Key', 'KMS.Alias'} for value in symbols):
            if len(symbols) == 2:
                forms = self.reference_forms(kind, path)
                refkind = self.resources[left['$resource'][0]][left['$resource'][1]]['resourceType']
                allowed = {reference_attribute(refkind, form) for form in forms or ()}
                if left['$resource'] == right['$resource'] and left['$attribute'] in allowed and right['$attribute'] in allowed:
                    if left['$attribute'] != right['$attribute']:
                        self.reference_equivalent = True
                    return True
                return same(left, right)
            other = right if isinstance(left, ResourceReference) else left
            if not isinstance(other, str):
                return unproven('literal versus reference has no proven string contract')
            forms = self.reference_forms(kind, path)
            refkind = self.resources[symbols[0]['$resource'][0]][symbols[0]['$resource'][1]]['resourceType']
            if forms and 'Arn' in forms and other.startswith('arn:') and symbols[0]['$attribute'] != reference_attribute(refkind, 'Arn'):
                return unproven('literal uses an alternative allowed format; local reference value is unproven')
            try:
                concrete = self.reference_literal(symbols[0])
            except (Blocked, ValueError, KeyError, TypeError, OSError) as error:
                return unproven(str(error))
            equal = same(concrete, other)
            if equal:
                self.reference_equivalent = True
            return equal
        if len(symbols) != 2:
            # No observed/AWS values: a literal cannot prove this symbolic identity.
            return unproven('literal versus symbolic reference; no observed value proves identity or format')
        if left['$resource'] != right['$resource']:
            # Aliases retain their own identity; a mutable alias is not a direct key.
            return False
        forms = self.reference_forms(kind, path)
        if forms is not None:
            if left['$attribute'] == right['$attribute'] and left['$attribute'] not in forms:
                return unproven('same reference identity; both attributes are outside the allowed property forms')
            equal = left['$attribute'] in forms and right['$attribute'] in forms
            if equal and left['$attribute'] != right['$attribute']:
                self.reference_equivalent = True
            return equal
        return True if left['$attribute'] == right['$attribute'] else unproven('same reference identity; no property contract proves equivalence of these attributes')

    def desired_reference(self, service, value, kind, path, attribute=None, context=None):
        path = re.sub(r'\[\d+\]', '[]', path)
        if self.local_comparison and kind + '.' + path in KMS_COMPARISON_FORMS:
            symbol = self.reference(service, value)
            refservice, identity = symbol['$resource']
            refkind = self.resources[refservice][identity]['resourceType']
            if KMS_COMPARISON_FORMS[kind + '.' + path] <= {'KeyArn', 'AliasArn'}:
                selected = 'AliasArn' if refkind == 'KMS.Alias' else 'Arn' if refkind == 'KMS.Key' else symbol['$attribute']
                return ResourceReference(dict(symbol, **{'$attribute': selected}))
            return self.reference(service, value, attribute) if attribute else symbol
        context = context or {}
        expected_kind = None
        contract = REFERENCE_PROPERTIES.get(kind + '.' + path)
        if self.local_comparison:
            if kind == 'CloudTrail.Trail' and path == 'EventSelectors[].DataResources[].Values[]':
                if context.get('Type', 'AWS::Lambda::Function') != 'AWS::Lambda::Function':
                    raise Blocked('CloudTrail DataResource link requires a confirmed Lambda ARN; other resource/prefix contracts are unproven')
                expected_kind = 'Lambda.Function'
                attribute = 'Arn'
            elif kind == 'CodePipeline.Pipeline' and path.startswith('Stages[].Actions[].Configuration.'):
                action = context.get('ActionTypeId', {})
                field = path.removeprefix('Stages[].Actions[].Configuration.')
                contracts = {'RepositoryName': ('Source', 'CodeCommit', 'CodeCommit.Repository', 'Name'),
                             'ProjectName': ('Build', 'CodeBuild', 'CodeBuild.Project', 'Name')}
                contract = contracts.get(field)
                if not contract or action != dict(Category=contract[0], Owner='AWS', Provider=contract[1], Version='1'):
                    raise Blocked(f'CodePipeline {field} reference contract unproven: ActionTypeId={action}')
                _, _, expected_kind, attribute = contract
            elif kind == 'CodeBuild.Project' and path == 'Environment.EnvironmentVariables[].Value':
                variable_type = context.get('Type')
                if variable_type == 'SECRETS_MANAGER':
                    expected_kind, attribute = 'SecretsManager.Secret', 'Id'
                elif variable_type == 'PLAINTEXT':
                    if attribute is None:
                        # Preserve the existing bucket-name link; arbitrary strings have no default attribute.
                        expected_kind, attribute = 'S3.Bucket', 'BucketName'
                else:
                    raise Blocked('reference property contract unproven: CodeBuild environment Type is required')
            elif contract:
                expected_kind, default_attribute = contract
                if attribute is None:
                    attribute = default_attribute
            elif kind == 'EC2.FlowLog' and path == 'ResourceId':
                # ResourceId denotes a VPC only with the explicit ResourceType discriminator.
                # https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ec2-flowlog.html
                if context.get('ResourceType') != 'VPC' or attribute not in {None, 'VpcId'}:
                    raise Blocked('reference property contract unproven: EC2.FlowLog.ResourceId requires ResourceType=VPC')
                expected_kind, attribute = 'EC2.VPC', 'VpcId'
            elif attribute is None and self.reference_forms(kind, path) == {'Arn'}:
                attribute = 'Arn'
            elif attribute is None and self.reference_forms(kind, path) is None:
                raise Blocked(f'reference property contract unproven: {kind}.{path}')
        symbol = self.reference(service, value, attribute)
        forms = self.reference_forms(kind, path) if self.local_comparison else None
        refservice, identity = symbol['$resource']
        refkind = self.resources[refservice][identity]['resourceType']
        if forms and symbol['$attribute'] not in {reference_attribute(refkind, form) for form in forms}:
            error = Blocked(f'reference attribute {symbol["$attribute"]} is outside property contract: {kind}.{path}')
            error.reference_detail = (symbol, path)
            raise error
        if expected_kind:
            if refkind not in ((expected_kind,) if isinstance(expected_kind, str) else expected_kind):
                raise Blocked(f'reference target must be {expected_kind}: {kind}.{path}')
        return symbol

    def desired_value(self, service, row, kind, *, stack=None, context=None):
        raw = row.get('document', row['value'])
        if 'document' in row:
            value = strict_json(raw)
        elif URI.fullmatch(raw):
            prop = re.sub(r'\[\d+\]', '[]', row['property'].removeprefix(kind + '.'))
            # A schema-typed ARN property selects the referenced Arn, never a current ARN.
            attribute = 'Arn' if row['property'] == 'CodeBuild.Project.ServiceRole' else None
            node = self.catalog.property_schema(kind, prop)
            symbol = self.desired_reference(service, raw, kind, prop + ('[]' if node.get('type') == 'array' else ''), attribute, context)
            return [symbol] if node.get('type') == 'array' else symbol
        else:
            value = literal(raw)
            if value in {'UNSET', 'PENDING_DEPLOY', 'TBD', 'TODO', '未確定'}:
                raise Blocked('desired value is unresolved')
            node = self.catalog.property_schema(kind, re.sub(r'\[\d+\]', '[]', row['property'].removeprefix(kind + '.')))
            schema_type = node.get('type')
            if schema_type != 'string':
                if schema_type is None:
                    raise Blocked('property type is not uniquely determined')
                value = strict_json(value)
        policy = row['property'].rsplit('.', 1)[-1] in {'PolicyDocument', 'AssumeRolePolicyDocument', 'KeyPolicy', 'Policy'}
        def references(item, field='', operands=False, path='', context=context):
            if isinstance(item, str) and URI.fullmatch(item):
                attribute = 'Arn' if policy and field in {'Resource', 'NotResource', 'AWS'} else None
                return self.desired_reference(service, item, kind, path, attribute, context)
            if isinstance(item, list):
                return [references(child, field, operands, path + '[]', context) for child in item]
            if isinstance(item, dict):
                if '$resource' in item and not (self.local_comparison and kind == 'CodeBuild.Project'
                        and path == 'Environment.EnvironmentVariables[].Value'):
                    if (set(item) - {'$resource', '$attribute'} or not isinstance(item['$resource'], str)
                            or not URI.fullmatch(item['$resource'])
                            or ('$attribute' in item and (not isinstance(item['$attribute'], str) or not item['$attribute']))):
                        raise Blocked('invalid structured Model resource reference')
                    attribute = item.get('$attribute', 'Arn' if policy and field in {'Resource', 'NotResource', 'AWS'} else None)
                    return self.desired_reference(service, item['$resource'], kind, path, attribute, context)
                if self.local_comparison:
                    if (kind == 'CodeBuild.Project' and path == 'Environment.EnvironmentVariables[].Value'
                            and {'$resource', '$attribute'} & item.keys()):
                        if (set(item) != {'$resource', '$attribute'} or not context or context.get('Type') != 'PLAINTEXT'
                                or not all(isinstance(part, str) and part for part in item.values())
                                or not URI.fullmatch(item['$resource'])):
                            raise Blocked('Model environment reference requires PLAINTEXT, an explicit resource link and attribute')
                        symbol = self.desired_reference(service, item['$resource'], kind, path, item['$attribute'], context)
                        target_service, identity = symbol['$resource']
                        target_kind = self.resources[target_service][identity]['resourceType']
                        if not (target_kind == 'KMS.Alias' and symbol['$attribute'] == 'AliasArn') and self.catalog.property_schema(target_kind, symbol['$attribute']).get('type') != 'string':
                            raise Blocked('Model environment reference attribute must be a proven string')
                        return symbol
                    intrinsic = next((key for key in item if key == 'Ref' or key.startswith('Fn::')), None)
                    if intrinsic:
                        if kind == 'SQS.QueuePolicy' and intrinsic == 'Fn::GetAtt' and len(item) == 1 and stack is not None:
                            return self.evaluate(stack, item)
                        if intrinsic not in {'Fn::Split', 'Fn::Select', 'Fn::Join', 'Fn::Sub'} or len(item) != 1 or stack is None:
                            raise Blocked(f'unproven model intrinsic reference: {intrinsic} {item[intrinsic]}; no confirmed template/target binding')
                        argument = references(item[intrinsic], field, True, path, context)
                        if intrinsic == 'Fn::Sub':
                            text, variables = (argument, {}) if isinstance(argument, str) else argument if isinstance(argument, list) and len(argument) == 2 else (None, None)
                            if not isinstance(text, str) or not isinstance(variables, dict):
                                raise ValueError('invalid Fn::Sub')
                            _, parameters, pseudo = self.stack_inputs[stack]
                            bindings = parameters.keys() | pseudo.keys() | variables.keys()
                            if any(not key.startswith('!') and key not in bindings for key in re.findall(r'\$\{([^}]+)\}', text)):
                                raise Blocked('unproven model Sub variable; explicit bindings required')
                        # Model resource variables still require explicit link bindings.
                        return self.evaluate(stack, {intrinsic: argument})
                if path.endswith(('.Actions[]', '.DataResources[]', '.EnvironmentVariables[]')):
                    context = item
                return {key: references(child, field if operands else key, operands, path + '.' + key, context) for key, child in item.items()}
            return item
        path = row['property'].removeprefix(kind + '.')
        if (self.local_comparison and kind == 'CodeBuild.Project' and
                re.sub(r'\[\d+\]', '[]', path) == 'Environment.EnvironmentVariables[].Value'
                and isinstance(value, str) and value.startswith('{')):
            try:
                selector = strict_json(value)
            except ValueError:
                selector = None
            if isinstance(selector, dict) and {'$resource', '$attribute'} & selector.keys():
                value = selector
                path = re.sub(r'\[\d+\]', '[]', path)
        return references(value, path=path)

    def templates(self):
        if self._templates is not None:
            return self._templates
        stackpath = self.root / 'model' / self.environment / self.directory / 'cloudformation-stacks.properties'
        if not model_exists(stackpath):
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
                        direct, _ = self.index()
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
                property_key = next((entry for entry in owner.get('Properties', {}) if entry == key), None)
                mark = getattr(property_key, 'start_mark', None) or getattr(owner, 'start_mark', None)
                if mark is not None:
                    iac_source['line'] = mark.line + 1
                actual = owner.get('Properties', {}).get(key)
                inverse_roles = self.local_comparison and rowkind == 'IAM.ManagedPolicy' and key == 'Roles'
                if key not in owner.get('Properties', {}) and not inverse_roles:
                    self.record('difference', service, identity, prop, 'property missing', desired=value, stack=name,
                                source=sources[key][0], template=iac_source)
                    self.results[-1]['model_sources'] = sources[key]
                    continue
                try:
                    if inverse_roles:
                        actual = self.managed_policy_roles(service, identity, name, owner.get('Properties', {}).get(key, []))
                    else:
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
                diagnostics = []
                reference = (lambda left, right, path: self.reference_same(left, right, rowkind, path, diagnostics)) if self.local_comparison else None
                equal = (unordered_same(value, actual, reference=reference, path=key) if inverse_roles else
                         same(value, actual, reference=reference, path=key) if key in exact else
                         selected_same(value, actual, key, reference=reference, path=key))
                if equal is None:
                    self.record('uncompared', service, identity, prop, 'reference identity or property format is unproven',
                                stack=name, source=sources[key][0], template=iac_source)
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
                    from issues_reports import identifier, value_differences
                    self.display_differences[identifier(self.results[-1])] = value_differences(
                        value, actual, prop, exact=key in exact, redact=self.redacted, reference=reference)
                else:
                    reason = 'reference expression equivalent' if self.reference_equivalent else 'equal'
                    self.record('matched', service, identity, prop, reason, stack=name, source=sources[key][0], template=iac_source)
