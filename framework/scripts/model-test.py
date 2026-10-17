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
from model_core import entries
from model_files import load_model
from model_references import catalog_outputs
from model_templates import model_paths, publication_lock
from script_loader import module
from task_contract import task_revision, status, SELECTOR
from validation_cache import input_scope

ROOT = Path(__file__).resolve().parents[2]


def definitions(path, names):
    """Copy existing implementations verbatim; fail if an upstream name disappears."""
    source = path.read_text(encoding='utf-8')
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
    cache, included, pending = {}, {}, [(selected, None)]

    def read(path):
        if path.stem not in cache:
            cache[path.stem] = load_model(path)
        return cache[path.stem]

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
        new = wanted - included.get(path.stem, set())
        if not new:
            continue
        included.setdefault(path.stem, set()).update(new)
        for number in sorted(new):
            spec = specs[number]
            stack = cfn_resource_identity(spec['cfn-logicalId'])[0] if 'cfn-logicalId' in spec else None
            values = [value for key, value in data.values.items() if
                      key.startswith('desired.row.' + number + '-') or key == 'desired.resource.' + number + '.parentReference']
            for value in values:
                for filename, anchor in re.findall(r'\[[^\]]+\]\(([^)#]*?)#([^)]+)\)', value):
                    if filename and (Path(filename).name != filename or not filename.endswith('.md')):
                        raise ValueError('reference must stay in the same target')
                    producer = path.parent / (Path(filename).stem + '.properties') if filename else path
                    matches = {rid for rid, item in entries(read(producer).values, 'desired.resource.') if item.get('anchor') == anchor}
                    pending.append((producer, matches))
                try:
                    names = logical_names(json.loads(value.strip('`')))
                except (ValueError, TypeError):
                    names = set()
                if names:
                    for producer in model_paths(root, target['environment'], target['directory']):
                        matches = set()
                        for rid, item in entries(read(producer).values, 'desired.resource.'):
                            identity = cfn_resource_identity(item['cfn-logicalId']) if 'cfn-logicalId' in item else (None, item.get('logicalId'))
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
    m = module('check-model-aws.py', 'model_aws_compare')
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
    for name, data in sorted(models.items()):
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
        for _, row in entries(data.values, 'desired.row.'):
            key = row['property']
            if key not in props:
                props[key] = Property(m.Field(classification='unimplemented', reason='no AWS Compare Mapping for selected attribute'),
                                      False, False, key, 'model')
        mappings[name] = {'getters': {k: dict(v) for k, v in mapping.getters.items()},
                          'identities': {k: asdict(v) for k, v in mapping.identities.items()},
                          'properties': {k: asdict(replace(v, field=replace(v.field, default=v.field.copy_default())))
                                         for k, v in props.items()}}
        for _, row in entries(data.values, 'desired.row.'):
            prop = row['property']
            kind = '.'.join(prop.split('.')[:2])
            try:
                schema = catalog.property_schema(kind, prop[len(kind) + 1:])
                schemas[prop] = {k: schema[k] for k in ('type', 'minLength') if k in schema}
            except KeyError:
                pass  # Existing Resource.parse treats design-only properties as strings.
            outputs[kind] = sorted(catalog_outputs(ROOT, kind))
    files = {str(file.relative_to(root)): content for data in models.values() for file, content in data.files.items()}
    for name in models:
        observed = root / 'model/parameters' / environment / selector / name / 'observed.json'
        if not observed.exists():
            files[observed.relative_to(root).as_posix()] = None
    files['project.json'] = project_source
    model_hash = hashlib.sha256(m.stable({'sources': files, 'target': target}).encode('utf-8')).hexdigest()
    scripts = ROOT / 'framework/scripts'
    engine = ('from __future__ import annotations\n'
              'import argparse, hashlib, json, os, re, subprocess, sys\n'
              'from collections import Counter, defaultdict\n'
              'from dataclasses import dataclass\nfrom pathlib import Path\nfrom urllib.parse import unquote\n'
              'ROOT = Path("/model-test-snapshot")\n'
              'LINK = re.compile(r"^\\[([^\\]]+)\\]\\(([^)]*?)#([^)]+)\\)$")\n'
              'def memo_table(): return None\n')
    engine += definitions(scripts / 'iac_values.py', ['unique_object', 'invalid_constant', 'cfn_resource_identity'])
    engine += definitions(scripts / 'model_core.py', ['entries', 'literal'])
    engine += definitions(scripts / 'comparison_rows.py', ['Unresolved', 'select', 'put_row'])
    engine += 'MISSING = {"absent": True}\n'
    # Preserve the exact collection semantics maintained by the existing comparator.
    original = (scripts / 'check-model-aws.py').read_text(encoding='utf-8')
    tree = ast.parse(original)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {'MAP_ARRAYS', 'SET_ARRAYS'} for t in node.targets):
            engine += ast.get_source_segment(original, node) + '\n'
    engine += definitions(scripts / 'check-model-aws.py', ['Field', 'AcquisitionError', 'sdk_error', 'one', 'project',
                          'canonical', 'stable', 'policy', 'redacted', 'Context', 'Model', 'Resource',
                          'normalize', 'source', 'compare_resource'])
    projection = definitions(scripts / 'aws_mapping_catalog.py', ['project'])
    mapped = definitions(scripts / 'aws_mapping_compare.py', ['value'])
    adapters = {name: (scripts / 'aws-compare-services' / (name + '.py')).read_text(encoding='utf-8')
                for name in sorted(set(mappings) | {'iam', 'kms'})}
    snapshot = {'target': target, 'service': service, 'modelHash': model_hash,
                'models': {name: data.values for name, data in sorted(models.items())},
                'schemas': schemas, 'outputs': outputs, 'mappings': mappings,
                'adapters': adapters, 'engine': engine, 'projection': projection, 'mapped': mapped}
    runtime = (scripts / 'model_test_runtime.py').read_text(encoding='utf-8')
    result = ('#!/usr/bin/env python3\n# Generated offline by /model-test; regenerate after Model changes.\n'
              'import json\nSNAPSHOT = json.loads(' + repr(m.stable(snapshot)) + ')\n' + runtime)
    compile(result, f'{service}.py', 'exec')
    unsupported = []
    for _, resource in entries(models[service].values, 'desired.resource.'):
        kind = resource['resourceType']
        if kind in outputs:
            unsupported.extend((key, 'resource identifier; not a desired configuration value') for key in outputs[kind]
                               if any(row['property'] == key for _, row in entries(models[service].values, 'desired.row.')))
    for _, row in entries(models[service].values, 'desired.row.'):
        key = row['property']
        field = mappings[service]['properties'][key]['field']
        if field['classification'] != 'supported':
            unsupported.append((key, field['reason']))
    return result, files, sorted(set(unsupported))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--service', required=True)
    parser.add_argument('--task-file', required=True)
    args = parser.parse_args()
    try:
        root = ROOT
        os.environ[SELECTOR] = args.task_file
        from issue_gate import require_no_issues
        from validation_scope import active_scope
        require_no_issues(root, active_scope(root))
        output = root / 'tests' / args.environment / args.target / (args.service + '.py')
        # Resolve selectors through topology before constructing any write directories.
        expected_task = task_revision(root, args.task_file)
        name, text = expected_task
        if text is not None and status(text, name == 'tasks/active.md') != 'running':
            raise ValueError('completed task cannot write')
        source, inputs, unsupported = generate(root, args.environment, args.target, args.service)
        if not output.resolve().is_relative_to(root / 'tests') or any(p.is_symlink() for p in [output, *output.parents] if p != root.parent):
            raise ValueError('unsafe output path')
        with publication_lock(root):
            for relative, content in inputs.items():
                file = root / relative
                actual = file.read_bytes().decode('utf-8') if file.is_file() else None
                if actual != content:
                    raise ValueError('Model inputs changed during generation; regenerate')
            changed = not output.exists() or output.read_text(encoding='utf-8') != source
            if task_revision(root, args.task_file) != expected_task:
                raise ValueError('task scope changed during generation; regenerate')
            if changed:
                output.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent, delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(source)
                try:
                    temporary.replace(output)
                finally:
                    temporary.unlink(missing_ok=True)
        print(f'Generated: {output.relative_to(root)} (syntax OK; AWS not contacted)')
        for key, reason in unsupported:
            print(f'  ERROR check: {key}: {reason}')
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f'Model test generation: FAIL: {error}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
