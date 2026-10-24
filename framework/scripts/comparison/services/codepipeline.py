"""codepipeline comparison contracts and projections."""

from design.services.codepipeline import pipeline_rows
from utils.cloudformation.inputs import Blocked
from utils.reference_contracts import action_contexts, configuration_contract

contexts = action_contexts

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


def reference_contract(path, attribute, context):
    if not path.startswith('Stages[].Actions[].Configuration.'):
        return NotImplemented
    contract = configuration_contract('CodePipeline.Pipeline.' + path, context)
    if not contract:
        raise Blocked(f'CodePipeline {path} reference contract unproven: ActionTypeId={context.get("ActionTypeId")}')
    kind, = contract
    expected, = contract[kind]
    if attribute is not None and attribute != expected:
        raise Blocked(f'CodePipeline {path} reference attribute must be {expected}')
    return kind, expected
