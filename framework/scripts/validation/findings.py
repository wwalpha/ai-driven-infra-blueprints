"""Ordered validation findings and check counts."""


from pathlib import Path

class Findings:
    def __init__(self, root: Path):
        self.canonical_root = root.resolve()
        self.relative_paths = {}
        self.errors = []
        self.checks = 0

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
