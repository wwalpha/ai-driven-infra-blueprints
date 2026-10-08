"""Ordered findings, counts and the mutable file gate; global checks fail closed."""


from pathlib import Path

class Findings:
    def __init__(self, root: Path, repository_wide_gate: bool):
        self.canonical_root = root.resolve()
        self.relative_paths = {}
        self.repository_wide_gate = repository_wide_gate
        self.file_gate_paths = None
        self.errors = []
        self.non_blocking_findings = []
        self.checks = 0

    def check(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.errors.append(message)


    def check_file(self, condition: bool, path: Path, message: str) -> None:
        self.checks += 1
        if not condition:
            # Unresolved authority fails closed; global checks always use check().
            blocking = (self.repository_wide_gate or self.file_gate_paths is None
                        or self.relative(path) in self.file_gate_paths)
            (self.errors if blocking else self.non_blocking_findings).append(message)


    def relative(self, path: Path) -> str:
        if path not in self.relative_paths:
            self.relative_paths[path] = path.resolve().relative_to(self.canonical_root).as_posix()
        return self.relative_paths[path]


    def report_findings(self) -> None:
        print(f"Checks: {self.checks}")
        print(f"Blocking errors: {len(self.errors)}")
        print(f"Non-blocking findings: {len(self.non_blocking_findings)}")
        for finding in self.non_blocking_findings:
            print(f"- non-blocking: {finding}")


