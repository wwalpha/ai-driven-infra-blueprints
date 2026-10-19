"""Mapping-owned Markdown names and visibility; formal Model rows stay intact."""
from pathlib import Path

from utils.aws_mappings import owners
from model_core import entries
from validation_cache import input_scope, memoized

ROOT = Path(__file__).resolve().parents[2]
MODEL_ONLY = frozenset({'EC2.VPC.Name', 'EC2.Subnet.Name', 'EC2.RouteTable.Name',
                        'EC2.FlowLog.Name', 'S3.Bucket.Region'})


@memoized
def rules(root, kind):
    from aws_mapping import runtime_registry
    if kind == 'CloudFormation.Stack':
        return {}
    service = owners(root).get(kind)
    if service is None:
        raise ValueError('display Mapping resource type missing: ' + kind)
    return {key: prop for key, prop in runtime_registry(root, service).properties.items()
            if key.startswith(kind + '.')}


def rule(prop, root=ROOT):
    if prop in MODEL_ONLY:
        return None
    kind = '.'.join(prop.split('.')[:2])
    result = rules(root, kind)
    if prop not in result:
        raise ValueError('display Mapping property missing: ' + prop)
    return result[prop]


def show(prop, root=ROOT):
    item = rule(prop, root)
    return item is None or item.show


def display_name(prop, heading, root=ROOT):
    from design_layout import GROUPED, RESOURCE_PROPERTY_PREFIXES
    item = rule(prop, root)
    name = item.name if item else prop.removeprefix(heading + '.')
    owner = '.'.join(prop.split('.')[:2])
    if owner != heading and owner in GROUPED:
        if name.startswith(heading + '.'):
            return name.removeprefix(heading + '.')
        if name.startswith(owner.split('.', 1)[0] + '.') or name.startswith(RESOURCE_PROPERTY_PREFIXES):
            return name
        return owner + '.' + name.removeprefix(owner + '.')
    return name.removeprefix(heading + '.')


@memoized
def reverse_names(root, heading):
    from design_layout import GROUPED_RESOURCE_TYPES
    result = {}
    visibility = {}
    for owner in [heading, *sorted(GROUPED_RESOURCE_TYPES.get(heading, set()))]:
        for formal, item in rules(root, owner).items():
            name = display_name(formal, heading, root)
            if name in result and result[name] != formal:
                if item.show and visibility[name]:
                    raise ValueError('display name collision in grouped table: ' + name)
                if not item.show:
                    continue
            result[name], visibility[name] = formal, item.show
    return result


def formal_name(display, heading, root=ROOT):
    if heading == 'Config.ConfigurationRecorder' and display == 'RoleARN':
        return heading + '.RoleARN'
    return reverse_names(root, heading).get(display)


def structural(prop):
    """These rows supply existing hidden/grouped identity metadata, not ordinary rows."""
    from design_layout import GROUPED, LAMBDA_PERMISSION
    owner = '.'.join(prop.split('.')[:2])
    group = GROUPED.get(owner, {})
    return prop in {LAMBDA_PERMISSION + '.Id', LAMBDA_PERMISSION + '.FunctionName'} or (
        owner in GROUPED and prop == owner + '.' + str(group.get('parentProperty'))) or (
        group.get('display') == 'rule-table' and prop == owner + '.Id')


def compact_group(prop):
    """Keep existing multi-row producers atomic when one constituent is hidden."""
    if prop in {'Glue.Job.DefaultArguments', 'Glue.Job.NonOverridableArguments'}:
        return prop
    for prefix in ('CodeBuild.Project.Environment.EnvironmentVariables[].',
                   'GuardDuty.Detector.Features[].', 'CloudTrail.Trail.EventSelectors[].DataResources[].',
                   'Glue.Job.DefaultArguments[].', 'Glue.Job.NonOverridableArguments[].',
                   'CodePipeline.Pipeline.Stages[].', 'EC2.Instance.BlockDeviceMappings[].', 'EC2.SecurityGroup.Tags[].',
                   'EC2.Instance.Tags[].', 'EC2.VPCEndpoint.Tags[].'):
        if prop.startswith(prefix):
            return prefix
    if prop.startswith(('EC2.SecurityGroup.SecurityGroupIngress[].', 'EC2.SecurityGroup.SecurityGroupEgress[].')):
        return prop.rsplit('.', 1)[0]
    if prop.startswith(('EC2.SecurityGroupIngress.', 'EC2.SecurityGroupEgress.')) and prop.rsplit('.', 1)[1] in {'FromPort', 'ToPort'}:
        return prop.rsplit('.', 1)[0] + '.Ports'
    return None


@input_scope
def selected_rows(rows, root=ROOT):
    from design_layout import GROUPED, LAMBDA_PERMISSION
    hidden_groups = {compact_group(row[1]) for row in rows if not show(row[1], root)} - {None}
    blocked = set()
    for identity, prop, *_ in rows:
        owner = '.'.join(prop.split('.')[:2])
        field = prop.removeprefix(owner + '.')
        group = GROUPED.get(owner, {})
        critical = (field == group.get('identityProperty') and not structural(prop)) or (
            owner == LAMBDA_PERMISSION and field == 'Action') or (
            group.get('display') == 'rule-table' and field in {
                'IpProtocol', 'CidrIp', 'CidrIpv6', 'SourcePrefixListId', 'DestinationPrefixListId',
                'SourceSecurityGroupId', 'DestinationSecurityGroupId'})
        if critical and not show(prop, root):
            blocked.add((identity.rpartition('-')[0], owner))
    result = [row for row in rows if (row[0].rpartition('-')[0], '.'.join(row[1].split('.')[:2])) not in blocked
              and (structural(row[1]) or (show(row[1], root) and compact_group(row[1]) not in hidden_groups))]
    return result


@input_scope
def projection(source, root=ROOT):
    rows = [[identity, row['property'], row['value'], row.get('comment', '')]
            for identity, row in entries(source, 'desired.row.')]
    from design_layout import GROUPED
    retained = {row[0] for row in selected_rows(rows, root)}
    hidden_resources = {identity for identity, resource in entries(source, 'desired.resource.')
                        if resource['resourceType'] in GROUPED and not any(row.startswith(identity + '-') for row in retained)}
    return {key: value for key, value in source.items() if not (
        key.startswith(('desired.row.', 'observed.row.')) and key.split('.')[2] not in retained) and not (
        key.startswith(('desired.resource.', 'display.resource.')) and key.split('.')[2] in hidden_resources)}


def validate_mappings(source, root=ROOT):
    from aws_mapping import registry
    services = {owners(root).get(resource['resourceType']) for _, resource in entries(source, 'desired.resource.')
                if resource['resourceType'] != 'CloudFormation.Stack'}
    for service in services:
        if service is None:
            raise ValueError('display Mapping resource type missing')
        registry(root, service)


@input_scope
def validation_rows(rows, source, kind, logical_id, root=ROOT):
    """Reinsert only hidden source rows for existing semantic validators."""
    if not source:
        return rows
    validate_mappings(source, root)
    projected = projection(source, root)
    if projected == source:
        return rows
    from collections import defaultdict, deque
    from model_references import resource_rows
    from model_display import catalog_display_rows
    resources = dict(entries(source, 'desired.resource.'))
    targets = [(identity, resource) for identity, resource in resources.items()
               if resource['resourceType'] == kind and resource['logicalId'] == logical_id]
    if not targets:
        return rows
    identity, resource = targets[0]
    targets += [(rid, child) for rid, child in resources.items()
                if child.get('parentReference') == f'[{logical_id}](#{resource["anchor"]})']
    ordered = [row for rid, child in targets
               for row in catalog_display_rows(resource_rows(source, rid, child['resourceType'], root), child['resourceType'], root)]
    positions = defaultdict(deque)
    for number, row in enumerate(ordered):
        positions[row[1]].append(number)
    result = []
    for row in rows:
        result.append((positions[row[1]].popleft() if positions[row[1]] else len(ordered), row))
    for number, row in enumerate(ordered):
        if f'desired.row.{row[0]}.property' not in projected:
            offset = next((i for i, (position, _) in enumerate(result) if position > number), len(result))
            result.insert(offset, (number, row))
    return [[str(number), *row[1:]] for number, (_, row) in enumerate(result, 1)]


@input_scope
def validation_lines(lines, source, root=ROOT):
    """A semantic view for link validation; never returned as generated Markdown."""
    if not source:
        return lines
    validate_mappings(source, root)
    if projection(source, root) == source:
        return lines
    from design_layout import ANCHOR, RESOURCE, HEADER, ALIGNMENT
    resources = {resource['anchor']: resource for _, resource in entries(source, 'desired.resource.')}
    result = []
    resource = None
    anchor = ''
    index = 0
    while index < len(lines):
        line = lines[index]
        if match := ANCHOR.fullmatch(line):
            anchor = match.group(1)
        if RESOURCE.fullmatch(line):
            resource = resources.get(anchor)
        elif line.startswith('#'):
            resource = None
        result.append(line)
        index += 1
        if line != HEADER or resource is None:
            continue
        result.append(ALIGNMENT)
        index += 1
        rows = []
        while index < len(lines) and lines[index].startswith('|'):
            rows.append([cell.strip() for cell in lines[index].strip('|').split('|')])
            index += 1
        result += ['| ' + ' | '.join(row) + ' |' for row in validation_rows(
            rows, source, resource['resourceType'], resource['logicalId'], root)]
    return result
