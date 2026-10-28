"""Ordered validation findings and check counts."""

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from model.core import ReferenceDiagnosticError

from .diagnostics import (
    Diagnostic,
    InputValidationError,
    relative_path,
    service_scope,
    stable_id,
)


class FindingsError(ValueError):
    def __init__(self, findings):
        super().__init__("\n- ".join(findings.errors))
        self.findings = findings


def reference_identity(root, diagnostic):
    fields = (
        "category",
        "resourceLogicalId",
        "pointer",
        "targetLogicalId",
        "attribute",
    )
    if diagnostic.get("category") in {
        "REFERENCE_UNRESOLVED",
        "REFERENCE_PENDING_DEPLOY",
    }:
        diagnostic = dict(diagnostic)
        if diagnostic.get("producerModel"):
            diagnostic["producerModel"] = relative_path(
                root, diagnostic["producerModel"].replace("\\", "/")
            )
        if diagnostic.get("producerModel") or diagnostic.get("producerModelKey"):
            fields += ("producerModel", "producerModelKey")
    return Diagnostic.create(
        root,
        code=diagnostic["code"],
        check_id="model.references",
        service=service_scope(root, diagnostic.get("model")),
        source_path=diagnostic.get("model"),
        location=diagnostic.get("modelKey"),
        cause_key=json.dumps(
            [diagnostic.get(field) for field in fields]
            if diagnostic.get("model") and diagnostic.get("modelKey")
            else {
                key: value
                for key, value in diagnostic.items()
                if key not in {"cause_kind", "diagnostic_id"}
            },
            sort_keys=True,
        ),
        message=diagnostic["message"],
    ).identity


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
    if "reason" in metadata and not isinstance(metadata["reason"], str):
        raise TypeError("reason must be a string")
    if "status" in metadata and metadata["status"] not in {"PASS", "FAIL"}:
        raise ValueError("invalid validation status")
    return unavailable, unverified


def finish_result(result):
    unavailable, unverified = check_metadata(result.metadata)
    if result.status not in {"PASS", "FAIL"}:
        result.errors = (
            *result.errors,
            f"{result.check_id}: invalid final validation status {result.status!r}",
        )
        result.status = "FAIL"
    incomplete = result.metadata.get("complete") is not True or bool(
        unavailable or unverified
    )
    result.status = (
        "FAIL"
        if result.errors
        or result.status == "FAIL"
        or result.metadata.get("status") == "FAIL"
        or incomplete
        else "PASS"
    )
    if result.status == "FAIL":
        causes = [*result.errors]
        causes.extend(str(item.get("message") or item) for item in unverified)
        causes.extend(str(item.get("message") or item) for item in unavailable.values())
        causes = [cause for cause in causes if cause.strip()]
        reason = result.metadata.get("reason", "").strip()
        generic = {
            "unspecified",
            "processing",
            "reference",
            "dependency",
            "view",
            "expansion",
            "view-read",
        }
        if causes and (not reason or reason.lower() in generic):
            reason = "; ".join(dict.fromkeys(causes))
        elif not reason or reason.lower() in generic:
            reason = (
                f"{result.check_id}: required check has not started"
                if not result.started and not result.errors
                else f"{result.check_id}: required validation did not complete"
                if incomplete
                else f"{result.check_id}: handler reported failure without diagnostic details"
            )
        elif causes:
            reason = "; ".join(
                [
                    reason,
                    *(cause for cause in dict.fromkeys(causes) if cause not in reason),
                ]
            )
        result.metadata["reason"] = reason
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
    status: str = "FAIL"
    errors: tuple = ()
    warnings: tuple = ()
    checks: int = 0
    metadata: dict = field(default_factory=dict)
    started: bool = False
    reserved: bool = False  # Local plan slot; imported results are child evidence.


class Findings:
    def __init__(self, root: Path, *, source_path=None):
        self.canonical_root = root.resolve()
        self.relative_paths = {}
        self.errors = []
        self.warnings = []
        self.unverified = []
        self.processing_errors = []
        self.information = []
        self.reference_errors = []
        self.reference_error_positions = {}
        self.diagnostics = []
        self.diagnostic_errors = {}
        self.diagnostic_positions = {}
        self.diagnostic_failures = 0
        self.checks = 0
        self.results = {}
        self.candidate = object()
        self.source_path = source_path
        self.check_id = "validation.input"
        self.check_scope = None
        self.error_contexts = {}
        self._evaluations = []

    @property
    def status(self):
        # An in-flight status read must not finalize active or later planned checks.
        if self._evaluations:
            return "FAIL"
        results = [
            result
            for result in self.results.values()
            if result.candidate is self.candidate
        ]
        results = [finish_result(result) for result in results]
        if self.errors or any(result.status == "FAIL" for result in results):
            return "FAIL"
        if self.unverified:
            return "FAIL"
        return "PASS"

    def bind_candidate(self, candidate, common_checks):
        previous = self.candidate
        self.candidate = candidate
        for result in list(self.results.values()):
            if result.candidate is previous and (
                result.check_id in common_checks
                or finish_result(result).status == "FAIL"
            ):
                retained = replace(result, candidate=candidate)
                key = (retained.check_id, retained.scope, candidate)
                if key in self.results:
                    key = (retained.check_id, retained.scope, (candidate, object()))
                self.results[key] = retained

    def get_result(self, check_id, scope):
        """Read this candidate's result without registering an unexecuted check."""
        scope = None if scope is None else frozenset(scope)
        return self.results.get((check_id, scope, self.candidate))

    def _use_result(self, key):
        if self._evaluations and key != self._evaluations[-1][0]:
            self._evaluations[-1][1].add(key)

    def aggregate(self, check_id, scope, required):
        """Combine exact required child identities before replacing a same-key parent."""
        scope = None if scope is None else frozenset(scope)
        key = (check_id, scope, self.candidate)
        parent = self.results.get(key)
        reservation = (
            parent
            if parent is not None
            and parent.reserved
            and not parent.started
            and not parent.errors
            and parent.metadata.get("complete") is not True
            else None
        )
        children, missing = [], []
        for child_id, child_scope in required:
            child_scope = None if child_scope is None else frozenset(child_scope)
            matches = [
                finish_result(child)
                for child in self.results.values()
                if child.candidate is self.candidate
                and child.check_id == child_id
                and child.scope == child_scope
                and child is not reservation
            ]
            children.extend(matches)
            if not matches:
                missing.append(
                    f"{child_id} {sorted(child_scope or [])}: required child result missing"
                )
        failures = [child for child in children if child.status == "FAIL"]
        if not children and not missing:
            missing.append(f"{check_id}: required child plan is empty")
        result = CheckResult(
            check_id,
            scope,
            self.candidate,
            status="FAIL" if failures or missing else "PASS",
            errors=tuple(error for child in children for error in child.errors),
            warnings=tuple(warning for child in children for warning in child.warnings),
            checks=sum(child.checks for child in children),
            metadata={
                **(children[0].metadata if len(children) == 1 else {}),
                "complete": not missing
                and all(child.metadata["complete"] for child in children),
                "reason": "; ".join(
                    [
                        *missing,
                        *(
                            f"{child.check_id} {sorted(child.scope or [])}: {child.metadata['reason']}"
                            for child in failures
                        ),
                    ]
                ),
                "unavailable_services": {
                    key: value
                    for child in children
                    for key, value in child.metadata["unavailable_services"].items()
                },
                "unverified": [
                    item for child in children for item in child.metadata["unverified"]
                ],
            },
        )
        if key in self.results and self.results[key] is not reservation:
            self.results[(check_id, scope, (self.candidate, object()))] = self.results[
                key
            ]
        self.results[key] = finish_result(result)
        self._use_result(key)
        return result

    def failures(self):
        """Concrete raw failures; Acceptance may exclude records, never rewrite them."""
        records = {}
        by_id = {d.identity: d for d in self.diagnostics}
        for index, message in enumerate(self.errors):
            reference = self.reference_error_positions.get(index)
            diagnostic = by_id.get(
                self.diagnostic_errors.get(index)
            ) or self.error_contexts.get(index)
            if reference is not None:
                diagnostic = Diagnostic.create(
                    self.canonical_root,
                    code=reference["code"],
                    check_id="model.references",
                    service=service_scope(self.canonical_root, reference.get("model")),
                    source_path=reference.get("model"),
                    cause_kind=reference["cause_kind"],
                    message=reference["message"],
                    location=reference.get("modelKey"),
                    details=reference,
                )
            if diagnostic is None:
                diagnostic = Diagnostic.create(
                    self.canonical_root,
                    code="validation.unclassified",
                    check_id="validation.input",
                    service=None,
                    message=message,
                    cause_key=message,
                )
            record = diagnostic.record()
            identity = (
                stable_id(reference_identity(self.canonical_root, reference))
                if reference is not None
                else stable_id(diagnostic.identity)
            )
            records[identity] = dict(
                record,
                diagnostic_id=identity,
                status="FAIL",
                reason=message or f"{diagnostic.check_id}: empty failure diagnostic",
                scope=[
                    list(s)
                    for s in (
                        diagnostic.affected_services
                        or ((diagnostic.service,) if diagnostic.service else ())
                    )
                ],
            )
        for result in self.results.values():
            if (
                result.candidate is not self.candidate
                or finish_result(result).status != "FAIL"
            ):
                continue
            if (
                result.errors
                and result.metadata.get("complete")
                and all(error in self.errors for error in result.errors)
            ):
                continue
            if result.metadata.get("complete") and any(
                record["check_id"] == result.check_id
                and record["reason"] == result.metadata["reason"]
                for record in records.values()
            ):
                continue
            identity = stable_id(
                [result.check_id, sorted(result.scope or []), result.metadata["reason"]]
            )
            records[identity] = dict(
                diagnostic_id=identity,
                status="FAIL",
                check_id=result.check_id,
                scope=[list(s) for s in sorted(result.scope or [])],
                reason=result.metadata["reason"],
                cause_kind="check_failure",
                source_path=None,
                diagnostics=result.metadata.get("unverified", []),
            )
        for item in self.unverified:
            reason = item.get("message") or str(item)
            identity = item.get("diagnostic_id") or stable_id(item)
            records.setdefault(
                identity,
                dict(
                    item,
                    diagnostic_id=identity,
                    status="FAIL",
                    check_id=item.get(
                        "check_id", item.get("phase", "validation.coverage")
                    ),
                    scope=item.get("scope", []),
                    reason=reason,
                    cause_kind="check_failure",
                ),
            )
        return list(records.values())

    def result(self, check_id, scope):
        scope = None if scope is None else frozenset(scope)
        key = (check_id, scope, self.candidate)
        self._use_result(key)
        return self.results.setdefault(
            key, CheckResult(check_id, scope, self.candidate, reserved=True)
        )

    def evaluate(self, check_id, scope, handler, *, isolate=False, source_path=None):
        scope = None if scope is None else frozenset(scope)
        key = (check_id, scope, self.candidate)
        result = self.result(check_id, scope)
        if any(active == key for active, _ in self._evaluations):
            result.status = "FAIL"
            result.metadata.update(
                complete=False, reason=f"{check_id}: reentrant check has not completed"
            )
            return finish_result(result)
        if result.metadata.get("complete") is True or result.errors:
            return finish_result(result)
        result = CheckResult(
            check_id, scope, self.candidate, status="PASS", metadata={}, started=True
        )
        self.results[key] = result
        previous_results = {
            child_key: (id(child), child.status, child.errors, dict(child.metadata))
            for child_key, child in self.results.items()
            if child_key != key
        }
        used = set()
        self._evaluations.append((key, used))
        diagnostic_failures = self.diagnostic_failures
        incomplete_start = len(self.unverified)
        before, checks, warning_start = (
            len(self.errors),
            self.checks,
            len(self.warnings),
        )
        try:
            previous = self.check_id, self.check_scope, self.source_path
            self.check_id, self.check_scope = check_id, scope
            self.source_path = source_path or self.source_path
            metadata = handler()
            if isinstance(metadata, CheckResult):
                returned = finish_result(metadata)
                for message in returned.errors:
                    self.check(False, message, source_path=source_path)
                for warning in returned.warnings:
                    self.warn(warning)
                metadata = dict(returned.metadata, status=returned.status)
            if isinstance(metadata, dict):
                check_metadata(metadata)
                result.metadata.update(metadata)
            result.metadata.setdefault("complete", True)
            check_metadata(result.metadata)
        except ReferenceDiagnosticError as error:
            self.warn(error)
            result.metadata.update(
                complete=False,
                reason=f"{check_id} interrupted by reference resolution: {error}",
            )
        except InputValidationError as error:
            self.input_failure(error)
            result.metadata.setdefault("complete", True)
        except FindingsError as error:
            self.include_diagnostics(error.findings)
            result.metadata.setdefault("complete", True)
        except (Exception, KeyboardInterrupt) as error:
            self.processing_failure(check_id, scope, error)
            result.metadata.update(
                complete=False,
                reason=f"{check_id}: {type(error).__name__}: {str(error).strip() or 'check interrupted'}",
            )
        finally:
            self._evaluations.pop()
            self.check_id, self.check_scope, self.source_path = previous
        child_failures = [
            finish_result(child)
            for child_key, child in self.results.items()
            if (
                child_key in used
                or (id(child), child.status, child.errors, child.metadata)
                != previous_results.get(child_key)
            )
            and child.candidate is self.candidate
            and child is not result
            and finish_result(child).status == "FAIL"
        ]
        if child_failures:
            result.status = "FAIL"
            result.metadata.update(
                complete=result.metadata.get("complete") is True
                and all(child.metadata.get("complete") for child in child_failures),
                reason="; ".join(
                    filter(
                        None,
                        [
                            result.metadata.get("reason"),
                            *(
                                f"{child.check_id}: {child.metadata['reason']}"
                                for child in child_failures
                            ),
                        ],
                    )
                ),
            )
        # Repeated diagnostics still fail their check without adding duplicate ERRORs.
        if self.diagnostic_failures > diagnostic_failures:
            result.status = "FAIL"
            causes = [d.message for d in self.diagnostics if d.check_id == check_id]
            if causes:
                result.metadata["reason"] = "; ".join(
                    dict.fromkeys(
                        filter(None, [result.metadata.get("reason"), *causes])
                    )
                )
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
                reason=result.metadata.get("reason") or reason,
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

    def _retain_diagnostic(self, diagnostic):
        if diagnostic.identity in self.diagnostic_positions:
            return False
        self.diagnostic_positions[diagnostic.identity] = len(self.diagnostics)
        self.diagnostics.append(diagnostic)
        return True

    def add_diagnostic(self, diagnostic: Diagnostic, *, display_error=None):
        self.diagnostic_failures += 1
        if not self._retain_diagnostic(diagnostic):
            return
        self.diagnostic_errors[len(self.errors)] = diagnostic.identity
        self.checks += 1
        self.errors.append(
            diagnostic.message if display_error is None else display_error
        )

    def include_diagnostics(self, findings, *, scope=None, exclude_checks=()):
        for child in getattr(findings, "results", {}).values():
            if (
                child.candidate is not findings.candidate
                or child.check_id in exclude_checks
            ):
                continue
            child_scope = child.scope if child.scope is not None else scope
            child_scope = None if child_scope is None else frozenset(child_scope)
            retained = finish_result(
                replace(
                    child, scope=child_scope, candidate=self.candidate, reserved=False
                )
            )
            key = (retained.check_id, retained.scope, self.candidate)
            if key in self.results:
                key = (retained.check_id, retained.scope, (self.candidate, object()))
            self.results[key] = retained
        for warning in findings.warnings:
            self.warn(warning)
        if findings.errors:
            self.diagnostic_failures += 1
        known = set(self.diagnostic_errors.values())
        for index, error in enumerate(findings.errors):
            if index in findings.reference_error_positions:
                self.warn(findings.reference_error_positions[index])
                continue
            identity = findings.diagnostic_errors.get(index)
            if identity is not None:
                if identity in known:
                    continue
                known.add(identity)
                self.diagnostic_errors[len(self.errors)] = identity
            self.errors.append(error)
            if index in findings.error_contexts:
                self.error_contexts[len(self.errors) - 1] = findings.error_contexts[
                    index
                ]
        for diagnostic in findings.diagnostics:
            self._retain_diagnostic(diagnostic)
        for channel in ("processing_errors", "unverified", "information"):
            retained = getattr(self, channel)
            retained.extend(
                item for item in getattr(findings, channel) if item not in retained
            )

    def processing_failure(self, check_id, scope, error, *, source_path=None):
        source_path = source_path or self.source_path
        message = f"{check_id}: {type(error).__name__}: {str(error).strip() or 'check interrupted'}"
        diagnostic = Diagnostic.create(
            self.canonical_root,
            code="mechanical.processing",
            cause_kind="check_failure",
            check_id=check_id,
            source_path=source_path,
            service=service_scope(self.canonical_root, source_path),
            cause_key=json.dumps([check_id, str(error)])
            if source_path is not None
            else json.dumps([check_id, sorted(scope or []), str(error)]),
            affected_services=tuple(sorted(scope or [])),
            location=type(error).__name__,
            message=message,
        )
        failure = dict(
            diagnostic_id=stable_id(diagnostic.identity),
            cause_kind="check_failure",
            source_path=diagnostic.source_path,
            code="mechanical.processing",
            phase=check_id,
            scope=["/".join(entry) for entry in sorted(scope or [])],
            exception=type(error).__name__,
            message=message,
        )
        if failure not in self.processing_errors:
            self.processing_errors.append(failure)
            self.unverified.append(dict(failure, complete=False))
        self.add_diagnostic(diagnostic)
        result = self.result(check_id, scope)
        result.status = "FAIL"
        result.metadata = dict(
            complete=False,
            reason=message,
        )

    def input_failure(self, error, *, source_path=None, display_error=None):
        source_path = error.source_path or source_path or self.source_path
        diagnostic = Diagnostic.create(
            self.canonical_root,
            code="validation.input",
            cause_kind="input_invalid",
            check_id=self.check_id,
            service=service_scope(self.canonical_root, source_path),
            source_path=source_path,
            cause_key=str(error)
            if source_path is not None
            else json.dumps(
                [self.check_id, sorted(self.check_scope or []), str(error)]
            ),
            message=str(error),
        )
        self.add_diagnostic(diagnostic, display_error=display_error)
        return diagnostic

    def warn(self, condition, message=None, *, code="reference.validation", **details):
        if isinstance(condition, ReferenceDiagnosticError):
            for diagnostic in condition.diagnostics:
                self.warn(diagnostic, **details)
            return
        if isinstance(condition, dict) and condition.get("category") in {
            "MODEL_NEEDS_FIX",
            "FRAMEWORK_UNSUPPORTED",
            "REFERENCE_UNRESOLVED",
            "REFERENCE_PENDING_DEPLOY",
        }:
            condition = dict(
                condition,
                cause_kind={
                    "MODEL_NEEDS_FIX": "input_invalid",
                    "FRAMEWORK_UNSUPPORTED": "check_failure",
                    "REFERENCE_UNRESOLVED": "dependency_wait",
                    "REFERENCE_PENDING_DEPLOY": "dependency_wait",
                }[condition["category"]],
            )
        if isinstance(condition, dict) and condition.get("category") in {
            "MODEL_NEEDS_FIX",
            "FRAMEWORK_UNSUPPORTED",
        }:
            diagnostic = {**condition, **details}
            identity = reference_identity(self.canonical_root, diagnostic)
            if identity not in self.diagnostic_errors.values():
                self.reference_errors.append(diagnostic)
                self.reference_error_positions[len(self.errors)] = diagnostic
                self.diagnostic_errors[len(self.errors)] = identity
                message = json.dumps(diagnostic, ensure_ascii=False)
                if diagnostic["category"] == "FRAMEWORK_UNSUPPORTED":
                    self.processing_errors.append(
                        dict(
                            diagnostic,
                            diagnostic_id=stable_id(identity),
                            phase="reference",
                            message=message,
                        )
                    )
                    self.unverified.append(
                        dict(
                            diagnostic,
                            diagnostic_id=stable_id(identity),
                            complete=False,
                        )
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
            if warning.get("category") in {
                "REFERENCE_PENDING_DEPLOY",
                "REFERENCE_UNRESOLVED",
            }:
                warning.setdefault(
                    "diagnostic_id",
                    stable_id(reference_identity(self.canonical_root, warning)),
                )
                if warning["category"] != "REFERENCE_PENDING_DEPLOY" and not any(
                    item.get("diagnostic_id") == warning["diagnostic_id"]
                    for item in self.unverified
                ):
                    self.unverified.append(warning)
        else:
            warning = {"code": code, "message": str(condition), **details}
        if warning not in self.warnings and not (
            warning.get("diagnostic_id")
            and any(
                item.get("diagnostic_id") == warning["diagnostic_id"]
                for item in self.warnings
            )
        ):
            self.warnings.append(warning)

    def check(
        self,
        condition: bool,
        message: str,
        *,
        source_path=None,
        cause_kind=None,
        check_id=None,
        location=None,
    ) -> None:
        self.checks += 1
        if not condition:
            source_path = source_path or self.source_path
            diagnostic = Diagnostic.create(
                self.canonical_root,
                code="validation.check"
                if cause_kind == "input_invalid"
                else "validation.unclassified",
                cause_kind=cause_kind or "unclassified",
                check_id=check_id or self.check_id,
                source_path=source_path,
                service=service_scope(self.canonical_root, source_path),
                cause_key=message
                if source_path is not None
                else json.dumps(
                    [check_id or self.check_id, sorted(self.check_scope or []), message]
                ),
                message=message,
                affected_services=tuple(sorted(self.check_scope or [])),
                location=location,
            )
            if cause_kind is not None:
                self.checks -= 1
                self.add_diagnostic(diagnostic)
                return
            self.error_contexts[len(self.errors)] = diagnostic
            self.errors.append(message)

    def check_file(
        self,
        condition: bool,
        path: Path,
        message: str,
        *,
        cause_kind=None,
        location=None,
    ) -> None:
        self.check(
            condition,
            message,
            source_path=path,
            cause_kind=cause_kind,
            location=location,
        )

    def input_check(self, condition, path, message, *, location=None):
        self.check_file(
            condition, path, message, cause_kind="input_invalid", location=location
        )

    def relative(self, path: Path) -> str:
        if path not in self.relative_paths:
            self.relative_paths[path] = relative_path(self.canonical_root, path)
        return self.relative_paths[path]

    def report_findings(self) -> None:
        print(f"Checks: {self.checks}")
        print(f"Blocking errors: {len(self.errors)}")
        print(f"Warnings: {len(self.warnings)}")
        for failure in self.failures():
            print(
                f"FAIL [{failure['diagnostic_id']}] "
                + json.dumps(failure, ensure_ascii=False)
            )
        for information in self.information:
            if information.get("kind") == "view_generation":
                print("View generation: " + json.dumps(information, ensure_ascii=False))
        for warning in self.warnings:
            print(
                "WARNING ["
                + warning["code"]
                + "] "
                + json.dumps(warning, ensure_ascii=False)
            )
