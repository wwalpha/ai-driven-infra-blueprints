"""Task boundary and Acceptance state."""

from __future__ import annotations

import re
from pathlib import Path

import deploy.contracts as _imports_deploy_contracts
import import_guard as _imports_import_guard
import model.importing.repository as repository
import model.observed as _imports_model_observed
import worktree_state
from model.core import properties as properties
from model.impact import task_impact
from task_contract_core import (
    TASK_NAME,
    issues_save_only,
    matches,
    task_path,
    task_snapshot,
)
from task_contract_core import TASK_TYPES as TASK_TYPES
from utils.git_changes import GitWorkingPaths, collect_working_paths, read_paths
from utils.input_cache import input_text


class TaskValidation:
    def __init__(self, root, findings, *, final_candidate=None):
        self.root = root
        self.final_candidate = final_candidate
        self.findings = findings
        self.check = findings.check
        self.relative = findings.relative
        self.changed_paths = set()
        self.permission_paths = None
        self.baseline = None
        self.baseline_fixed = False
        self.issues_only = False
        self.task_type = ""
        self.infrastructure_phase = ""
        self.requirement_ids = []
        self.acceptance_checks = []
        self.acceptance_results = []
        self.impact = None
        self.design_impact = None
        self.contract_text = None
        self.import_checked = False

    @property
    def scope_paths(self):
        return (
            self.changed_paths
            if self.permission_paths is None
            else self.permission_paths
        )

    def git_paths(self, args: list[str]) -> set[str]:
        return read_paths(self.root, *args)

    def fix_baseline(self):
        if self.final_candidate is not None:
            self.baseline = self.final_candidate.base_commit
            self.baseline_fixed = True
            return
        if self.baseline_fixed:
            return
        self.issues_only = issues_save_only(self.root)
        if self.issues_only:
            self.baseline_fixed = True
            return
        prompt = task_path(self.root, required=False)
        start = (
            repository.task_start_commit(
                self.root,
                prompt.relative_to(self.root).as_posix(),
            )
            if prompt is not None
            else None
        )
        if start is None:
            head = worktree_state.git(
                self.root, "rev-parse", "--verify", "HEAD^{commit}", check=False
            )
            if head.returncode == 0:
                start = head.stdout.strip()
            else:
                # A missing branch ref is unborn; detached/broken HEAD and non-Git fail.
                ref = worktree_state.output(self.root, "symbolic-ref", "HEAD")
                missing = worktree_state.git(
                    self.root, "show-ref", "--verify", "--quiet", ref, check=False
                )
                if missing.returncode != 1:
                    raise ValueError("cannot determine Git baseline: invalid HEAD")
        self.baseline = start  # None explicitly means the empty unborn baseline.
        self.baseline_fixed = True

    def final_paths(self, working: GitWorkingPaths | None = None) -> set[str]:
        if self.final_candidate is not None:
            return set(self.final_candidate.changed_paths)
        self.fix_baseline()
        if self.issues_only:
            return set()
        untracked = (
            working.untracked
            if working is not None
            else self.git_paths(["ls-files", "--others", "--exclude-standard", "-z"])
        )
        if self.baseline is None:
            tracked = {
                p
                for p in self.git_paths(["ls-files", "--cached", "-z"])
                if (self.root / p).exists() or (self.root / p).is_symlink()
            }
        else:
            tracked = self.git_paths(
                ["diff", "--no-renames", "--name-only", "-z", self.baseline, "--"]
            )
        return (tracked | untracked) - {".lock"}

    def check_task_scope(self, contract_text=None) -> None:
        require_import_changes = _imports_import_guard.require_import_changes
        self.fix_baseline()
        prompt = task_path(self.root, required=False)
        if self.final_candidate is not None:
            self.changed_paths = self.final_paths()
            self.permission_paths = set(self.final_candidate.changed_paths)
        elif self.issues_only:
            self.changed_paths, self.permission_paths = set(), set()
        else:
            working = collect_working_paths(self.root, path_reader=self.git_paths)
            self.changed_paths = self.final_paths(working)
            self.permission_paths = set(working.all_paths) - {".lock"}
            if self.baseline is not None:
                self.permission_paths |= self.git_paths(
                    [
                        "diff",
                        "--no-renames",
                        "--name-only",
                        "-z",
                        self.baseline,
                        "HEAD",
                        "--",
                    ]
                ) - {".lock"}
        if not self.permission_paths and (
            prompt is None or "- Task type:" not in task_snapshot(self.root).text
        ):
            return
        if prompt is None:
            self.check(
                not self.permission_paths,
                "selected task contract missing while repository has changes",
            )
            return

        self.contract_text = (
            contract_text
            if contract_text is not None
            else task_snapshot(self.root).text
        )
        lines = self.contract_text.splitlines()
        contract = self.section(lines, "## Task contract")
        task_types = []
        for line in contract:
            match = re.fullmatch(r"- Task type: `([^`]+)`", line)
            if match:
                task_types.append(match.group(1))
        self.check(
            len(task_types) == 1,
            f"Task type must appear exactly once in Task contract: {self.relative(prompt)}",
        )
        if task_types:
            self.task_type = task_types[0]
            self.check(
                self.task_type in TASK_TYPES, f"unknown Task type: {self.task_type}"
            )

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
                self.infrastructure_phase
                in {"implement", "deploy", "update", "destroy"},
                f"unknown Infrastructure phase: {self.infrastructure_phase}",
            )

        requirement_ids: list[str] = []
        for line in self.section(lines, "## Required changes"):
            if not line.startswith("- "):
                continue
            match = re.fullmatch(r"- \[([A-Z][A-Z0-9-]*)\] .+", line)
            self.check(
                match is not None,
                f"invalid Required changes entry: {self.relative(prompt)}: {line}",
            )
            if match:
                requirement_ids.append(match.group(1))
        self.check(
            bool(requirement_ids),
            f"Required changes section missing or empty: {self.relative(prompt)}",
        )
        self.check(
            len(requirement_ids) == len(set(requirement_ids)),
            f"duplicate requirement ID: {self.relative(prompt)}",
        )
        self.requirement_ids = requirement_ids

        acceptance_ids: set[str] = set()
        for line in self.section(lines, "## Acceptance checks"):
            if not line.startswith("- "):
                continue
            match = re.fullmatch(
                r"- \[([A-Z][A-Z0-9-]*)\] `(changed|exists|absent|check):([^`]+)`",
                line,
            )
            self.check(
                match is not None,
                f"invalid Acceptance checks entry: {self.relative(prompt)}: {line}",
            )
            if not match:
                continue
            requirement_id, kind, value = match.groups()
            acceptance_ids.add(requirement_id)
            self.acceptance_checks.append((requirement_id, kind, value))
            self.check(
                requirement_id in requirement_ids,
                f"Acceptance check uses unknown requirement ID: {requirement_id}",
            )
            if kind != "check":
                candidate = Path(value)
                self.check(
                    not candidate.is_absolute() and ".." not in candidate.parts,
                    f"unsafe Acceptance check path: {value}",
                )
        for requirement_id in requirement_ids:
            self.check(
                requirement_id in acceptance_ids,
                f"requirement has no Acceptance check: {requirement_id}",
            )

        allowed = [
            match.group(1)
            for line in self.section(lines, "## Allowed paths")
            if (match := re.fullmatch(r"- `([^`]+)`", line))
        ]
        self.check(
            bool(allowed),
            f"Allowed paths section missing or empty: {self.relative(prompt)}",
        )

        delegated = set()
        if self.infrastructure_phase == "deploy":
            try:
                accepted_changes = _imports_deploy_contracts.accepted_changes
                delegated = accepted_changes(
                    self.root, self.contract_text, self.permission_paths
                )
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.check(False, f"invalid child IaC attribution: {error}")
        for changed in sorted(self.permission_paths - delegated):
            permitted = any(self.matches(changed, pattern) for pattern in allowed)
            self.check(permitted, f"changed path is outside task scope: {changed}")
        self.check_task_boundary(prompt, self.scope_paths)
        try:
            # Normal Task validation also covers generation=True, with stricter IMPORT completion.
            for warning in (
                require_import_changes(
                    self.root, self.scope_paths, final_candidate=self.final_candidate
                )
                or ()
            ):
                self.findings.warn(warning)
            self.import_checked = True
        except (OSError, ValueError, KeyError) as error:
            self.check(False, str(error))

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

    def check_task_boundary(self, prompt: Path, paths=None) -> None:
        if self.task_type not in TASK_TYPES:
            return
        prompt_path = self.relative(prompt)
        for changed in sorted(self.changed_paths if paths is None else paths):
            if self.task_type == "design":
                forbidden = self.under(changed, "infra") or self.under(changed, "tests")
                self.check(not forbidden, f"design task boundary violation: {changed}")
            elif self.task_type == "infrastructure":
                forbidden = self.under(changed, "tests")
                self.check(
                    not forbidden, f"infrastructure task boundary violation: {changed}"
                )
                if self.infrastructure_phase == "destroy":
                    permitted = (
                        changed == prompt_path
                        or changed.startswith("model/")
                        and changed.endswith(".properties")
                        or changed.startswith("docs/designs/")
                        and Path(changed).suffix in {".md", ".json"}
                    )
                    self.check(
                        permitted,
                        f"infrastructure destroy phase permits only observed models/generated views/active contract: {changed}",
                    )
            elif self.task_type == "scenario-test":
                permitted = (
                    changed == prompt_path
                    or self.under(changed, "tests/scenarios")
                    or self.under(changed, "tests/results")
                )
                self.check(
                    permitted, f"scenario-test task boundary violation: {changed}"
                )
            elif self.task_type in {
                "initialization",
                "governance",
                "catalog-maintenance",
                "migration",
            }:
                forbidden = self.under(changed, "tests/scenarios") or self.under(
                    changed, "tests/results"
                )
                self.check(
                    not forbidden,
                    f"{self.task_type} task boundary violation: {changed}",
                )

    def check_task_type_requirements(self) -> None:
        changed = {path for path in self.changed_paths if not TASK_NAME.fullmatch(path)}
        if self.task_type == "initialization":
            self.check(
                "project.json" in changed,
                "initialization task must change project.json",
            )
        elif self.task_type == "design":
            markdown = {
                path
                for path in changed
                if path.startswith("docs/designs/") and path.endswith(".md")
            }
            artifacts = {
                path
                for path in changed
                if path.startswith("docs/designs/") and path.endswith(".json")
            }
            model_files = {
                path
                for path in changed
                if path.startswith("model/") and path.endswith(".properties")
            }
            design_sources = set(model_files)
            text = self.contract_text or task_snapshot(self.root).text
            if "- Workflow: `import`" in self.section(
                text.splitlines(), "## Task contract"
            ):
                require_import_changes = _imports_import_guard.require_import_changes
                try:
                    if not self.import_checked:
                        require_import_changes(
                            self.root,
                            self.scope_paths,
                            final_candidate=self.final_candidate,
                        )
                except (OSError, ValueError) as error:
                    self.check(False, str(error))
            models = {
                "model/" + "/".join(entry) + ".properties"
                for entry in (
                    self.design_impact
                    if self.design_impact is not None
                    else task_impact(
                        self.root, design_sources, base=self.baseline
                    ).services
                )
            }
            self.check(
                bool(design_sources) and bool(models),
                "design task must change authoritative properties service inputs",
            )
            for path in markdown:
                expected = (
                    "model/"
                    + path.removeprefix("docs/designs/").removesuffix(".md")
                    + ".properties"
                )
                self.check(
                    expected in models,
                    f"changed design Markdown lacks changed service model: {path}",
                )
            for path in artifacts:
                parts = Path(path).parts
                if len(parts) >= 6:
                    expected = f"model/{parts[2]}/{parts[3]}/{parts[4]}.properties"
                    self.check(
                        expected in models,
                        f"changed design JSON lacks changed service model: {path}",
                    )
        elif self.task_type == "infrastructure":
            iac_changed = any(self.under(path, "infra") for path in changed)
            if self.infrastructure_phase == "implement":
                self.check(
                    iac_changed,
                    "infrastructure implement phase must change selected IaC",
                )
            elif self.infrastructure_phase == "deploy":
                if iac_changed:
                    accepted_changes = _imports_deploy_contracts.accepted_changes
                    try:
                        attributed = accepted_changes(
                            self.root,
                            task_snapshot(self.root).text,
                            {path for path in changed if self.under(path, "infra")},
                        )
                        self.check(
                            attributed
                            == {path for path in changed if self.under(path, "infra")},
                            "infrastructure deploy phase must not change IaC without verified child attribution",
                        )
                    except (OSError, ValueError, KeyError, TypeError) as error:
                        self.check(
                            False,
                            f"infrastructure deploy phase must not change IaC: {error}",
                        )
            elif self.infrastructure_phase == "update":
                self.check(
                    iac_changed, "infrastructure update phase must change selected IaC"
                )
                self.check(
                    any(
                        path.startswith("docs/designs/") and path.endswith(".md")
                        for path in changed
                    ),
                    "infrastructure update phase must include generated detailed-design Markdown",
                )
                self.check(
                    any(
                        path.startswith("model/") and path.endswith(".properties")
                        for path in changed
                    ),
                    "infrastructure update phase must include human-changed authoritative properties service inputs",
                )
            elif self.infrastructure_phase == "destroy":
                self.check(
                    not iac_changed, "infrastructure destroy phase must not change IaC"
                )
                for relative in sorted(changed):
                    if relative.startswith("model/"):
                        try:
                            verify_observed_outputs = (
                                _imports_model_observed.verify_observed_outputs
                            )
                            if self.baseline is None:
                                raise ValueError(
                                    "destroy requires a versioned Model baseline"
                                )
                            previous = worktree_state.git(
                                self.root,
                                "show",
                                self.baseline + ":" + relative,
                                check=False,
                            )
                            if previous.returncode:
                                raise ValueError(
                                    "destroy cannot add or remove Model files"
                                )
                            path = self.root / relative
                            verify_observed_outputs(
                                {path: previous.stdout.encode("utf-8")},
                                {path: input_text(path, encoding="utf-8")},
                            )
                        except (OSError, ValueError, TypeError) as error:
                            self.check(
                                False,
                                f"destroy permits only observation patches: {relative}: {error}",
                            )

    def check_acceptance_checks(
        self, registered, scope=None, *, results_only=False
    ) -> None:
        for requirement_id, kind, value in self.acceptance_checks:
            before = len(self.findings.errors)
            if kind == "changed":
                self.check(
                    any(self.matches(path, value) for path in self.changed_paths),
                    f"required changed path missing: {requirement_id}: {value}",
                )
            elif kind == "exists":
                self.check(
                    any(self.root.glob(value)),
                    f"required path missing: {requirement_id}: {value}",
                )
            elif kind == "absent":
                self.check(
                    not any(self.root.glob(value)),
                    f"forbidden path exists: {requirement_id}: {value}",
                )
            else:
                handler = registered.get(value)
                self.check(
                    handler is not None,
                    f"unknown registered Acceptance check: {requirement_id}: {value}",
                )
                if handler:
                    result = (
                        self.findings.result(value, scope)
                        if results_only
                        else self.findings.evaluate(value, scope, handler)
                    )
                    self.check(
                        result.status == "PASS"
                        or (
                            self.task_type in {"design", "migration"}
                            and result.model_completion_allowed
                        ),
                        f"Acceptance check is {result.status}: {requirement_id}: {value}",
                    )
            if len(self.findings.errors) == before:
                self.acceptance_results.append(f"{requirement_id}:{kind}:{value}")
