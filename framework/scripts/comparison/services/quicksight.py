"""quicksight comparison contracts and projections."""

import model.importing.references as _imports_model_importing_references
from design.policy_tables import literal
from utils.cloudformation.inputs import Blocked

IMPORT_CONSUMER = ('QuickSight.DataSource.Permissions[].Principal', 'QuickSight.Group', 'Arn')

def imported_group_arn(all_rows, catalog, partition, target, stack_inputs):
    known = _imports_model_importing_references.known
    fields = {}
    for field in catalog.schema('QuickSight.Group')['identityProperties']:
        rows = [row for _, row in all_rows
                if row['property'] == 'QuickSight.Group.' + field]
        if len(rows) != 1 or 'document' in rows[0]:
            raise Blocked('QuickSight Group requires one scalar identity property: ' + field)
        candidate = literal(rows[0]['value'])
        if not known(candidate) or catalog.literal_errors('QuickSight.Group', field, candidate):
            raise Blocked('QuickSight Group requires one confirmed identity property: ' + field)
        fields[field] = candidate
    # stack_input establishes partition from the target's recorded SDK Region.
    region = target.get('awsRegion')
    if not partition or not region or not any(
            pseudo.get('AWS::Region') == region and pseudo.get('AWS::Partition') == partition
            for _, _, pseudo in stack_inputs.values()):
        raise Blocked('QuickSight Group ARN requires a confirmed CloudFormation Region and partition')
    # https://docs.aws.amazon.com/cli/latest/reference/quicksight/create-group.html
    return (f"arn:{partition}:quicksight:{region}:{fields['AwsAccountId']}:"
            f"group/{fields['Namespace']}/{fields['GroupName']}")

IMPORTED_ARN_KINDS = {'QuickSight.Group'}
