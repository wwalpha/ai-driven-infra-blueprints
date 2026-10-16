#!/usr/bin/env python3
"""Replace selected IMPORT configuration with a read-only AWS CLI inventory."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import re
import sys

import task_contract

from design_layout import resource_anchor, is_service_role_reference
from import_guard import workflow, require_import_changes, record_import, finish_import
from model_core import LINK, entries
from model_files import model_file_contents, model_parts, resource_row_index
from model_parameter_inputs import yaml_read
from model_templates import publication_lock, json_read, json_text, publish, service_source, parse_template, bound_definition, variables
from model_references import catalog_outputs
from task_contract import reserved_batches, task_path, section, DeferredExhausted
from validation_scope import active_scope
from validation_cache import input_scope, memo_table
from script_loader import module as load_script
from sync_files import atomic_files
from aws_mapping_compare import MODEL_ONLY, import_comparison as comparison, value as mapping_value
from import_sources import equivalent, input_plan, optional_plan
from import_promotion import plan_promotions, preserve_consumers, apply_promotions

ROOT = Path(__file__).resolve().parents[2]


def comparator():
    return load_script('check-model-aws.py', 'model_aws_compare')


# Explicit inventory shapes; property mapping and schema validation remain in the existing engine.
INVENTORY = {
    'EC2.VPC': ('ec2', 'describe_vpcs', 'Vpcs'),
    'EC2.Subnet': ('ec2', 'describe_subnets', 'Subnets'),
    'EC2.RouteTable': ('ec2', 'describe_route_tables', 'RouteTables'),
    'EC2.FlowLog': ('ec2', 'describe_flow_logs', 'FlowLogs'),
    'EC2.TransitGatewayVpcAttachment': ('ec2', 'describe_transit_gateway_vpc_attachments', 'TransitGatewayVpcAttachments'),
    'Config.ConfigurationRecorder': ('config', 'describe_configuration_recorders', 'ConfigurationRecorders'),
    'Config.DeliveryChannel': ('config', 'describe_delivery_channels', 'DeliveryChannels'),
    'Logs.LogGroup': ('logs', 'describe_log_groups', 'logGroups'),
    'QuickSight.DataSource': ('quicksight', 'list_data_sources', 'DataSources'),
    'QuickSight.VPCConnection': ('quicksight', 'list_vpc_connections', 'VPCConnectionSummaries'),
    'KinesisFirehose.DeliveryStream': ('firehose', 'list_delivery_streams', 'DeliveryStreamNames'),
    'SecurityHub.Hub': ('securityhub', 'describe_hub', None),
}


def import_context(root, target, runner=None, service=None):
    profile = target.get('awsProfile')
    if 'awsProfile' in target and (not isinstance(profile, str) or not profile or profile != profile.strip() or profile == 'UNSET' or any(c in profile for c in '\r\n\0')):
        raise ValueError('AWS target has an invalid project.json awsProfile; no fallback')
    region = target.get('awsRegion')
    if not isinstance(region, str) or not re.fullmatch(r'[a-z]{2}(?:-[a-z]+)+-[1-9][0-9]*', region):
        raise ValueError('AWS target RegionMismatch; use the project.json awsRegion')
    return comparator().Context(root, target, cli_runner=runner, services=(service,) if service else ())


def target_for(root, environment, service, selector=None):
    if not environment or not service or any(not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', x) for x in (environment, service)):
        raise ValueError('environment and service are required exact identifiers')
    topology = json_read((root / 'project.json').read_text(encoding='utf-8'))
    choices = [t for t in topology['targets'] if isinstance(t, dict) and t.get('environment') == environment]
    if not choices:
        raise ValueError('environment is not registered')
    if selector is None and len(choices) > 1:
        choices = [t for t in choices if (root / 'model/parameters' / environment /
                   t.get('alias', t['awsAccountId']) / service).is_dir()]
    if selector is None:
        if len(choices) != 1:
            raise ValueError('target is required when the environment has multiple targets for this service')
        selector = choices[0].get('alias', choices[0]['awsAccountId'])
    choices = [t for t in choices if t.get('alias', t.get('awsAccountId')) == selector]
    if len(choices) != 1:
        raise ValueError('target must resolve exactly once')
    entry = choices[0]
    resolver = load_script('check-deploy-context.py', 'import_target')
    target = resolver.load_target(root, environment, alias=entry.get('alias'),
                                  account_id=None if 'alias' in entry else selector)
    target.update(environment=environment, directory=selector)
    return target


def inventory(ctx, service):
    if service == 'cloudformation-stacks':
        resource_types = (comparator().service_module(service).STACK_TYPE,)
    else:
        mapping, _ = comparison(ctx.root, service)
        resource_types = sorted(mapping.adapter_resource_types)
    unsupported = set(resource_types) - INVENTORY.keys() - {'EC2.SubnetRouteTableAssociation'}
    if unsupported:
        raise ValueError('IMPORT inventory is unimplemented for: ' + ', '.join(sorted(unsupported)))
    ctx.allowed.update((api, operation) for kind in resource_types if kind in INVENTORY
                       for api, operation, _ in [INVENTORY[kind]])
    records = []
    for kind in resource_types:
        if kind == 'EC2.SubnetRouteTableAssociation':
            continue  # Expand the confirmed route table associations below.
        api, operation, collection = INVENTORY[kind]
        inputs = {'AwsAccountId': ctx.target.get('awsExecutionAccountId', ctx.target['awsAccountId'])} if api == 'quicksight' else {}
        response = ctx.pages(api, operation, **inputs)
        if collection is not None and (collection not in response or not isinstance(response[collection], list)):
            raise comparator().AcquisitionError(api + '.' + operation, 'InvalidInventoryResponse')
        items = response[collection] if collection else [response]
        for item in items:
            if kind == 'KinesisFirehose.DeliveryStream':
                item = ctx.call('firehose', 'describe_delivery_stream', DeliveryStreamName=item)['DeliveryStreamDescription']
            if api == 'quicksight':
                operation, key, result_key = ('describe_data_source', 'DataSourceId', 'DataSource') if kind == 'QuickSight.DataSource' else ('describe_vpc_connection', 'VPCConnectionId', 'VPCConnection')
                item = dict(ctx.call(api, operation, **inputs, **{key: item[key]})[result_key], **inputs)
            record = dict(item)
            if api == 'ec2':
                names = [tag['Value'] for tag in record.get('Tags', []) if tag.get('Key') == 'Name']
                if len(names) > 1:
                    raise ValueError('IMPORT inventory has ambiguous Name tags')
                record['NameTag'] = names[0] if names else comparator().MISSING
            descriptor = mapping.identities[kind]
            getter, id_path = descriptor.getter, descriptor.id_path
            identity = comparator().select(record, id_path)
            if not isinstance(identity, str) or not identity or identity == comparator().MISSING:
                raise ValueError('IMPORT inventory has no confirmed resource identifier')
            getters = {getter: record}
            if kind == 'QuickSight.DataSource':
                getters['permissions'] = ctx.call('quicksight', 'describe_data_source_permissions', **inputs, DataSourceId=record['DataSourceId'])
            records.append({'kind': kind, 'identity': identity, 'getters': getters})
            if kind == 'EC2.RouteTable':
                for association in record.get('Associations', []):
                    if association.get('SubnetId') and association.get('AssociationState', {}).get('State', 'associated') == 'associated':
                        records.append({'kind': 'EC2.SubnetRouteTableAssociation', 'identity': association['RouteTableAssociationId'],
                                        'getters': {'association': {'RouteTableId': record['RouteTableId'], 'SubnetId': association['SubnetId'], 'Id': association['RouteTableAssociationId']}}})
    for association in [record for record in records if record['kind'] == 'EC2.SubnetRouteTableAssociation']:
        payload = association['getters']['association']
        subnet = next((record for record in records if record['kind'] == 'EC2.Subnet' and record['identity'] == payload['SubnetId']), None)
        if subnet is None or 'association' in subnet['getters']:
            raise ValueError('IMPORT subnet association is missing or ambiguous')
        subnet['getters']['association'] = payload
    records = [record for record in records if record['kind'] != 'EC2.SubnetRouteTableAssociation']
    if len({(r['kind'], r['identity']) for r in records}) != len(records):
        raise ValueError('IMPORT inventory contains duplicate identifiers')
    return records


def old_identity(resource):
    mapping, mapped = resource.model.ctx.comparison(resource.model.service)
    descriptor = mapping.identities.get(resource.kind)
    if not descriptor:
        return resource.current('Id')
    id_path, name = descriptor.id_path, descriptor.name_property
    candidates = [prop.removeprefix(resource.kind + '.') for prop, item in mapped.items()
                  if prop.startswith(resource.kind + '.') and item.field.path == id_path]
    outputs = catalog_outputs(resource.ctx.root, resource.kind)
    candidates.sort(key=lambda prop: resource.kind + '.' + prop not in outputs)
    return next((value for prop in [*candidates, name] if prop and (value := resource.current(prop))), None)


def snapshot_values(ctx, model, records, bindings):
    m = comparator()
    mapping, mapped = comparison(ctx.root, model.service)
    old = model.values
    resources = {r.number: r for r in model.resources}
    rows_by_resource = resource_row_index(old)
    creates = {r.number for r in model.resources if r.spec.get('resourceMode', 'CREATE') != 'IMPORT'}
    main_slot = bindings.get('main-vpc', {}) if model.service == 'vpc' else {}
    main_vpcs = [resources[rid] for rid in main_slot.get('resources', {}).values()
                 if resources[rid].kind == 'EC2.VPC' and rid not in creates]
    if len(main_vpcs) > 1:
        raise ValueError('IMPORT main-vpc must contain exactly one IMPORT VPC')
    main_vpc = main_vpcs[0] if main_vpcs else None
    main_vpc_assigned = False
    vpc_anchors = {r.spec['anchor'] for r in model.resources if r.kind == 'EC2.VPC' and r.number not in creates}
    identities = {}
    for r in model.resources:
        identity = old_identity(r)
        if identity:
            key = (r.kind, identity)
            if key in identities:
                raise ValueError('IMPORT existing identity is ambiguous')
            identities[key] = r
    # The main-vpc logical slot is retained; old values never filter AWS acquisition.
    values = {k: v for k, v in old.items() if k.startswith(('desired.service.', 'display.service.', 'desired.note.')) or
              len(k.split('.')) >= 4 and k.split('.')[1] in {'resource', 'row'} and
              (k.split('.')[2] if k.split('.')[1] == 'resource' else k.split('.')[2].rpartition('-')[0]) in creates}
    imported, unreflected, reports = [], [], []
    used = set(resources)
    for record in sorted(records, key=lambda r: (r['kind'], r['identity'])):
        known = identities.get((record['kind'], record['identity']))
        if known and known.number in creates:
            continue
        if main_vpc and record['kind'] == 'EC2.VPC':
            if not main_vpc_assigned:
                known = main_vpc
                main_vpc_assigned = True
            elif known is main_vpc:
                known = None
        rid = known.number if known else 'i' + hashlib.sha256((record['kind'] + '\0' + record['identity']).encode()).hexdigest()[:16]
        if not known and rid in used:
            raise ValueError('IMPORT resource ID collision')
        used.add(rid)
        payload = next(iter(record['getters'].values()))
        descriptor = mapping.identities.get(record['kind'])
        name_prop = descriptor.name_property if descriptor else None
        name_item = mapped.get(record['kind'] + '.' + name_prop) if name_prop else None
        name_field = name_item.field if name_item else None
        display_name = m.select(payload, name_field.path) if name_field else record['identity'] if record['kind'] == 'EC2.SubnetRouteTableAssociation' or sum(item['kind'] == record['kind'] for item in records) > 1 else record['kind']
        if display_name in (m.MISSING, None):
            display_name = record['identity']
        anchor = known.spec['anchor'] if known else resource_anchor(model.service, display_name, record['kind'])
        spec = {'resourceType': record['kind'], 'resourceMode': 'IMPORT', 'anchor': anchor,
                'logicalId': known.spec.get('logicalId', 'Imported' + rid) if known else 'Imported' + rid}
        if known:
            values.update({k: v for k, v in old.items() if k.startswith((f'desired.resource.{rid}.', f'display.resource.{rid}.', f'desired.row.{rid}-', f'observed.row.{rid}-'))})
        values.update({f'desired.resource.{rid}.{key}': value for key, value in spec.items()})
        values.setdefault(f'display.resource.{rid}.comment', 'AWS実環境から取得した設定')
        if not name_field and (record['kind'] == 'EC2.SubnetRouteTableAssociation' or sum(item['kind'] == record['kind'] for item in records) > 1) or name_field and display_name == record['identity'] and m.select(payload, name_field.path) in (m.MISSING, None):
            values[f'display.resource.{rid}.label'] = display_name
        record.update(number=rid, anchor=anchor)
        imported.append(record)
    if main_vpc and not main_vpc_assigned:
        raise ValueError('IMPORT main-vpc has no retrieved VPC; its logical references cannot be preserved')
    for record in imported:
        kind, rid = record['kind'], record['number']
        seed = dict(record['getters'][next(iter(record['getters']))])
        seed_rows = []
        for prop, item in mapped.items():
            field = item.field
            if prop.startswith(kind + '.') and field.getter in record['getters'] and (value := m.select(record['getters'][field.getter], field.path)) not in (m.MISSING, None):
                seed_rows.append((rid + '-' + str(len(seed_rows) + 1).zfill(3), {'property': prop, 'value': model_literal(value)}))
        proxy = m.Resource(model, rid, {'resourceType': kind, 'resourceMode': 'IMPORT', 'anchor': record['anchor']}, seed_rows)
        for getter, payload in record['getters'].items():
            ctx.fetch_cache[(model.path, rid, getter)] = payload
            ctx.fetch_trace[(model.path, rid, getter)] = []
        properties = {p: item for p, item in mapped.items() if p.startswith(kind + '.') and item.include}
        fields = {p: item.field for p, item in properties.items()}
        fields.update({p: item.field for p, item in mapped.items() if p in MODEL_ONLY and p.startswith(kind + '.')})
        if kind == 'EC2.Subnet' and 'association' in record['getters']:
            fields.update({p: item.field for p, item in mapped.items() if p == 'EC2.SubnetRouteTableAssociation.RouteTableId' and item.include})
        selected = {p.removeprefix(kind + '.') for p in fields}
        outputs = catalog_outputs(ROOT, kind)
        if kind == 'EC2.FlowLog':
            resource_id = seed.get('ResourceId', '')
            resource_type = next((name for prefix, name in [('vpc-', 'VPC'), ('subnet-', 'Subnet'), ('eni-', 'NetworkInterface')] if resource_id.startswith(prefix)), None)
            if resource_type:
                ctx.fetch_cache[(model.path, rid, 'resource_type')] = {'ResourceType': resource_type}
                ctx.fetch_trace[(model.path, rid, 'resource_type')] = []
        if {'Tags[].Key', 'Tags[].Value'} <= selected and seed.get('Tags'):
            tags = [tag for tag in seed['Tags'] if tag.get('Key') != 'Name' or kind not in {'EC2.VPC', 'EC2.Subnet', 'EC2.RouteTable', 'EC2.FlowLog'}]
            ctx.fetch_cache[(model.path, rid, 'tags')] = {'Tags': sorted(tags, key=lambda tag: tag['Key'])}
            ctx.fetch_trace[(model.path, rid, 'tags')] = []
            fields.update({kind + '.Tags[].' + leaf: m.Field('tags', 'Tags[].' + leaf) for leaf in ('Key', 'Value')})
        captured, cleared = [], set()
        for prop, field in fields.items():
            property_kind = '.'.join(prop.split('.')[:2])
            try:
                if sensitive(proxy, prop):
                    raise ValueError('sensitive Property')
                if field.classification != 'supported':
                    raise ValueError(field.classification + ': ' + field.reason)
                if prop in properties and field.getter != 'tags':
                    payload, value = mapping_value(ctx, proxy, mapping, properties[prop], prop)
                else:
                    payload = ctx.fetch(proxy, field.getter)
                    value = m.select(payload, field.path)
                if value == m.MISSING:
                    reason = 'AWS optional value not retrieved; existing row retained when present'
                    reports.append({'resource': rid, 'property': prop, 'status': 'missing', 'reason': reason})
                    if resources.get(rid) and resources[rid].rows_for(prop):
                        unreflected.append({'resource': rid, 'property': prop, 'classification': 'missing', 'reason': reason})
                    continue
                if '[]' in prop and value == []:
                    cleared.add(prop)
                    reports.append({'resource': rid, 'property': prop, 'aws': [], 'status': 'captured'})
                    continue
                extracted = value if '[]' in prop else [value]
                field_captured = []
                for occurrence, value in enumerate(extracted):
                    if value == m.MISSING:
                        raise m.Unresolved('AWS array contains an unacquired member')
                    schema = ctx.catalog.property_schema(property_kind, schema_property(property_kind, prop))
                    expected = schema.get('type')
                    types = {'string': (str,), 'integer': (int,), 'number': (int, float), 'boolean': (bool,), 'object': (dict,), 'array': (list,), 'null': (type(None),)}
                    allowed = expected if isinstance(expected, list) else [expected] if expected else []
                    if allowed and not any(type(value) in types.get(name, ()) for name in allowed):
                        raise ValueError('AWS value type does not match the registered schema')
                    if unsafe(value):
                        raise ValueError('sensitive or unresolved AWS value')
                    field_captured.append((prop, occurrence, value))
                captured.extend(field_captured)
            except (ValueError, KeyError, TypeError, m.AcquisitionError, m.Unresolved) as error:
                reason = error.code if isinstance(error, m.AcquisitionError) else str(error)
                classification = ('sensitive' if sensitive(proxy, prop) else 'type-mismatch' if 'type' in reason or 'schema' in reason else
                                  'conflict' if 'reference' in reason or 'mapping' in reason else field.classification if field.classification != 'supported' else 'unavailable')
                unreflected.append({'resource': rid, 'property': prop, 'classification': classification, 'reason': reason})
                reports.append({'resource': rid, 'property': prop, 'aws': '[REDACTED]' if sensitive(proxy, prop) else '[UNCONFIRMED]', 'status': classification, 'reason': reason})
        prior_rows = {}
        for row_id, row in rows_by_resource.get(rid, []):
            prior_rows.setdefault(row['property'], []).append(row_id)
        allocated = {row_id for ids in prior_rows.values() for row_id in ids}
        replaced = {prop for prop, _, _ in captured} | cleared
        for prop in replaced:
            for row_id in prior_rows.get(prop, []):
                for key in list(values):
                    if key.startswith(('desired.row.' + row_id + '.', 'observed.row.' + row_id + '.')):
                        del values[key]
        next_row = max((int(row_id.rpartition('-')[2]) for row_id in allocated), default=0) + 1
        ordered = sorted(captured, key=lambda item: (item[0].replace('[]', '[' + str(item[1]).zfill(8) + ']'), item[1]))
        for prop, occurrence, value in ordered:
            prior = prior_rows.get(prop, [])
            row_id = prior[occurrence] if occurrence < len(prior) else None
            if row_id is None:
                row_id = rid + '-' + str(next_row).zfill(3)
                next_row += 1
            key = 'desired.row.' + row_id
            if key + '.document' in old:
                from model_projection import document_sha256
                if isinstance(value, str) and LINK.fullmatch(value):
                    raise ValueError('IMPORT conflict: JSON document cannot become a logical reference')
                values[key + '.document'] = json_text(value)
                values[key + '.artifactSha256'] = document_sha256(value)
                rendered = old[key + '.value']
            elif key + '.value' in old and (LINK.fullmatch(old[key + '.value']) or '<<' in old[key + '.value']):
                rendered = old[key + '.value']
                values['observed.row.' + row_id + '.value'] = model_literal(value)
            elif prop in outputs and isinstance(value, str):
                rendered = '[' + values[f'desired.resource.{rid}.logicalId'] + '](#' + record['anchor'] + ')'
                values['observed.row.' + row_id + '.value'] = model_literal(value)
            elif isinstance(value, str) and LINK.fullmatch(value):
                rendered = value
            else:
                referenced = next((r for r in imported if r['identity'] == value), None) if isinstance(value, str) and fields[prop].norm == 'id' else None
                if referenced and (referenced is not record or property_kind_from(prop) != kind):
                    rendered = '[' + values[f"desired.resource.{referenced['number']}.logicalId"] + '](#' + referenced['anchor'] + ')'
                    values['observed.row.' + row_id + '.value'] = value
                else:
                    rendered = model_literal(value)
            if key + '.value' in old and equivalent(old[key + '.value'], rendered):
                rendered = old[key + '.value']
            values.update({key + '.property': prop, key + '.value': rendered, key + '.comment': old.get(key + '.comment', 'AWSから取得した設定')})
            reports.append({'resource': rid, 'property': prop, 'aws': '[REFERENCE]' if isinstance(value, str) and LINK.fullmatch(value) else value, 'status': 'captured',
                            'source': properties[prop].source if prop in properties else 'aws'})
    if main_vpc:
        identifier = next((m.literal(values['observed.row.' + row_id + '.value'])
                           for row_id, row in resource_row_index(values)[main_vpc.number]
                           if row['property'] == 'EC2.VPC.VpcId' and 'observed.row.' + row_id + '.value' in values), None)
        if identifier:
            from cloudformation_observed import propagate_references
            design = (ctx.root / 'docs/designs' / model.path.relative_to(ctx.root / 'model')).with_suffix('.md')
            changes = {}
            propagate_references(ctx.root, {model.path: values}, changes, {(design.resolve(), main_vpc.spec['anchor']): identifier})
            values.update({key: value for key, value in changes.get(model.path, {}).items()
                           if key.split('.')[2].rpartition('-')[0] in creates})
    values[f'desired.service.{model.service}.serviceId'] = model.service
    values[f'desired.service.{model.service}.ownedCatalogResourceTypes'] = ','.join(sorted({spec['resourceType'] for _, spec in entries(values, 'desired.resource.')} | {property_kind_from(row['property']) for _, row in entries(values, 'desired.row.')})) or old.get(f'desired.service.{model.service}.ownedCatalogResourceTypes', ','.join(sorted(mapping.adapter_resource_types)))
    return values, imported, unreflected, reports


def property_kind_from(prop):
    return '.'.join(prop.split('.')[:2])


def schema_property(kind, prop):
    if kind in {'EC2.VPC', 'EC2.Subnet', 'EC2.RouteTable', 'EC2.FlowLog'} and prop == kind + '.Name':
        return 'Tags[].Value'  # Existing Model design-only Name is the AWS Name tag.
    return prop.removeprefix(kind + '.')


def snapshot_sources(path, expansion, values, source_files=None):
    root, template, directory = service_source(path)
    prefix = 'Import_' + hashlib.sha256('/'.join(path.relative_to(root / 'model').parts).encode()).hexdigest()[:16]
    resources = dict(entries(values, 'desired.resource.'))
    rows = resource_row_index(values)
    original_bindings = json_read(expansion.files[directory / 'bindings.json'])['instances']
    original_definitions, _ = parse_template(template, source_files)
    original_parameters = yaml_read(expansion.files[directory / 'parameters.yaml'])
    original_parameters, original_bindings = optional_plan(original_definitions, original_parameters, original_bindings, values)
    original_parameters, selected_definitions = input_plan(template, original_definitions, original_parameters,
                                                          original_bindings, expansion, values, path.parent.parent.name)
    from import_sources import parameter_edit
    def observations():
        observed = {key: value for key, value in sorted(values.items()) if key.startswith('observed.') and key.endswith('.value')}
        return json_text({'version': 1, 'values': observed}) + '\n' if observed else None
    from model_templates import expand_for_edit
    reused, _, _ = expand_for_edit(template, original_parameters, {'version': 1, 'values': {}},
                          {'instances': original_bindings}, path.parent.parent.name, _parsed=parse_template(template, source_files))
    desired = {key: value for key, value in values.items() if not key.startswith('observed.')}
    if reused.keys() == desired.keys() and all(equivalent(reused[key], value) for key, value in desired.items()):
        output = {directory / 'parameters.yaml': parameter_edit(expansion.files[directory / 'parameters.yaml'], original_parameters),
                  directory / 'bindings.json': json_text({'instances': original_bindings}) + '\n',
                  directory / 'observed.json': observations()}
        return {file: content for file, content in output.items() if (file.read_text(encoding='utf-8') if file.is_file() else None) != content}
    groups = {}
    assigned = set()
    for instance, binding in original_bindings.items():
        ids = set(binding['resources'].values()) & resources.keys()
        if ids or any(trace.get('instance') == instance and key.startswith(('desired.service.', 'display.service.', 'desired.note.'))
                      for key, trace in expansion.provenance.items()):
            groups[instance] = ids
            assigned |= ids
    for rid in resources.keys() - assigned:
        groups['aws_' + rid] = {rid}
    if not groups:
        groups['imported'] = set()
    metadata = {key: value for key, value in values.items() if key.startswith(('desired.service.', 'display.service.', 'desired.note.'))}
    template_text = ''.join(expansion.files[part] for part in model_parts(template))
    blocks, bindings, parameters, declarations = [], {'instances': {}}, {'instances': {}, **({'parameters': original_parameters['parameters']} if 'parameters' in original_parameters else {})}, {}
    from model_templates import Definition
    catalog = comparator().DesignSchemaCatalog(ROOT)
    for index, (instance, ids) in enumerate(sorted(groups.items())):
        name = prefix + '_' + hashlib.sha256((instance + json_text(values)).encode()).hexdigest()[:16]
        original_binding = original_bindings.get(instance, {})
        resource_aliases = {rid: local for local, rid in original_binding.get('resources', {}).items()}
        row_aliases = {rid: local for local, rid in original_binding.get('rows', {}).items()}
        resource_map = {resource_aliases.get(rid, 'r_' + rid): rid for rid in sorted(ids)}
        row_map = {row_aliases.get(row_id, 'row_' + row_id): row_id for rid in sorted(ids) for row_id, _ in rows[rid]}
        aliases = {rid: local for local, rid in resource_map.items()}
        row_locals = {rid: local for local, rid in row_map.items()}
        subset = {key: value for key, value in values.items() if len(key.split('.')) >= 4 and key.split('.')[1] in {'resource', 'row'} and
                  (key.split('.')[2] if key.split('.')[1] == 'resource' else key.split('.')[2].rpartition('-')[0]) in ids}
        subset = {**{key: value for key, value in metadata.items() if expansion.provenance.get(key, {}).get('instance') == instance or
                     index == 0 and key not in expansion.provenance}, **subset}
        # Reuse the original definition and explicit maps when only its inputs changed.
        original_keys = {key for key, trace in expansion.provenance.items()
                         if trace.get('instance') == instance and not trace.get('derivedFrom') and not key.startswith('observed.')}
        candidate_keys = {key for key in subset if not key.startswith('observed.') and not key.endswith('.artifactSha256')}
        if original_binding and original_keys == candidate_keys and all(
                key in reused and equivalent(reused[key], values[key])
                for key in candidate_keys):
            bindings['instances'][instance] = original_binding
            supplied = original_parameters.get('instances', {}).get(instance)
            if supplied:
                parameters['instances'][instance] = supplied
            declarations[original_binding['definition']] = original_definitions[original_binding['definition']]
            continue
        lines = ['# definition: ' + name]
        supplied, internal, specs = {}, {}, {}
        selected_contexts = {}
        preserved_definition = None
        lines.extend('# resource: ' + local for local in resource_map)
        lines.extend('# row: ' + local + ' ' + aliases[rid.rpartition('-')[0]] for local, rid in row_map.items())
        for key, value in subset.items():
            if key.startswith('observed.') or key.endswith('.artifactSha256'):
                continue
            parts = key.split('.')
            if parts[1] == 'resource':
                rid = parts[2]
                parts[2] = aliases[rid]
                if key.endswith('.anchor') and (key not in expansion.provenance or not variables(
                        selected_definitions[instance].values[expansion.provenance[key]['key']])):
                    parameter = 'BoundAnchor_' + hashlib.sha256(key.encode()).hexdigest()[:16]
                    spec = {'type': 'string', 'internal': True, 'description': '固定Anchor', 'required': True}
                    lines.append('# parameter: ' + parameter + ' ' + json_text(spec))
                    internal[parameter] = value
                    value = '<<' + parameter + '>>'
            elif parts[1] == 'row':
                row_id = parts[2]
                parts[2] = row_locals[row_id]
                if key.endswith('.value') and key not in expansion.provenance and resources[row_id.rpartition('-')[0]].get('resourceMode') == 'IMPORT' and not LINK.fullmatch(value):
                    parameter = 'Value_' + hashlib.sha256(key.encode()).hexdigest()[:16]
                    raw = comparator().literal(value)
                    row = next(row for identity, row in rows[row_id.rpartition('-')[0]] if identity == row_id)
                    kind = property_kind_from(row['property'])
                    schema = catalog.property_schema(kind, schema_property(kind, row['property']))
                    declared_type = schema.get('type', 'string')
                    if not isinstance(declared_type, str):
                        raise ValueError('IMPORT conflict: new union-typed row has no unambiguous parameter type')
                    typed = raw if declared_type == 'string' else json.loads(raw)
                    spec = {'type': declared_type, 'description': 'AWS実環境の設定値', 'required': True}
                    specs[parameter] = spec
                    lines.append('# parameter: ' + parameter + ' ' + json_text(spec))
                    supplied[parameter] = typed
                    value = '`<<' + parameter + '>>`' if isinstance(typed, str) else '<<' + parameter + '>>'
            if key in expansion.provenance:
                trace = expansion.provenance[key]
                original_definition = selected_definitions[trace['instance']]
                if trace['definition'] not in selected_contexts:
                    old_supplied = {name: spec['default'] for name, spec in original_definition.parameters.items() if isinstance(spec, dict) and 'default' in spec}
                    old_supplied.update(original_parameters.get('parameters', {}))
                    old_supplied.update(original_parameters.get('instances', {}).get(instance, {}).get('parameters', {}))
                    old_supplied.update(original_binding.get('parameters', {}))
                    selected_contexts[trace['definition']] = (old_supplied, bound_definition(original_definition, old_supplied))
                old_supplied, selected = selected_contexts[trace['definition']]
                raw = selected.values[trace['key']]
                retargeted_reference = any(raw == '<<' + name + '>>' and spec.get('type') == 'reference' and
                    spec != original_definitions[trace['definition']].parameters[name]
                    for name, spec in original_definition.parameters.items())
                if equivalent(reused.get(key), value) or equivalent(expansion.values[key], value) or retargeted_reference:
                    value = raw
                elif variables(raw):
                    raise ValueError('IMPORT conflict: unresolved expression mismatch after promotion: ' + trace['key'])
                for variable in variables(value) & original_definition.parameters.keys():
                    if variable in specs:
                        continue
                    spec = original_definition.parameters[variable]
                    specs[variable] = spec
                    declaration = json_text(spec) if isinstance(spec, dict) else spec
                    if isinstance(spec, dict) and spec.get('source') == 'template':
                        reference = {key: spec[key] for key in ('service', 'resourceType', 'format', 'property') if key in spec}
                        reference['instance' if 'service' not in spec or 'instance' in spec else 'resource'] = spec['target']
                        lines.append('# reference: ' + variable + ' ' + json_text(reference))
                    elif not isinstance(spec, dict) or spec.get('source') not in {'service', 'consumer.environment', 'consumer.executionAccountId'}:
                        lines.append('# parameter: ' + variable + ' ' + declaration)
                    if variable in original_binding.get('parameters', {}):
                        internal[variable] = original_binding['parameters'][variable]
                    elif isinstance(spec, dict) and spec.get('source') is None and variable in old_supplied:
                        supplied[variable] = old_supplied[variable]
            lines.append('.'.join(parts) + '=' + value)
        if original_binding and set(original_binding['resources'].values()) <= set(resource_map.values()) and set(original_binding['rows'].values()) <= set(row_map.values()):
            original = original_definitions[original_binding['definition']]
            block = re.search(r'^# definition: ' + re.escape(original_binding['definition']) + r'\n(.*?)^# end-definition', template_text, re.M | re.S)
            if block is None:
                raise ValueError('IMPORT conflict: original definition block is unavailable')
            generated = {line.partition('=')[0]: line.partition('=')[2] for line in lines if line.startswith(('desired.', 'display.'))}
            references = {line.split()[2]: line for line in lines if line.startswith('# reference: ')}
            preserved = ['# definition: ' + name]
            for line in block[1].splitlines():
                key = line.partition('=')[0]
                if key in generated:
                    conditional = any(item[0] == key for item in original.choices) or any(item[0] == key for item in original.optional_json)
                    if conditional:
                        trace_key = next((out for out, trace in expansion.provenance.items() if trace.get('instance') == instance and trace.get('key') == key), None)
                        if trace_key and not equivalent(expansion.values[trace_key], values[trace_key]) and not variables(selected_definitions[instance].values[key]):
                            raise ValueError('IMPORT conflict: fixed conditional branch cannot be safely rewritten')
                    else:
                        line = key + '=' + generated[key]
                elif line.startswith('# reference: ') and line.split()[2] in references:
                    line = references[line.split()[2]]
                preserved.append(line)
            preserved.extend(line for line in lines if
                line.startswith('# parameter: ') and line.split()[2] not in original.parameters or
                line.startswith('# row: ') and line.split()[2] not in original.rows or
                line.startswith(('desired.', 'display.')) and line.partition('=')[0] not in original.values)
            lines = preserved
            preserved_definition = original
            internal = {**original_binding.get('parameters', {}), **internal}
            supplied = {**original_parameters.get('instances', {}).get(instance, {}).get('parameters', {}), **supplied}
            specs = {**original.parameters, **specs}
        elif original_binding:
            original = original_definitions[original_binding['definition']]
            if original.optional or original.optional_json or original.choices:
                raise ValueError('IMPORT conflict: conditional definition removal needs an explicit safe shape plan')
        lines += ['# end-definition', '']
        blocks.append('\n'.join(lines))
        bindings['instances'][instance] = {'definition': name, 'resources': resource_map, 'rows': row_map, 'parameters': internal}
        labels = {key: value for key, value in original_binding.get('labels', {}).items() if key in specs}
        if labels:
            bindings['instances'][instance]['labels'] = labels
        if supplied:
            parameters['instances'][instance] = {'parameters': supplied}
        raw_values = {line.partition('=')[0]: line.partition('=')[2] for line in lines if line.startswith(('desired.', 'display.'))}
        declarations[name] = (preserved_definition._replace(parameters=specs, values=raw_values,
                              resources=preserved_definition.resources | resource_map.keys(),
                              rows={**preserved_definition.rows, **{local: aliases[rid.rpartition('-')[0]] for local, rid in row_map.items()}})
                              if preserved_definition else Definition(specs, set(resource_map), {}, raw_values, {}, set(), {}, {}, {}))
    text = template_text
    # Existing definitions may be used by unselected consumers; append private derivatives only.
    text += ''.join(blocks)
    output = model_file_contents(template, text, validate=False)
    output.update({part: None for part in set(model_parts(template)) - output.keys() - {template}})
    output[directory / 'bindings.json'] = json_text(bindings) + '\n'
    output[directory / 'parameters.yaml'] = parameter_edit(expansion.files[directory / 'parameters.yaml'], parameters)
    output[directory / 'observed.json'] = observations()
    return {file: content for file, content in output.items() if (file.read_text(encoding='utf-8') if file.is_file() else None) != content}


def promoted_sources(path, expansion, values):
    """Plan source edits in memory; only direct shared-Definition users are inspected."""
    from model_templates import load_for_edit
    catalog = comparator().DesignSchemaCatalog(ROOT)
    module = comparator().service_module(path.stem)
    plans, parameters = plan_promotions(path, expansion, values,
        lambda prop: catalog.property_schema(property_kind_from(prop), schema_property(property_kind_from(prop), prop)),
        unsafe, lambda prop: sensitive(SimpleNamespace(module=module), prop))
    preserved = preserve_consumers(path, expansion, plans)
    output = apply_promotions(path, plans, parameters, preserved)
    reports = [{'property': plan['property'], 'definition': plan['definition'], 'instances': sorted(plan['targets']),
                'expression': parse_template(service_source(path)[1])[0][plan['definition']].values[plan['key']],
                'parameter': plan['parameter'], 'environment': path.parent.parent.name,
                'preservedConsumers': len(preserved) - 1} for plan in plans]
    promoted = load_for_edit(path, output) if output else expansion
    output.update(snapshot_sources(path, promoted, values, output))
    return {file: content for file, content in output.items()
            if (file.read_bytes().decode('utf-8') if file.is_file() else None) != content}, preserved, reports


def sensitive(resource, prop):
    return resource.module.sensitive(prop or '') or bool(re.search(r'password|credential|accesskey|secretstring|secretbinary|privatekey|token|authorization|username', prop or '', re.I))


def unsafe(value):
    text = json_text(value)
    return ('[REDACTED]' in text or '<<' in text or
            any(x in text for x in ('PENDING_DEPLOY', 'UNSET')) or comparator().redacted(value) != value)


def model_literal(value):
    text = value if isinstance(value, str) else json_text(value)
    if any(c in text for c in '\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029`'):
        raise ValueError('AWS value cannot be represented losslessly as a Model scalar')
    return '`' + text + '`'


def contract_scope(root, scope):
    workflow(root)
    text = task_path(root).read_text(encoding='utf-8')
    if '- Task type: `design`' not in section(text, '## Task contract'):
        raise ValueError('normal import requires a registered design Task Contract')
    declared = active_scope(root)
    pins = [line for line in section(text, '## Task contract') if line.startswith('- IMPORT target:')]
    if pins:
        expected = '- IMPORT target: `' + '/'.join(next(iter(scope))) + '`' if len(scope) == 1 else None
        if pins != [expected]:
            raise ValueError('IMPORT acquisition must match the fixed Task target')
    elif declared != scope:
        raise ValueError('IMPORT initially requires exactly one acquisition target in Validation scope')
    from import_scope import selected
    if len(scope) != 1 or selected(root) not in scope or declared is None or not scope <= declared:
        raise ValueError('IMPORT requires one fixed environment/target/service within Validation scope')
    if task_contract.status(text, task_path(root).name == 'active.md') != 'running':
        raise ValueError('IMPORT requires a running Task Contract')


def reserve_outputs(root, identity, sources, views, consumers=None):
    """Register only exact selected candidate paths under the existing task lock."""
    from import_scope import source_paths
    template, parts, parameters = source_paths(identity)
    consumers = set(consumers or {identity})
    environment, target, service = identity
    document = root / 'docs/designs' / environment / target / (service + '.md')
    for file in sources:
        relative = file.relative_to(root).as_posix()
        if not (relative == template or
                file.parent == root / parts and re.fullmatch(r'part-[0-9]{3}\.properties', file.name) or
                file.parent == root / parameters and file.name in {'parameters.yaml', 'bindings.json', 'observed.json'} or
                any(file == root / 'model/parameters' / Path(*item) / 'parameters.yaml' and item[1:] == identity[1:]
                    for item in consumers)):
            raise ValueError('IMPORT output is outside selected environment/target/service')
    if any(file != document and not (file.parent == document.with_suffix('') and file.suffix == '.json') for file in views):
        raise ValueError('IMPORT view is outside selected environment/target/service')
    paths = {file.relative_to(root).as_posix() for file in sources | views}
    for relative in paths:
        task_contract.safe_path(root, relative)
    with task_contract.registration_lock(root):
        contract_scope(root, {identity})
        records = task_contract.contracts(root, include_foreign=True)
        selected = task_path(root)
        name = selected.relative_to(root).as_posix()
        text = task_contract.selected_text(root, records, name)
        fixed = '- IMPORT target: `' + '/'.join(identity) + '`'
        if not re.search(r'^- IMPORT target:', text, re.M):
            text = text.replace('- Workflow: `import`', '- Workflow: `import`\n' + fixed)
        declared = active_scope(root)
        body = '## Validation scope\n\n' + ''.join('- `' + '/'.join(item) + '`\n' for item in sorted(declared | consumers)) + '\n'
        text = re.sub(r'^## Validation scope\n.*?(?=^## |\Z)', lambda _: body, text, flags=re.M | re.S)
        for heading in ('## Allowed paths', '## Modified files'):
            existing = task_contract.paths_in(text, heading)
            if paths - existing:
                body = heading + '\n\n' + ''.join('- `' + path + '`\n' for path in sorted(existing | paths)) + '\n'
                text = re.sub(r'^' + heading + r'\n.*?(?=^## |\Z)', lambda _: body, text, flags=re.M | re.S)
        text = task_contract.acquire(root, name, text, records)
        if text != records[name]:
            atomic_files({selected: text}, staging_directory=root)


@input_scope
def refresh(root, environment, service, selector=None, dry_run=False, cli_runner=None, no_profile=False):
    from import_scope import restrict, read_consumers
    root = root.resolve()
    target = target_for(root, environment, service, selector)
    if no_profile:
        target.pop('awsProfile', None)
    identity = (environment, target['directory'], service)
    with restrict(identity), read_consumers({identity}):
        return refresh_selected(root, target, service, dry_run, cli_runner)


def refresh_selected(root, target, service, dry_run, cli_runner):
    from model_templates import load_for_edit, safe
    from sync_runtime import owned_artifacts, view_plan
    m = comparator()
    identity = (target['environment'], target['directory'], service)
    scope = {identity}
    path = root / 'model' / identity[0] / identity[1] / (service + '.properties')
    expansion = load_for_edit(path)
    if not dry_run:
        contract_scope(root, scope)
        require_import_changes(root, generation=True)
    snapshot = {file: text.encode('utf-8') for file, text in expansion.files.items()}
    snapshot[root / 'project.json'] = (root / 'project.json').read_bytes()
    mapping_file = root / 'framework/mappings/aws' / (service + '.yaml')
    snapshot[mapping_file] = mapping_file.read_bytes()
    snapshot.setdefault(service_source(path)[2] / 'observed.json', None)
    ctx = import_context(root, target, cli_runner, service)
    ctx.verify()
    ctx.comparisons[service] = comparison(root, service)
    model = SimpleNamespace(ctx=ctx, path=path, service=service, values=expansion.values, resources=[])
    rows = resource_row_index(expansion.values)
    model.resources = [m.Resource(model, rid, spec, rows[rid]) for rid, spec in entries(expansion.values, 'desired.resource.')]
    ctx.models[path.resolve()] = model
    records = inventory(ctx, service)
    bindings = json_read(expansion.files[service_source(path)[2] / 'bindings.json'])['instances']
    values, imported, unreflected, reports = snapshot_values(ctx, model, records, bindings)
    from model_templates import consumers
    output, preserved, promotions = promoted_sources(path, expansion, values)
    direct_consumers = set(preserved) if promotions else set()
    for current, _, _, _ in preserved.values():
        for file, text in current.files.items():
            snapshot.setdefault(file, text.encode('utf-8'))
    for file in output:
        safe(root, file)
        snapshot.setdefault(file, file.read_bytes() if file.is_file() else None)
    result = {'status': 'dry-run' if dry_run else 'complete', 'scope': ['/'.join(identity)],
              'resources': {'import': len(imported), 'create': sum(r.spec.get('resourceMode', 'CREATE') != 'IMPORT' for r in model.resources)},
              'connection': {'profile': target.get('awsProfile'), 'region': target['awsRegion'], 'account': target.get('awsExecutionAccountId', target['awsAccountId']), 'sts': 'verified'},
              'rows': reports, 'unreflected': unreflected, 'automatic': sum(row['status'] == 'captured' for row in reports),
              'unconfirmed': len(unreflected), 'files': sorted(file.relative_to(root).as_posix() for file in output),
              'model': 'unchanged', 'markdown': 'not-run', 'designValidation': 'not-run', 'dryRun': dry_run,
              'affectedConsumers': sorted('/'.join(item) for item in set(preserved) - scope), 'promotions': promotions}
    def unchanged(expected):
        if promotions and consumers(root, identity[1], identity[2]) != direct_consumers:
            raise ValueError('Model registered consumers changed during import')
        if any((file.read_bytes() if file.is_file() else None) != data for file, data in expected.items()):
            raise ValueError('Model sources changed during import; concurrent changes were not overwritten')
    unchanged(snapshot)
    if dry_run:
        result['status'] = 'incomplete' if unreflected else 'dry-run'
        return result
    document = root / 'docs/designs' / identity[0] / identity[1] / (service + '.md')
    managed = owned_artifacts(document, expansion.values)
    reserve_outputs(root, identity, set(output), set(), preserved)
    for _ in reserved_batches(root, {'import-model': set(output)}):
        with publication_lock(root):
            contract_scope(root, scope)
            unchanged(snapshot)
            from import_guard import proof_path
            evidence = proof_path(root)
            previous_proof = evidence.read_text(encoding='utf-8') if evidence.is_file() else None
            record_import(root, output, scope, ctx, {'values': values, 'sources': {str(p.relative_to(root)): text for p, text in output.items()},
                          'ownedArtifacts': sorted(p.relative_to(root).as_posix() for p in managed)}, complete=not unreflected)
            try:
                publish(root, output, inputs=snapshot, verify=lambda: finish_import(root, 'reflected' if output else 'unchanged'))
            except (OSError, ValueError):
                from sync_files import atomic_files
                atomic_files({evidence: previous_proof}, staging_directory=evidence.parent)
                raise
    result['model'] = 'reflected' if output else 'unchanged'
    snapshot.update({p: None if text is None else text.encode('utf-8') for p, text in output.items()})
    memo_table().clear()
    try:
        with publication_lock(root):
            unchanged(snapshot)
            saved = load_for_edit(path)
            publication, view_inputs = view_plan(document, saved.values, root, managed)
        reserve_outputs(root, identity, set(), set(publication), preserved)
        for _ in reserved_batches(root, {'import-views': set(publication)}):
            with publication_lock(root):
                contract_scope(root, scope)
                unchanged(snapshot)
                unchanged(view_inputs)
                publish(root, publication, inputs={**snapshot, **view_inputs})
                finish_import(root, markdown='generated' if publication else 'unchanged')
        result['files'] = sorted(set(result['files']) | {p.relative_to(root).as_posix() for p in publication})
        result['markdown'] = 'generated' if publication else 'unchanged'
    except Exception as error:
        result['markdown'] = 'failed'
        result['displayError'] = str(error)
        try:
            finish_import(root, markdown='failed')
        except (OSError, ValueError) as evidence_error:
            result['displayError'] += '; evidence update failed: ' + type(evidence_error).__name__
    result['status'] = 'incomplete' if unreflected else 'display-failed' if result['markdown'] == 'failed' else 'complete'
    return result


def print_report(result):
    print('Scope: ' + ', '.join(result['scope']))
    connection = result['connection']
    print(f"AWS CLI: Profile={connection['profile'] or 'default credential chain'}; Region={connection['region']}; Account={connection['account']}; STS={connection['sts']}")
    counts = result['resources']
    print(f"Status: {result['status']}; AWS IMPORT resources: {counts['import']}; preserved CREATE: {counts['create']}; "
          f"captured: {result['automatic']}; unconfirmed: {result['unconfirmed']}; Markdown: {result['markdown']}")
    print(f"Model: {result['model']}; Markdown/JSON: {result['markdown']}; Design validation: {result['designValidation']}")
    if result.get('displayError'):
        print('Display error: ' + result['displayError'])
    print('| Resource | Property | AWS | 状態 |')
    print('| --- | --- | --- | --- |')
    for row in result['rows']:
        cells = [row.get(key) for key in ('resource', 'property', 'aws', 'status')]
        if row.get('reason'):
            cells[-1] += ': ' + row['reason']
        print('| ' + ' | '.join(json.dumps(cell, ensure_ascii=False).replace('|', '&#124;') for cell in cells) + ' |')
    for promotion in result.get('promotions', []):
        print('Promotion: ' + json.dumps(promotion, ensure_ascii=False))
    if result.get('files'):
        print('Planned files: ' + ', '.join(result['files']))
    if result.get('affectedConsumers'):
        print('Affected consumers: ' + ', '.join(result['affectedConsumers']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository-root', type=Path, default=ROOT)
    parser.add_argument('--environment', required=True)
    parser.add_argument('--service', required=True)
    parser.add_argument('--target')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-profile', action='store_true',
                        help='Omit the configured awsProfile for this run; use the AWS CLI default credential chain')
    args = parser.parse_args()
    try:
        result = refresh(args.repository_root, args.environment, args.service, args.target, args.dry_run,
                         no_profile=args.no_profile)
        print_report(result)
        return 2 if result['status'] == 'incomplete' else 3 if result['markdown'] == 'failed' else 0
    except DeferredExhausted:
        print('{"status":"pending","reason":"reservations remain Deferred; import is unfinished"}')
        return 2
    except Exception as error:
        # CLI errors can contain credential data; only controlled diagnostic messages leave this boundary.
        controlled = ('environment ', 'target ', 'explicit profile ', 'AWS ', 'IMPORT ', 'import ',
                      'Model sources changed',
                      'reference catalog material missing:', 'reference property is not a catalog identifier output',
                      'no service entrance', 'service entrance', 'unimplemented service:',
                      'normal import requires', 'include every affected consumer', 'unknown instance reference: ')
        reason = (error.code if isinstance(error, comparator().AcquisitionError) else
                  str(error) if type(error) is ValueError and str(error).startswith(controlled) else type(error).__name__)
        failure = {'status': 'failed', 'model': 'failed', 'markdown': 'not-run', 'designValidation': 'not-run', 'reason': reason}
        trace = error.__traceback__
        while trace is not None:
            file = Path(trace.tb_frame.f_code.co_filename).resolve()
            if file.is_relative_to(ROOT / 'framework/scripts') and file.is_file():
                failure['location'] = {'file': file.relative_to(ROOT).as_posix(), 'line': trace.tb_lineno}
            trace = trace.tb_next
        print(json.dumps(failure, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
