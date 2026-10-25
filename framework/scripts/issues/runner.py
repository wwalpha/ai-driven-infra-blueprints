import io
import os
import re
import time
import uuid
from contextlib import redirect_stdout
from functools import partial

from model.core import ReferenceResolutionError, entries
from model.validation import codebuild_reference_errors
from task_contract_core import task_read_scope
from utils.input_cache import input_scope
from utils.reference_contracts import reference_error
from utils.script_loader import module

import issues.artifact as _imports_issues_artifact
import issues.cfn_lint as _imports_issues_cfn_lint

from .aggregate import aggregate
from .inputs import Comparison, view_text
from .integrity import selected_scope
from .materials import existing_materials, naming_materials
from .records import identifier, safe_text
from .reports import issue_key


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


def check_targets(result):
    return [
        dict(
            service=entry[2],
            check_id=result.check_id,
            rule=result.check_id,
            resource="*",
            property="*",
            scope="/".join(entry),
        )
        for entry in sorted(result.scope or [])
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


@input_scope
def scan(root, environment, directory, services, *, fresh=False, jobs=4):
    started = time.perf_counter()
    scope = selected_scope(environment, directory, services)
    scan_id = uuid.uuid4().hex
    comparison = Comparison(root, environment, directory, services)
    for service in services:
        doc = root / "docs/designs" / environment / directory / (service + ".md")
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
    seen = set()
    diagnostic_messages = [
        (message, diagnostic)
        for message in dict.fromkeys(errors)
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
                r"/" + re.escape(service) + r"(?:\.md|\.properties|/)", message
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
            "verification_targets": [
                target
                for result in validator.findings.results.values()
                if message in result.errors
                for target in check_targets(result)
                if target["service"] == owner
            ],
        }
        (ordinary if owner else judgments).append(candidate)
    naming, naming_judgments = naming_materials(comparison)
    judgments.extend(naming_judgments)
    existing, human = existing_materials(root, environment, directory, services)
    judgments.extend(
        {
            "id": item["id"],
            "service": item["service"],
            "kind": "existing-issue-correspondence",
            "materials": item,
        }
        for item in existing
    )
    for service in services:
        doc = root / "docs/designs" / environment / directory / (service + ".md")
        if doc.is_file() and doc not in comparison.view_errors:
            text = view_text(comparison, doc, phase="review-prose")
            if text is None:
                continue
            # Only notes/implementation prose remains for LLM review; verified tables are not repeated.
            known_notes = (
                {
                    value
                    for key, value in comparison.models[service].values.items()
                    if key.startswith("desired.note.")
                }
                if service in comparison.models
                else set()
            )
            notes = []
            for line in text.splitlines():
                if (
                    line.strip()
                    and not line.startswith(("#", "|", "<", "- Design", "- Owned"))
                    and not line.startswith("```")
                    and line.removeprefix("- ").strip() not in known_notes
                ):
                    notes.append(safe_text(line))
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
    current = {}
    for record in ordinary:
        current.setdefault(issue_key(root, record), []).append(record["id"])
    for item in judgments:
        if item.get("kind") == "existing-issue-correspondence":
            item["materials"]["current_diagnostic_ids"] = current.get(
                item["materials"].get("marker"), []
            )
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
    processing = lint.pop("processing_errors")
    processing.extend(validator.findings.processing_errors)
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
        version=3,
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
        human_confirmations=[safe_text(line) for line in human],
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
    artifact["checks"] = validator.checks
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
            verification_targets=check_targets(result),
        )
        for result in validator.findings.results.values()
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
