"""Task ownership, boundary, issue gate and Acceptance state."""


from __future__ import annotations
import re
import subprocess
from pathlib import Path
from model_core import properties
from model_files import service_model_path
from validation_scope import active_scope
from issue_gate import require_no_issues
from task_contract import task_path, task_changes, contracts, reservations, TASK_NAME, matches

TASK_TYPES = {
    "initialization",
    "design",
    "infrastructure",
    "scenario-test",
    "governance",
    "catalog-maintenance",
    "migration",
}


class TaskValidation:
    def __init__(self, root, findings):
        self.root = root
        self.findings = findings
        self.check = findings.check
        self.relative = findings.relative
        self.changed_paths = set()
        self.task_type = ""
        self.infrastructure_phase = ""
        self.requirement_ids = []
        self.acceptance_checks = []
        self.acceptance_results = []
        self.deferred_files = set()
        self.deferred_acceptance = []

    def git_paths(self, args: list[str]) -> set[str]:
        result = subprocess.run(
            ["git", *args], cwd=self.root, check=False, capture_output=True, text=True
        )
        self.check(result.returncode == 0, f"git {' '.join(args)} failed")
        return {path for path in result.stdout.split("\0") if path} if result.returncode == 0 else set()


    def check_task_scope(self) -> None:
        prompt = task_path(self.root)
        self.changed_paths = (
            self.git_paths(["diff", "--no-renames", "--name-only", "-z"])
            | self.git_paths(["diff", "--cached", "--no-renames", "--name-only", "-z"])
            | self.git_paths(["ls-files", "--others", "--exclude-standard", "-z"])
        ) - {".lock"}  # Per-repository password configuration is not a task artifact.
        if not self.changed_paths and (not prompt.is_file() or
                "- Task type:" not in prompt.read_text(encoding="utf-8")):
            return  # Preserve the unchanged legacy idle state.
        if prompt.is_file():
            records = contracts(self.root)
            entry = reservations(self.root, records)[self.relative(prompt)]
            from worktree_task import committed_task_paths
            committed = committed_task_paths(self.root, self.relative(prompt))
            if committed is not None:
                # Attribution uses the existing local grants, excluding other tasks/Deferred files.
                self.changed_paths |= committed & (entry.active or set())
            else:
                # Exact acquired Modified files are the stable legacy task contract authority.
                self.findings.file_gate_paths = entry.active
        if not prompt.is_file():
            if contracts(self.root, include_foreign=True):
                self.changed_paths = task_changes(self.root, self.changed_paths)
                return
            self.check(
                not (self.changed_paths - {"tasks/active.md"}),
                f"active task prompt missing: {self.relative(prompt)} while repository has non-contract changes",
            )
            return

        self.changed_paths = task_changes(self.root, self.changed_paths, self.relative(prompt))
        if committed is not None:
            self.findings.file_gate_paths = self.changed_paths
        self.deferred_files = set(entry.deferred)
        lines = prompt.read_text(encoding="utf-8").splitlines()
        contract = self.section(lines, "## Task contract")
        task_types = []
        for line in contract:
            match = re.fullmatch(r"- Task type: `([^`]+)`", line)
            if match:
                task_types.append(match.group(1))
        self.check(len(task_types) == 1, f"Task type must appear exactly once in Task contract: {self.relative(prompt)}")
        if task_types:
            self.task_type = task_types[0]
            self.check(self.task_type in TASK_TYPES, f"unknown Task type: {self.task_type}")

        infrastructure_phases = []
        for line in contract:
            match = re.fullmatch(r"- Infrastructure phase: `([^`]+)`", line)
            if match:
                infrastructure_phases.append(match.group(1))
        expected_phase_count = 1 if self.task_type == "infrastructure" else 0
        self.check(
            len(infrastructure_phases) == expected_phase_count,
            f"Infrastructure phase must appear exactly once for infrastructure tasks only: {self.relative(prompt)}",
        )
        if infrastructure_phases:
            self.infrastructure_phase = infrastructure_phases[0]
            self.check(
                self.infrastructure_phase in {"implement", "deploy", "update", "destroy"},
                f"unknown Infrastructure phase: {self.infrastructure_phase}",
            )

        requirement_ids: list[str] = []
        for line in self.section(lines, "## Required changes"):
            if not line.startswith("- "):
                continue
            match = re.fullmatch(r"- \[([A-Z][A-Z0-9-]*)\] .+", line)
            self.check(match is not None, f"invalid Required changes entry: {self.relative(prompt)}: {line}")
            if match:
                requirement_ids.append(match.group(1))
        self.check(bool(requirement_ids), f"Required changes section missing or empty: {self.relative(prompt)}")
        self.check(len(requirement_ids) == len(set(requirement_ids)), f"duplicate requirement ID: {self.relative(prompt)}")
        self.requirement_ids = requirement_ids

        acceptance_ids: set[str] = set()
        for line in self.section(lines, "## Acceptance checks"):
            if not line.startswith("- "):
                continue
            match = re.fullmatch(
                r"- \[([A-Z][A-Z0-9-]*)\] `(changed|exists|absent|check):([^`]+)`",
                line,
            )
            self.check(match is not None, f"invalid Acceptance checks entry: {self.relative(prompt)}: {line}")
            if not match:
                continue
            requirement_id, kind, value = match.groups()
            acceptance_ids.add(requirement_id)
            self.acceptance_checks.append((requirement_id, kind, value))
            self.check(requirement_id in requirement_ids, f"Acceptance check uses unknown requirement ID: {requirement_id}")
            if kind != "check":
                candidate = Path(value)
                self.check(not candidate.is_absolute() and ".." not in candidate.parts, f"unsafe Acceptance check path: {value}")
        for requirement_id in requirement_ids:
            self.check(requirement_id in acceptance_ids, f"requirement has no Acceptance check: {requirement_id}")

        allowed = [match.group(1) for line in self.section(lines, "## Allowed paths")
                   if (match := re.fullmatch(r"- `([^`]+)`", line))]
        self.check(bool(allowed), f"Allowed paths section missing or empty: {self.relative(prompt)}")

        for changed in sorted(self.changed_paths):
            permitted = any(self.matches(changed, pattern) for pattern in allowed)
            self.check(permitted, f"changed path is outside task scope: {changed}")
        self.check_task_boundary(prompt)


    @staticmethod
    def section(lines: list[str], heading: str) -> list[str]:
        content: list[str] = []
        in_section = False
        for line in lines:
            if line == heading:
                in_section = True
                continue
            if in_section and line.startswith("## "):
                break
            if in_section:
                content.append(line)
        return content


    matches = staticmethod(matches)


    @staticmethod
    def under(path: str, prefix: str) -> bool:
        return path == prefix or path.startswith(prefix + "/")


    def check_task_boundary(self, prompt: Path) -> None:
        if self.task_type not in TASK_TYPES:
            return
        prompt_path = self.relative(prompt)
        for changed in sorted(self.changed_paths):
            if self.task_type == "design":
                forbidden = self.under(changed, "infra") or self.under(changed, "tests")
                self.check(not forbidden, f"design task boundary violation: {changed}")
            elif self.task_type == "infrastructure":
                forbidden = self.under(changed, "tests")
                self.check(not forbidden, f"infrastructure task boundary violation: {changed}")
                if self.infrastructure_phase == "destroy":
                    permitted = changed == prompt_path or changed.startswith("model/") and changed.endswith(".properties") or changed.startswith("docs/designs/") and Path(changed).suffix in {".md", ".json"}
                    self.check(permitted, f"infrastructure destroy phase permits only observed models/generated views/active contract: {changed}")
            elif self.task_type == "scenario-test":
                permitted = changed == prompt_path or self.under(changed, "tests/scenarios") or self.under(changed, "tests/results")
                self.check(permitted, f"scenario-test task boundary violation: {changed}")
            elif self.task_type in {"initialization", "governance", "catalog-maintenance", "migration"}:
                forbidden = self.under(changed, "tests/scenarios") or self.under(changed, "tests/results")
                self.check(not forbidden, f"{self.task_type} task boundary violation: {changed}")


    def check_issue_gate(self) -> None:
        if not self.task_type:
            return
        try:
            scope = active_scope(self.root)
            if self.task_type == "migration" and scope:
                reports = {f"issues/{env}/{target}/{name}" for env, target, _ in scope
                           for name in ("issues.md", "iac-issues.md", "diff.md")}
                prompt = task_path(self.root)
                permitted = reports | {self.relative(prompt)}
                lines = prompt.read_text(encoding="utf-8").splitlines()
                allowed = self.section(lines, "## Allowed paths")
                allowed = {line[3:-1] for line in allowed if re.fullmatch(r"- `[^`]+`", line)}
                if allowed & reports and allowed <= permitted and self.changed_paths <= permitted:
                    return  # Report-only saves may continue; model saves and AWS guards still apply.
            service_changed = any(path.startswith(("model/", "docs/designs/", "infra/", "issues/")) for path in self.changed_paths)
            if self.task_type in {"governance", "catalog-maintenance"} and scope is None and not service_changed:
                scope = set()  # Framework-wide validation does not target consumer services.
            require_no_issues(self.root, scope)
        except (OSError, ValueError) as error:
            self.check(False, str(error))


    def check_task_type_requirements(self) -> None:
        changed = {path for path in self.changed_paths if not TASK_NAME.fullmatch(path)}
        if self.task_type == "initialization":
            self.check("project.json" in changed, "initialization task must change project.json")
        elif self.task_type == "design":
            markdown = {path for path in changed if path.startswith("docs/designs/") and path.endswith(".md")}
            artifacts = {path for path in changed if path.startswith("docs/designs/") and path.endswith(".json")}
            model_files = {path for path in changed if path.startswith("model/") and path.endswith(".properties")}
            models = {service_model_path(self.root / path, self.root / "model").relative_to(self.root).as_posix()
                      for path in model_files}
            self.check(bool(models), "design task must change authoritative service properties")
            for path in markdown:
                expected = "model/" + path.removeprefix("docs/designs/").removesuffix(".md") + ".properties"
                self.check(expected in models, f"changed design Markdown lacks changed service model: {path}")
            for path in artifacts:
                parts = Path(path).parts
                if len(parts) >= 6:
                    expected = f"model/{parts[2]}/{parts[3]}/{parts[4]}.properties"
                    self.check(expected in models, f"changed design JSON lacks changed service model: {path}")
        elif self.task_type == "infrastructure":
            iac_changed = any(self.under(path, "infra") for path in changed)
            if self.infrastructure_phase == "implement":
                self.check(iac_changed, "infrastructure implement phase must change selected IaC")
            elif self.infrastructure_phase == "deploy":
                if iac_changed:
                    from deploy_preparation import repair_changes
                    try:
                        repair_changes(self.root, task_path(self.root).read_text(encoding="utf-8"),
                                       {path for path in changed if self.under(path, "infra")})
                    except (OSError, ValueError, KeyError, TypeError) as error:
                        self.check(False, f"infrastructure deploy phase must not change IaC without controlled repair evidence: {error}")
            elif self.infrastructure_phase == "update":
                self.check(iac_changed, "infrastructure update phase must change selected IaC")
                self.check(
                    any(path.startswith("docs/designs/") and path.endswith(".md") for path in changed),
                    "infrastructure update phase must include generated detailed-design Markdown",
                )
                self.check(
                    any(path.startswith("model/") and path.endswith(".properties") for path in changed),
                    "infrastructure update phase must include human-changed authoritative service properties",
                )
            elif self.infrastructure_phase == "destroy":
                self.check(not iac_changed, "infrastructure destroy phase must not change IaC")
                for relative in sorted(changed):
                    if not relative.startswith("model/") or not relative.endswith(".properties"):
                        continue
                    before = subprocess.run(["git", "show", "HEAD:" + relative], cwd=self.root,
                                            capture_output=True, text=True, encoding="utf-8")
                    path = self.root / relative
                    try:
                        old = properties(before.stdout) if before.returncode == 0 else {}
                        new = properties(path.read_text(encoding="utf-8")) if path.is_file() else {}
                        intended = lambda values: {key: value for key, value in values.items() if not key.startswith("observed.")}
                        self.check(intended(old) == intended(new), f"infrastructure destroy phase must not change desired/display model: {relative}")
                    except (OSError, ValueError) as error:
                        self.check(False, f"destroy observed-only validation: {relative}: {error}")
        elif self.task_type == "scenario-test":
            self.check(any(self.under(path, "tests/scenarios") for path in changed), "scenario-test task must change a scenario")
            self.check(any(self.under(path, "tests/results") for path in changed), "scenario-test task must change its current result")
        elif self.task_type == "governance":
            self.check(bool(changed), "governance task must change framework files")
        elif self.task_type == "catalog-maintenance":
            self.check(any(self.under(path, "framework/materials/aws") for path in changed), "catalog-maintenance task must change catalog files")
            self.check("framework/materials/catalog.sha256" in changed, "catalog-maintenance task must update framework/materials/catalog.sha256")
        elif self.task_type == "migration":
            self.check(bool(changed), "migration task must change its required outputs")


    def check_acceptance_checks(self, registered) -> None:
        for requirement_id, kind, value in self.acceptance_checks:
            if kind != "check" and any(self.matches(path, value) for path in self.deferred_files):
                self.deferred_acceptance.append(f"{requirement_id}:{kind}:{value}")
                continue  # Pending work is not a passed Acceptance check.
            before = len(self.findings.errors)
            if kind == "changed":
                self.check(any(self.matches(path, value) for path in self.changed_paths), f"required changed path missing: {requirement_id}: {value}")
            elif kind == "exists":
                self.check(any(self.root.glob(value)), f"required path missing: {requirement_id}: {value}")
            elif kind == "absent":
                self.check(not any(self.root.glob(value)), f"forbidden path exists: {requirement_id}: {value}")
            else:
                handler = registered.get(value)
                self.check(handler is not None, f"unknown registered Acceptance check: {requirement_id}: {value}")
                if handler:
                    handler()
            if len(self.findings.errors) == before:
                self.acceptance_results.append(f"{requirement_id}:{kind}:{value}")


    def check_tasks(self) -> None:
        try:
            reservations(self.root, contracts(self.root))
        except (OSError, ValueError) as error:
            self.check(False, str(error))

