"""Validate declarative mappings and project response values for AWS Compare.

Acquisition remains in service adapters. Provider paths are checked against the
pinned CFn schema without AWS calls.
"""

import re
from pathlib import Path

import aws_mapping as _imports_aws_mapping
import utils.aws_catalogs as _imports_utils_aws_catalogs
import utils.aws_schemas as _imports_utils_aws_schemas
import utils.aws_sdk as _imports_utils_aws_sdk
import utils.mapping_runtime as _mapping_runtime
from design_catalog import DesignSchemaCatalog as DesignSchemaCatalog
from utils.aws_sdk import aws_runtime
from utils.json_format import exact
from utils.script_loader import module

# Existing fetch code explicitly copies these inputs into its projected response.
INPUT_SOURCES = {
    'Macie.Session.AwsAccountId': 'target',
    'QuickSight.DataSource.AwsAccountId': 'model', 'QuickSight.VPCConnection.AwsAccountId': 'model',
    'QuickSight.Group.AwsAccountId': 'model', 'QuickSight.Group.Namespace': 'model',
    'SQS.Queue.QueueName': 'model', 'SQS.QueuePolicy.Queues[]': 'model',
    'Glue.Connection.CatalogId': 'model', 'Glue.Database.CatalogId': 'model',
    'Glue.Table.CatalogId': 'model', 'Glue.Table.DatabaseName': 'model',
    'Route53.RecordSet.HostedZoneId': 'model',
    'ElasticLoadBalancingV2.ListenerCertificate.ListenerArn': 'model', 'SNS.TopicPolicy.Topics': 'model',
}


def project(prop, payload):
    """Apply a validated YAML path and transform to an acquired response payload."""
    comparator = module('model/adapters/aws.py', 'model.adapters.aws')
    value = payload if prop.field.path == '$' else comparator.select(payload, prop.field.path)
    if prop.transform == 'present':
        return value != comparator.MISSING and value is not None
    if prop.transform == 'unique' and isinstance(value, list):
        if not value or comparator.MISSING in value:
            return comparator.MISSING
        if any(item != value[0] for item in value[1:]):
            raise comparator.Unresolved('response does not uniquely identify the original input')
        return value[0]
    return value


def pointer(path):
    return '/properties/' + path.replace('[]', '/*').replace('.', '/')


def under(path, pointers):
    return any(pointer(path) == value or pointer(path).startswith(value + '/') for value in pointers)


def access(schema, path):
    return [label for label, key in [('read-only', 'readOnlyProperties'), ('write-only', 'writeOnlyProperties'),
                                    ('create-only', 'createOnlyProperties'), ('conditional-create-only', 'conditionalCreateOnlyProperties')]
            if under(path, schema.get(key, []))] or ['read-write']


def sdk_shape(sdk, definition):
    response_shape = _imports_aws_mapping.response_shape
    text = _imports_aws_mapping.text
    api = tuple(text(definition[key], key) for key in ('service', 'operation'))
    if not api[1].startswith(('get_', 'describe_', 'list_', 'batch_get_')):
        raise ValueError('Mapping API must be read-only')
    sdk = sdk.service_model(api[0])
    operation = aws_runtime().operation_name(sdk, api[1])
    if operation is None:
        raise ValueError(f'unknown SDK operation: {api}')
    shape = sdk.operation_model(operation).output_shape
    return shape if definition['result'] == '$' else response_shape(shape, definition['result'])


def catalog_properties(root: Path, service, document, *, sdk=None, schemas=None, catalogs=None):
    NORMALIZATIONS = _imports_aws_mapping.NORMALIZATIONS
    Property = _imports_aws_mapping.Property
    response_shape = _imports_aws_mapping.response_shape
    text = _imports_aws_mapping.text
    comparator = module('model/adapters/aws.py', 'model.adapters.aws')
    exact(document, {'version', 'service', 'getters', 'resourceTypes'}, 'Mapping v3')
    if type(document['version']) is not int or document['version'] != 3:
        raise ValueError('Mapping version must be 3')
    if document['service'] != service or not isinstance(document['resourceTypes'], dict) or not document['resourceTypes']:
        raise ValueError('Mapping service/resourceTypes mismatch')
    if not isinstance(document['getters'], dict):
        raise ValueError('Mapping getters must be an object')
    if any(not isinstance(d, dict) or d.get('kind') not in {'adapter', 'sdk', 'cloudcontrol'} for d in document['getters'].values()):
        raise ValueError('unknown getter kind')
    catalogs_for = _imports_utils_aws_catalogs.catalogs_for
    schemas_for = _imports_utils_aws_schemas.schemas_for
    sdk_for = _imports_utils_aws_sdk.sdk_for
    sdk = sdk if sdk is not None else sdk_for(root)
    schemas = schemas if schemas is not None else schemas_for(root)
    catalogs = catalogs if catalogs is not None else catalogs_for(root)
    catalog, getters, result, used = DesignSchemaCatalog(root, definitions=schemas), {}, {}, set()
    for name, definition in document['getters'].items():
        text(name, 'getter')
        kind = definition.get('kind')
        if kind == 'adapter':
            exact(definition, {'kind', 'resources'}, 'adapter getter')
            adapter = comparator.service_module(service)
            if not callable(adapter.fetch):
                raise ValueError('adapter fetch is unavailable')
            resources = definition['resources']
            if (not isinstance(resources, list) or not resources
                    or any(not isinstance(resource, str) or resource not in document['resourceTypes'] for resource in resources)
                    or len(resources) != len(set(resources))):
                raise ValueError('adapter getter/resource mismatch')
            getters[name] = (kind, definition, adapter)
        elif kind in {'sdk', 'cloudcontrol'}:
            keys = {'kind', 'service', 'operation', 'result', 'resourceType'}
            if kind == 'cloudcontrol':
                keys |= {'identifier'}
            exact(definition, keys, 'AWS getter')
            shape = sdk_shape(sdk, definition)
            resource = definition['resourceType']
            if resource not in document['resourceTypes']:
                raise ValueError('getter resource is outside mapping')
            if kind == 'cloudcontrol':
                schema = catalog.schema(resource)
                if (definition['service'], definition['operation'], definition['result']) != (
                        'cloudcontrol', 'get_resource', 'ResourceDescription.Properties'):
                    raise ValueError('invalid Cloud Control read envelope')
                if shape.type_name != 'string' or 'read' not in schema.get('handlers', {}):
                    raise ValueError('resource has no provider read handler')
                if definition['identifier'] != schema.get('primaryIdentifier') or not definition['identifier']:
                    raise ValueError('provider primary identifier mismatch')
            getters[name] = (kind, definition, shape)
        else:
            raise ValueError('unknown getter kind')
    for resource, values in document['resourceTypes'].items():
        exact(values, {'properties'} | ({'identity'} if isinstance(values, dict) and 'identity' in values else set()), resource)
        selected = catalogs.selected(resource)
        if not selected:
            raise ValueError('unknown catalog resource: ' + resource)
        exact(values['properties'], selected, resource + ' catalog properties')
        schema = catalog.schema(resource) if resource not in catalog.api_schemas else None
        if 'identity' in values:
            identity = values['identity']
            exact(identity, {'getter', 'idPath', 'arnPath', 'nameProperty'}, resource + ' identity')
            getter_name = text(identity['getter'], resource + ' identity getter')
            if getter_name not in getters:
                raise ValueError(resource + ': unknown identity getter')
            kind, getter, evidence = getters[getter_name]
            if resource not in (getter['resources'] if kind == 'adapter' else [getter['resourceType']]):
                raise ValueError(resource + ': identity getter/resource mismatch')
            try:
                for key in ('idPath', 'arnPath', 'nameProperty'):
                    path = identity[key]
                    if path is None and key != 'idPath':
                        continue
                    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\[\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\])?)*',
                                        text(path, resource + ' identity ' + key)):
                        raise ValueError(resource + ': invalid identity path')
                    if key == 'nameProperty':
                        if kind != 'adapter' or resource + '.' + path not in getattr(evidence, 'MODEL_FIELDS', {}):
                            catalog.property_schema(resource, path)
                    elif kind == 'sdk':
                        response_shape(evidence, path)
                    elif kind == 'cloudcontrol':
                        if under(path, catalog.schema(resource).get('writeOnlyProperties', [])):
                            raise ValueError(resource + ': write-only identity path')
                        catalog.property_schema(resource, path)
            except KeyError as error:
                raise ValueError(resource + ': unknown identity path') from error
            used.add(getter_name)
        names = set()
        for path, definition in values['properties'].items():
            key = resource + '.' + path
            if ('aws' in definition) == ('source' in definition):
                raise ValueError(key + ': exactly one of aws/source required')
            exact(definition, {'model', 'display', 'access', 'aws' if 'aws' in definition else 'source'}, key)
            exact(definition['model'], {'include'}, key + ' model')
            exact(definition['display'], {'show', 'name'}, key + ' display')
            include, show = definition['model']['include'], definition['display']['show']
            if type(include) is not bool or type(show) is not bool or show and not include:
                raise ValueError('boolean include/show required; show requires include')
            name = text(definition['display']['name'], key + ' name')
            if name in names:
                raise ValueError('display name collision: ' + name)
            names.add(name)
            expected_access = access(schema, path) if schema else ['api']
            if definition['access'] != expected_access:
                raise ValueError(key + ': provider access classification mismatch')
            constraint = ''
            if 'aws' in definition:
                aws = definition['aws']
                exact(aws, {'getter', 'path', 'normalize'} | ({'default'} if 'default' in aws else set()) | ({'transform'} if 'transform' in aws else set()), key + ' aws')
                if aws.get('transform', 'identity') not in {'identity', 'present', 'unique'}:
                    raise ValueError('unknown projection transform')
                if aws.get('transform') == 'present' and key != 'CodeBuild.Project.Triggers.Webhook':
                    raise ValueError('presence transform is specific to CodeBuild webhook')
                if aws['normalize'] not in NORMALIZATIONS:
                    raise ValueError('unknown normalization')
                field = comparator.Field(text(aws['getter'], 'getter'), text(aws['path'], 'path'), aws['normalize'], aws.get('default', comparator.MISSING))
                if field.getter not in getters:
                    raise ValueError('unknown getter')
                kind, getter, evidence = getters[field.getter]
                if 'default' in aws and field.norm == 'boolean':
                    try:
                        comparator.normalize(None, field.default, field.norm)
                    except comparator.Unresolved as error:
                        raise ValueError(key + ': invalid response default') from error
                if kind == 'adapter':
                    if aws.get('transform', 'identity') != 'identity':
                        raise ValueError('adapter projections already provide the final value')
                    if resource not in getter['resources']:
                        raise ValueError(key + ': adapter getter/resource mismatch')
                    catalog.property_schema(resource, path)
                elif getter['resourceType'] != resource:
                    raise ValueError('getter/resource mismatch')
                elif kind == 'sdk':
                    if (getter['service'], getter['operation'], field.path) == ('sns', 'get_topic_attributes', 'Attributes.Policy'):
                        # SNS documents Policy as an Attributes map key; SDK shapes expose only map<string,string>.
                        if response_shape(evidence, 'Attributes').type_name != 'map':
                            raise ValueError('SNS Attributes must be a map')
                    elif field.path != '$':
                        leaf = response_shape(evidence, field.path)
                        expected = catalog.property_schema(resource, path).get('type')
                        actual = {'structure': 'object', 'map': 'object', 'list': 'array', 'long': 'integer',
                                  'double': 'number', 'float': 'number', 'blob': 'string', 'timestamp': 'string'}.get(leaf.type_name, leaf.type_name)
                        if field.path.count('[]') > path.count('[]') and expected != 'array' and aws.get('transform') != 'unique':
                            raise ValueError('additional response array requires a unique projection')
                        if expected and actual not in ([expected] if isinstance(expected, str) else expected) and not (actual == 'integer' and expected == 'number') and aws.get('transform') != 'present':
                            raise ValueError(key + ': SDK/provider type mismatch: ' + actual + '/' + str(expected))
                else:
                    if field.path != path or under(path, schema.get('writeOnlyProperties', [])):
                        raise ValueError('provider path is mismatched or write-only')
                    catalog.property_schema(resource, field.path)
                used.add(field.getter)
                source = 'aws'
            else:
                source = definition['source']
                exact(source, {'kind', 'location', 'constraint', 'classification'} | ({'extraction'} if 'extraction' in source else set()), key + ' source')
                kind = source['kind']
                constraint = text(source['constraint'], key + ' constraint')
                text(source['location'], key + ' location')
                if kind not in {'model', 'target', 'provider-output'} or source['classification'] not in {'local_metadata', 'sdk_unavailable'}:
                    raise ValueError('unknown non-AWS source/classification')
                if kind in {'model', 'target'} and INPUT_SOURCES.get(key) != kind and not (
                        schema and under(path, schema.get('writeOnlyProperties', []))):
                    raise ValueError(key + ': non-AWS source lacks input provenance')
                if kind == 'provider-output' and (not schema or not under(path, schema.get('readOnlyProperties', []))):
                    raise ValueError('provider-output must be a read-only schema property')
                if 'extraction' in source:
                    extraction = source['extraction']
                    exact(extraction, {'getter', 'path', 'normalize'} | ({'default'} if 'default' in extraction else set()), key + ' input extraction')
                    getter_name = extraction['getter']
                    if getter_name not in getters or getters[getter_name][0] != 'adapter':
                        raise ValueError('input extraction must reference an existing adapter')
                    getter = getters[getter_name][1]
                    field = comparator.Field(getter_name, extraction['path'], extraction['normalize'], extraction.get('default', comparator.MISSING))
                    if (INPUT_SOURCES.get(key) != kind or resource not in getter['resources']
                            or field.norm not in NORMALIZATIONS):
                        raise ValueError('input extraction lacks adapter provenance')
                    text(field.path, key + ' input path')
                    field = comparator.Field(field.getter, field.path, field.norm, field.default, source['classification'], constraint)
                    used.add(getter_name)
                else:
                    field = comparator.Field(classification=source['classification'], reason=constraint)
                source = kind
            result[key] = Property(field, include, show, name, source, constraint, definition.get('aws', {}).get('transform', 'identity'))
    if used != getters.keys():
        raise ValueError('unused Mapping getter')
    return result




def runtime_properties(root, service, document):
    return _mapping_runtime.runtime_properties(root, service, document)
