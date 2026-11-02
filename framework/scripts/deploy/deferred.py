"""Retained reference work belongs to the existing Stack progress, not a new run."""

import re

from model.configuration import foreign_observation
from model.core import structural_entries
from model.references import usages
from model.sources import load_model, raw_model
from utils.cloudformation.inputs import Blocked
from utils.iac_values import cfn_resource_identity


def key(record):
    return tuple(record[name] for name in ("producer", "consumer", "consumerKey"))


def producer_owner(path, logical):
    resources = [
        resource
        for _, resource in structural_entries(
            raw_model(path).authoritative, "desired.resource."
        )
        if resource.get("logicalId") == logical
    ]
    if len(resources) != 1:
        raise Blocked("deferred Producer ownership is ambiguous")
    return cfn_resource_identity(resources[0].get("cfn-logicalId", ""))


def verify(root, record, mappings, target):
    consumer = record["consumer"].split("/")
    producer = record["producer"].split("/")
    if (
        len(consumer) != 3
        or len(producer) != 4
        or tuple(consumer[:2]) != target
        or tuple(producer[:2]) != target
    ):
        raise Blocked("deferred reference belongs to another Target")
    if not re.fullmatch(
        r"desired\.row\.[A-Za-z0-9_-]+\.(?:value|document)", record["consumerKey"]
    ):
        raise Blocked("deferred Consumer must identify a reference Row")
    source = root / ("model/" + "/".join(consumer) + ".properties")
    snapshot = raw_model(source)
    matching = [
        usage
        for usage in usages(snapshot)
        if usage.attribute
        and usage.consumer_key == record["consumerKey"]
        and usage.producer_scope == "/".join(producer[:3])
        and usage.logical_id == producer[3]
    ]
    if not matching:
        raise Blocked("deferred reference no longer matches typed Producer/Consumer")
    row = record["consumerKey"].split(".")[2]
    if record["consumerKey"].endswith(".value"):
        if not foreign_observation(snapshot, row):
            raise Blocked(
                "Consumer reference cannot authorize a native physical identifier observation"
            )
    elif f"observed.row.{row}.value" in snapshot.authoritative:
        raise Blocked(
            "document Consumer has a stale observation without a proven reference-value Row; retain it for Model review"
        )
    stack, logical = producer_owner(
        root / ("model/" + "/".join(producer[:3]) + ".properties"), producer[3]
    )
    if record.get("stack", stack) != stack or mappings.get(stack, {}).get(
        logical
    ) != dict(service=producer[2], resource=producer[3]):
        raise Blocked("deferred Producer has no unique fixed Stack ownership")
    return dict(
        record, stack=stack, referenceSynced=bool(record.get("referenceSynced"))
    )


def remember(states, records, loaded):
    for record in records:
        producer = record["producer"].split("/")
        source = next(
            (
                path
                for path in loaded
                if (*path.parent.parts[-2:], path.stem) == tuple(producer[:3])
            ),
            None,
        )
        # The producer is always loaded by the selected Stack mapping.
        if source is None:
            raise Blocked("deferred Producer Model evidence is missing")
        stack, _ = producer_owner(source, producer[3])
        if stack not in states:
            raise Blocked("deferred Producer Stack is outside Deployment scope")
        record = dict(
            record,
            stack=stack,
            ownerObservedSynced=bool(states[stack].get("observedSynced")),
            referenceSynced=False,
        )
        retained = states[stack].setdefault("deferredConsumers", [])
        if not any(key(item) == key(record) for item in retained):
            retained.append(record)


def approved(context):
    return [
        record
        for state in context.get("states", {}).values()
        for record in state.get("deferredConsumers", [])
        if record.get("approved")
    ]


def check_updates(root, path, updates, records):
    snapshot = load_model(path)
    service = "/".join(
        (snapshot.scope.environment, snapshot.scope.target, snapshot.scope.service)
    )
    keys = {
        item["consumerKey"].replace("desired.", "observed.", 1)
        for item in records
        if item["consumer"] == service and item["consumerKey"].endswith(".value")
    }
    if any(
        name not in keys
        or value is not None
        or not foreign_observation(snapshot, name.split(".")[2])
        for name, value in updates.items()
    ):
        raise Blocked(
            "Consumer write must only remove a proven stale reference observation"
        )


def model_saved(context, plan):
    services = set(plan["services"])
    stacks = set(plan["evidence"])
    for state in context["states"].values():
        for record in state.get("deferredConsumers", []):
            if record["stack"] in stacks:
                record["ownerObservedSynced"] = True
                record["referenceSynced"] = False
            if record.get("approved") and record["consumer"].split("/")[-1] in services:
                record["referenceObservedSynced"] = True


def views_saved(context):
    for state in context["states"].values():
        for record in state.get("deferredConsumers", []):
            view = "docs/designs/" + record["consumer"] + ".md"
            if (
                record.get("approved")
                and record.get("referenceObservedSynced")
                and view not in context.get("pendingGeneration", {})
                and not context.get("generationError")
            ):
                record["referenceSynced"] = True
