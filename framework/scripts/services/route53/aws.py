"""route53: selected properties -> read-only SDK responses; inputs in fetch()."""

from model.adapters.aws import Unresolved, one
from model.importing.sdk_inventory import route53_pages, route53_projection

APIS = {
    ("route53", "list_resource_record_sets"),
    ("route53", "list_hosted_zones"),
    ("route53", "get_hosted_zone"),
}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if r.kind == "Route53.HostedZone":
        current = r.current("Id")
        if not current:
            name = r.value("Name").rstrip(".").lower()
            candidates = [
                v
                for v in ctx.pages("route53", "list_hosted_zones").get(
                    "HostedZones", []
                )
                if v["Name"].rstrip(".").lower() == name
            ]
            # Same DNS name can identify both public and private zones. Preserve VPC association.
            if r.rows_for("VPCs[].VPCId"):
                desired = {r.parse(row, "id") for _, row in r.rows_for("VPCs[].VPCId")}
                candidates = [
                    v
                    for v in candidates
                    if desired
                    == {
                        item["VPCId"]
                        for item in ctx.call(
                            "route53", "get_hosted_zone", Id=v["Id"]
                        ).get("VPCs", [])
                    }
                ]
            current = one(candidates, "route53.list_hosted_zones")["Id"]
        result = ctx.call("route53", "get_hosted_zone", Id=current)
        if getter == "vpcs":
            return result
        return dict(
            result["HostedZone"],
            Id=result["HostedZone"]["Id"].removeprefix("/hostedzone/"),
        )
    zone = r.value("HostedZoneId", "id").removeprefix("/hostedzone/")
    name = r.value("Name").rstrip(".").lower()
    kind = r.value("Type")
    set_identifier = r.optional("SetIdentifier")
    records = route53_pages(ctx, zone)
    candidates = [
        v
        for v in records
        if v["Name"].rstrip(".").lower() == name and v["Type"] == kind
    ]
    if set_identifier is None and any(v.get("SetIdentifier") for v in candidates):
        raise Unresolved("RecordSet SetIdentifier is required for routing records")
    record = one(
        [v for v in candidates if v.get("SetIdentifier") == set_identifier],
        "route53.list_resource_record_sets",
    )
    return route53_projection(record, zone)
