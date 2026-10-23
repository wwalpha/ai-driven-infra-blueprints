"""Target-batched, local desired → CloudFormation comparison. No AWS/provider calls."""
from __future__ import annotations

import re

from cloudformation_inputs import Blocked, condition_active
from model.adapters.observed import mapped_resource
from design_layout import resource_mode
from iac_values import cfn_resource_identity
from model.projection import catalog_outputs, reference_attribute, scalar_reference
from model.sources import model_paths
from policy_tables import literal, POLICY_FORMATS


from iac_evaluation import Evaluation, RETURN_ATTRIBUTE_PROPERTIES
from iac_values import ResourceReference, Expression, same, unordered_same
from utils.json_format import policy_json as strict_json


from reference_contracts import REFERENCE_FORMS, REFERENCE_PROPERTIES, SCALAR_REFERENCE_PROPERTIES

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
from model.identity import resource_link

def reference(self, service, value, expected_attribute=None, *, consumer_property=None):
    from model.identity import parse_reference, anchor_index, select_anchor
    from model.sources import Scope
    consumer = Scope(self.root, self.environment, self.directory, service)
    environment, directory, refservice, anchor = parse_reference(value, consumer)
    if (environment, directory) != (self.environment, self.directory):
        from model.identity import Resolver
        Resolver(self.root).resolve(value, consumer)
        raise Blocked('cross-target IaC reference requires a proven handoff')
    model = self.model(refservice)
    if not hasattr(self, 'reference_anchor_indexes'):
        self.reference_anchor_indexes = {}
    if refservice not in self.reference_anchor_indexes:
        self.reference_anchor_indexes[refservice] = anchor_index(model.values)
    try:
        identity, resource = select_anchor(self.reference_anchor_indexes[refservice], anchor, value)
    except ReferenceResolutionError as error:
        raise Blocked(str(error)) from error
    attributes = {row['property'].removeprefix(resource['resourceType'] + '.')
                  for _, row in self.rows[refservice][identity]
                  if row['property'] in catalog_outputs(self.root, resource['resourceType'])}
    schema = self.catalog.schema(resource['resourceType'])
    primary = schema.get('primaryIdentifier', [])
    if expected_attribute is None:
        expected_attribute = REF_ATTRIBUTES.get(resource['resourceType'])
        if expected_attribute is None:
            raise Blocked(f'reference attribute is unproven: {resource["resourceType"]}; explicit property contract required')
    expected_attribute = reference_attribute(resource['resourceType'], expected_attribute)
    # The link label is never a physical ID, including PENDING_DEPLOY.
    readonly = schema.get('readOnlyProperties', [])
    alias_arn = resource['resourceType'] == 'KMS.Alias' and expected_attribute == 'AliasArn'
    if (not alias_arn and expected_attribute not in attributes
            and expected_attribute not in schema.get('identifierOutputs', [])
            and '/properties/' + expected_attribute not in primary + readonly):
        raise Blocked(f'reference attribute not confirmed: {expected_attribute}')
    symbol = ResourceReference({'$resource': [refservice, identity], '$attribute': expected_attribute})
    if resource_mode(resource) == 'IMPORT':
        if (self.local_comparison and consumer_property == 'QuickSight.DataSource.Permissions[].Principal'
                and REFERENCE_PROPERTIES.get(consumer_property) == (resource['resourceType'], expected_attribute)
                and self.target['iacEngine'] == 'cloudformation'):
            self.reference_literal(symbol)
            return symbol
        observed = [literal(self.models[refservice].values.get(f'observed.row.{rid}.value', 'PENDING_DEPLOY'))
                    for rid, row in self.rows[refservice][identity]
                    if row['property'] == resource['resourceType'] + '.' + expected_attribute]
        if not observed or all(value == 'PENDING_DEPLOY' for value in observed):
            raise Blocked('IMPORT reference is PENDING_DEPLOY (not imported/unobserved); comparison deferred until approved handoff; no physical ID inference')
        raise Blocked('IMPORT reference requires approved handoff; no physical ID inference')
    return symbol


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
    direct = self.index()
    try:
        entry = mapped_resource(direct, stack, logical, definition['Type'])
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
    explicit = getattr(left, 'explicit_attribute', False) and kind + '.' + path in SCALAR_REFERENCE_PROPERTIES
    forms = {'KeyArn'} if explicit else self.reference_forms(kind, path)
    symbols = all(isinstance(value, ResourceReference) for value in (left, right))
    identity = ('same' if left['$resource'] == right['$resource'] else 'different') if symbols else 'unproven'
    def format_status(value):
        if explicit or self.local_comparison and kind + '.' + path in KMS_COMPARISON_FORMS:
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
    if (self.local_comparison and resource['resourceType'] == 'QuickSight.Group'
            and resource_mode(resource) == 'IMPORT' and value['$attribute'] == 'Arn'
            and self.target['iacEngine'] == 'cloudformation'):
        from model.importing.references import known
        fields = {}
        for field in self.catalog.schema('QuickSight.Group')['identityProperties']:
            rows = [row for _, row in self.rows[service][identity]
                    if row['property'] == 'QuickSight.Group.' + field]
            if len(rows) != 1 or 'document' in rows[0]:
                raise Blocked('QuickSight Group requires one scalar identity property: ' + field)
            candidate = literal(rows[0]['value'])
            if not known(candidate) or self.catalog.literal_errors('QuickSight.Group', field, candidate):
                raise Blocked('QuickSight Group requires one confirmed identity property: ' + field)
            fields[field] = candidate
        # stack_input establishes partition from the target's recorded SDK Region.
        partition = getattr(self, 'partition', None)
        region = self.target.get('awsRegion')
        if not partition or not region or not any(
                pseudo.get('AWS::Region') == region and pseudo.get('AWS::Partition') == partition
                for _, _, pseudo in self.stack_inputs.values()):
            raise Blocked('QuickSight Group ARN requires a confirmed CloudFormation Region and partition')
        # https://docs.aws.amazon.com/cli/latest/reference/quicksight/create-group.html
        return (f"arn:{partition}:quicksight:{region}:{fields['AwsAccountId']}:"
                f"group/{fields['Namespace']}/{fields['GroupName']}")
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
    setting = RETURN_ATTRIBUTE_PROPERTIES.get((resource['resourceType'], attribute))
    if (attribute != REF_ATTRIBUTES.get(resource['resourceType']) and not secret_name and setting is None) or (setting or attribute) not in properties:
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
    if any(isinstance(value, Expression) and value.operation == 'Unverified' for value in (left, right)):
        return None
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
    if getattr(left, 'explicit_attribute', False) and kind + '.' + path in SCALAR_REFERENCE_PROPERTIES:
        allowed = {'KeyArn'}
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
            elif variable_type != 'PLAINTEXT':
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
    symbol = self.reference(service, value, attribute, consumer_property=kind + '.' + path)
    forms = self.reference_forms(kind, path) if self.local_comparison else None
    refservice, identity = symbol['$resource']
    refkind = self.resources[refservice][identity]['resourceType']
    if (self.local_comparison and kind == 'CodeBuild.Project' and path == 'Environment.EnvironmentVariables[].Value'
            and context.get('Type') == 'PLAINTEXT' and attribute is None and refkind != 'S3.Bucket'):
        raise Blocked(f'CodeBuild PLAINTEXT reference requires an explicit attribute for {refkind}; only S3.Bucket defaults to BucketName')
    if forms and symbol['$attribute'] not in {reference_attribute(refkind, form) for form in forms}:
        error = Blocked(f'reference attribute {symbol["$attribute"]} is outside property contract: {kind}.{path}')
        error.reference_detail = (symbol, path)
        raise error
    if expected_kind:
        if refkind not in ((expected_kind,) if isinstance(expected_kind, str) else expected_kind):
            raise Blocked(f'reference target must be {expected_kind}: {kind}.{path}')
    return symbol


def desired_value(self, service, row, kind, *, stack=None, context=None):
    selector = scalar_reference(row)
    if selector is not None:
        prop = re.sub(r'\[\d+\]', '[]', row['property'])
        symbol = self.desired_reference(service, selector['$resource'], kind,
            prop.removeprefix(kind + '.'), selector['$attribute'], context)
        refservice, identity = symbol['$resource']
        if self.resources[refservice][identity]['resourceType'] != SCALAR_REFERENCE_PROPERTIES[prop][0]:
            raise Blocked('scalar Arn reference requires a KMS.Key')
        symbol.explicit_attribute = True
        return symbol
    raw = row.get('document', row['value'])
    if 'document' in row:
        value = strict_json(raw)
    elif resource_link(raw):
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
    def references(item, field='', operands=False, path='', context=context, pointer=''):
        if isinstance(item, str) and resource_link(item):
            attribute = 'Arn' if policy and field in {'Resource', 'NotResource', 'AWS'} else None
            return self.desired_reference(service, item, kind, path, attribute, context)
        if isinstance(item, list):
            return [references(child, field, operands, path + '[]', context, pointer + '/' + str(index))
                    for index, child in enumerate(item)]
        if isinstance(item, dict):
            if '$resource' in item and not (self.local_comparison and kind == 'CodeBuild.Project'
                    and path == 'Environment.EnvironmentVariables[].Value'):
                if (set(item) - {'$resource', '$attribute'} or not isinstance(item['$resource'], str)
                        or not resource_link(item['$resource'])
                        or ('$attribute' in item and (not isinstance(item['$attribute'], str) or not item['$attribute']))):
                    raise Blocked('invalid structured Model resource reference')
                attribute = item.get('$attribute', 'Arn' if policy and field in {'Resource', 'NotResource', 'AWS'} else None)
                return self.desired_reference(service, item['$resource'], kind, path, attribute, context)
            if self.local_comparison:
                if (kind == 'CodeBuild.Project' and path == 'Environment.EnvironmentVariables[].Value'
                        and {'$resource', '$attribute'} & item.keys()):
                    if (set(item) != {'$resource', '$attribute'} or not context or context.get('Type') != 'PLAINTEXT'
                            or not all(isinstance(part, str) and part for part in item.values())
                            or not resource_link(item['$resource'])):
                        raise Blocked('Model environment reference requires PLAINTEXT, an explicit resource link and attribute')
                    symbol = self.desired_reference(service, item['$resource'], kind, path, item['$attribute'], context)
                    target_service, identity = symbol['$resource']
                    target_kind = self.resources[target_service][identity]['resourceType']
                    if not (target_kind == 'KMS.Alias' and symbol['$attribute'] == 'AliasArn') and self.catalog.property_schema(target_kind, symbol['$attribute']).get('type') != 'string':
                        raise Blocked('Model environment reference attribute must be a proven string')
                    return symbol
                from json_intrinsics import intrinsic, project_document
                if intrinsic(item) and not operands:
                    expression = {key: references(child, field, True, path, context, pointer + '/' + key)
                                  for key, child in item.items()}
                    return project_document(expression,
                        evaluate=(lambda value: self.evaluate(stack, value)) if stack is not None else None,
                        unresolved=lambda value: Expression('Unverified', [value]),
                        warnings=getattr(self, 'warnings', None), property_name=row['property'],
                        model_path=self.root / 'model' / self.environment / self.directory / (service + '.properties'), pointer=pointer)
            if path.endswith(('.Actions[]', '.DataResources[]', '.EnvironmentVariables[]')):
                context = item
            return {key: references(child, field if operands else key, operands, path + '.' + key, context,
                                    pointer + '/' + key.replace('~', '~0').replace('/', '~1')) for key, child in item.items()}
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


