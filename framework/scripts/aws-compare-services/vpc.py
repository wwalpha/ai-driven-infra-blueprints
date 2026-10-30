"""vpc: selected properties -> read-only SDK responses; inputs in fetch()."""

from model.adapters.aws import MISSING, Field, Unresolved, one

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
    else:
        inputs = {"Filters": [{"Name": "tag:Name", "Values": [r.value("Name")]}]}
        if r.kind == "EC2.FlowLog":
            inputs["Filters"].append(
                {"Name": "resource-id", "Values": [r.value("ResourceId", "id")]}
            )
            inputs["Filter"] = inputs.pop("Filters")
        elif r.kind != "EC2.VPC" and r.rows_for("VpcId"):
            inputs["Filters"].append(
                {"Name": "vpc-id", "Values": [r.value("VpcId", "id")]}
            )
    record = dict(one(ctx.pages("ec2", op, **inputs).get(collection, []), "ec2." + op))
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
