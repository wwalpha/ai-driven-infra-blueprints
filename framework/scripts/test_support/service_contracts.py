"""Typed service contracts over authored, disposable authorities."""
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import model_templates as t
from model_files import load_model, resource_row_index
from model_parameter_inputs import yaml_read, literal
from service_rows import pipeline_rows, pipeline_display_rows
from validation_cache import input_scope
ROOT = Path(__file__).resolve().parents[3]

def cases(service):
    paths = [p for p in t.model_paths(ROOT) if p.stem == service]
    assert paths, 'no service contract cases: ' + service
    for path in paths:
        environment, alias = (path.parent.parent.name, path.parent.name)
        _, template, directory = t.source_paths(path)
        human = yaml_read((directory / 'parameters.yaml').read_text(encoding='utf-8'))
        bindings = t.json_read((directory / 'bindings.json').read_text(encoding='utf-8'))
        observed = t.read_observed(directory)[0]
        before = load_model(path).values
        assert not (directory / 'parameters.json').exists()
        yield (environment, alias, directory, template, path, human, bindings, observed, before)

def check_kms():
    for environment, alias, directory, template, path, human, bindings, observed, before in cases('kms'):
        original = copy.deepcopy(human)
        human['instances']['log-key']['parameters']['PendingWindowInDays'] = 20
        after = t.expand(template, human, observed, bindings, environment)[0]
        changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
        row = next((key.removesuffix('.property') for key, value in before.items() if key.startswith('desired.row.001-') and value == 'KMS.Key.PendingWindowInDays'))
        assert changed == {row + '.value'} and after[row + '.value'] == '`20`'
        human = copy.deepcopy(original)
        human['parameters']['AliasSuffix'] = '-acceptance'
        after = t.expand(template, human, observed, bindings, environment)[0]
        alias_rows = {key.removesuffix('.property') + '.value' for key, value in before.items() if value == 'KMS.Alias.AliasName'}
        assert {key for key in before if before[key] != after[key]} == alias_rows
        assert alias_rows
        assert all((after[key].endswith('-acceptance`') for key in alias_rows))
        assert t.expand(template, original, observed, bindings, environment)[0] == before
        for invalid, phrase in [('unknown', 'unknown parameter'), ('missing', 'missing required parameter'), ('type', 'parameter type mismatch')]:
            human = copy.deepcopy(original)
            inputs = human['instances']['log-key']['parameters']
            if invalid == 'unknown':
                inputs['Unknown'] = True
            elif invalid == 'missing':
                del inputs['Enabled']
            else:
                inputs['Enabled'] = 'true'
            rejected(lambda: t.expand(template, human, observed, bindings, environment), phrase)

def check_security_group():
    for environment, alias, directory, template, path, original, bindings, observed, before in cases('security-group'):
        identity, parameter = next(((identity, parameter) for identity, item in original['instances'].items() for parameter in item['parameters'] if parameter.endswith('FromPort')))
        human = copy.deepcopy(original)
        previous = human['instances'][identity]['parameters'][parameter]
        assert type(previous) is int
        human['instances'][identity]['parameters'][parameter] = previous + 1
        after = t.expand(template, human, observed, bindings, environment)[0]
        changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
        assert len(changed) == 1
        key = next(iter(changed))
        assert key.endswith('.value') and before[key.removesuffix('.value') + '.property'].endswith('.FromPort')
        assert after[key] == '`' + str(previous + 1) + '`'
        assert t.expand(template, original, observed, bindings, environment)[0] == before
        for invalid, phrase in [('unknown', 'unknown parameter'), ('missing', 'missing required parameter'), ('type', 'parameter type mismatch')]:
            human = copy.deepcopy(original)
            inputs = human['instances'][identity]['parameters']
            if invalid == 'unknown':
                inputs['Unknown'] = 1
            elif invalid == 'missing':
                del inputs[parameter]
            else:
                inputs[parameter] = str(previous)
            rejected(lambda: t.expand(template, human, observed, bindings, environment), phrase)

def check_route53():
    for environment, alias, directory, template, path, original, bindings, observed, before in cases('route53'):
        if alias == 'cde':
            assert type(original['instances']['quicksight-alias']['parameters']['EvaluateTargetHealth']) is bool
        identity, parameter = next(((identity, parameter) for identity, item in original['instances'].items() for parameter in item['parameters'] if parameter == 'TtlSeconds'))
        human = copy.deepcopy(original)
        previous = human['instances'][identity]['parameters'][parameter]
        assert type(previous) is int
        human['instances'][identity]['parameters'][parameter] = previous + 1
        after = t.expand(template, human, observed, bindings, environment)[0]
        changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
        assert len(changed) == 1
        key = next(iter(changed))
        assert key.endswith('.value') and before[key.removesuffix('.value') + '.property'].endswith('.TTL')
        assert after[key] == '`' + str(previous + 1) + '`'
        assert t.expand(template, original, observed, bindings, environment)[0] == before
        if environment == 'dev':
            human = copy.deepcopy(original)
            human['parameters']['SnowflakeAccountLocator'] += 'x'
            changed_name = t.expand(template, human, observed, bindings, environment)[0]
            differences = {key for key in before.keys() | changed_name.keys() if before.get(key) != changed_name.get(key)}
            assert len(differences) == 4
            assert all((key.endswith('.anchor') or (key.endswith('.value') and before[key.removesuffix('.value') + '.property'] == 'Route53.RecordSet.Name') for key in differences))
            assert {key for key in changed_name if key.endswith('.resourceType')} == {key for key in before if key.endswith('.resourceType')}
        for invalid, phrase in [('unknown', 'unknown parameter'), ('missing', 'missing required parameter'), ('type', 'parameter type mismatch')]:
            human = copy.deepcopy(original)
            inputs = human['instances'][identity]['parameters']
            if invalid == 'unknown':
                inputs['Unknown'] = 1
            elif invalid == 'missing':
                del inputs[parameter]
            else:
                inputs[parameter] = str(previous)
            rejected(lambda: t.expand(template, human, observed, bindings, environment), phrase)

def check_iam():
    objects = 0
    for environment, alias, directory, template, path, original, bindings, observed, before in cases('iam'):
        for key, value in before.items():
            if key.endswith('.document'):
                document = t.json_read(value)
                assert isinstance(document, dict)
                statement = document['Statement']
                assert isinstance(statement, (dict, list))
                objects += isinstance(statement, dict)
        parameter = 'TrustedAccountId'
        human = copy.deepcopy(original)
        previous = human['parameters'][parameter]
        assert isinstance(previous, str) and len(previous) == 12
        human['parameters'][parameter] = '123456789012'
        after = t.expand(template, human, observed, bindings, environment)[0]
        differences = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
        assert differences and any((key.endswith('.document') for key in differences))
        assert all((key.endswith(('.document', '.artifactSha256', '.comment')) for key in differences))
        assert t.expand(template, original, observed, bindings, environment)[0] == before
        for invalid, phrase in [('unknown', 'unknown parameter'), ('missing', 'missing required parameter'), ('type', 'parameter type mismatch')]:
            human = copy.deepcopy(original)
            inputs = human['parameters']
            if invalid == 'unknown':
                inputs['Unknown'] = 1
            elif invalid == 'missing':
                del inputs[parameter]
            else:
                inputs[parameter] = int(previous)
            rejected(lambda: t.expand(template, human, observed, bindings, environment), phrase)
    assert objects > 0

def check_s3():
    trails = 0
    for environment, alias, directory, template, path, human, bindings, observed, before in cases('s3'):
        identity = next((i for i, item in human['instances'].items() if 'ExpirationDays' in item['parameters']))
        invalid = copy.deepcopy(human)
        days = invalid['instances'][identity]['parameters']['ExpirationDays']
        assert type(days) is int
        invalid['instances'][identity]['parameters']['ExpirationDays'] += 1
        changed = t.expand(template, invalid, observed, bindings, environment)[0]
        differences = {k for k in before.keys() | changed.keys() if before.get(k) != changed.get(k)}
        assert len(differences) == 1 and next(iter(differences)).endswith('.value')
        assert before[next(iter(differences)).removesuffix('.value') + '.property'].endswith('.ExpirationInDays')
        assert t.expand(template, human, observed, bindings, environment)[0] == before
        for kind, phrase in [('unknown', 'unknown parameter'), ('missing', 'missing required parameter'), ('type', 'parameter type mismatch')]:
            invalid = copy.deepcopy(human)
            inputs = invalid['instances'][identity]['parameters']
            if kind == 'unknown':
                inputs['Unknown'] = 1
            elif kind == 'missing':
                del inputs['ExpirationDays']
            else:
                inputs['ExpirationDays'] = str(days)
            rejected(lambda: t.expand(template, invalid, observed, bindings, environment), phrase)
        trail = path.with_name('cloudtrail.properties')
        if trail in t.model_paths(ROOT):
            assert load_model(trail).values
            trails += 1
        for key, value in before.items():
            if key.endswith('.document'):
                document = t.json_read(value)
                assert isinstance(document, dict) and isinstance(document['Statement'], list)
    assert trails == len([p for p in t.model_paths(ROOT) if p.stem == 'cloudtrail'])
    assert trails > 0

def check_glue():
    jobs = 0
    for environment, alias, directory, template, path, human, bindings, observed, before in cases('glue'):
        defs, _ = t.parse_template(template)
        removed = {'Timeout'} | ({'Description', 'ScriptObjectKey'} if alias == 'cde' else set())
        assert not any(removed & d.parameters.keys() for d in defs.values())
        timeouts = [row['value'] for rows in resource_row_index(before).values() for _, row in rows if row['property'] == 'Glue.Job.Timeout']
        assert timeouts and all(value == '`30`' for value in timeouts)
        edited = copy.deepcopy(human)
        edited['parameters']['Suffix'] = '-a1b2c3'
        renamed = t.expand(template, edited, observed, bindings, environment)[0]
        for rows in resource_row_index(renamed).values():
            for _, row in rows:
                if row['property'] == 'Glue.Job.SecurityConfiguration':
                    assert row['value'] == '[glsc-a1b2c3](#glue-glsc-a1b2c3)'
                if row['property'] == 'Glue.Job.DefaultArguments':
                    arguments = t.json_read(literal(row['value']))
                    assert isinstance(arguments, dict) and all((isinstance(v, str) for v in arguments.values()))
                    jobs += 1
        assert t.expand(template, human, observed, bindings, environment)[0] == before
        logs = ROOT / 'model' / environment / alias / 'cloudwatch-logs.properties'
    assert jobs > 0

def check_cloudwatch_logs():
    groups = 0
    producers = set()
    for env, alias, directory, template, path, human, bindings, observed, before in cases('cloudwatch-logs'):
        defs, _ = t.parse_template(template)
        for d in defs.values():
            producers.update((s['service'] for s in d.parameters.values() if isinstance(s, dict) and s.get('format') == 'name'))
        groups += len(resource_row_index(before))
        assert not any({'RetentionInDays', 'DeletionProtectionEnabled'} & d.parameters.keys() for d in defs.values())
        for rows in resource_row_index(before).values():
            name = next(row['value'] for _, row in rows if row['property'] == 'Logs.LogGroup.LogGroupName')
            values = {row['property']: row['value'] for _, row in rows}
            assert values['Logs.LogGroup.DeletionProtectionEnabled'] == '`false`'
            assert values['Logs.LogGroup.RetentionInDays'] == ('`30`' if name.startswith('`/aws/vpc/flow-logs') else '`365`')
        assert t.expand(template, human, observed, bindings, env)[0] == before
    assert {'lambda', 'glue', 'iam', 'codebuild', 'mwaa', 'cloudtrail'} <= producers

def check_lambda():
    functions = permissions = 0
    for env, alias, directory, template, path, human, bindings, observed, before in cases('lambda'):
        for rid, rows in resource_row_index(before).items():
            kind = before['desired.resource.' + rid + '.resourceType']
            functions += kind == 'Lambda.Function'
            permissions += kind == 'Lambda.Permission'
            for _, r in rows:
                if r['property'] == 'Lambda.Function.Architectures':
                    assert t.json_read(literal(r['value'])) == ['x86_64']
                if r['property'] == 'Lambda.Permission.Principal':
                    assert literal(r['value']) in ('s3.amazonaws.com', 'events.amazonaws.com')
        edited = copy.deepcopy(human)
        identity = next((i for i, item in human['instances'].items() if 'MemorySize' in item['parameters']))
        params = edited['instances'][identity]['parameters']
        assert type(params['MemorySize']) is int
        params['MemorySize'] += 1
        after = t.expand(template, edited, observed, bindings, env)[0]
        diff = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
        assert len(diff) == 1
        key = next(iter(diff))
        assert before[key.removesuffix('.value') + '.property'] == 'Lambda.Function.MemorySize'
        assert t.expand(template, human, observed, bindings, env)[0] == before
        event = path.with_name('eventbridge.properties')
    assert functions > 0 and permissions > 0

def check_eventbridge():
    rules = schedules = 0
    for env, alias, directory, template, path, human, bindings, observed, before in cases('eventbridge'):
        for rid, rows in resource_row_index(before).items():
            kind = before['desired.resource.' + rid + '.resourceType']
            rules += kind == 'Events.Rule'
            schedules += kind == 'Scheduler.Schedule'
            for rowid, r in rows:
                if r['property'] == 'Events.Rule.EventPattern':
                    doc = t.json_read(before['desired.row.' + rowid + '.document'])
                    assert doc['detail']['eventName'] == ['GetObject']
                    assert type(doc['detail']['userIdentity']['userName']) is list
                    assert type(doc['detail']['requestParameters']['bucketName']) is list
                if r['property'].endswith('.ScheduleExpressionTimezone'):
                    assert literal(r['value']) == 'Asia/Tokyo'
                if r['property'].endswith('.ScheduleExpression'):
                    assert literal(r['value']).startswith('cron(')
                if r['property'].endswith('.State'):
                    assert literal(r['value']) in ('ENABLED', 'DISABLED')
        fixed_retry = {'MaximumEventAgeInSeconds': 3600, 'MaximumRetryAttempts': 3}
        for name, value in fixed_retry.items():
            assert all(name not in item['parameters'] for item in human['instances'].values())
            retry_rows = [r for rows in resource_row_index(before).values() for _, r in rows
                          if r['property'].endswith('.RetryPolicy.' + name)]
            assert retry_rows and all(r['value'] == f'`{value}`' for r in retry_rows)
            edited = copy.deepcopy(human)
            next(iter(edited['instances'].values()))['parameters'][name] = value
            rejected(lambda: t.expand(template, edited, observed, bindings, env), 'unknown parameter')
        assert t.expand(template, human, observed, bindings, env)[0] == before
        producer = path.with_name('lambda.properties')
    assert rules > 0 and schedules > 0

def check_codepipeline():
    pipelines = 0
    configurations = 0
    for env, alias, directory, template, path, human, bindings, observed, before in cases('codepipeline'):
        for rid, rows in resource_row_index(before).items():
            pipelines += 1
            formal = [[rowid, r['property'].removeprefix('CodePipeline.Pipeline.'), r['value'], r['comment']] for rowid, r in rows]
            restored = pipeline_display_rows(pipeline_rows(formal))
            assert [(r[1].removeprefix('CodePipeline.Pipeline.'), r[2]) for r in restored] == [(r[1], r[2]) for r in formal]
            for _, r in rows:
                if r['property'].endswith('.Configuration'):
                    doc = t.json_read(literal(r['value']))
                    assert isinstance(doc, dict) and all((type(v) is str for v in doc.values()))
                    configurations += 1
        edited = copy.deepcopy(human)
        identity = next((i for i, item in human['instances'].items() if 'SourceBranch' in item['parameters']))
        edited['instances'][identity]['parameters']['SourceBranch'] += '-yaml-probe'
        after = t.expand(template, edited, observed, bindings, env)[0]
        diff = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
        assert len(diff) == 1
        key = next(iter(diff))
        assert before[key.removesuffix('.value') + '.property'].endswith('.Configuration')
        old = t.json_read(literal(before[key]))
        new = t.json_read(literal(after[key]))
        assert new == {**old, 'BranchName': old['BranchName'] + '-yaml-probe'}
        assert t.expand(template, human, observed, bindings, env)[0] == before
    assert pipelines > 0

def rejected(call, phrase):
    try:
        call()
    except ValueError as error:
        assert phrase in str(error), (phrase, str(error))
    else:
        raise AssertionError('invalid service input accepted: ' + phrase)

def check_responsibilities():
    from model_core import entries
    from model_projection import document_sha256
    from model_parameter_inputs import parameter_text, service_inputs
    services = {'config', 'data-firehose', 'guardduty', 'macie', 'quicksight', 'codebuild', 'ec2', 'mwaa', 'cloudformation-stacks', 'transit-gateway'}
    for service in sorted(services):
        checked = set()
        for env, alias, directory, template, path, human, bindings, observed, before in cases(service):
            defs = t.parse_template(template)[0]
            if service == 'cloudformation-stacks':
                # Fixed placement bindings retain their names when human StackNames change.
                assert set(bindings['stacks']) == {identity for identity, _ in entries(before, 'desired.stack.')}
                assert type(human['parameters']['MaxConcurrentStacks']) is int
            if service == 'macie':
                assert all(('ArtifactSha256' not in b['parameters'] for b in bindings['instances'].values()))
            for key, value in before.items():
                if key.endswith('.document'):
                    assert before[key.removesuffix('.document') + '.artifactSha256'] == document_sha256(t.json_read(value))
            expand = lambda h, b=bindings: t.expand(template, h, observed, b, env)[0]
            assert expand(human) == before
            assert 'definition:' not in parameter_text(human, defs, bindings)
            reordered = copy.deepcopy(bindings)
            reordered['instances'] = dict(reversed(list(bindings['instances'].items())))
            assert expand(human, reordered) == before
            scope = {(env, alias, service)}
            assert scope <= t.affected(ROOT, [template.relative_to(ROOT)])
            assert scope <= t.affected(ROOT, [(directory / 'parameters.yaml').relative_to(ROOT)])
            trace = t.load_expansion(path).provenance
            assert before and trace
            if human['instances'] or human.get('parameters'):
                assert any((s.get('inputs') or s.get('references') for s in trace.values()))
            for source in trace.values():
                for spec in source.get('inputs', {}).values():
                    assert spec['description'] and spec['modelKey']
                    if spec['source'] == 'consumer.executionAccountId':
                        assert spec['value'] and ROOT / 'project.json' in t.source_inputs(path)
            slots = [(None, human['parameters'])] if 'parameters' in human else []
            slots += [(identity, item['parameters']) for identity, item in human['instances'].items()]
            for identity, params in slots:
                for name, value in params.items():
                    declarations = defs[bindings['instances'][identity]['definition']].parameters if identity is not None else service_inputs(defs, bindings, human)
                    spec = declarations[name]
                    unknown_name = 'Value1'
                    while unknown_name in declarations:
                        unknown_name += '_'
                    feature = (alias, name, t.json_text({k: v for k, v in spec.items() if k not in {'description'}}))
                    if feature in checked:
                        continue
                    checked.add(feature)

                    def changed(value=value, remove=False, unknown=False):
                        h = copy.deepcopy(human)
                        target = h['parameters'] if identity is None else h['instances'][identity]['parameters']
                        if remove:
                            target.pop(name)
                        elif unknown:
                            target[unknown_name] = 'retired'
                        else:
                            target[name] = value
                        return h
                    if spec['required'] or 'default' not in spec:
                        rejected(lambda: expand(changed(remove=True)), 'missing required parameter')
                    else:
                        expand(changed(remove=True))
                    rejected(lambda: expand(changed(True if spec['type'] in {'integer', 'number'} else 17)), 'parameter type mismatch')
                    rejected(lambda: expand(changed(unknown=True)), 'unknown parameter')
                    probes = {'ImageId': ('ami-0123456789abcdef0', 'EC2.Instance.ImageId'), 'MaxConcurrentStacks': (value + 1 if type(value) is int else value, None), 'SubnetId1': ('subnet-0123456789abcdef0', None)}
                    if name in probes:
                        replacement, prop = probes[name]
                        after = expand(changed(replacement))
                        difference = {k for k in before if before[k] != after[k]}
                        assert difference
                        if prop:
                            assert difference == {k.removesuffix('.property') + '.value' for k, v in before.items() if v == prop}
                        if name == 'MaxConcurrentStacks':
                            assert difference == {'desired.deployment.maxConcurrentStacks'}
                        if name == 'SubnetId1':
                            assert len(difference) == 2 and any((k.startswith('desired.note.') for k in difference))
                        assert all((after[k] == v for k, v in before.items() if k.startswith(('desired.resource.', 'observed.'))))
                    invalid = {'ImageId': ('not-an-ami', 'constraint pattern'), 'MinWorkers': (0, 'constraint minimum'), 'WebserverAccessMode': ('INVALID', 'constraint enum'), 'MaxConcurrentStacks': (0, 'constraint minimum')}
                    if name in invalid:
                        value, phrase = invalid[name]
                        rejected(lambda: expand(changed(value)), phrase)
            if slots:
                assert checked, 'no input cases: ' + service
    print('Service responsibilities: PASS (bindings-only instances, fixed mappings, hashes, context provenance, input/type/constraint rejection, typed isolated edits)')

@input_scope
def check():
    from test_support.service_fixtures import typed_services
    with TemporaryDirectory(prefix="typed-services-") as directory:
        root = Path(directory)
        typed_services(root)
        with patch(__name__+".ROOT", root):
            check_fixtures()


def check_fixtures():
    check_responsibilities()
    check_kms()
    check_security_group()
    check_route53()
    check_iam()
    check_s3()
    check_glue()
    check_cloudwatch_logs()
    check_lambda()
    check_eventbridge()
    check_codepipeline()
    print('Service contracts: PASS (typed edits, Policy/arrays, producer names, references, nested Pipeline restoration, strict rejection)')
