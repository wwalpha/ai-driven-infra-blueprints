"""Change Validation entrypoints; Full Model validation is never called here."""

from functools import partial

from design.catalog import DesignSchemaCatalog
from model.change_scope import change_reads
from model.core import structural_entries as entries
from model.identity import Resolver, display_anchor
from model.reference_values import ProducerValues
from utils.reference_contracts import contract, reference_attribute
from validation.findings import Findings

from model import change_plan, references, validation

BROKEN_REFERENCES = {
    "producer Model is absent",
    "producer Stack is absent",
    "producer Resource is absent or ambiguous",
    "producer Resource Type differs",
    "producer Property is absent or ambiguous",
    "producer Property does not belong to the expected Resource Type",
    "declared producer differs from the saved link; both meanings are retained",
}


def reference_inputs(snapshot, keys):
    """Keep receiving context and only the selected reference-bearing values."""
    values = snapshot.authoritative
    selected_rows = {
        key.split(".")[2] for key in keys if key.startswith("desired.row.")
    }
    selected = {
        key: value
        for key, value in values.items()
        if (
            not key.startswith(("desired.row.", "observed.row.", "desired.reference."))
            and not key.endswith(".parentReference")
            or key.startswith(("desired.row.", "observed.row."))
            and key.split(".")[2] in selected_rows
            or key in keys
        )
    }
    for identity, spec in entries(values, "desired.reference."):
        if spec.get("consumerKey") in keys:
            selected.update(
                (key, value)
                for key, value in values.items()
                if key.startswith(f"desired.reference.{identity}.")
            )
    return snapshot._replace(authoritative=selected)


def check_references(snapshot, keys, reads, findings):
    if not keys:
        return
    selected = reference_inputs(snapshot, keys)
    details = {}
    warnings, _ = references.diagnose(
        selected, reads, errors=findings.errors, details=details
    )
    validate_producer_inputs(
        selected, details, reads, findings, context_values=snapshot.authoritative
    )
    for warning in warnings:
        if warning.get("message") in BROKEN_REFERENCES:
            findings.check(
                False,
                f"invalid candidate reference: {snapshot.scope.path}: {warning['message']}",
            )
        else:
            findings.warn(warning)


def validate_plan(root, plan, scope=None, *, definitions_root=None):
    findings = Findings(root)
    if scope is not None and not plan.services <= scope:
        raise ValueError(
            "changed Model services require Validation scope: "
            + ", ".join("/".join(s) for s in sorted(plan.services - scope))
        )
    models = {
        change.after.scope.path: change.after
        for change in plan.changes.values()
        if change.after is not None
    }
    plan.metadata.setdefault("snapshots", {}).update(models)
    models.update(plan.metadata["snapshots"])
    with change_reads(root, plan.reads, models, metadata=plan.metadata):
        for change in plan.changes.values():
            if change.after is None:
                continue
            changed_resources = {
                logical: (number, resource)
                for logical, (number, resource) in change_plan.resource_map(
                    change.after.authoritative
                ).items()
                if logical in change.resources
            }
            anchors = [
                resource.get("anchor", logical)
                for logical, (_, resource) in change_plan.resource_map(
                    change.after.authoritative
                ).items()
            ]
            for _, resource in changed_resources.values():
                anchor = display_anchor(resource)
                if anchors.count(anchor) != 1:
                    raise ValueError("duplicate Resource anchor: " + anchor)
            result = validation.check_change_inputs(
                change.after.scope.path,
                change.after.authoritative,
                root,
                change,
                definitions_root=definitions_root,
            )
            findings.include_diagnostics(result)
            findings.checks += result.checks
            findings.warnings.extend(result.warnings)
            check_references(change.after, change.reference_keys, plan.reads, findings)
        for snapshot, keys in plan.contracts.values():
            # Incoming references have no permission to validate consumer quality.
            check_references(snapshot, keys, plan.reads, findings)
            selected = reference_inputs(snapshot, keys)
            findings.evaluate(
                "change.incoming-reference",
                {identity_for(snapshot)},
                partial(
                    validation.validate_json_documents,
                    selected.authoritative,
                    snapshot.scope.path,
                    warnings=findings.warnings,
                    reference_values=snapshot.authoritative,
                ),
            )

    return findings


def validate_task(
    root,
    changed=None,
    output=None,
    scope=None,
    *,
    base=None,
    contract_file=None,
    definitions_root=None,
):
    plan = change_plan.task_plan(
        root, changed, output=output, base=base, contract_file=contract_file
    )
    findings = validate_plan(root, plan, scope, definitions_root=definitions_root)
    if findings.errors:
        raise ValueError("\n".join(findings.errors))
    return findings.warnings


def validate_save(before, after, reads):
    # An edit-base intentionally retains old bytes without assuming old validity.
    if before.files and not before.authoritative:
        before = change_plan.comparison_snapshot(before)
    change = change_plan.compare(before if before.files else None, after)
    identity = after.scope.environment, after.scope.target, after.scope.service
    plan = change_plan.ChangePlan(changes={identity: change}, reads=reads)
    plan.metadata["snapshots"] = {after.scope.path: after}
    change_plan.collect_contracts(after.scope.root, plan)
    findings = validate_plan(after.scope.root, plan)
    if findings.errors:
        raise ValueError("\n".join(findings.errors))
    return findings.warnings


def identity_for(snapshot):
    return snapshot.scope.environment, snapshot.scope.target, snapshot.scope.service


def validate_producer_inputs(snapshot, details, reads, findings, *, context_values):
    resolver = Resolver(snapshot.scope.root, reads)
    resolver.catalog = DesignSchemaCatalog(snapshot.scope.root)
    resolver.models.update(details.get("models", {}))
    declarations = references.declarations(snapshot.authoritative)
    checked = set()
    for usage in details.get("usages", ()):
        if (
            usage.producer_kind != "resource"
            or usage.attribute is not None
            or usage.producer_id is None
        ):
            continue
        producer = next(
            (
                model
                for model in resolver.models.values()
                if model is not None
                and "/".join(
                    (model.scope.environment, model.scope.target, model.scope.service)
                )
                == usage.producer_scope
            ),
            None,
        )
        if producer is None:
            continue
        resources = dict(entries(producer.authoritative, "desired.resource."))
        resource = resources.get(usage.producer_id)
        if resource is None:
            continue
        spec = declarations.get(usage.metadata_id, {})
        prop = snapshot.authoritative.get(
            usage.consumer_key.rsplit(".", 1)[0] + ".property", ""
        )
        context = None
        if usage.consumer_key.startswith("desired.row."):
            rid = usage.consumer_key.split(".")[2]
            row = dict(entries(context_values, "desired.row."))[rid]
            context = validation.reference_context_for(
                context_values, rid, row, row.get("value"), "", snapshot.scope.root
            )
        forms = contract(prop, context).get(resource["resourceType"], ())
        if spec.get("property"):
            forms = (spec["property"].split(".", 2)[-1],)
        if len(forms) != 1:
            continue  # A display-only link grants no authority to infer an output attribute.
        attribute = reference_attribute(resource["resourceType"], forms[0])
        key = producer.scope.path, usage.producer_id, attribute
        if key in checked:
            continue
        checked.add(key)
        values = ProducerValues(producer, usage.producer_id, resource, resolver)
        evaluate = (
            partial(values.arn, attribute)
            if attribute == reference_attribute(resource["resourceType"], "Arn")
            else partial(values.value, attribute)
        )
        findings.evaluate("change.producer-attribute", None, evaluate)
