"""codepipeline comparison contracts and projections."""

import re

from cloudformation_inputs import Blocked
from comparison_rows import put_row
from policy_tables import literal
from service_rows import pipeline_rows

KMS_FORMS = {'CodePipeline.Pipeline.ArtifactStore.EncryptionKey.Id': {'AliasArn'}}




def prepare_rows(rows, *, index_rows):
    kind = 'CodePipeline.Pipeline'
    if not any('Stages[].' in row['property'] for _, row in rows):
        return rows
    original = dict(rows)
    displayed = pipeline_rows([[rid, row['property'].removeprefix(kind + '.'), row['value'], row.get('comment', '')] for rid, row in rows])
    prepared, configurations = [], set()
    for rid, prop, value, _ in index_rows(displayed, kind):
        row = original[rid]
        if row['property'].endswith('.Configuration'):
            if rid in configurations:
                continue
            configurations.add(rid)
            prop = prop.split('.Configuration.', 1)[0] + '.Configuration'
            value = row['value']
        prepared.append((rid, dict(row, property=kind + '.' + prop, value=value)))
    return prepared


def contexts(rows):
    contexts = {}
    for _, row in rows:
        prop = row['property'].removeprefix('CodePipeline.Pipeline.')
        action = re.fullmatch(r'(.*\.Actions\[\d+\])\.ActionTypeId\.(Category|Owner|Provider|Version)', prop)
        if action:
            put_row(contexts.setdefault(action[1], {}), 'ActionTypeId.' + action[2], literal(row['value']))
    return contexts


def reference_contract(path, attribute, context):
    if not path.startswith('Stages[].Actions[].Configuration.'):
        return NotImplemented
    action = context.get('ActionTypeId', {})
    field = path.removeprefix('Stages[].Actions[].Configuration.')
    contracts = {'RepositoryName': ('Source', 'CodeCommit', 'CodeCommit.Repository', 'Name'),
                 'ProjectName': ('Build', 'CodeBuild', 'CodeBuild.Project', 'Name')}
    contract = contracts.get(field)
    if not contract or action != dict(Category=contract[0], Owner='AWS', Provider=contract[1], Version='1'):
        raise Blocked(f'CodePipeline {field} reference contract unproven: ActionTypeId={action}')
    return contract[2], contract[3]
