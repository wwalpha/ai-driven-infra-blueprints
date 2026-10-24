"""Typed design references; identity lookup belongs to model.identity.Resolver."""

import base64
import json
import re
from dataclasses import dataclass

from design.services.definitions.registry import POLICY_FORMATS
from iac_evaluation import RETURN_ATTRIBUTE_PROPERTIES
from utils.aws_catalogs import catalog_outputs
from utils.json_format import strict_json, validate_aws_document
from utils.reference_contracts import reference_attribute, reference_context

from model.core import ReferenceResolutionError, entries, literal, resource_link


@dataclass(frozen=True)
class ReferenceNode:
    logical_id: str
    attribute: str
    pointer: str = ''


def is_reference(value):
    return isinstance(value, dict) and '$modelRef' in value


def parse(value, pointer=''):
    if not is_reference(value) or set(value) != {'$modelRef'}:
        raise ValueError(f'invalid $modelRef object: JSON Pointer={pointer!r}')
    body = value['$modelRef']
    if not isinstance(body, dict) or set(body) != {'logicalId', 'attribute'}:
        raise ValueError(f'$modelRef requires exactly logicalId and attribute: JSON Pointer={pointer!r}')
    for key in ('logicalId', 'attribute'):
        if not isinstance(body[key], str) or re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]*', body[key]) is None:
            raise ValueError(f'invalid $modelRef {key}: JSON Pointer={pointer!r}')
    return ReferenceNode(body['logicalId'], body['attribute'], pointer)


def nodes(value, pointer=''):
    """Enumerate atomic nodes, including JSON encoded inside a string."""
    if is_reference(value):
        yield parse(value, pointer)
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from nodes(child, pointer + '/' + key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from nodes(child, pointer + '/' + str(index))
    elif isinstance(value, str) and value.lstrip().startswith(('{', '[')):
        try:
            encoded = strict_json(value)
        except ValueError:
            return
        yield from nodes(encoded, pointer)


def receiving_property(property_name, pointer):
    path = property_name
    for token in pointer.split('/')[1:]:
        token = token.replace('~1', '/').replace('~0', '~')
        if token.startswith('Fn::'):
            break
        path += '[]' if token.isdigit() else '.' + token
    return path


def context_at(value, property_name, pointer, context=None):
    """Select context by the exact JSON position, with zero-based pointer indexes."""
    path = property_name
    for token in pointer.split('/')[1:]:
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(value, str):
            value = strict_json(value)
        if isinstance(value, dict):
            context = reference_context(path, value, context)
            value = value[token]
            path += '.' + token
        else:
            value = value[int(token)]
            path += '[]'
    return context


def resolve(node, scope, resolver, *, field=None, property_name=None, context=None):
    snapshot, number, resource = resolver.resolve_logical(node.logical_id, scope)
    operand = any(token.startswith('Fn::') for token in node.pointer.split('/'))
    resolver.validate_attribute(resource['resourceType'], node.attribute, field=field, context=context, operand=operand)
    if field and not operand:
        resolver.validate_reference_type(resource['resourceType'], node.attribute, field)
    terminal = node.pointer.rstrip('/').split('/')
    terminal = next((token for token in reversed(terminal) if not token.isdigit()), '')
    if (POLICY_FORMATS.get(property_name) in {'statement', 'wrapped-statement'} and
            terminal in {'Resource', 'NotResource', 'AWS'} and
            reference_attribute(resource['resourceType'], node.attribute) != reference_attribute(resource['resourceType'], 'Arn')):
        raise ReferenceResolutionError('policy Resource/Principal requires the ARN attribute')
    return snapshot, number, resource, node.attribute


def project(value, render=None, pointer=''):
    """Copy a tree for display; never alter Desired or design JSON."""
    if is_reference(value):
        node = parse(value, pointer)
        return render(node) if render else 'unresolved'
    if isinstance(value, dict):
        return {key: project(child, render, pointer + '/' + key.replace('~', '~0').replace('/', '~1'))
                for key, child in value.items()}
    if isinstance(value, list):
        return [project(child, render, pointer + '/' + str(index)) for index, child in enumerate(value)]
    if isinstance(value, str) and value.lstrip().startswith(('{', '[')):
        try:
            encoded = strict_json(value)
        except ValueError:
            return value
        displayed = project(encoded, render, pointer)
        return value if displayed == encoded else json.dumps(displayed, ensure_ascii=False)
    return value


def display_source(value):
    """Opaque restoration metadata keeps Model nodes out of human-facing tables."""
    return base64.b64encode(json.dumps(value, ensure_ascii=True).encode('utf-8')).decode('ascii')


def read_display_source(value):
    return strict_json(base64.b64decode(value, validate=True).decode('utf-8'))


def project_text(value):
    raw = literal(value)
    try:
        parsed = strict_json(raw)
    except ValueError:
        return value
    if not any(nodes(parsed)):
        return value
    displayed = project(parsed)
    text = displayed if isinstance(displayed, str) else json.dumps(displayed, ensure_ascii=False)
    return '`' + text + '`' if value.startswith('`') else text


def display_value(resolver, scope, node):
    snapshot, number, resource, attribute = resolve(node, scope, resolver)
    attribute = reference_attribute(resource['resourceType'], attribute)
    attribute = RETURN_ATTRIBUTE_PROPERTIES.get((resource['resourceType'], attribute), attribute)
    rows = [(rid, row) for rid, row in entries(snapshot.authoritative, 'desired.row.')
            if rid.rpartition('-')[0] == number and row.get('property') == resource['resourceType'] + '.' + attribute]
    observations = [literal(snapshot.authoritative[f'observed.row.{rid}.value']) for rid, _ in rows
                    if f'observed.row.{rid}.value' in snapshot.authoritative]
    if len(observations) == 1:
        value = observations[0]
        if value == 'PENDING_DEPLOY' and resource.get('resourceMode', 'CREATE') == 'CREATE':
            return 'pending_deploy'
        if value and value.lower() not in {'unresolved', 'unset', 'tbd', 'todo', 'pending_deploy'}:
            validate_aws_document(value)
            if not resource_link(value):
                return value
    outputs = catalog_outputs(resolver.root, resource['resourceType'])
    states = [literal(snapshot.authoritative.get(f'observed.row.{rid}.value', ''))
              for rid, row in entries(snapshot.authoritative, 'desired.row.')
              if rid.rpartition('-')[0] == number and row.get('property') in outputs]
    if resource.get('resourceMode', 'CREATE') == 'CREATE' and states and all(state == 'PENDING_DEPLOY' for state in states):
        return 'pending_deploy'
    return 'unresolved'


