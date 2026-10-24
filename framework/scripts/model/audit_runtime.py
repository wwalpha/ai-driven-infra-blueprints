"""Runtime source embedded into each generated file; requires only Python stdlib."""

import argparse
import io
import json
import re
import sys
from collections import Counter
from datetime import datetime
from functools import partial as _bind_framework_callback
from functools import partialmethod
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _callback_engine_load_model(m, snapshot, /, path):
    address = path.relative_to(m.ROOT / 'model').with_suffix('').as_posix()
    if address not in snapshot['models']:
        raise m.Unresolved('producer Model is absent from audit snapshot: ' + address)
    values = snapshot['models'][address]
    return SimpleNamespace(values=values, locations={key: (Path('embedded') / path.name, 0) for key in values})


def _callback_engine_resolve_json(self, m, original_resolve, /, value, norm='typed'):
    if isinstance(value, dict) and 'Fn::GetAtt' in value:
        item = value['Fn::GetAtt']
        attribute = item[1] if isinstance(item, list) and len(item) == 2 else item.partition('.')[2] if isinstance(item, str) else None
        if len(value) != 1 or attribute != 'Arn':
            raise m.Unresolved('unsupported GetAtt attribute; only Arn has a confirmed identity mapping')
    return original_resolve(self, value, norm)


def engine(snapshot):
    """Bind copied comparison code to immutable, embedded Model/Mapping inputs."""
    m = ModuleType('audit_comparison')
    sys.modules[m.__name__] = m
    exec(compile(snapshot['engine'], '<existing-comparator>', 'exec'), m.__dict__)
    sys.modules['iac_values'] = m
    m._imports_iac_values = m
    m.SERVICES = tuple(snapshot['adapters'])
    adapters = {}
    for name, source in snapshot['adapters'].items():
        adapter = ModuleType('audit_' + name.replace('-', '_'))
        source = source.replace('from model.adapters.aws import', 'from audit_comparison import')
        exec(compile(source, '<adapter:' + name + '>', 'exec'), adapter.__dict__)
        adapters[name] = adapter
    m.service_module = adapters.__getitem__
    m.model_paths = lambda root, environment, directory: [root / 'model' / (name + '.properties')
        for name in snapshot['models'] if name.rsplit('/', 1)[0] == environment + '/' + directory]

    load_model = _bind_framework_callback(_callback_engine_load_model, m, snapshot)

    original_resolve = m.Resource.resolve_json
    m.Resource.resolve_json = partialmethod(_callback_engine_resolve_json, m, original_resolve)
    m.load_model = load_model
    m.DesignSchemaCatalog = lambda root: SimpleNamespace(property_schema=lambda kind, path: snapshot['schemas'][kind + '.' + path])
    m.catalog_outputs = lambda root, kind: snapshot['outputs'].get(kind, [])
    mappings = {}
    for name, data in snapshot['mappings'].items():
        props = {key: SimpleNamespace(**{**prop, 'field': m.Field(**prop['field'])})
                 for key, prop in data['properties'].items()}
        mapping = SimpleNamespace(getters=data['getters'], identities={key: SimpleNamespace(**value)
                                                                      for key, value in data['identities'].items()})
        mappings[name] = (mapping, props)
    m.Context.comparison = lambda self, service: mappings[service]
    projection = ModuleType('audit_projection')
    projection.module = lambda *args: m
    exec(compile(snapshot['projection'], '<existing-mapping-projection>', 'exec'), projection.__dict__)
    mapped = ModuleType('aws_mapping_compare')
    mapped.select, mapped.module, mapped.project = m.select, projection.module, projection.project
    exec(compile(snapshot['mapped'], '<existing-mapping-value>', 'exec'), mapped.__dict__)
    sys.modules[mapped.__name__] = mapped
    m._imports_aws_mapping_compare = mapped
    return m


SENSITIVE = re.compile(r'password|secret|token|credential|privatekey|accesskey|authorization', re.I)


def masked(value, key=''):
    if SENSITIVE.search(key):
        return '[REDACTED]'
    if isinstance(value, dict):
        return {k: masked(v, k) for k, v in value.items()}
    if isinstance(value, list):
        # Tag/variable maps store sensitive names in Key/Name, outside the Value key.
        return [('[REDACTED]' if isinstance(v, dict) and SENSITIVE.search(str(v.get('Key', v.get('Name', ''))))
                 else masked(v)) for v in value]
    if isinstance(value, str):
        if '{{resolve:' in value:
            return '[REDACTED]'
        raw = value.strip('`')
        if raw.startswith(('{', '[')):
            try:
                return masked(json.loads(raw))
            except ValueError:
                pass
    return value


def different_paths(left, right, path='$'):
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        return [p for key in sorted(left.keys() | right.keys()) for p in
                ([path + '.' + key] if key not in left or key not in right else different_paths(left[key], right[key], path + '.' + key))]
    if isinstance(left, list):
        return [p for index in range(max(len(left), len(right))) for p in
                ([f'{path}[{index}]'] if index >= len(left) or index >= len(right)
                 else different_paths(left[index], right[index], f'{path}[{index}]'))]
    return [] if left == right else [path]


def attributes(result):
    """Existing acquisition diagnostics group failures; audit rows remain independent."""
    for item in result:
        if item.get('affectedKeys'):
            for prop in item['affectedKeys']:
                yield {**item, 'propertiesKey': prop, 'designValue': item.get('designValues', {}).get(prop)}
        else:
            yield item


def audit(snapshot, profile=None, cli_runner=None):
    m = engine(snapshot)
    target = dict(snapshot['target'])
    ctx = None
    account, records = 'unverified', []
    try:
        selected = m.select_profile(target, profile)
        if selected is not None:
            target['awsProfile'] = selected
        ctx = m.Context(m.ROOT, target, cli_runner=cli_runner)
        account = ctx.verify()
    except Exception as error:
        reason = error.code if isinstance(error, (m.AcquisitionError, m.IdentityError)) else str(error) if isinstance(error, (m.Unresolved, ValueError)) else type(error).__name__
        if ctx is None:
            ctx = m.Context(m.ROOT, snapshot['target'], cli_runner=cli_runner)
        # Account/credential failure stops all resource APIs, but records every attribute.
        model = ctx.model(m.ROOT / 'model' / target['environment'] / target['directory'] / (snapshot['service'] + '.properties'))
        for resource in model.resources:
            for prop in dict.fromkeys(row['property'] for _, row in resource.rows):
                records.append({'resource': resource.spec['logicalId'], 'propertiesKey': prop,
                                'status': 'acquisition_failed', 'reason': reason, 'designValue':
                                [row.get('document', row['value']) for _, row in resource.rows if row['property'] == prop],
                                'awsValue': None, 'apis': ctx.trace})
        return m, account, records
    model = ctx.model(m.ROOT / 'model' / target['environment'] / target['directory'] / (snapshot['service'] + '.properties'))
    for resource in model.resources:
        try:
            records.extend(attributes(m.compare_resource(ctx, resource)))
        except Exception as error:
            # Never turn a new upstream dependency or malformed response into a silent skip.
            for prop in dict.fromkeys(row['property'] for _, row in resource.rows):
                records.append({'resource': resource.spec['logicalId'], 'propertiesKey': prop,
                                'status': 'design_unresolved', 'reason': 'comparison failed: ' + type(error).__name__,
                                'designValue': [row.get('document', row['value']) for _, row in resource.rows if row['property'] == prop],
                                'awsValue': None, 'apis': ctx.trace})
    return m, account, records


def _callback_report_line(output, /, value=''):
    print(value, file=output)


def report(snapshot, profile, account, records, timestamp):
    output = io.StringIO()
    line = _bind_framework_callback(_callback_report_line, output)
    target = snapshot['target']
    line('Executed: ' + timestamp.isoformat())
    for label, value in [('Environment', target['environment']), ('Alias', target['directory']),
                         ('Service', snapshot['service']), ('Profile', profile or '(default credential chain)'),
                         ('Region', target['awsRegion']), ('Account', account), ('Model SHA256', snapshot['modelHash'])]:
        line(f'{label}: {value}')
    line()
    counts = Counter()
    for item in records:
        state = {'match': 'OK', 'difference': 'NG'}.get(item['status'], 'ERROR')
        counts[state] += 1
        prop = item.get('propertiesKey') or '(resource)'
        line(f'[{state}] {item["resource"]}.{prop}')
        expected = masked(item.get('designValue'), prop)
        actual = masked(item.get('awsValue'), prop)
        line('  Model: ' + json.dumps(expected, ensure_ascii=False, sort_keys=True))
        line('  AWS:   ' + json.dumps(actual, ensure_ascii=False, sort_keys=True))
        line('  API: ' + ', '.join(dict.fromkeys('aws ' + ('s3api' if entry['api'].split('.')[0] == 's3' else entry['api'].split('.')[0]) +
                                                   ' ' + entry['api'].split('.')[1].replace('_', '-') for entry in item.get('apis', []))))
        if state != 'OK':
            line('  Reason: ' + item.get('reason', 'value differs' if state == 'NG' else item['status']))
        if state == 'NG':
            line('  Diff paths: ' + ', '.join(different_paths(expected, actual) or ['$ (redacted values differ)']))
        line()
    if not records:
        counts['ERROR'] += 1
        line('[ERROR] No selected desired attributes')
    line('--------------------------------')
    line(f'Total: {sum(counts.values())}')
    for state in ('OK', 'NG', 'ERROR'):
        line(f'{state}: {counts[state]}')
    code = 2 if counts['ERROR'] else 1 if counts['NG'] else 0
    line('Result: ' + ('FAIL' if code else 'PASS'))
    return output.getvalue(), code


def main(argv=None, cli_runner=None, script_path=None):
    SNAPSHOT = globals()['SNAPSHOT']
    parser = argparse.ArgumentParser(description='Read-only audit against embedded Model expectations')
    parser.add_argument('--profile')
    args = parser.parse_args(argv)
    timestamp = datetime.now().astimezone()
    target = SNAPSHOT['target']
    script = Path(script_path or __file__).resolve()
    # tests/<environment>/<alias>/<service>.py -> tests/results/<environment>/<alias>/
    layout = ('tests', target['environment'], target['directory'])
    tests = script.parents[2] if script.parent.parts[-3:] == layout else Path.cwd() / 'tests'
    directory = tests / 'results' / target['environment'] / target['directory']
    try:
        directory.mkdir(parents=True, exist_ok=True)
        filename = SNAPSHOT['service'] + '-' + timestamp.strftime('%Y%m%d-%H%M%S')
        path = directory / (filename + '.log')
        try:
            handle = path.open('x', encoding='utf-8', newline='\n')
        except FileExistsError:
            handle = (directory / (filename + timestamp.strftime('-%f') + '.log')).open('x', encoding='utf-8', newline='\n')
        with handle:
            _, account, records = audit(SNAPSHOT, args.profile, cli_runner)
            text, code = report(SNAPSHOT, args.profile or target.get('awsProfile'), account, records, timestamp)
            handle.write(text)
            handle.flush()
            sys.stdout.write(text)
        return code
    except OSError as error:
        print('[ERROR] audit log unavailable: ' + type(error).__name__)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
