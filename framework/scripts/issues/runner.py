import io
import json
import os
import re
import time
import uuid
from contextlib import contextmanager, redirect_stdout
from functools import partial

from model.core import ReferenceResolutionError, entries
from model.validation import codebuild_reference_errors
from task_contract_core import task_read_scope
from utils.input_cache import input_scope
from utils.reference_contracts import reference_error
from utils.script_loader import module
from validation.findings import Findings

import issues.artifact as _imports_issues_artifact
import issues.cfn_lint as _imports_issues_cfn_lint

from .aggregate import aggregate
from .inputs import Comparison, view_text
from .integrity import selected_scope, target_services
from .materials import naming_materials
from .records import identifier, safe_text
from .review import human_confirmations


@task_read_scope
def mechanical(
    root,
    scope,
    *,
    fresh=False,
    jobs=4,
    catalog=None,
    warnings=None,
    validator_out=None,
    view_errors=None,
    view_reader=None,
):
    """Run service diagnostics without PASS caches, contract/deploy or full-loop checks."""
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    validator_module = module("validate-blueprint.py", "issues_validator")
    validator = validator_module.Validator(root, scope, fresh=fresh, workers=jobs)
    validator.schema_catalog = catalog
    if validator_out is not None:
        validator_out.append(validator)
    output = io.StringIO()
    with redirect_stdout(output):
        for check_id, handler in (
            ("mechanical.topology", validator.check_project_topology),
            ("mechanical.scope", validator.check_validation_scope),
            ("mechanical.models", validator.check_model_files),
            (
                "mechanical.designs",
                partial(
                    validator.check_scoped_designs,
                    view_errors=view_errors,
                    view_reader=view_reader,
                ),
            ),
            ("mechanical.iac-selection", validator.check_iac_selection),
        ):
            validator.findings.evaluate(check_id, scope, handler, isolate=True)
    if warnings is not None:
        warnings.extend(validator.warnings)
    return validator.errors, validator.checks, output.getvalue()


@contextmanager
def scan_stage(findings, phase, scope):
    try:
        yield
    except Exception as error:
        findings.processing_failure(phase, scope, error)


def review_materials(comparison, service):
    doc = (
        comparison.root
        / "docs/designs"
        / comparison.environment
        / comparison.directory
        / (service + ".md")
    )
    if not doc.is_file() or doc in comparison.view_errors:
        return []
    text = view_text(comparison, doc, phase="review-prose")
    if text is None:
        return []
    # Only notes/implementation prose remains; verified tables are not repeated.
    known_notes = (
        {
            value
            for key, value in comparison.models[service].values.items()
            if key.startswith("desired.note.")
        }
        if service in comparison.models
        else set()
    )
    return [
        safe_text(line)
        for line in text.splitlines()
        if line.strip()
        and not line.startswith(("#", "|", "<", "- Design", "- Owned", "```"))
        and line.removeprefix("- ").strip() not in known_notes
    ]


def codebuild_plaintext_diagnostics(message, comparison):
    """Identify only this policy across its Model and saved-View error wrappers."""
    reason = reference_error(
        "CodeBuild.Project.Environment.EnvironmentVariables[].Value",
        {"Type": "PLAINTEXT"},
    )
    pattern = re.compile(
        r"(?:Model=.+?, Resource=.+? \([^)]+\), |"
        r"Resource=CodeBuild\.Project#[^:]+: )"
        r"Name=.+?, Type=PLAINTEXT, "
        r"Property=CodeBuild\.Project\.Environment\.EnvironmentVariables\[\d*\]\.Value: "
        + re.escape(reason)
        + r"$"
    )
    if not any(pattern.search(line) for line in message.splitlines()):
        return [message]
    result = []
    for line in message.splitlines():
        match = pattern.search(line)
        if match is None:
            result.append(line)
            continue
        diagnostic = match[0]
        if diagnostic.startswith("Resource="):
            view = f"docs/designs/{comparison.environment}/{comparison.directory}/codebuild.md"
            if view not in message:
                result.append(line)
                continue
            fallback = f"{view}: {diagnostic}"
            try:
                model = comparison.model("codebuild")
            except (OSError, ValueError, KeyError, TypeError):
                result.append(fallback)
                continue
            anchor, detail = diagnostic.removeprefix(
                "Resource=CodeBuild.Project#"
            ).split(": ", 1)
            resources = [
                (identity, resource)
                for identity, resource in entries(model.values, "desired.resource.")
                if resource["resourceType"] == "CodeBuild.Project"
                and resource.get("anchor") == anchor
            ]
            if len(resources) != 1:
                result.append(fallback)
                continue
            identity, resource = resources[0]
            path = (
                comparison.root
                / "model"
                / comparison.environment
                / comparison.directory
                / "codebuild.properties"
            )
            diagnostic = (
                f"Model={path}, Resource={resource['logicalId']} ({identity}), {detail}"
            )
            diagnostic = next(
                (
                    error
                    for error in codebuild_reference_errors(path, model.values).values()
                    if re.sub(r"\[\d+\]", "[]", error) == diagnostic
                ),
                diagnostic,
            )
        result.append(diagnostic)
    return result


def reference_issues(findings, comparison, services):
    """Use the existing stable identifier on Model position/code, independent of prose."""
    records = {}
    for diagnostic in findings.reference_errors:
        if diagnostic["category"] != "MODEL_NEEDS_FIX":
            continue
        fix_models = diagnostic.get("fixModels", ())
        if not fix_models and (
            diagnostic["code"] == "MODEL_REF_INVALID_SYNTAX"
            or diagnostic["code"] == "MODEL_REF_TARGET_AMBIGUOUS"
            and diagnostic.get("modelKey", "").startswith("desired.resource.")
        ):
            fix_models = [diagnostic.get("model")]
        identity = [
            diagnostic.get(field)
            for field in (
                "code",
                "model",
                "resourceLogicalId",
                "modelKey",
                "pointer",
                "targetLogicalId",
                "attribute",
            )
        ]
        for model in fix_models:
            owner = next(
                (
                    service
                    for service in services
                    if model and model.endswith("/" + service + ".properties")
                ),
                None,
            )
            if owner is None:
                continue
            key = identifier(
                [
                    value.replace(str(comparison.root) + "/", "")
                    if isinstance(value, str)
                    else value
                    for value in [model, *identity]
                ]
            )
            records[key] = dict(
                id=key,
                key=key,
                service=owner,
                severity="ERROR",
                message=safe_text(
                    comparison.redacted(json.dumps(diagnostic, ensure_ascii=False))
                ),
                diagnostic=comparison.redacted(diagnostic),
                resource=(
                    match[1]
                    if model == diagnostic.get("model")
                    and (
                        match := re.fullmatch(
                            r"desired\.(?:row|resource)\.(\d+)(?:-\d+)?\.[^.]+",
                            diagnostic.get("modelKey", ""),
                        )
                    )
                    else None
                ),
                property=diagnostic.get("property")
                if model == diagnostic.get("model")
                else None,
                rule=diagnostic["code"],
            )
    return list(records.values())


@input_scope
def scan(root, environment, directory, services, *, fresh=False, jobs=4):
    started = time.perf_counter()
    scope = selected_scope(environment, directory, services)
    scan_id = uuid.uuid4().hex
    all_services = target_services(root, environment, directory)
    human = human_confirmations(root, environment, directory)
    comparison = Comparison(root, environment, directory, services)
    stages = Findings(root)
    for service in services:
        doc = root / "docs/designs" / environment / directory / (service + ".md")
        with scan_stage(stages, "view-preflight", {(environment, directory, service)}):
            view_text(comparison, doc, phase="view-preflight")
    warnings = list(comparison.warnings)
    begin = time.perf_counter()
    validators = []
    try:
        errors, _, diagnostics = mechanical(
            root,
            scope,
            fresh=fresh,
            jobs=jobs,
            catalog=comparison.catalog,
            warnings=warnings,
            validator_out=validators,
            view_errors=comparison.view_errors,
            view_reader=partial(view_text, comparison),
        )
    except Exception as error:
        if not validators:
            validators.append(
                module("validate-blueprint.py", "issues_validator").Validator(
                    root, scope
                )
            )
        validator = validators[0]
        validator.findings.processing_failure("mechanical", scope, error)
        errors, diagnostics = validator.errors, ""
        warnings.extend(validator.warnings)
    mechanical_seconds = time.perf_counter() - begin
    ordinary, judgments = [], []
    validator = validators[0]
    ordinary.extend(reference_issues(validator.findings, comparison, all_services))
    reference_messages = {
        json.dumps(d, ensure_ascii=False) for d in validator.findings.reference_errors
    }
    seen = set()
    diagnostic_messages = [
        (message, diagnostic)
        for message in dict.fromkeys(errors)
        if message not in reference_messages
        for diagnostic in codebuild_plaintext_diagnostics(message, comparison)
    ]
    for message, diagnostic in diagnostic_messages:
        if any(
            message == item["message"] for item in validator.findings.processing_errors
        ):
            continue
        found = [
            service
            for service in services
            if re.search(
                r"/" + re.escape(service) + r"(?:\.md|\.properties|/)", diagnostic
            )
        ]
        owner = (
            found[0] if len(found) == 1 else services[0] if len(services) == 1 else None
        )
        # Model diagnostics retain their identity across View error context wrappers.
        diagnostic = re.sub(r"^[^\n]*?: (?=Model=)", "", diagnostic)
        key = identifier(diagnostic)
        if key in seen:
            continue
        seen.add(key)
        candidate = {
            "id": key,
            "service": owner,
            "message": safe_text(comparison.redacted(diagnostic)),
            "key": key,
        }
        (ordinary if owner else judgments).append(candidate)
    naming = {"names": [], "rules": {}}
    for service in sorted(set(services)):
        with scan_stage(
            stages, "materials.naming", {(environment, directory, service)}
        ):
            material, naming_judgments = naming_materials(comparison, service=service)
            naming["names"].extend(material["names"])
            naming["rules"].update(material.get("rules", {}))
            naming.update(
                (key, value)
                for key, value in material.items()
                if key not in {"names", "rules"}
            )
            judgments.extend(naming_judgments)
    for service in services:
        with scan_stage(
            stages, "materials.review-prose", {(environment, directory, service)}
        ):
            notes = review_materials(comparison, service)
            if notes:
                judgments.append(
                    {
                        "id": identifier([service, "design-notes"]),
                        "service": service,
                        "kind": "nonmechanical-design-prose",
                        "materials": notes,
                    }
                )
    begin = time.perf_counter()
    comparison_failure = None
    try:
        iac = comparison.run()
    except ReferenceResolutionError as error:
        comparison_failure = error
        warnings.append(comparison.redacted(error.diagnostic))
        iac = list(comparison.results) + [
            {
                "category": "uncompared",
                "service": service,
                "resource": "*",
                "property": "*",
                "reason": safe_text(comparison.redacted(str(error))),
                "comparison_incomplete": True,
                "cause": {"kind": "reference-unresolved"},
            }
            for service in services
        ]
    except Exception as error:
        comparison_failure = error
        iac = list(comparison.results) + [
            {
                "category": "error",
                "service": service,
                "resource": "*",
                "property": "*",
                "reason": safe_text(comparison.redacted(str(error))),
                "comparison_incomplete": True,
            }
            for service in services
        ]
    if comparison_failure is not None:
        result = validator.findings.result("iac.comparison", scope)
        result.metadata = dict(complete=False, reason="comparison-interrupted")
        validator.findings.unverified.append(
            dict(
                code="iac.comparison_unverified",
                phase="iac.comparison",
                scope=["/".join(entry) for entry in sorted(scope)],
                exception=type(comparison_failure).__name__,
                message=str(comparison_failure),
                complete=False,
            )
        )
    warnings.extend(w for w in comparison.warnings if w not in warnings)
    iac_seconds = time.perf_counter() - begin
    run_lint = _imports_issues_cfn_lint.run_lint
    begin = time.perf_counter()
    lint = dict(
        jobs=[],
        coverage=[],
        status="incomplete",
        **{
            name: []
            for name in (
                "ordinary",
                "judgments",
                "warnings",
                "information",
                "unverified",
                "processing_errors",
            )
        },
    )
    try:
        lint = run_lint(comparison, result=lint)
    except Exception as error:
        validator.findings.processing_failure("cfn-lint", scope, error)
        covered = {item.get("job_id") for item in lint["coverage"]}
        lint["coverage"].extend(
            dict(job_id=job["id"], status="unverified", reason="lint stage interrupted")
            for job in lint["jobs"]
            if job["id"] not in covered
        )
    lint_seconds = time.perf_counter() - begin
    ordinary.extend(lint.pop("ordinary"))
    judgments.extend(lint.pop("judgments"))
    warnings.extend(lint.pop("warnings"))
    naming_context = comparison.redacted(
        {key: value for key, value in naming.items() if key != "names"}
    )
    context_id = identifier(naming_context)
    naming = {
        "names": [dict(item, naming_context_id=context_id) for item in naming["names"]]
    }
    unverified = list(lint.pop("unverified"))
    validator = validators[0]
    unverified.extend(validator.findings.unverified)
    view_errors = list(comparison.view_errors.values())
    unverified.extend(
        dict(error, code="mechanical.view_unverified") for error in view_errors
    )
    for entry in sorted(scope):
        view = root / "docs/designs" / entry[0] / entry[1] / (entry[2] + ".md")
        with scan_stage(stages, "materials.view-availability", {entry}):
            if not view.is_file():
                unverified.append(
                    {
                        "code": "mechanical.view_missing",
                        "service": entry[2],
                        "message": "saved View checks unavailable",
                    }
                )
    for entry, info in (
        validator.findings.result("framework.generated-service-model", scope)
        .metadata.get("unverified", {})
        .items()
    ):
        unverified.append(
            {"code": "mechanical.view_unverified", "scope": entry, "details": info}
        )
    unverified.extend(stages.unverified)
    processing = lint.pop("processing_errors")
    processing.extend(validator.findings.processing_errors)
    processing.extend(stages.processing_errors)
    processing.extend(view_errors)
    # Stage failures are distinct from the number of affected comparison records.
    stage_errors = {}
    for record in iac:
        if record["category"] == "error":
            key = identifier(
                [record.get("reason"), record.get("cause"), record.get("iac")]
            )
            stage_errors.setdefault(
                key,
                dict(
                    id=key,
                    code="iac.processing",
                    message=record.get("reason"),
                    affected_records=0,
                ),
            )["affected_records"] += 1
    processing.extend(stage_errors.values())
    begin = time.perf_counter()
    data = aggregate(
        iac,
        environment,
        directory,
        services,
        comparison.display_differences,
        redact=comparison.redacted,
    )
    aggregation_seconds = time.perf_counter() - begin
    artifact = dict(
        version=4,
        target_services=all_services,
        service_results=[
            dict(service=service, status="scanned") for service in sorted(set(services))
        ],
        root=str(root),
        scan_id=scan_id,
        naming_context_id=context_id,
        naming_context=naming_context,
        environment=environment,
        target=directory,
        services=sorted(set(services)),
        executed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        ordinary=ordinary,
        naming=naming,
        judgments=judgments,
        warnings=warnings,
        human_confirmations=human,
        information=lint.pop("information"),
        unverified=unverified,
        processing_errors=processing,
        cfn_lint=lint,
        machine_diagnostics=safe_text(comparison.redacted(diagnostics)),
        **data,
    )
    # Redact every channel before hashing/review/output; masked material never regains raw values.
    for key in (
        "ordinary",
        "judgments",
        "warnings",
        "information",
        "unverified",
        "processing_errors",
        "naming_context",
        "naming",
        "human_confirmations",
    ):
        artifact[key] = comparison.redacted(artifact[key])
    artifact["checks"] = validator.checks + stages.checks
    artifact["check_results"] = [
        dict(
            id=identifier([result.check_id, sorted(result.scope or [])]),
            check_id=result.check_id,
            scope=["/".join(entry) for entry in sorted(result.scope or [])],
            status=result.status,
            complete=result.status == "PASS"
            and result.metadata.get("complete") is not False
            and not result.metadata.get("unverified"),
            checks=result.checks,
            # Only this complete service check validates the selected setting tables.
            # Other checks (including lint) have no proven per-setting PASS coverage.
            targets=[
                dict(
                    service=service,
                    resource=identity,
                    property=row["property"],
                    rule=result.check_id,
                )
                for env, target, service in sorted(result.scope or [])
                if (env, target) == (environment, directory)
                for identity, rows in comparison.rows.get(service, {}).items()
                for _, row in rows
            ]
            if result.check_id == "design.service"
            and result.status == "PASS"
            and result.checks > 0
            else [],
        )
        for result in [*validator.findings.results.values(), *stages.results.values()]
    ]
    artifact["metrics"] = comparison.metrics | dict(
        mechanical_seconds=mechanical_seconds,
        iac_seconds=iac_seconds,
        lint_seconds=lint_seconds,
        aggregation_seconds=aggregation_seconds,
        wall_seconds=time.perf_counter() - started,
        wall_scope="runner through aggregation; excludes CLI JSON/output",
    )
    CHANNELS = _imports_issues_artifact.CHANNELS
    channel_summary = _imports_issues_artifact.channel_summary
    validation_status = _imports_issues_artifact.validation_status
    artifact["validation_status"] = validation_status(artifact)
    artifact["review_required"] = True
    artifact["notice_overview"] = {
        name: channel_summary(artifact[name], name) for name in CHANNELS
    }
    artifact["metrics"]["wall_seconds"] = time.perf_counter() - started
    return artifact
