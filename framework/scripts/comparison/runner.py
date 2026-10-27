"""Assemble lazy inputs and atomic comparison steps; run() retains its full-scan contract."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TypeAlias

import model.environment_values as environment_values
from design.catalog import DesignSchemaCatalog
from design.layout import resource_mode
from design.layout_schema import GROUPED
from design.services.definitions.registry import HIDDEN_PROPERTIES
from model.core import ReferenceResolutionError
from model.literal_values import value_shape
from model.sources import project_root
from task_contract_core import task_reads
from utils.aws_catalogs import catalog_outputs
from utils.cloudformation.inputs import Blocked, condition_active
from utils.comparison_rows import Unresolved, project, put_row, select
from utils.iac_values import Expression, ResourceReference
from utils.type_contracts import JsonObject, JsonValue

from . import evaluation, registry
from . import resource as resource_rules
from . import rows as row_rules
from .deferral import (
    DesiredPendingDeployExcluded,
    ImportReferenceDeferred,
    failure_category,
)
from .inputs import Inputs
from .methods import compare_values
from .result import RowResult, record, setting_result
from .values import unverified

ComparisonValue: TypeAlias = (
    JsonValue
    | Expression
    | ResourceReference
    | tuple[str, str]
    | list["ComparisonValue"]
    | dict[str, "ComparisonValue"]
)


@dataclass
class Settings:
    desired: dict[str, ComparisonValue] = field(default_factory=dict)
    sources: dict[str, list[JsonObject | None]] = field(default_factory=dict)
    incomplete: dict[str, list[JsonObject]] = field(default_factory=dict)
    exact: set[str] = field(default_factory=set)
    result: RowResult = field(default_factory=RowResult)


class Comparison(Inputs):
    def __init__(
        self,
        root: Path,
        environment: str,
        directory: str,
        services: Iterable[str],
        *,
        catalog: DesignSchemaCatalog | None = None,
    ) -> None:
        super().__init__(root, environment, directory, services, catalog=catalog)
        self.results, self.display_differences = [], {}

    def make_record(
        self,
        category: str,
        service: str,
        identity: str,
        prop: str,
        reason: str,
        desired: ComparisonValue = None,
        actual: ComparisonValue = None,
        stack: str | None = None,
        source: JsonObject | None = None,
        template: JsonObject | None = None,
        cause: JsonObject | None = None,
        **details: JsonValue,
    ) -> JsonObject:
        return record(
            category,
            service,
            identity,
            prop,
            reason,
            desired,
            actual,
            stack,
            source or self.source(service, f"desired.resource.{identity}.resourceType"),
            template,
            cause,
            redact=self.redacted,
            **details,
        )

    def record(self, *args: ComparisonValue, **kwargs: ComparisonValue) -> JsonObject:
        item = self.make_record(*args, **kwargs)
        self.results.append(item)
        return item

    def inactive_record(
        self,
        service: str,
        identity: str,
        prop: str,
        name: str,
        logical: str,
        template: Path,
        definition: JsonObject,
    ) -> JsonObject:
        document, parameters, pseudo = self.stack_inputs[name]
        stack_id, unit = next(
            (stack_id, unit)
            for stack_id, unit in self.templates()
            if unit["name"] == name
        )
        parameter_path, supplied = self.parameter_keys(unit)
        location, cause = resource_rules.inactive_evidence(
            name,
            logical,
            definition,
            document,
            parameters,
            pseudo,
            path=template.relative_to(self.root).as_posix(),
            parameter_path=parameter_path.relative_to(self.root).as_posix(),
            supplied=supplied,
            stack_id=stack_id,
            target=self.target,
            environment=self.environment,
            directory=self.directory,
            marks=self.template_locations.get(id(definition), {}),
            source_lookup=self.source,
            redact=self.redacted,
        )
        return self.make_record(
            "difference",
            service,
            identity,
            prop,
            "CREATE resource is inactive under confirmed parameters",
            stack=name,
            template=location,
            cause=cause,
        )

    def record_inactive(self, *args: str | Path | JsonObject) -> None:
        self.results.append(self.inactive_record(*args))

    def run(self) -> list[JsonObject]:
        with task_reads(project_root(self.root)):
            return self._run()

    def _run(self) -> list[JsonObject]:
        self.local_comparison = True
        self.symbols.clear()
        for service, message in self.reference_unavailable.items():
            self.record(
                "uncompared",
                service,
                "*",
                "*",
                message,
                cause={"kind": "reference-unresolved"},
            )
        for service, error in self.load_errors:
            self.record("error", service, "*", "*", error)
        if self.target["iacEngine"] != "cloudformation":
            for service in self.services:
                self.record(
                    "uncompared",
                    service,
                    "*",
                    "*",
                    "Terraform: no existing local resource correspondence/evaluator; no init/plan/provider calls",
                )
            return self.results
        stacks = dict((unit["name"], unit) for _, unit in self.templates())
        # Load/evaluate only stacks explicitly assigned to selected resources.
        for service in self.services:
            for identity, resource in self.resources[service].items():
                mode = resource_mode(resource)
                if mode == "IMPORT":
                    self.record(
                        "excluded",
                        service,
                        identity,
                        "*",
                        "IMPORT is outside IaC generation",
                    )
                    continue
                try:
                    kind = resource.get("resourceType")
                    if not isinstance(kind, str) or not kind:
                        raise ValueError("resourceType is missing or malformed")
                    if kind in self.catalog.api_schemas:
                        self.record(
                            "uncompared",
                            service,
                            identity,
                            "*",
                            "CloudFormation unsupported; outside CFn comparison; API implementation status unverified",
                            cause={
                                "kind": "cloudformation-unsupported",
                                "resource_type": kind,
                                "implementation_status": "unverified",
                            },
                        )
                        continue
                    if (
                        self.catalog.canonical_type(kind)
                        not in self.catalog.resource_types
                    ):
                        raise ValueError(f"unknown resource type: {kind}")
                    cfn_type = self.catalog.cloudformation_type(kind)
                    name, logical, unit = resource_rules.correspondence(
                        resource, stacks
                    )
                    template = (
                        self.root
                        / "infra/cloudformation/templates"
                        / self.target.get("alias", "")
                        / unit["template"]
                    )
                    self.inputs.add(template)
                    if not template.is_file():
                        self.record(
                            "difference",
                            service,
                            identity,
                            "*",
                            "モデルに対応するtemplateが存在しない（CREATE未実装）",
                            desired={"resourceType": kind, "logical": logical},
                            stack=name,
                            template={
                                "path": template.relative_to(self.root).as_posix()
                            },
                            cause={
                                "kind": "template-missing",
                                "path": template.relative_to(self.root).as_posix(),
                                "stack": name,
                                "relationship": "direct",
                            },
                        )
                        continue
                    template, (document, parameters, pseudo) = self.stack(unit)
                    definition = document.get("Resources", {}).get(logical)
                    # Explicit identity is authoritative even if the template resource is missing.
                    direct = self.index()
                    if len(direct.get((name, logical), [])) != 1:
                        raise Blocked(
                            f"duplicate resource correspondence: {name}/{logical}"
                        )
                    if document.get("Transform"):
                        raise Blocked("Transform requires external evaluation")
                    if definition is None:
                        self.record(
                            "difference",
                            service,
                            identity,
                            "*",
                            "resource missing",
                            desired={"resourceType": kind, "logical": logical},
                            stack=name,
                            template={
                                "path": template.relative_to(self.root).as_posix()
                            },
                        )
                        continue
                    if definition.get("Type") != cfn_type:
                        raise Blocked(
                            f"formal resource type mismatch: {definition.get('Type')} != {cfn_type}"
                        )
                    if not condition_active(document, parameters, pseudo, definition):
                        self.record_inactive(
                            service, identity, "*", name, logical, template, definition
                        )
                        continue
                    batch = self.compare_rows(
                        service,
                        identity,
                        resource,
                        name,
                        logical,
                        template,
                        definition,
                        document,
                    )
                    self.results.extend(batch.records)
                    self.warnings.extend(batch.warnings)
                    self.display_differences.update(batch.display_differences)
                    if batch.failure is not None:
                        raise batch.failure
                except (Blocked, KeyError) as error:
                    self.record(
                        failure_category(error),
                        service,
                        identity,
                        "*",
                        str(error),
                        cause=getattr(error, "iac_cause", None),
                    )
                except ReferenceResolutionError as error:
                    self.warnings.append(
                        {**error.diagnostic, "service": service, "resource": identity}
                    )
                    self.record(
                        "uncompared",
                        service,
                        identity,
                        "*",
                        str(error),
                        cause={"kind": "reference-unresolved"},
                    )
                except (OSError, ValueError, ImportError, TypeError) as error:
                    self.record("error", service, identity, "*", str(error))
        return self.results

    def compare_rows(
        self,
        service: str,
        identity: str,
        resource: dict[str, str],
        name: str,
        logical: str,
        template: Path,
        definition: JsonObject,
        document: JsonObject,
        *,
        properties: set[str] | None = None,
    ) -> RowResult:
        result = RowResult()
        grouped = row_rules.grouped_rows(resource, self.rows[service][identity])
        for rowkind, rows in grouped.items():
            batch = self.compare_group(
                service,
                identity,
                resource["resourceType"],
                rowkind,
                rows,
                name,
                logical,
                template,
                definition,
                document,
                properties=properties,
            )
            result.records.extend(batch.records)
            result.warnings.extend(batch.warnings)
            result.display_differences.update(batch.display_differences)
            if batch.failure is not None:
                result.failure = batch.failure
                break
        return result

    def compare_group(
        self,
        service: str,
        identity: str,
        kind: str,
        rowkind: str,
        rows: list[tuple[str, dict[str, str]]],
        name: str,
        logical: str,
        template: Path,
        definition: JsonObject,
        document: JsonObject,
        *,
        properties: set[str] | None = None,
    ) -> RowResult:
        result = RowResult()
        try:
            if properties is not None:
                context_properties = registry.resource(rowkind).context_properties
                required = set(properties).union(
                    *(context_properties.get(prop, set()) for prop in properties)
                )
                rows = row_rules.selected_rows(rowkind, rows, required)
                if not rows:
                    return result
            prepare = registry.resource(rowkind).prepare_rows
            if prepare:
                try:
                    rows = self.project_rows(rowkind, rows)
                except Unresolved as error:
                    deferred = registry.resource(rowkind).deferred_rows
                    if not deferred:
                        raise
                    result.records.append(
                        self.make_record(
                            "uncompared",
                            service,
                            identity,
                            rowkind + "." + deferred,
                            str(error),
                            stack=name,
                            source=self.source(
                                service, f"desired.row.{rows[0][0]}.property"
                            ),
                        )
                    )
                    rows = [
                        (rid, row)
                        for rid, row in rows
                        if not row["property"].startswith(rowkind + "." + deferred)
                    ]
            rows, unresolved = row_rules.validated_rows(rowkind, rows)
            for setting, (rid, reason) in unresolved.items():
                if properties is None or any(
                    setting == prop or setting.startswith((prop + ".", prop + "["))
                    for prop in properties
                ):
                    result.records.append(
                        self.make_record(
                            "uncompared",
                            service,
                            identity,
                            rowkind + "." + setting,
                            reason,
                            stack=name,
                            source=self.source(service, f"desired.row.{rid}.property"),
                        )
                    )
            contexts = registry.resource(rowkind).contexts
            contexts = contexts(rows) if self.local_comparison and contexts else {}
            if properties is not None:
                rows = row_rules.selected_rows(rowkind, rows, properties)
            _, parameters, pseudo = self.stack_inputs[name]
            rule = GROUPED.get(rowkind)
            childtype = (
                self.catalog.cloudformation_type(rowkind)
                if rowkind != kind
                and rule
                and rule["parent"] == kind
                and rule["identityProperty"] is None
                else None
            )
            owner, failure = resource_rules.inline_owner(
                kind,
                rowkind,
                logical,
                definition,
                document,
                parameters,
                pseudo,
                childtype,
            )
            if failure:
                category, reason = failure
                if category == "difference":
                    item = self.make_record(
                        category,
                        service,
                        identity,
                        rowkind,
                        reason,
                        desired={"resourceType": rowkind},
                        stack=name,
                        source=self.source(
                            service, f"desired.row.{rows[0][0]}.property"
                        ),
                        template={"path": template.relative_to(self.root).as_posix()},
                    )
                else:
                    item = self.make_record(
                        category, service, identity, rowkind, reason
                    )
                result.records.append(item)
                return result
            if rowkind != kind and not condition_active(
                document, parameters, pseudo, owner
            ):
                child_logical = next(
                    key
                    for key, child in document["Resources"].items()
                    if child is owner
                )
                result.records.append(
                    self.inactive_record(
                        service, identity, rowkind, name, child_logical, template, owner
                    )
                )
                return result
            settings = self.prepare_settings(
                service, identity, rowkind, rows, contexts, name, owner, template
            )
            result.records.extend(settings.result.records)
            result.warnings.extend(settings.result.warnings)
            if settings.result.failure is not None:
                result.failure = settings.result.failure
                return result
            for key, value in settings.desired.items():
                batch = self.compare_setting(
                    service,
                    identity,
                    rowkind,
                    key,
                    value,
                    settings,
                    name,
                    owner,
                    template,
                )
                result.records.extend(batch.records)
                result.warnings.extend(batch.warnings)
                result.display_differences.update(batch.display_differences)
            return result

        except (
            Blocked,
            KeyError,
            OSError,
            ValueError,
            ImportError,
            TypeError,
        ) as error:
            result.failure = error
            return result

    def prepare_settings(
        self,
        service: str,
        identity: str,
        kind: str,
        rows: list[tuple[str, dict[str, str]]],
        contexts: dict[str, JsonObject],
        name: str,
        owner: JsonObject,
        template: Path,
    ) -> Settings:
        settings = Settings()
        contexts = dict(
            contexts,
            **environment_values.row_contexts(
                kind, rows, environment_values.mapping_for(self.root, kind)
            ),
        )
        try:
            outputs = catalog_outputs(self.root, kind) | HIDDEN_PROPERTIES
            for rid, row in rows:
                prop = row["property"]
                short = prop.removeprefix(kind + ".")
                source = self.source(
                    service,
                    f"desired.resource.{identity}.parentReference"
                    if rid == "@parent"
                    else f"desired.row.{rid}.document"
                    if "document" in row
                    else f"desired.row.{rid}.value",
                )
                if prop in outputs or short in registry.resource(kind).design_only:
                    settings.result.records.append(
                        self.make_record(
                            "excluded",
                            service,
                            identity,
                            prop,
                            "identifier output/design-only metadata",
                            source=source,
                        )
                    )
                    continue
                tagged = row_rules.name_tag(
                    kind,
                    short,
                    row["value"],
                    {kind} if registry.resource(kind).name_tag else set(),
                )
                if tagged:
                    short, value = tagged
                else:
                    try:
                        parent = re.split(
                            r"\.(?:Configuration|Values)(?:\[|\.|$)", short
                        )[0]
                        prepared = self.prepare_value(
                            service,
                            row,
                            kind,
                            row_id=rid,
                            stack=name,
                            context=contexts.get(rid, contexts.get(parent)),
                        )
                        settings.result.warnings.extend(prepared.warnings)
                        for path, pointer, error in prepared.failures:
                            self.incomplete_value(
                                settings,
                                service,
                                identity,
                                kind,
                                kind + "." + path,
                                error,
                                dict(source or {}, pointer=pointer),
                                name,
                                owner,
                                template,
                            )
                        if prepared.error is not None:
                            raise prepared.error
                        value = prepared.value
                    except (
                        Blocked,
                        KeyError,
                        OSError,
                        ValueError,
                        ImportError,
                        TypeError,
                        IndexError,
                    ) as error:
                        self.incomplete_value(
                            settings,
                            service,
                            identity,
                            kind,
                            prop,
                            error,
                            source,
                            name,
                            owner,
                            template,
                        )
                        if isinstance(error, DesiredPendingDeployExcluded):
                            continue
                        value = Expression("Unverified", [])
                if "." not in short and not short.endswith("[]"):
                    settings.exact.add(short)
                if value_shape(row) == "projection":
                    project(settings.desired, short, value)
                else:
                    put_row(settings.desired, short, value)
                settings.sources.setdefault(
                    re.sub(r"\[\d*\]", "", short.split(".", 1)[0]), []
                ).append(source)
            return settings

        except (
            Blocked,
            KeyError,
            OSError,
            ValueError,
            ImportError,
            TypeError,
        ) as error:
            settings.result.failure = error
            return settings

    def incomplete_value(
        self,
        settings: Settings,
        service: str,
        identity: str,
        kind: str,
        prop: str,
        error: Exception,
        source: JsonObject | None,
        name: str,
        owner: JsonObject,
        template: Path,
    ) -> None:
        details = dict(
            stack=name, template={"path": template.relative_to(self.root).as_posix()}
        )
        category = failure_category(error)
        if hasattr(error, "reference_detail"):
            symbol, field = error.reference_detail
            try:
                actual = self.evaluate(name, select(owner.get("Properties", {}), field))
                reason = "Model attribute is outside allowed property forms; comparison remains deferred"
            except (
                Blocked,
                KeyError,
                ValueError,
                TypeError,
                IndexError,
            ) as actual_error:
                actual = {"unresolved": self.redacted(str(actual_error))}
                reason = "Model attribute is outside allowed property forms; IaC reference evaluation also failed"
            details["reference_diagnostics"] = [
                self.reference_diagnostic(symbol, actual, kind, field, reason)
            ]
        item = self.make_record(
            category,
            service,
            identity,
            prop,
            str(error),
            source=source,
            cause=getattr(error, "iac_cause", None),
            **details,
        )
        settings.result.records.append(item)
        if isinstance(error, DesiredPendingDeployExcluded) and not (source or {}).get(
            "pointer"
        ):
            return
        key = re.sub(r"\[\d*\]", "", prop.removeprefix(kind + ".").split(".", 1)[0])
        settings.incomplete.setdefault(key, []).append(self.redacted(item))

    def compare_setting(
        self,
        service: str,
        identity: str,
        kind: str,
        key: str,
        value: ComparisonValue,
        settings: Settings,
        name: str,
        owner: JsonObject,
        template: Path,
    ) -> RowResult:
        prop = kind + "." + key
        sources = settings.sources[key]
        iac_source = {"path": template.relative_to(self.root).as_posix()}
        marks = self.template_locations.get(id(owner.get("Properties", {})), {})
        if line := marks.get(key, self.template_locations.get(id(owner), {}).get(None)):
            iac_source["line"] = line
        actual = owner.get("Properties", {}).get(key)
        rule = registry.require(kind, key)
        actual_provider = rule.actual if self.local_comparison else None
        missing = (
            "property missing"
            if key not in owner.get("Properties", {}) and not actual_provider
            else None
        )
        warnings, actual_error = [], None
        failures = []
        raw_actual = actual
        try:
            if actual_provider:
                actual = actual_provider(self, service, identity, name, owner, key)
            elif not missing:
                if self.local_comparison:
                    prepared = evaluation.project_actual(
                        actual,
                        evaluate=lambda child: self.evaluate(name, child),
                        property_name=prop,
                        model_path=template,
                        desired=value,
                        exact=key in settings.exact,
                        rules=registry.rules(kind),
                        rule_path=key,
                    )
                    warnings.extend(prepared.warnings)
                    actual = prepared.value
                    for _path, pointer, error in prepared.failures:
                        if isinstance(error, (Blocked, KeyError)) and not isinstance(
                            error, ImportReferenceDeferred
                        ):
                            actual_error = actual_error or error
                            continue
                        location = dict(iac_source, pointer=pointer)
                        node = raw_actual
                        for token in pointer.lstrip("/").split("/") if pointer else []:
                            token = token.replace("~1", "/").replace("~0", "~")
                            key_or_index = (
                                int(token) if isinstance(node, list) else token
                            )
                            if line := self.template_locations.get(id(node), {}).get(
                                key_or_index
                            ):
                                location["line"] = line
                            node = node[key_or_index]
                        failures.append(
                            self.make_record(
                                failure_category(error),
                                service,
                                identity,
                                prop + ("#" + pointer if pointer else ""),
                                str(error),
                                source=sources[0],
                                stack=name,
                                template=location,
                                cause=getattr(error, "iac_cause", None),
                            )
                        )
                else:
                    actual = self.evaluate(name, actual)
        except (Blocked, KeyError, ValueError, TypeError, IndexError) as error:
            category = failure_category(error)
            return RowResult(
                [
                    self.make_record(
                        category,
                        service,
                        identity,
                        prop,
                        str(error),
                        source=sources[0],
                        template=iac_source,
                        cause=getattr(error, "iac_cause", None),
                    )
                ],
                warnings,
            )
        try:
            actual = environment_values.project(
                kind,
                prop,
                actual,
                environment_values.mapping_for(self.root, kind),
                environment_values.identity,
            )
        except (ValueError, TypeError) as error:
            return RowResult(
                [
                    self.make_record(
                        "error",
                        service,
                        identity,
                        prop,
                        str(error),
                        source=sources[0],
                        template=iac_source,
                    )
                ],
                warnings,
            )
        if actual == {"$noValue": True}:
            missing = "property omitted by AWS::NoValue"
        reference = (
            (lambda a, b, path: self.reference_decision(a, b, kind, path))
            if self.local_comparison
            else None
        )
        decision = compare_values(
            value,
            actual,
            key,
            rules=registry.rules(kind),
            whole=key in settings.exact,
            reference=reference,
            local=self.local_comparison,
            missing=bool(missing),
        )
        if actual_error is not None and decision.equal is True:
            decision = replace(decision, equal=None, differences=())
        if failures and decision.equal is not False:
            if (
                actual_error is None
                and not decision.diagnostics
                and not list(unverified(value))
            ):
                return RowResult(failures, warnings)
            decision = replace(decision, equal=None, differences=())
        if key in settings.incomplete and decision.equal is True:
            return RowResult(warnings=warnings)
        if (
            key in settings.incomplete
            and decision.equal is None
            and actual_error is None
            and not decision.diagnostics
            and not list(unverified(value))
            and not list(unverified(actual))
        ):
            return RowResult(warnings=warnings)
        batch = setting_result(
            service,
            identity,
            prop,
            value,
            actual,
            decision,
            name,
            sources,
            iac_source,
            actual_error=actual_error,
            redact=self.redacted,
            default_source=self.source(
                service, f"desired.resource.{identity}.resourceType"
            ),
            missing=missing,
            deferred_children=[
                item
                for item in settings.incomplete.get(key, [])
                if item["category"] not in {"deferred", "excluded"}
            ],
        )
        batch.records.extend(failures)
        batch.warnings.extend(warnings)
        return batch
