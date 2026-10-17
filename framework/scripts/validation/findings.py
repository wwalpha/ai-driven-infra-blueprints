"""Ordered validation findings and check counts."""


from pathlib import Path
from dataclasses import dataclass, field, replace


@dataclass
class CheckResult:
    check_id: str
    scope: frozenset | None
    candidate: object
    status: str = "NOT_RUN"
    errors: tuple = ()
    checks: int = 0
    metadata: dict = field(default_factory=dict)


class Findings:
    def __init__(self, root: Path):
        self.canonical_root = root.resolve()
        self.relative_paths = {}
        self.errors = []
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
        before, checks = len(self.errors), self.checks
        try:
            metadata = handler()
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.check(False, str(error))
            metadata = None
        result.errors = tuple(self.errors[before:])
        result.checks = self.checks - checks
        result.status = 'FAIL' if result.errors else 'PASS'
        if isinstance(metadata, dict):
            result.metadata = metadata
        return result

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
