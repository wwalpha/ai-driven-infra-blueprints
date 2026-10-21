"""codepipeline: selected properties -> read-only SDK responses; inputs in fetch()."""

from model.adapters.aws import MISSING

APIS = {('codepipeline', 'get_pipeline')}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    result=ctx.call('codepipeline', 'get_pipeline', name=r.value('Name'))
    return dict(result['pipeline'],PipelineArn=result.get('metadata',{}).get('pipelineArn',MISSING))
