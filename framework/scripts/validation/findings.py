"""Ordered validation findings and check counts."""

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from model.core import ReferenceDiagnosticError

from .diagnostics import Diagnostic, relative_path


class FindingsError(ValueError):
    def __init__(self, findings):
        super().__init__("\n- ".join(findings.errors))
        self.findings = findings


def check_metadata(metadata):
    unavailable = metadata.get("unavailable_services", {})
    unverified = metadata.get("unverified", [])
    if not isinstance(unavailable, dict) or any(
        not isinstance(key, str) or not isinstance(value, dict)
        for key, value in unavailable.items()
    ):
        raise TypeError("unavailable_services must be dict[str, dict]")
    if not isinstance(unverified, list) or any(
        not isinstance(item, dict) for item in unverified
    ):
        raise TypeError("unverified must be list[dict]")
    if "complete" in metadata and not isinstance(metadata["complete"], bool):
        raise TypeError("complete must be bool")
    if "status" in metadata and metadata["status"] not in {"PASS", "FAIL", "NOT_RUN"}:
        raise ValueError("invalid validation status")
    return unavailable, unverified


def finish_result(result):
    unavailable, unverified = check_metadata(result.metadata)
    incomplete = (
        result.status == "NOT_RUN"
        or result.metadata.get("complete") is False
        or result.metadata.get("status") == "NOT_RUN"
        or bool(unavailable or unverified)
    )
    result.status = (
        "FAIL"
        if result.errors
        or result.status == "FAIL"
        or result.metadata.get("status") == "FAIL"
        else "NOT_RUN"
        if incomplete
        else "PASS"
    )
    result.metadata.update(
        status=result.status,
        complete=not incomplete,
        unavailable_services=unavailable,
        unverified=unverified,
    )
    return result


@dataclass
class CheckResult:
    check_id: str
    scope: frozenset | None
    candidate: object
    status: str = "NOT_RUN"
    errors: tuple = ()
    warnings: tuple = ()
    checks: int = 0
    metadata: dict = field(default_factory=dict)

    @property
    def model_completion_allowed(self):
        return self.status == "PASS" or (
            self.status == "NOT_RUN"
            and not self.errors
            and self.metadata.get("reason") == "reference"
        )


class Findings:
    def __init__(self, root: Path):
        self.canonical_root = root.resolve()
        self.relative_paths = {}
        self.errors = []
        self.warnings = []
        self.unverified = []
        self.processing_errors = []
        self.reference_errors = []
        self.diagnostics = []
        self.diagnostic_errors = {}
        self.checks = 0
        self.results = {}
        self.candidate = object()

    @property
    def status(self):
        results = [
            result
            for result in self.results.values()
            if result.candidate is self.candidate
        ]
        if self.errors or any(
            result.status == "FAIL" or result.metadata.get("status") == "FAIL"
            for result in results
        ):
            return "FAIL"
        if self.unverified or any(
            result.status == "NOT_RUN"
            or result.metadata.get("status") == "NOT_RUN"
            or result.metadata.get("complete") is False
            or result.metadata.get("unavailable_services")
            or result.metadata.get("unverified")
            for result in results
        ):
            return "NOT_RUN"
        return "PASS"

    def bind_candidate(self, candidate, common_checks):
        previous = self.candidate
        self.candidate = candidate
        for result in list(self.results.values()):
            if result.candidate is previous and result.check_id in common_checks:
                retained = replace(result, candidate=candidate)
                self.results[(retained.check_id, retained.scope, candidate)] = retained

    def result(self, check_id, scope):
        scope = None if scope is None else frozenset(scope)
        key = (check_id, scope, self.candidate)
        return self.results.setdefault(
            key, CheckResult(check_id, scope, self.candidate)
        )

    def evaluate(self, check_id, scope, handler, *, isolate=False):
        scope = None if scope is None else frozenset(scope)
        key = (check_id, scope, self.candidate)
        result = self.result(check_id, scope)
        if result.status != "NOT_RUN":
            return result
        result = CheckResult(check_id, scope, self.candidate, status="PASS")
        self.results[key] = result
        incomplete_start = len(self.unverified)
        before, checks, warning_start = (
            len(self.errors),
            self.checks,
            len(self.warnings),
        )
        try:
            metadata = handler()
            if isinstance(metadata, CheckResult):
                metadata = dict(metadata.metadata, status=metadata.status)
            if isinstance(metadata, dict):
                check_metadata(metadata)
                result.metadata.update(metadata)
            check_metadata(result.metadata)
        except ReferenceDiagnosticError as error:
            self.warn(error)
            result.metadata.update(complete=False, reason="reference")
        except Exception as error:
            if not isolate and not isinstance(
                error, (OSError, ValueError, KeyError, TypeError)
            ):
                raise
            self.processing_failure(check_id, scope, error)
            result.metadata.update(complete=False, reason="processing")
        result.errors = tuple(self.errors[before:])
        result.warnings = tuple(self.warnings[warning_start:])
        result.checks = self.checks - checks
        unverified = self.unverified[incomplete_start:]
        if unverified:
            reason = "reference"
            if any(
                item.get("reason") != "reference"
                and item.get("category")
                not in {"REFERENCE_PENDING_DEPLOY", "REFERENCE_UNRESOLVED"}
                for item in unverified
            ):
                reason = "dependency"
            result.metadata.update(
                complete=False,
                reason=(
                    result.metadata.get("reason", reason)
                    if reason == "reference"
                    or result.metadata.get("reason") == "processing"
                    else reason
                ),
            )
            retained = result.metadata.setdefault("unverified", [])
            retained.extend(item for item in unverified if item not in retained)
        return finish_result(result)

    @property
    def unstructured_errors(self):
        return [
            error
            for index, error in enumerate(self.errors)
            if index not in self.diagnostic_errors
        ]

    def add_diagnostic(self, diagnostic: Diagnostic, *, display_error=None):
        if any(item.identity == diagnostic.identity for item in self.diagnostics):
            return
        self.diagnostics.append(diagnostic)
        self.diagnostic_errors[len(self.errors)] = diagnostic.identity
        self.check(
            False, diagnostic.message if display_error is None else display_error
        )

    def include_diagnostics(self, findings):
        offset = len(self.errors)
        self.diagnostic_errors.update(
            (offset + index, identity)
            for index, identity in findings.diagnostic_errors.items()
        )
        self.errors.extend(findings.errors)
        for diagnostic in findings.diagnostics:
            if not any(
                item.identity == diagnostic.identity for item in self.diagnostics
            ):
                self.diagnostics.append(diagnostic)

    def processing_failure(self, check_id, scope, error):
        failure = dict(
            code="mechanical.processing",
            phase=check_id,
            scope=["/".join(entry) for entry in sorted(scope or [])],
            exception=type(error).__name__,
            message=f"{check_id}: {error}",
        )
        self.processing_errors.append(failure)
        self.unverified.append(dict(failure, complete=False))
        self.check(False, failure["message"])
        result = self.result(check_id, scope)
        result.status = "FAIL"
        result.metadata = dict(complete=False, reason="processing")

    def warn(self, condition, message=None, *, code="reference.validation", **details):
        if isinstance(condition, ReferenceDiagnosticError):
            for diagnostic in condition.diagnostics:
                self.warn(diagnostic, **details)
            return
        if isinstance(condition, dict) and condition.get("category") in {
            "MODEL_NEEDS_FIX",
            "FRAMEWORK_UNSUPPORTED",
        }:
            diagnostic = {**condition, **details}
            if diagnostic not in self.reference_errors:
                self.reference_errors.append(diagnostic)
                message = json.dumps(diagnostic, ensure_ascii=False)
                if diagnostic["category"] == "FRAMEWORK_UNSUPPORTED":
                    self.processing_errors.append(
                        dict(diagnostic, phase="reference", message=message)
                    )
                self.check(False, message)
            return
        if message is not None:
            self.checks += 1
            if condition:
                return
            warning = {"code": code, "message": message, **details}
        elif isinstance(condition, dict):
            warning = {**condition, **details}
            if (
                warning.get("category")
                in {"REFERENCE_PENDING_DEPLOY", "REFERENCE_UNRESOLVED"}
                and warning not in self.unverified
            ):
                self.unverified.append(warning)
        else:
            warning = {"code": code, "message": str(condition), **details}
        if warning not in self.warnings:
            self.warnings.append(warning)

    def check(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.errors.append(message)

    def check_file(self, condition: bool, path: Path, message: str) -> None:
        self.checks += 1
        if not condition:
            self.errors.append(message)

    def relative(self, path: Path) -> str:
        if path not in self.relative_paths:
            self.relative_paths[path] = relative_path(self.canonical_root, path)
        return self.relative_paths[path]

    def report_findings(self) -> None:
        print(f"Checks: {self.checks}")
        print(f"Blocking errors: {len(self.errors)}")
        print(f"Warnings: {len(self.warnings)}")
        for warning in self.warnings:
            print(
                "WARNING ["
                + warning["code"]
                + "] "
                + json.dumps(warning, ensure_ascii=False)
            )
