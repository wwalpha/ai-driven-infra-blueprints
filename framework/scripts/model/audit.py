#!/usr/bin/env python3
"""Generate one standalone audit test from authoritative Model sources, offline."""
import argparse
import ast
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from aws_mapping_compare import comparison
from design_catalog import DesignSchemaCatalog
from model.core import entries
from model.sources import load_model
from model.projection import catalog_outputs
from model.sources import model_paths, publication_lock
from script_loader import module
from task_contract import task_revision, status, SELECTOR
from validation_cache import input_scope, input_text

ROOT = Path(__file__).resolve().parents[3]


def definitions(path, names):
    """Copy existing implementations verbatim; fail if an upstream name disappears."""
    source = input_text(path, encoding='utf-8')
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    found = {node.name: ''.join(lines[min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1:node.end_lineno]).rstrip() for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    missing = set(names) - found.keys()
    if missing:
        raise ValueError(f'missing runtime definitions in {path.name}: {sorted(missing)}')
    return '\n\n'.join(found[name] for name in names) + '\n'


def dependencies(root, target, selected):
    """Embed only selected resources and explicitly referenced producer resources."""
    from iac_values import cfn_resource_identity
    from model.sources import FileReads
    reads = FileReads()
    from model.identity import Resolver
    identity_resolver = Resolver(root, reads)
    cache, included, pending = {}, {}, [(selected, None)]

    def model_identity(path):
        return path.relative_to(root / 'model').with_suffix('').as_posix()

    def read(path):
        key = model_identity(path)
        if key not in cache:
            cache[key] = None if reads.kind(path) == 'missing' else load_model(path, reads)
        return cache[key]

    def logical_names(value):
        if isinstance(value, list):
            return set().union(*(logical_names(v) for v in value)) if value else set()
        if not isinstance(value, dict):
            return set()
        names = set()
        if 'Ref' in value:
            names.add(value['Ref'])
        if 'Fn::GetAtt' in value:
            item = value['Fn::GetAtt']
            names.add(item[0] if isinstance(item, list) else item.split('.')[0])
        if 'Fn::Sub' in value:
            sub = value['Fn::Sub']
            text, local = sub if isinstance(sub, list) else (sub, {})
            names.update(key.split('.')[0] for key in re.findall(r'\$\{([^}]+)\}', text)
                         if key not in local and not key.startswith('!'))
        for child in value.values():
            names.update(logical_names(child))
        return {name for name in names if not name.startswith('AWS::')}

    while pending:
        path, numbers = pending.pop()
        data = read(path)
        specs = dict(entries(data.values, 'desired.resource.'))
        wanted = set(specs) if numbers is None else set(numbers)
        new = wanted - included.get(model_identity(path), set())
        if not new:
            continue
        included.setdefault(model_identity(path), set()).update(new)
        for number in sorted(new):
            spec = specs[number]
            stack = cfn_resource_identity(spec['cfn-logicalId'])[0] if 'cfn-logicalId' in spec else None
            values = [value for key, value in data.values.items() if
                      key.startswith('desired.row.' + number + '-') or key == 'desired.resource.' + number + '.parentReference']
            for value in values:
                from model.identity import reference_tokens
                resolver = identity_resolver
                for uri in reference_tokens(value):
                    source, rid, _ = resolver.resolve(uri[0])
                    pending.append((source.scope.path, {rid}))
                try:
                    names = logical_names(json.loads(value.strip('`')))
                except (ValueError, TypeError):
                    names = set()
                if names:
                    for producer in model_paths(root, data.scope.environment, data.scope.target):
                        matches = set()
                        for rid, item in entries(read(producer).values, 'desired.resource.'):
                            identity = cfn_resource_identity(item['cfn-logicalId']) if 'cfn-logicalId' in item else (None, None)
                            if identity[0] == stack and identity[1] in names:
                                matches.add(rid)
                        if matches:
                            pending.append((producer, matches))
    result = {}
    for name, numbers in included.items():
        data = cache[name]
        prefixes = tuple(prefix + number + suffix for number in sorted(numbers) for prefix, suffix in
                         [('desired.resource.', '.'), ('desired.row.', '-'), ('observed.row.', '-')])
        values = {key: value for key, value in data.values.items() if key.startswith(prefixes)}
        result[name] = data._replace(values=values)
    return result


@input_scope
def generate(root, environment, selector, service):
    m = module('model/adapters/aws.py', 'model.adapters.aws')
    project_source = (root / 'project.json').read_bytes().decode('utf-8')
    target, = m.targets(root, environment, selector)
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', selector):
        raise ValueError('unsafe target selector')
    _, path = m.inventory(root, [target], [service])[0]
    if service == 'cloudformation-stacks':
        raise ValueError('cloudformation-stacks has no resource-property Mapping; unsupported')
    models = dependencies(root, target, path)
    catalog = DesignSchemaCatalog(ROOT)
    mappings, schemas, outputs = {}, {}, {}
    for name in sorted({data.scope.service for data in models.values()}):
        selected_rows = [row for data in models.values() if data.scope.service == name
                         for _, row in entries(data.values, 'desired.row.')]
        if name == 'cloudformation-stacks':
            continue
        mapping, props = comparison(ROOT, name)
        props = dict(props)
        if name == 'iam':
            # Audit-only projection: existing Compare keeps its CloudControl classification.
            from aws_mapping import response_shape
            from botocore.session import get_session
            sdk = get_session().get_service_model('iam')
            for kind, operation, result in [('IAM.Role', 'GetRole', 'Role'), ('IAM.User', 'GetUser', 'User')]:
                response_shape(sdk.operation_model(operation).output_shape, result + '.PermissionsBoundary.PermissionsBoundaryArn')
                key = kind + '.PermissionsBoundary'
                prop = props[key]
                props[key] = replace(prop, field=replace(prop.field, getter='base', path='PermissionsBoundary.PermissionsBoundaryArn',
                                                       norm='arn', classification='supported', reason=''))
        from aws_mapping import Property
        for row in selected_rows:
            key = row['property']
            if key not in props:
                props[key] = Property(m.Field(classification='unimplemented', reason='no AWS Compare Mapping for selected attribute'),
                                      False, False, key, 'model')
        mappings[name] = {'getters': {k: dict(v) for k, v in mapping.getters.items()},
                          'identities': {k: asdict(v) for k, v in mapping.identities.items()},
                          'properties': {k: asdict(replace(v, field=replace(v.field, default=v.field.copy_default())))
                                         for k, v in props.items()}}
        for row in selected_rows:
            prop = row['property']
            kind = '.'.join(prop.split('.')[:2])
            try:
                schema = catalog.property_schema(kind, prop[len(kind) + 1:])
                schemas[prop] = {k: schema[k] for k in ('type', 'minLength') if k in schema}
            except KeyError:
                pass  # Existing Resource.parse treats design-only properties as strings.
            outputs[kind] = sorted(catalog_outputs(ROOT, kind))
    files = {str(file.relative_to(root)): None if content is None else content.decode('utf-8')
             for data in models.values() for file, content in data.dependencies.items()}
    files['project.json'] = project_source
    model_hash = hashlib.sha256(m.stable({'sources': files, 'target': target}).encode('utf-8')).hexdigest()
    scripts = ROOT / 'framework/scripts'
    engine = ('from __future__ import annotations\n'
              'import argparse, hashlib, json, os, re, subprocess, sys\n'
              'from collections import Counter, defaultdict\n'
              'from copy import deepcopy\nfrom threading import RLock\nfrom concurrent.futures import Future\n'
              'from dataclasses import dataclass\nfrom pathlib import Path, PurePosixPath\nfrom urllib.parse import unquote\n'
              'ROOT = Path("/model-test-snapshot")\n'
              'LINK = re.compile(r"^\\[([^\\]]+)\\]\\(([^)]*?)#([^)]+)\\)$")\n'
              'def memo_table(): return None\n')
    from model.identity import URI
    engine += 'URI = re.compile(' + repr(URI.pattern) + ')\n'
    engine += definitions(scripts / 'model/identity.py', ['parse_reference'])
    engine += definitions(scripts / 'model/references.py', ['link_scope'])
    engine += definitions(scripts / 'utils/lazy_definitions.py', ['load_once'])
    engine += definitions(scripts / 'utils/json_format.py', ['unique_object', 'invalid_constant', 'policy_json'])
    engine += definitions(scripts / 'iac_values.py', ['cfn_resource_identity'])
    engine += definitions(scripts / 'model/core.py', ['entries', 'literal'])
    engine += definitions(scripts / 'comparison_rows.py', ['Unresolved', 'select', 'put_row'])
    engine += 'MISSING = {"absent": True}\n'
    # Preserve the exact collection semantics maintained by the existing comparator.
    original = input_text(scripts / 'model/adapters/aws.py', encoding='utf-8')
    tree = ast.parse(original)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {'MAP_ARRAYS', 'SET_ARRAYS'} for t in node.targets):
            engine += ast.get_source_segment(original, node) + '\n'
    engine += definitions(scripts / 'model/adapters/aws.py', ['Field', 'AcquisitionError', 'sdk_error', 'one', 'project',
                          'canonical', 'stable', 'policy', 'redacted', 'Context', 'Model', 'Resource',
                          'normalize', 'source', 'compare_resource'])
    projection = definitions(scripts / 'aws_mapping_catalog.py', ['project'])
    mapped = definitions(scripts / 'aws_mapping_compare.py', ['value'])
    adapters = {name: input_text(scripts / 'aws-compare-services' / (name + '.py'), encoding='utf-8')
                for name in sorted(set(mappings) | {'iam', 'kms'})}
    snapshot = {'target': target, 'service': service, 'modelHash': model_hash,
                'models': {name: dict(data.values) for name, data in sorted(models.items())},
                'schemas': schemas, 'outputs': outputs, 'mappings': mappings,
                'adapters': adapters, 'engine': engine, 'projection': projection, 'mapped': mapped}
    runtime = input_text(scripts / 'model/audit_runtime.py', encoding='utf-8')
    result = ('#!/usr/bin/env python3\n# Generated offline by /model-test; regenerate after Model changes.\n'
              'import json\nSNAPSHOT = json.loads(' + repr(m.stable(snapshot)) + ')\n' + runtime)
    compile(result, f'{service}.py', 'exec')
    unsupported = []
    for _, resource in entries(models['/'.join((environment, target['directory'], service))].values, 'desired.resource.'):
        kind = resource['resourceType']
        if kind in outputs:
            unsupported.extend((key, 'resource identifier; not a desired configuration value') for key in outputs[kind]
                               if any(row['property'] == key for _, row in entries(models['/'.join((environment, target['directory'], service))].values, 'desired.row.')))
    for _, row in entries(models['/'.join((environment, target['directory'], service))].values, 'desired.row.'):
        key = row['property']
        field = mappings[service]['properties'][key]['field']
        if field['classification'] != 'supported':
            unsupported.append((key, field['reason']))
    return result, files, sorted(set(unsupported))


def main(argv=None):
    from generation_inputs import GenerationInputs
    from validation_cache import recording_inputs
    from task_contract import selected_task, validate_contract, paths_in, matches
    from sync_files import atomic_files
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository-root', type=Path, default=Path.cwd())
    parser.add_argument('--environment', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--service', required=True)
    parser.add_argument('--task-file', required=True)
    args = parser.parse_args(argv)
    root = args.repository_root.resolve()
    inputs = None
    try:
        with selected_task(root, args.task_file):
            from issue_gate import require_no_issues
            from validation_scope import active_scope
            require_no_issues(root, active_scope(root))
            expected_task = task_revision(root, args.task_file)
            name, text = expected_task
            if text is None or status(text, name == 'tasks/active.md') != 'running':
                raise ValueError('audit generation requires a running Task')
            validate_contract(root, name, text)
            output = root / 'tests' / args.environment / args.target / (args.service + '.py')
            from model.sources import safe
            safe(root, output)
            relative = output.relative_to(root).as_posix()
            if relative not in paths_in(text, '## Modified files') or not any(matches(relative, p) for p in paths_in(text, '## Allowed paths')):
                raise ValueError('audit output is outside the registered Task paths')
            inputs = GenerationInputs(root, task_file=name)
            with recording_inputs(inputs):
                source, _, unsupported = generate(root, args.environment, args.target, args.service)
                previous = inputs.read(output)
            with publication_lock(root):
                inputs.verify()
                if task_revision(root, args.task_file) != expected_task:
                    raise ValueError('task scope changed during audit generation')
                if previous != source.encode('utf-8'):
                    atomic_files({output: source})
            print(f'Generated: {relative} (syntax OK; AWS not contacted)')
            for key, reason in unsupported:
                print(f'  ERROR check: {key}: {reason}')
            return 0
    except (OSError, ValueError, KeyError) as error:
        print(f'Model test generation: FAIL: {error}')
        return 2
    finally:
        if inputs is not None:
            inputs.close()
