"""vpc: selected properties -> read-only SDK responses; inputs in fetch()."""

from model.adapters.aws import AcquisitionError, MISSING, Field, Unresolved, one

APIS = {
    ("ec2", "describe_vpc_attribute"),
    ("ec2", "describe_subnets"),
    ("ec2", "describe_flow_logs"),
    ("ec2", "describe_route_tables"),
    ("ec2", "describe_vpcs"),
}

MODEL_FIELDS = {
    kind + ".Name": Field("base", "NameTag", default=MISSING)
    for kind in ("EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog")
}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if getter in {"hostnames", "support"}:
        return ctx.call(
            "ec2",
            "describe_vpc_attribute",
            VpcId=r.identity(),
            Attribute="enableDnsHostnames"
            if getter == "hostnames"
            else "enableDnsSupport",
        )
    if getter == "association":
        records = ctx.pages(
            "ec2",
            "describe_route_tables",
            Filters=[{"Name": "association.subnet-id", "Values": [r.identity()]}],
        ).get("RouteTables", [])
        record = one(
            [
                v
                for v in records
                if any(
                    a.get("SubnetId") == r.identity()
                    and a.get("AssociationState", {}).get("State", "associated")
                    == "associated"
                    for a in v.get("Associations", [])
                )
            ],
            "ec2.describe_route_tables",
        )
        return {"RouteTableId": record["RouteTableId"]}
    operations = {
        "EC2.VPC": ("describe_vpcs", "Vpcs", "VpcId", "VpcIds"),
        "EC2.Subnet": ("describe_subnets", "Subnets", "SubnetId", "SubnetIds"),
        "EC2.RouteTable": (
            "describe_route_tables",
            "RouteTables",
            "RouteTableId",
            "RouteTableIds",
        ),
        "EC2.FlowLog": ("describe_flow_logs", "FlowLogs", "Id", "FlowLogIds"),
    }
    op, collection, prop, argument = operations[r.kind]
    current = r.current(prop)
    if current:
        inputs = {argument: [current]}
    elif r.kind == "EC2.FlowLog":
        try:
            resource_id = r.value("ResourceId", "id")
        except AcquisitionError as error:
            if error.status == "resource_missing":
                raise Unresolved("Flow Log ResourceId could not be resolved") from error
            raise
        if not isinstance(resource_id, str) or not resource_id.startswith(
            ("vpc-", "subnet-", "eni-")
        ) or resource_id.endswith("-"):
            raise Unresolved("Flow Log ResourceId is unresolved")
        inputs = {"Filter": [{"Name": "resource-id", "Values": [resource_id]}]}
    else:
        inputs = {"Filters": [{"Name": "tag:Name", "Values": [r.value("Name")]}]}
        if r.kind != "EC2.VPC" and r.rows_for("VpcId"):
            inputs["Filters"].append(
                {"Name": "vpc-id", "Values": [r.value("VpcId", "id")]}
            )
    response = ctx.pages("ec2", op, **inputs)
    if r.kind == "EC2.FlowLog" and not isinstance(response.get(collection), list):
        raise Unresolved("Flow Log response lacks a complete collection")
    records = response.get(collection, [])
    if r.kind == "EC2.FlowLog" and not current and len(records) > 1:
        for prop in ("LogDestinationType", "LogDestination", "LogGroupName"):
            if r.rows_for(prop):
                value = r.value(prop)
                matches = [record for record in records if record.get(prop) == value]
                if not matches:
                    raise Unresolved("resource selector is ambiguous")
                records = matches
        if len(records) != 1:
            raise Unresolved("resource selector is ambiguous")
    record = dict(one(records, "ec2." + op))
    record["NameTag"] = (
        one(
            [v["Value"] for v in record.get("Tags", []) if v["Key"] == "Name"],
            "ec2." + op,
        )
        if any(v["Key"] == "Name" for v in record.get("Tags", []))
        else MISSING
    )
    if getter == "resource_type":
        # ResourceId is returned by DescribeFlowLogs. Prefix is AWS's typed ID grammar.
        rid = record["ResourceId"]
        kind = next(
            (
                value
                for prefix, value in [
                    ("vpc-", "VPC"),
                    ("subnet-", "Subnet"),
                    ("eni-", "NetworkInterface"),
                ]
                if rid.startswith(prefix)
            ),
            None,
        )
        if not kind:
            raise Unresolved("unknown SDK-confirmed flow log resource type")
        return {"ResourceType": kind}
    return record
