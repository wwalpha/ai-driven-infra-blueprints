"""Compile all Mapping properties for Compare without changing acquisition permissions."""
from dataclasses import replace
from types import MappingProxyType

from aws_mapping import Property, registry
from aws_mapping_catalog import project
from comparison_rows import select
from script_loader import module
from validation_cache import memoized


# These five design-only keys deliberately have no Catalog entry.
MODEL_ONLY = frozenset({'EC2.VPC.Name', 'EC2.Subnet.Name', 'EC2.RouteTable.Name',
                        'EC2.FlowLog.Name', 'S3.Bucket.Region'})


@memoized
def comparison(root, service):
    return compile_comparison(root, service, registry(root, service))


def import_comparison(root, service):
    from aws_mapping import runtime_registry
    return compile_comparison(root, service, runtime_registry(root, service))


def compile_comparison(root, service, mapping):
    m = module('check-model-aws.py', 'model_aws_compare')
    adapter = m.service_module(service)
    properties = dict(mapping.properties)
    for key, prop in properties.items():
        field = prop.field
        # Request-input projections retain their established comparison semantics.
        if prop.source != 'aws' and field.getter:
            field = replace(field, classification='supported', reason='')
        if field.classification == 'supported':
            getter = mapping.getters[field.getter]
            if getter.get('kind') in {'sdk', 'cloudcontrol'}:
                api = (getter['service'], getter['operation'])
                if api not in adapter.APIS:
                    field = replace(field, classification='sdk_unavailable',
                                    reason='Mapping API is outside the existing service read-only allowlist: ' + '.'.join(api))
                elif getattr(adapter, 'SDK_OPERATIONS', {}).get(getter['resourceType']) != getter['operation']:
                    field = replace(field, classification='sdk_unavailable',
                                    reason='Mapping has no confirmed resource selector in the existing adapter')
        properties[key] = replace(prop, field=field)
    for key in MODEL_ONLY:
        if key in getattr(adapter, 'MODEL_FIELDS', {}):
            field = getattr(adapter, 'MODEL_FIELDS', {})[key]
            properties[key] = Property(field, False, False, key.rsplit('.', 1)[-1], 'model')
    return mapping, MappingProxyType(properties)


def value(ctx, resource, mapping, prop, key):
    """Fetch via existing input selectors, then apply the YAML result/path/transform."""
    field = prop.field
    getter = mapping.getters.get(field.getter, {})
    if getter.get('kind') == 'sdk':
        api = (getter['service'], getter['operation'])
        if api not in resource.module.APIS or api not in ctx.allowed:
            raise ValueError('Mapping API is outside the read-only allowlist')
        response = ctx.fetch(resource, field.getter, getter)
        payload = response if getter['result'] == '$' else select(response, getter['result'])
        # A collection of resources requires one confirmed selection. Property arrays
        # (for example S3 Rules[]) retain their members and their association.
        path = key.removeprefix(resource.kind + '.')
        extra = getter['result'].count('[]') + field.path.count('[]') - path.count('[]')
        if extra > 0 and isinstance(payload, list):
            m = module('check-model-aws.py', 'model_aws_compare')
            payload = m.one(payload, '.'.join(api))
        if isinstance(payload, list):
            return response, [project(prop, item) for item in payload]
        return response, project(prop, payload)
    response = ctx.fetch(resource, field.getter)
    return response, project(prop, response)
