"""route53 IMPORT acquisition."""

import re
from typing import Any

from model.importing.sdk_inventory import identifier, record


def route53_projection(item: dict[str, Any], zone: str) -> dict[str, Any]:
    result = dict(item, HostedZoneId=zone)
    if "TTL" in result:
        if type(result["TTL"]) is not int or result["TTL"] < 0:
            raise ValueError("Invalid Route53 TTL")
        result["TTL"] = str(result["TTL"])
    return result


def route53_pages(ctx: Any, zone: str) -> list[dict[str, Any]]:
    inputs, seen, records = {"HostedZoneId": zone}, set(), []
    while True:
        page = ctx.call("route53", "list_resource_record_sets", **inputs)
        items = page.get("ResourceRecordSets")
        if not isinstance(items, list) or not isinstance(page.get("IsTruncated"), bool):
            raise ValueError("Invalid Route53 record page")
        if any(not isinstance(item, dict) for item in items):
            raise ValueError("Invalid Route53 record")
        records.extend(items)
        if not page["IsTruncated"]:
            return records
        name = identifier(page.get("NextRecordName"))
        kind = identifier(page.get("NextRecordType"))
        continuation = (name, kind, page.get("NextRecordIdentifier"))
        if continuation in seen:
            raise ValueError("Repeated Route53 continuation")
        seen.add(continuation)
        inputs = {
            "HostedZoneId": zone,
            "StartRecordName": name,
            "StartRecordType": kind,
        }
        if continuation[2] is not None:
            inputs["StartRecordIdentifier"] = identifier(continuation[2])


def route53_records(ctx: Any, parents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records, zones = [], set()
    for parent in parents:
        if parent.get("kind") != "Route53.HostedZone":
            raise ValueError("RecordSet requires acquired HostedZone parents")
        zone = identifier(parent.get("cloudProperties", {}).get("Id")).removeprefix(
            "/hostedzone/"
        )
        parent_id = identifier(parent.get("identity")).removeprefix("/hostedzone/")
        if parent_id != zone:
            raise ValueError("HostedZone identity mismatch")
        if not re.fullmatch(r"[A-Za-z0-9]+", zone) or zone in zones:
            raise ValueError("Invalid or duplicate HostedZone identity")
        zones.add(zone)
        for item in route53_pages(ctx, zone):
            name = identifier(item.get("Name")).rstrip(".").lower()
            kind = identifier(item.get("Type"))
            set_id = item.get("SetIdentifier")
            if set_id is not None:
                identifier(set_id)
            values = {
                "HostedZoneId": zone,
                "Name": name,
                "Type": kind,
                "SetIdentifier": set_id,
            }
            records.append(
                record(
                    "Route53.RecordSet",
                    values,
                    {"record": route53_projection(item, zone)},
                    selectors={"HostedZoneId": zone},
                )
            )
    return records


def identity_value(prop: str, value: str) -> str:
    if prop == "Route53.RecordSet.Name":
        return value.rstrip(".").lower()
    if prop == "Route53.RecordSet.HostedZoneId":
        return value.removeprefix("/hostedzone/")
    return value
