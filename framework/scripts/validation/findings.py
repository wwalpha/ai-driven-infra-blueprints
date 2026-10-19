"""Ordered validation findings and check counts."""


from pathlib import Path
from model_core import ReferenceResolutionError
from dataclasses import dataclass, field, replace


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
        return self.status == 'PASS' or (self.status == 'NOT_RUN' and not self.errors
                                        and self.metadata.get('reason') == 'reference')


class Findings:
    def __init__(self, root: Path):
        self.canonical_root = root.resolve()
        self.relative_paths = {}
        self.errors = []
        self.warnings = []
        self.unverified = []
        self.checks = 0
        self.results = {}
        self.candidate = object()


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
        return self.results.setdefault(key, CheckResult(check_id, scope, self.candidate))

    def evaluate(self, check_id, scope, handler):
        scope = None if scope is None else frozenset(scope)
        key = (check_id, scope, self.candidate)
        result = self.result(check_id, scope)
        if result.status != 'NOT_RUN':
            return result
        result = CheckResult(check_id, scope, self.candidate)
        self.results[key] = result
        incomplete_start = len(self.unverified)
        before, checks, warning_start = len(self.errors), self.checks, len(self.warnings)
        try:
            metadata = handler()
        except ReferenceResolutionError as error:
            self.warn(error)
            result.metadata = {'complete': False, 'reason': 'reference', 'unverified': [check_id]}
            result.warnings = tuple(self.warnings[warning_start:])
            result.errors = tuple(self.errors[before:])
            result.checks = self.checks - checks
            result.status = 'FAIL' if result.errors else 'NOT_RUN'
            return result
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.check(False, str(error))
            metadata = None
        result.errors = tuple(self.errors[before:])
        result.warnings = tuple(self.warnings[warning_start:])
        result.checks = self.checks - checks
        result.status = 'FAIL' if result.errors else 'NOT_RUN' if len(self.unverified) > incomplete_start else 'PASS'
        if isinstance(metadata, dict):
            result.metadata = metadata
        if result.status == 'NOT_RUN':
            result.metadata.update(complete=False, reason='reference', unverified=self.unverified[incomplete_start:])
        return result

    def warn(self, condition, message=None, *, code='reference.validation', **details):
        if message is not None:
            self.checks += 1
            if condition:
                return
            warning = {'code': code, 'message': message, **details}
        elif isinstance(condition, ReferenceResolutionError):
            self.unverified.append({**condition.diagnostic, **details})
            warning = {**condition.diagnostic, **details}
        elif isinstance(condition, dict):
            warning = {**condition, **details}
        else:
            warning = {'code': code, 'message': str(condition), **details}
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
            self.relative_paths[path] = path.resolve().relative_to(self.canonical_root).as_posix()
        return self.relative_paths[path]


    def report_findings(self) -> None:
        print(f"Checks: {self.checks}")
        print(f"Blocking errors: {len(self.errors)}")
        print(f"Warnings: {len(self.warnings)}")
        import json
        for warning in self.warnings:
            print('WARNING [' + warning['code'] + '] ' + json.dumps(warning, ensure_ascii=False))
