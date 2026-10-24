"""Decode CloudFormation JSON/YAML without evaluation or AWS access."""

import re
from functools import partial as _bind_framework_callback
from pathlib import Path

import yaml

import utils.iac_values as _imports_iac_values
import utils.input_cache as _imports_validation_cache


class CloudFormationLoader(yaml.SafeLoader):
    """Isolated CFn tags with the existing YAML scalar and merge interpretation."""


def mapping(loader, node):
    # Reject duplicate authored keys, but retain YAML merge/explicit override behavior.
    keys = set()
    for key, _ in node.value:
        if key.tag == 'tag:yaml.org,2002:merge':
            continue
        value = loader.construct_object(key, deep=True)
        try:
            if value is None or value in keys:
                raise yaml.constructor.ConstructorError(None, None, 'null/duplicate key: ' + str(value), key.start_mark)
            keys.add(value)
        except TypeError as error:
            raise yaml.constructor.ConstructorError(None, None, 'unhashable mapping key', key.start_mark) from error
    loader.flatten_mapping(node)
    result = loader.construct_mapping(node, deep=True)
    if loader.locations is not None:
        loader.locations[id(result)] = {loader.construct_object(key): key.start_mark.line + 1 for key, _ in node.value}
        loader.locations[id(result)][None] = node.start_mark.line + 1
    return result


def intrinsic(loader, suffix, node):
    name = suffix if suffix in {'Ref', 'Condition'} else 'Fn::' + suffix
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
        if name == 'Fn::GetAtt':
            value = value.split('.', 1)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = mapping(loader, node)
    return {name: value}


CloudFormationLoader.add_constructor('tag:yaml.org,2002:map', mapping)
CloudFormationLoader.add_multi_constructor('!', intrinsic)


def _recursive_decode_size(active, sizes, /, value):
    if not isinstance(value, (dict, list)):
        return 1
    identity = id(value)
    if identity in active:
        raise ValueError('recursive YAML alias')
    if identity not in sizes:
        active.add(identity)
        total = 1
        for child in value.values() if isinstance(value, dict) else value:
            total += _recursive_decode_size(active, sizes, child)
            if total > 250000:
                raise ValueError('YAML alias expansion exceeds 250000 nodes')
        active.remove(identity)
        sizes[identity] = total
    return sizes[identity]


def decode(text, source='<template>', *, locations=None):
    """Return (plain values, parse errors); accept already acquired text or bytes."""
    try:
        if isinstance(text, bytes):
            text = text.decode('utf-8-sig')
        loader = CloudFormationLoader(text)
        loader.locations = locations
        try:
            document = loader.get_single_data()
        finally:
            loader.dispose()
        # Bound alias expansion and reject cycles before downstream recursive walkers.
        sizes, active = {}, set()
        size = _bind_framework_callback(_recursive_decode_size, active, sizes)
        if '&' in text:
            size(document)
        return {} if document is None else document, []
    except (yaml.YAMLError, ValueError, TypeError, RecursionError) as error:
        return None, [f'{source}: {error}']


def decode_file(path, *, locations=None):
    input_bytes = _imports_validation_cache.input_bytes
    return decode(input_bytes(Path(path)), str(path), locations=locations)


JSON_INTRINSICS = {'Ref', 'Condition', 'Fn::GetAtt', 'Fn::Sub', 'Fn::Join', 'Fn::Split', 'Fn::Select',
                   'Fn::If', 'Fn::Equals', 'Fn::And', 'Fn::Or', 'Fn::Not', 'Fn::FindInMap',
                   'Fn::ImportValue', 'Fn::GetAZs', 'Fn::Base64', 'Fn::Cidr', 'Fn::Length',
                   'Fn::ToJsonString', 'Fn::Transform'}


def _lambda_intrinsic_shape_error_sequence_111(argument, /, count):
    return isinstance(argument, list) and len(argument) == count


def _lambda_intrinsic_shape_error_string_110(symbolic, /, value):
    return isinstance(value, str) or symbolic(value)


def _lambda_intrinsic_shape_error_symbolic_108(Expression, ResourceReference, /, value):
    return isinstance(value, (Expression, ResourceReference)) or (isinstance(value, dict) and len(value) == 1 and any((key == 'Ref' or key.startswith('Fn::') for key in value)))


def intrinsic_shape_error(name, argument):
    """The Model JSON structural contract, without template semantic validation."""
    Expression = _imports_iac_values.Expression
    ResourceReference = _imports_iac_values.ResourceReference
    symbolic = _bind_framework_callback(_lambda_intrinsic_shape_error_symbolic_108, Expression, ResourceReference)
    string = _bind_framework_callback(_lambda_intrinsic_shape_error_string_110, symbolic)
    sequence = _bind_framework_callback(_lambda_intrinsic_shape_error_sequence_111, argument)
    valid = True
    if name in {'Ref', 'Condition'}:
        valid = isinstance(argument, str) and bool(argument)
    elif name == 'Fn::GetAtt':
        valid = (isinstance(argument, str) and '.' in argument or sequence(2) and all(string(v) for v in argument))
    elif name == 'Fn::Sub':
        valid = (isinstance(argument, str) or sequence(2) and isinstance(argument[0], str) and isinstance(argument[1], dict))
        if valid:
            text = argument if isinstance(argument, str) else argument[0]
            valid = '${' not in re.sub(r'\$\{!?[A-Za-z0-9_.:]+\}', '', text)
    elif name in {'Fn::Join', 'Fn::Split', 'Fn::Select'}:
        valid = sequence(2)
        if valid and name == 'Fn::Join':
            valid = isinstance(argument[0], str) and (isinstance(argument[1], list) or symbolic(argument[1]))
        elif valid and name == 'Fn::Split':
            valid = isinstance(argument[0], str) and bool(argument[0]) and string(argument[1])
        elif valid:
            index = argument[0]
            valid = ((type(index) is int and index >= 0) or isinstance(index, str) and index.isdigit() or symbolic(index)) and (isinstance(argument[1], list) or symbolic(argument[1]))
    elif name == 'Fn::If':
        valid = sequence(3) and isinstance(argument[0], str)
    elif name == 'Fn::Equals':
        valid = sequence(2)
    elif name in {'Fn::And', 'Fn::Or'}:
        valid = isinstance(argument, list) and 2 <= len(argument) <= 10
    elif name == 'Fn::Not':
        valid = sequence(1)
    elif name == 'Fn::FindInMap':
        valid = isinstance(argument, list) and len(argument) in {3, 4}
    elif name in {'Fn::ImportValue', 'Fn::GetAZs', 'Fn::Base64'}:
        valid = string(argument)
    elif name in {'Fn::Cidr', 'Fn::Length', 'Fn::ToJsonString', 'Fn::Transform'}:
        valid = (sequence(3) if name == 'Fn::Cidr' else isinstance(argument, (list, dict))
                 if name != 'Fn::Transform' else isinstance(argument, dict))
    return None if valid else 'invalid argument shape'
