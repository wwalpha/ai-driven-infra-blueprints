"""Prove omitted services from fixed ownership and retained typed references."""

import base64
import hashlib

import task_contract_core as tasks
import worktree_state as ws
from contracts.model import key_parts, row_resource
from model.format import parse
from model.observed import verify_observed_outputs
from model.render import owned_artifacts
from model.sources import load_model, source_scope
from utils.cloudformation.inputs import Blocked

from deploy import deferred, preparation, scope


def ownership(root, state, context):
    identity = state["deployIdentity"]
    text = state.get("deployContract")
    if not isinstance(text, str) or tasks.task_digest(text) != identity["taskDigest"]:
        raise Blocked("fixed Deploy contract evidence is missing or inconsistent")
    mappings = preparation.owning_resources(
        root,
        identity["environment"],
        context["directory"],
        identity["target"],
        context["stepUnits"],
    )
    task = tasks.read_task_snapshot(root, state["task_file"], live=True)
    records = tasks.section(text, "## Execution scope")
    if not records:
        raise Blocked(
            "legacy Task has no fixed Execution scope; immutable Resource ownership "
            "evidence is missing; retain Task/Snapshot and review the original inputs"
        )
    mapped = {
        stack: {
            logical: (
                root
                / f"model/{identity['environment']}/{context['directory']}/{item['service']}.properties",
                None,
                {"logicalId": item["resource"]},
                None,
                None,
            )
            for logical, item in group.items()
        }
        for stack, group in mappings.items()
    }
    scope.check_fixed_resources(
        root,
        mapped,
        task=tasks.replace(task, text=text),
    )
    return mappings


def additions(root, task, original, candidate, state, context, approved):
    old = tasks.replace(task, text=original).scope or frozenset()
    live = task.scope or frozenset()
    new = tasks.replace(task, text=candidate).scope or frozenset()
    if not old <= live <= new:
        raise Blocked("Validation scope permits only monotone service additions")
    added = new - old
    target = (state["deployIdentity"]["environment"], context["directory"])
    if any(service[:2] != target for service in new):
        raise Blocked("correction cannot add another Target")
    retained = deferred.approved(context)
    if not added and not approved and not retained:
        return []
    mappings = ownership(root, state, context)
    owners = {
        (*target, item["service"])
        for group in mappings.values()
        for item in group.values()
    }
    consumers = added - owners
    requested = {tuple(scope.split("/")) for scope in approved}
    # An already-added consumer must still require approval until the atomic save succeeds.
    if requested != consumers:
        raise Blocked(
            "same-target reference consumers require explicit Human approval for each added service"
        )
    records = []
    for record in retained:
        records.append(deferred.verify(root, record, mappings, target))
    for service in sorted(consumers):
        matches = [
            record
            for item in context["states"].values()
            for record in item.get("deferredConsumers", [])
            if record.get("consumer") == "/".join(service)
        ]
        if not matches:
            raise Blocked(
                "unrelated service has no retained deferred reference: "
                + "/".join(service)
            )
        for record in matches:
            record = deferred.verify(root, record, mappings, target)
            record.setdefault(
                "ownerObservedSynced",
                bool(context["states"][record["stack"]].get("observedSynced")),
            )
            if record not in records:
                records.append(record)
    return records


def output_paths(root, snapshot, consumers=()):
    result = set()
    restricted = {record["consumer"] for record in consumers}
    for environment, directory, service in snapshot.scope or ():
        entry = f"{environment}/{directory}/{service}"
        source = root / f"model/{entry}.properties"
        model = load_model(source)
        if entry in restricted:
            keys = {
                record["consumerKey"]
                for record in consumers
                if record["consumer"] == entry
            }
            result.add(source.relative_to(root).as_posix())
            result.update(
                model.locations[key][0].relative_to(root).as_posix() for key in keys
            )
        else:
            result.update(preparation.model_input_paths(root, [entry]))
        design = root / f"docs/designs/{entry}.md"
        result.update(
            p.relative_to(root).as_posix()
            for p in (design, *owned_artifacts(design, model.values))
        )
    return result


def pending_outputs(root, state, context, consumers, plan=None):
    plan = plan if plan is not None else context.get("pendingObserved")
    if not plan or not plan["outputs"]:
        return
    mappings = ownership(root, state, context)
    owners = {
        (item["service"], item["resource"])
        for group in mappings.values()
        for item in group.values()
    }
    for relative, text in plan["outputs"].items():
        path = root / relative
        snapshot = load_model(source_scope(root, path))
        before = parse(
            base64.b64decode(plan["originals"][relative], validate=True).decode("utf-8")
        ).values
        after = parse(text).values
        updates = {
            key: after.get(key)
            for key in before.keys() | after.keys()
            if before.get(key) != after.get(key)
        }
        foreign = {}
        for key, value in updates.items():
            number = row_resource(key_parts(key)[2])
            logical = snapshot.authoritative.get(f"desired.resource.{number}.logicalId")
            if (snapshot.scope.service, logical) not in owners:
                foreign[key] = value
        deferred.check_updates(root, snapshot.scope.path, foreign, consumers)


def checkpoint_models(root, state, context, before, current, consumers):
    outputs, originals = {}, {}
    for relative, digest in current.items():
        if not relative.startswith("model/") or before.get(relative) == digest:
            continue
        if context.get("modelInputs", {}).get(relative) != digest:
            continue
        raw = ws.subprocess_bytes(root, state["tip"], relative)
        if hashlib.sha256(raw).hexdigest() != before.get(relative):
            raise ValueError(
                "checkpoint original Model bytes are not proven by its Git source: "
                + relative
            )
        path = root / relative
        text = path.read_text(encoding="utf-8")
        verify_observed_outputs({path: raw}, {path: text})
        outputs[relative], originals[relative] = (
            text,
            base64.b64encode(raw).decode("ascii"),
        )
    pending_outputs(
        root, state, context, consumers, dict(outputs=outputs, originals=originals)
    )
    return {relative: current[relative] for relative in outputs}
