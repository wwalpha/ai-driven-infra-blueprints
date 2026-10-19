#!/usr/bin/env python3
"""Offline raw producer names used by Logs: typed, traced and dependency-aware."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

import copy
from support.model_sources import write_model, write_fixture_files
import tempfile

import model_templates as t
from model_files import load_model
from support.model_sources import write_fixture_files as save_files


def rejected(function, phrase):
    try:
        function()
    except (ValueError, OSError) as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError('invalid name reference accepted: ' + phrase)


@it_case
def check(root):
    template = root / 'model/templates/team/cloudwatch-logs.properties.tpl'
    refs = {
        'Configuration': {'service': 'glue', 'resource': '006', 'resourceType': 'Glue.SecurityConfiguration', 'format': 'name'},
        'ExecutionRole': {'service': 'iam', 'resource': '054', 'resourceType': 'IAM.Role', 'format': 'name'},
        'Function': {'service': 'lambda', 'resource': '012', 'resourceType': 'Lambda.Function', 'format': 'name'},
        'Trail': {'service': 'cloudtrail', 'resource': '001', 'resourceType': 'CloudTrail.Trail', 'format': 'name'},
        'Project': {'service': 'codebuild', 'resource': '008', 'resourceType': 'CodeBuild.Project', 'format': 'name'},
        'ProjectLink': {'service': 'codebuild', 'resource': '008', 'resourceType': 'CodeBuild.Project'},
        'Repository': {'service': 'codecommit', 'resource': '017', 'resourceType': 'CodeCommit.Repository', 'format': 'name'},
        'RepositoryLink': {'service': 'codecommit', 'resource': '017', 'resourceType': 'CodeCommit.Repository'},
        'RoleLink': {'service': 'iam', 'resource': '054', 'resourceType': 'IAM.Role'},
    }
    text = '\n'.join([
        '# model-template: 1', '# definition: ExistingLogs',
        *['# reference: ' + name + ' ' + t.json_text(spec) for name, spec in refs.items()],
        '# resource: glue', '# resource: function',
        '# row: glueName glue', '# row: functionName function',
        'desired.resource.glue.resourceType=Logs.LogGroup',
        'desired.resource.glue.anchor=glue-log-<<Id_glue>>',
        'desired.resource.function.resourceType=Logs.LogGroup',
        'desired.resource.function.anchor=lambda-log-<<Id_function>>',
        'desired.row.glueName.property=Logs.LogGroup.LogGroupName',
        'desired.row.glueName.value=`/aws-glue/jobs/<<Configuration>>-role/<<ExecutionRole>>/error`',
        'desired.row.functionName.property=Logs.LogGroup.LogGroupName',
        'desired.row.functionName.value=`/aws/lambda/<<Function>>`',
        'desired.note.role.text=<<RoleLink>>',
        'desired.note.trail.text=`/aws/cloudtrail/<<Trail>>`',
        'desired.note.project.text=`/aws/codebuild/<<Project>>`',
        'desired.note.projectLink.text=<<ProjectLink>>',
        'desired.note.repository.document={"Resource":"arn:aws:codecommit:ap-northeast-1:111111111111:<<Repository>>"}',
        'desired.note.repositoryLink.text=<<RepositoryLink>>',
        'desired.note.names.document={"Role":"<<ExecutionRole>>","Enabled":true,"Count":2}',
        '# end-definition', '',
    ])
    bindings = {'instances': {'existing': {'definition': 'ExistingLogs',
        'resources': {'glue': '002', 'function': '003'},
        'rows': {'glueName': '002-001', 'functionName': '003-001'},
        'parameters': {}, 'labels': {'RoleLink': 'existing-role-label'}}}}
    human, observed = {'instances': {}}, {'version': 1, 'values': {}}
    write_fixture_files({template: text})
    records = {}
    for env, suffix in [('preview', '-Case_01'), ('later', '')]:
        producer_texts = {}
        for name, spec in refs.items():
            if name.endswith('Link'):
                continue
            kind = spec['resourceType']
            value = {'Configuration': 'glsc' + suffix, 'ExecutionRole': 'venusinf-' + env + '-IfInbound1802Role' + suffix,
                     'Function': 'lmda-' + env + '-inbound-detect' + suffix, 'Trail': 'trail-' + env + suffix,
                     'Project': 'cbld-' + env + suffix, 'Repository': 'ccmt-' + env + suffix}[name]
            prop = {'Configuration': 'Glue.SecurityConfiguration.Name', 'ExecutionRole': 'IAM.Role.RoleName',
                    'Function': 'Lambda.Function.FunctionName', 'Trail': 'CloudTrail.Trail.TrailName',
                    'Project': 'CodeBuild.Project.Name', 'Repository': 'CodeCommit.Repository.RepositoryName'}[name]
            rid = spec['resource']
            producer = root / 'model' / env / 'team' / (spec['service'] + '.properties')
            producer_texts[producer] = '\n'.join([
                'desired.resource.' + rid + '.resourceType=' + kind,
                'desired.resource.' + rid + '.anchor=' + spec['service'] + '-original',
                'desired.row.' + rid + '-001.property=' + prop,
                'desired.row.' + rid + '-001.value=`' + value + '`', '',
            ])
            if name == 'Project':
                producer_texts[producer] += ('desired.row.008-002.property=CodeBuild.Project.Environment.EnvironmentVariables[].Name\n'
                    'desired.row.008-002.value=`AWS_REGION`\n'
                    'desired.row.008-003.property=CodeBuild.Project.LogsConfig.CloudWatchLogs.GroupName\n'
                    'desired.row.008-003.value=[logs](cloudwatch-logs.md#codebuild-logs)\n')
        write_fixture_files(producer_texts)
        values, provenance, files = t.expand(template, human, observed, bindings, env)
        assert values['desired.row.002-001.value'] == '`/aws-glue/jobs/glsc' + suffix + '-role/venusinf-' + env + '-IfInbound1802Role' + suffix + '/error`'
        assert values['desired.row.003-001.value'] == '`/aws/lambda/lmda-' + env + '-inbound-detect' + suffix + '`'
        assert values['desired.note.trail.text'] == '`/aws/cloudtrail/trail-' + env + suffix + '`'
        assert values['desired.note.project.text'] == '`/aws/codebuild/cbld-' + env + suffix + '`'
        assert values['desired.note.projectLink.text'] == '[cbld-' + env + suffix + '](codebuild.md#codebuild-original)'
        assert t.json_read(values['desired.note.repository.document']) == {'Resource': 'arn:aws:codecommit:ap-northeast-1:111111111111:ccmt-' + env + suffix}
        assert values['desired.note.repositoryLink.text'] == '[ccmt-' + env + suffix + '](codecommit.md#codecommit-original)'
        assert values['desired.note.role.text'] == '[existing-role-label](iam.md#iam-original)'
        assert t.json_read(values['desired.note.names.document']) == {'Role': 'venusinf-' + env + '-IfInbound1802Role' + suffix, 'Enabled': True, 'Count': 2}
        assert provenance['desired.row.002-001.value']['parameters'] == ['Configuration', 'ExecutionRole']
        assert {file for producer in producer_texts for file in load_model(producer).files} <= files.keys()
        path = root / 'model' / env / 'team/cloudwatch-logs.properties'
        directory = root / 'model/parameters' / env / 'team/cloudwatch-logs'
        write_fixture_files({path: ''.join(k + '=' + v + '\n' for k, v in values.items()),

            directory / 'parameters.yaml': 'instances: {}\n', directory / 'bindings.json': t.json_text(bindings),
            directory / 'observed.json': t.json_text(observed)})
        records[env] = path, values, producer_texts
        assert load_model(path).values == values
    path, before, producers = records['preview']
    other_path, other_before, _ = records['later']
    producer = root / 'model/preview/team/iam.properties'
    original = producers[producer]
    initial_digest = t.design_source_digest(path)
    write_model(producer, original.replace('IfInbound1802Role', 'RenamedRole'))
    changed = load_model(path)
    assert 'RenamedRole' in changed.values['desired.row.002-001.value']
    assert changed.values['desired.row.003-001.value'] == before['desired.row.003-001.value']
    assert load_model(other_path).values == other_before
    assert t.design_source_digest(path) != initial_digest
    assert t.affected(root, [producer.relative_to(root)]) == {('preview', 'team', 'iam'), ('preview', 'team', 'cloudwatch-logs')}
    trace = t.load_expansion(path).provenance['desired.row.002-001.value']
    assert trace['references']['ExecutionRole']['format'] == 'name'
    write_model(producer, original)
    for bad, phrase in [
        (original.replace('resourceType=IAM.Role', 'resourceType=IAM.Policy'), 'zero matching candidates: resourceType mismatch'),
        (original.replace('054', '055'), 'zero candidates: fixed Resource ID absent or Instance has no active Resources'),
        (original.replace('IAM.Role.RoleName', 'IAM.Role.Path'), 'exactly one name'),
        (original.replace('IAM.Role.RoleName', 'Glue.SecurityConfiguration.Name'), 'exactly one name'),
        (original.replace('`venusinf-preview-IfInbound1802Role-Case_01`', '``'), 'exactly one name'),
        (original + 'desired.row.054-002.property=IAM.Role.RoleName\ndesired.row.054-002.value=`duplicate`\n', 'exactly one name'),
    ]:
        write_model(producer, bad)
        rejected(lambda: load_model(path), phrase)
    write_model(producer, original)
    bad = copy.deepcopy(bindings)
    bad['instances']['existing']['labels']['ExecutionRole'] = 'manual-name'
    rejected(lambda: t.expand(template, human, observed, bad, 'preview'), 'cannot override label')
    t.source_paths(producer)[2].joinpath('parameters.yaml').unlink()
    rejected(lambda: load_model(path), 'missing')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())
    print('Producer names: PASS (Glue/IAM/Lambda/CloudTrail/CodeBuild/CodeCommit; direct property only; raw fragments; case/empty suffix; typed JSON; link compatibility; producer hash/impact/trace; rejection)')
