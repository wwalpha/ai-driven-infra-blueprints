"""Service-specific IMPORT inventory handling."""

from utils.comparison_rows import MISSING


def name_tag(record):
    names = [tag["Value"] for tag in record.get("Tags", []) if tag.get("Key") == "Name"]
    if len(names) > 1:
        raise ValueError("IMPORT inventory has ambiguous Name tags")
    record["NameTag"] = names[0] if names else MISSING


def subnet_associations(record):
    return [
        {
            "kind": "EC2.SubnetRouteTableAssociation",
            "identity": association["RouteTableAssociationId"],
            "getters": {
                "association": {
                    "RouteTableId": record["RouteTableId"],
                    "SubnetId": association["SubnetId"],
                    "Id": association["RouteTableAssociationId"],
                }
            },
        }
        for association in record.get("Associations", [])
        if association.get("SubnetId")
        and association.get("AssociationState", {}).get("State", "associated")
        == "associated"
    ]


def flow_log_getters(seed):
    resource_type = next(
        (
            name
            for prefix, name in [
                ("vpc-", "VPC"),
                ("subnet-", "Subnet"),
                ("eni-", "NetworkInterface"),
            ]
            if seed.get("ResourceId", "").startswith(prefix)
        ),
        None,
    )
    return {"resource_type": {"ResourceType": resource_type}} if resource_type else {}


def attach_subnet_association(association, records):
    payload = association["getters"]["association"]
    subnet = next(
        (
            record
            for record in records
            if record["kind"] == "EC2.Subnet"
            and record["identity"] == payload["SubnetId"]
        ),
        None,
    )
    if subnet is not None:
        if "association" in subnet["getters"]:
            raise ValueError("IMPORT subnet association is ambiguous")
        subnet["getters"]["association"] = payload
