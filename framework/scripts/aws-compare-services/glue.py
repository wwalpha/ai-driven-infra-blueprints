"""glue: selected properties -> read-only SDK responses; inputs in fetch()."""

from model.adapters.aws import one

APIS = {('glue', 'get_security_configuration'), ('glue', 'get_catalog'), ('glue', 'get_table'), ('glue', 'get_catalogs'), ('glue', 'get_connection'), ('glue', 'get_database'), ('glue', 'get_job')}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if r.kind == 'Glue.Catalog':
        current=r.current('CatalogId')
        if current:
            return ctx.call('glue','get_catalog',CatalogId=current)['Catalog']
        return one([v for v in ctx.pages('glue','get_catalogs',ParentCatalogId=ctx.target.get('awsExecutionAccountId',ctx.target['awsAccountId'])).get('CatalogList',[]) if v['Name']==r.value('Name')], 'glue.get_catalogs')
    if r.kind == 'Glue.Connection':
        catalog=r.value('CatalogId')
        record=ctx.call('glue','get_connection',CatalogId=catalog,Name=r.value('ConnectionInput.Name'),HidePassword=True)['Connection']
        return dict(record,CatalogId=catalog)
    if r.kind == 'Glue.Database':
        catalog=r.value('CatalogId')
        return dict(ctx.call('glue','get_database',CatalogId=catalog,Name=r.value('DatabaseInput.Name'))['Database'],CatalogId=catalog)
    if r.kind == 'Glue.Table':
        catalog, database=r.value('CatalogId'),r.value('DatabaseName')
        record=ctx.call('glue','get_table',CatalogId=catalog,DatabaseName=database,Name=r.value('TableInput.Name'))['Table']
        return dict(record,CatalogId=catalog,DatabaseName=database)
    if r.kind == 'Glue.Job':
        return ctx.call('glue','get_job',JobName=r.value('Name'))['Job']
    return ctx.call('glue','get_security_configuration',Name=r.value('Name'))['SecurityConfiguration']


SDK_OPERATIONS = {'Glue.Connection': 'get_connection', 'Glue.Table': 'get_table'}


def fetch_sdk(ctx, r, operation):
    catalog = r.value('CatalogId')
    if r.kind == 'Glue.Connection':
        return ctx.call('glue', operation, CatalogId=catalog, Name=r.value('ConnectionInput.Name'), HidePassword=True)
    return ctx.call('glue', operation, CatalogId=catalog, DatabaseName=r.value('DatabaseName'), Name=r.value('TableInput.Name'))
