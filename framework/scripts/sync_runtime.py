"""Select, project, compare and publish Model views; independent of the CLI."""

import json
import re
import tempfile
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from functools import partial as _bind_framework_callback
from pathlib import Path

import import_guard as _imports_import_guard
import model.importing.cli as _imports_model_importing_cli
import model.importing.scope as _imports_model_importing_scope
import model.projection as _imports_model_projection
import model.sources as _imports_model_sources
import sync_views
import task_contract_core as _imports_task_contract
import validation_cache as _imports_validation_cache
from aws_mapping_display import validate_mappings as validate_mappings
from design.document import DisplayMismatchError, require_saved_identity
from design.layout_schema import STACK_DESIGN
from generation_inputs import GenerationInputs
from model.change_scope import change_reads, index_stage
from model.core import (
    ReferenceDiagnosticError,
    ReferenceResolutionError,
    entries,
    require_reference_diagnostics,
)
from model.format import JSON_LINK
from model.importing.scope import scoped as import_scoped
from model.importing.scope import selected as import_selection
from model.projection import resource_row_scope
from model.references import _json as model_json
from model.render import generate_files as generate_files
from model.render import render_validated_model as markdown_for
from model.sources import (
    _publish_transaction,
    load_model,
    model_exists,
    publication_lock,
    safe,
)
from model.sources import model_paths as registered_models
from model.validation import (
    validate_kms_policy_accounts as validate_kms_policy_accounts,
)
from model.validation import (
    validate_required_properties as validate_required_properties,
)
from sync_files import markdown_newlines
from sync_files import restore_files as restore_files
from sync_files import save_files as save_files
from sync_progress import (
    advance,
    completed,
    consumers,
    output_file,
    phase,
    total,
    tracked_sync,
)
from sync_progress import stage as progress_stage
from task_contract_core import task_path as task_path
from task_contract_core import task_read_scope, task_reads
from task_contract_core import task_revision as task_revision
from utils.aws_mappings import definition_root, mapping_alias
from utils.input_cache import (
    input_bytes,
    input_context,
    input_is_file,
    input_recorder,
    input_scope,
    input_select,
    recording_inputs,
)
from utils.input_cache import memo_table as memo_table
from utils.json_format import policy_json
from validation.diagnostics import (
    Diagnostic,
    display_diagnostics,
    service_scope,
)
from validation.findings import FindingsError
from validation_scope import scoped_files


def generation_failure(
    root, failures, code, path, message, *, target=None, affected=()
):
    if isinstance(message, FindingsError):
        checked = message.findings
        for diagnostic in checked.diagnostics:
            if not any(item.identity == diagnostic.identity for item in failures):
                failures.append(diagnostic)
        remaining = checked.unstructured_errors
        if not remaining:
            return
        message = ValueError("\n- ".join(remaining))
    if isinstance(message, Exception):
        message = (
            f"{path.relative_to(root)}: {message}" if path is not None else str(message)
        )
    diagnostic = Diagnostic.create(
        root,
        code=code,
        cause_kind="input_invalid" if code == "generation.mismatch" else "unclassified",
        check_id="framework.generated-service-model",
        service=service_scope(root, path),
        source_path=path,
        target_path=target,
        message=message,
        affected_services=tuple(sorted(affected)),
    )
    if not any(item.identity == diagnostic.identity for item in failures):
        failures.append(diagnostic)


def local_design_links(root, path, texts):
    """Existing local link targets, read through the generation input recorder."""
    result = set()
    for text in texts:
        for raw in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if raw.startswith(("https://", "http://", "mailto:")):
                continue
            target = raw.partition("#")[0]
            linked = (path.parent / target if target else path).resolve()
            if linked.is_relative_to(root / "docs/designs") and input_is_file(linked):
                safe(root, path.parent / target if target else path)
                result.add(linked)
    return result


def _callback_stage_inputs_links(root, /, path, texts):
    return {
        linked
        for linked in local_design_links(root, path, texts)
        if linked.suffix == ".md"
    }


def _callback_stage_inputs_add_model(
    inputs, models, reads, root, source_scope, visited, /, model
):
    pending = [model]
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        if not model_exists(current, reads):
            continue
        dependencies = load_model(current, reads).dependencies
        inputs.update(dependencies)
        # Stage authoritative dependencies, including producers of auxiliary Models.
        pending.extend(
            source_scope(root, path).path
            for path in dependencies
            if path.is_relative_to(models)
        )


@progress_stage("stage-placement/dependency-models")
def stage_inputs(
    stage,
    root,
    destinations,
    model_paths,
    markdown_paths,
    services,
    write,
    snapshot=None,
    definitions_root=None,
):
    """Copy the consumed project dependencies; definitions always stay at their source."""
    FileReads = _imports_model_sources.FileReads
    source_scope = _imports_model_sources.source_scope
    docs, models = root / "docs/designs", root / "model"
    views = set(markdown_paths)
    targets = {p.parent.relative_to(docs) for p in destinations}
    links = _bind_framework_callback(_callback_stage_inputs_links, root)
    for path, values in destinations.items():
        views.update(links(path, values.values()))
    # The Change Plan already selected affected consumers; retained peers are not inputs.
    inputs, visited = set(), set()
    reads = snapshot or FileReads()
    add_model = _bind_framework_callback(
        _callback_stage_inputs_add_model,
        inputs,
        models,
        reads,
        root,
        source_scope,
        visited,
    )
    for path in model_paths:
        if (docs / path.relative_to(models)).with_suffix(".md") in destinations:
            add_model(path)
    for path, values in destinations.items():
        target = models / path.parent.relative_to(docs)
        if path.name == STACK_DESIGN and any(
            key.startswith("desired.artifact.")
            or key == "desired.deployment.templateBucket"
            for key in values
        ):
            add_model(target / "s3.properties")
        if any(key.endswith(".cfn-logicalId") for key in values):
            add_model(target / "cloudformation-stacks.properties")
    # Bound anchors come from Models, independently of the saved Markdown.
    for view in views:
        add_model(models / view.relative_to(docs).with_suffix(".properties"))
    for view in views | destinations.keys():
        if view.name == STACK_DESIGN:
            environment, target = view.parent.relative_to(docs).parts
            for model in registered_models(root, environment, target):
                add_model(model)
    inputs.update(views)
    for path, texts in [(p, values.values()) for p, values in destinations.items()] + [
        (p, [input_bytes(p).decode("utf-8", errors="replace")])
        for p in views
        if p not in destinations and input_is_file(p)
    ]:
        inputs.update(
            linked
            for linked in local_design_links(root, path, texts)
            if linked.suffix != ".md"
        )
    # Stage existing JSONs only within the selected service ownership directories.
    for view in set(markdown_paths) | destinations.keys():
        inputs.update(
            input_select(
                view.with_suffix(""),
                "*.json",
                recursive=True,
                kinds=("file", "symlink"),
            )
        )
    if input_is_file(root / "project.json"):
        inputs.add(root / "project.json")
    with phase("stage-placement", total=len(inputs)):
        for path in sorted(inputs):
            if snapshot is not None:
                snapshot.copy_to_stage([path])
            else:
                destination = stage / path.relative_to(root)
                if input_is_file(path):
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(input_bytes(path))
            advance()
    failed_views = {
        (docs / p.relative_to(models)).with_suffix(".md") for p in model_paths
    } - destinations.keys()
    saved_paths = sorted(
        p
        for p in views
        if p not in failed_views and p.parent.relative_to(docs) in targets
    )
    return saved_paths


@progress_stage("candidate-generation")
@resource_row_scope()
def generate_views(
    stage,
    root,
    destinations,
    failures,
    definitions_root=None,
    *,
    warnings=None,
    unavailable=None,
    strict=False,
):
    warnings = warnings if warnings is not None else []
    unavailable = unavailable if unavailable is not None else {}
    definitions_root = definitions_root or definition_root(root)
    total(len(destinations))
    generated = {}
    # Render all valid base views before resolving cross-service links.
    for path, values in destinations.items():
        staged = stage / path.relative_to(root)
        artifacts = {}
        documents = {}
        failure_start = len(failures)
        try:
            model = _imports_model_sources.raw_model(
                (root / "model" / path.relative_to(root / "docs/designs")).with_suffix(
                    ".properties"
                )
            )
            diagnostics = []
            resolver = _imports_model_projection.reference_resolver(
                values, model.scope, root
            )
            project_document = (
                _imports_model_projection.generated_document
                if strict
                else _imports_model_projection.design_document
            )
            for identity, row in entries(values, "desired.row."):
                match = JSON_LINK.fullmatch(row.get("value", ""))
                if not match:
                    if "document" in row:
                        raise ValueError(
                            f"JSON document requires an artifact link: {identity}"
                        )
                    raw, structured = model_json(
                        f"desired.row.{identity}.value", row["value"]
                    )
                    if structured and strict:
                        try:
                            project_document(
                                raw,
                                root,
                                property_name=row["property"],
                                scope=model.scope,
                                resolver=resolver,
                                logical_id=values.get(
                                    f"desired.resource.{identity.rpartition('-')[0]}.logicalId"
                                ),
                                model_key=f"desired.row.{identity}.value",
                                context=_imports_model_projection.reference_context_for(
                                    values, identity, row, raw, "", root
                                ),
                                warnings=warnings,
                            )
                        except ReferenceDiagnosticError as error:
                            diagnostics.extend(error.diagnostics)
                    continue
                if "document" not in row:
                    raise ValueError(
                        f"authoritative JSON document missing: {path.name}: {identity}"
                    )
                artifact = (staged.parent / match.group(1)).resolve()
                safe(stage, staged.parent / match.group(1))
                if artifact.parent != staged.with_suffix("").resolve():
                    raise ValueError(
                        f"JSON artifact must belong to owning service: {identity}"
                    )
                try:
                    raw_document = policy_json(row["document"])
                    previous = documents.setdefault(artifact, raw_document)
                    if previous != raw_document:
                        raise ValueError(
                            "conflicting authoritative JSON documents: " + artifact.name
                        )
                    document = project_document(
                        raw_document,
                        root,
                        property_name=row["property"],
                        scope=model.scope,
                        resolver=resolver,
                        logical_id=values.get(
                            f"desired.resource.{identity.rpartition('-')[0]}.logicalId"
                        ),
                        model_key=f"desired.row.{identity}.document",
                        context=_imports_model_projection.reference_context_for(
                            values, identity, row, raw_document, "", root
                        ),
                        warnings=warnings,
                    )
                except ReferenceDiagnosticError as error:
                    diagnostics.extend(error.diagnostics)
                    continue
                if strict:
                    # Readiness checks must not materialize physical values in saved designs.
                    document = _imports_model_projection.design_document(
                        raw_document,
                        root,
                        property_name=row["property"],
                        scope=model.scope,
                        resolver=resolver,
                        logical_id=values.get(
                            f"desired.resource.{identity.rpartition('-')[0]}.logicalId"
                        ),
                        model_key=f"desired.row.{identity}.document",
                        context=_imports_model_projection.reference_context_for(
                            values, identity, row, raw_document, "", root
                        ),
                        warnings=warnings,
                    )
                if not isinstance(document, dict):
                    raise ValueError(f"JSON document must be an object: {identity}")
                content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
                if artifact in artifacts and artifacts[artifact] != content:
                    raise ValueError(
                        f"conflicting authoritative JSON documents: {artifact.name}"
                    )
                artifacts[artifact] = content
            if strict:
                require_reference_diagnostics(diagnostics)
            warnings.extend(d for d in diagnostics if d not in warnings)
            save_files(artifacts)
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_text(
                markdown_for(staged, values, stage, definitions_root=definitions_root),
                encoding="utf-8",
                newline="",
            )
            generated[path] = [*artifacts, staged]
        except ReferenceDiagnosticError as error:
            warnings.extend(
                {**diagnostic, "source": str(path.relative_to(root))}
                for diagnostic in error.diagnostics
            )
            if not strict or not isinstance(error, ReferenceResolutionError):
                message = f"{path.relative_to(root)}: {error}"
                generation_failure(
                    root, failures, "generation.reference", path, message
                )
            if len(failures) == failure_start:
                unavailable[path] = {
                    "reason": "reference",
                    "status": "NOT_RUN",
                    "diagnostics": error.diagnostics,
                    "retainedView": str(path.relative_to(root))
                    if input_is_file(path)
                    else None,
                }
            generated.pop(path, None)
            restore_view(stage, root, path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            generation_failure(
                root,
                failures,
                "generation.render",
                path,
                f"{path.relative_to(root)}: {error}",
            )
            restore_view(stage, root, path)
        advance()
    return generated


def restore_view(stage: Path, root: Path, path: Path) -> None:
    """Discard a failed service's temporary view and retain its saved reference state."""
    staged = stage / path.relative_to(root)
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.unlink(missing_ok=True)
    if path.is_file():
        staged.write_bytes(input_bytes(path))
    for file in staged.with_suffix("").rglob("*.json"):
        file.unlink()
    files = set(
        input_select(
            path.with_suffix(""), "*.json", recursive=True, kinds=("file", "symlink")
        )
    )
    for file in files:
        destination = stage / file.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(input_bytes(file))


def selected(
    path: Path,
    base: Path,
    environment: str | None,
    target_directory: str | None,
) -> bool:
    relative = path.relative_to(base)
    return (
        len(relative.parts) == 3
        and (environment is None or relative.parts[0] == environment)
        and (target_directory is None or relative.parts[1] == target_directory)
    )


def verify_saved(expected):
    for file, content in expected.items():
        if not file.is_file() or file.read_bytes() != content.encode("utf-8"):
            raise ValueError(f"generated output was not saved correctly: {file}")
    for view in (file for file in expected if file.suffix == ".md"):
        artifacts = {
            file
            for file in expected
            if file.suffix == ".json" and file.is_relative_to(view.with_suffix(""))
        }
        if set(view.with_suffix("").rglob("*.json")) != artifacts:
            raise ValueError(f"generated output file set changed: {view}")


def _sync(
    root: Path,
    write: bool,
    environment: str | None = None,
    target_directory: str | None = None,
    services: list[str] | None = None,
    jobs: int = 4,
    definitions_root: Path | None = None,
    snapshot=None,
) -> int:
    require_import_changes = _imports_import_guard.require_import_changes
    root = root.resolve()
    deferred = sync_views._saved_design_validation.get()
    if deferred is not None and (
        write
        or deferred != (root, (environment, target_directory, (services or [None])[0]))
        or services != [deferred[1][2]]
    ):
        raise ValueError(
            "saved design validation requires read-only generation of the selected single service"
        )
    _ = task_revision(root) if write else None
    with phase("import-guard"):
        require_import_changes(root, generation=True)
    if import_selection(root) is not None:
        readable = _imports_model_importing_scope.readable
        expected = {import_selection(root)} if write else readable(root)
        requested = {
            (environment, target_directory, service) for service in services or []
        }
        if not requested or not requested <= expected:
            raise ValueError(
                "IMPORT generation is outside selected environment/target/service"
            )
        if write:
            recover_display = _imports_model_importing_cli.recover_display
            identity = import_selection(root)
            recover_display(root, identity[0], identity[2], identity[1])
            consumers({identity})
            completed(identity)
            return 0
        jobs = 1
    scope = (
        {(environment, target_directory, service) for service in services}
        if services is not None
        else None
    )
    if services is not None and (not environment or not target_directory):
        raise ValueError("service selection requires environment and target directory")
    return run_generation(
        root,
        scope,
        write=write,
        environment=environment,
        target_directory=target_directory,
        jobs=jobs,
        definitions_root=definitions_root,
        snapshot=snapshot,
    )


@contextmanager
def generation_context(root, write, definitions_root=None):
    """The outer execution owns recording/aliases, including IMPORT preflight reads."""
    with task_reads(root):
        definitions_root = definitions_root or definition_root(root)
        with ExitStack() as lifetime:
            lifetime.enter_context(input_context())
            lifetime.enter_context(change_reads())
            if definitions_root != root and definition_root(root) != definitions_root:
                lifetime.enter_context(mapping_alias(definitions_root, root))
            snapshot = input_recorder(root)
            if snapshot is None and (not write or import_selection(root) is None):
                with publication_lock(root, read_only=not write):
                    snapshot = GenerationInputs(
                        root, definitions_root, read_only=not write
                    )
                lifetime.callback(snapshot.close)
                lifetime.enter_context(recording_inputs(snapshot))
                if write:
                    PassCache = _imports_validation_cache.PassCache
                    PassCache(root, definitions_root=definitions_root).common_inputs(
                        snapshot
                    )
            yield snapshot


@tracked_sync
@input_scope
@import_scoped
def sync(
    root,
    write,
    environment=None,
    target_directory=None,
    services=None,
    jobs=4,
    definitions_root=None,
):
    root = root.resolve()
    with generation_context(root, write, definitions_root) as snapshot:
        return _sync(
            root,
            write,
            environment,
            target_directory,
            services,
            jobs,
            definitions_root,
            snapshot,
        )


@dataclass
class Generation:
    root: Path
    stage: Path
    scope: object
    model_paths: list
    markdown_paths: list
    snapshot: object
    lifetime: ExitStack
    destinations: dict = field(default_factory=dict)
    generated: dict = field(default_factory=dict)
    failure_records: list = field(default_factory=list)
    saved: dict = field(default_factory=dict)
    expected_outputs: dict = field(default_factory=dict)
    reference_warnings: list = field(default_factory=list)
    unavailable: dict = field(default_factory=dict)
    candidate: object = field(default_factory=object)
    definitions_root: Path | None = None

    @property
    def failures(self):
        return [diagnostic.message for diagnostic in self.failure_records]

    @property
    def generated_scope(self):
        return {
            (*p.relative_to(self.root / "docs/designs").parts[:2], p.stem)
            for p in self.generated
        }

    def close(self):
        self.lifetime.close()


@progress_stage("snapshot")
@task_read_scope
def prepare_generation(
    root,
    scope,
    *,
    write=True,
    environment=None,
    target_directory=None,
    snapshot=None,
    definitions_root=None,
    strict=False,
):
    """Prepare every selected target in a single disposable stage."""
    if scope == set():
        raise ValueError(
            "--write requires service scope; framework scope cannot generate Models"
        )
    lifetime = ExitStack()
    try:
        # Recover the journal before snapshotting inputs, differences or originals.
        definitions_root = definitions_root or definition_root(root)
        snapshot = snapshot or input_recorder(root)
        if snapshot is not None and input_recorder(root) is not snapshot:
            lifetime.enter_context(recording_inputs(snapshot))
        if snapshot is None:
            with publication_lock(root, read_only=not write):
                snapshot = GenerationInputs(root, definitions_root, read_only=not write)
            lifetime.callback(snapshot.close)
            lifetime.enter_context(recording_inputs(snapshot))
            # Common fingerprints are guarded even when the standalone writer has no cache.
            if write:
                PassCache = _imports_validation_cache.PassCache
                PassCache(root, definitions_root=definitions_root).common_inputs(
                    snapshot
                )
        if definitions_root != root and definition_root(root) != definitions_root:
            lifetime.enter_context(mapping_alias(definitions_root, root))
        docs, models = root / "docs/designs", root / "model"
        model_paths = [
            p
            for p in scoped_files(root, "model", ".properties", scope)
            if selected(p, models, environment, target_directory)
        ]
        markdown_paths = [
            p
            for p in scoped_files(root, "docs/designs", ".md", scope)
            if selected(p, docs, environment, target_directory)
        ]
        if snapshot is not None:
            stage = snapshot.open_stage()
        else:
            stage = Path(
                lifetime.enter_context(tempfile.TemporaryDirectory())
            ).resolve()
            lifetime.enter_context(mapping_alias(definitions_root, stage))
        lifetime.enter_context(_imports_model_sources.model_stage(root, stage))
        lifetime.enter_context(change_reads())
        lifetime.enter_context(index_stage(root, stage))
        plan = Generation(
            root,
            stage,
            scope,
            model_paths,
            markdown_paths,
            snapshot,
            lifetime,
            definitions_root=definitions_root,
        )
        consumers((*p.relative_to(models).parts[:2], p.stem) for p in model_paths)
        for path in model_paths:
            destination = (docs / path.relative_to(models)).with_suffix(".md")
            try:
                with phase("dependency-model", total=1):
                    loaded = load_model(path)
                    advance()
                plan.reference_warnings.extend(getattr(loaded, "warnings", ()))
                plan.destinations[destination] = loaded.values
            except (OSError, ValueError, KeyError, TypeError) as error:
                message = f"{path.relative_to(root)}: {error}"
                if isinstance(error, ReferenceDiagnosticError):
                    plan.reference_warnings.extend(
                        dict(d, model=str(path)) for d in error.diagnostics
                    )
                generation_failure(
                    root,
                    plan.failure_records,
                    "generation.reference"
                    if isinstance(error, ReferenceDiagnosticError)
                    else "generation.model",
                    path,
                    message,
                )
        for path in sorted(
            set(markdown_paths)
            - {(docs / p.relative_to(models)).with_suffix(".md") for p in model_paths}
        ):
            generation_failure(
                root,
                plan.failure_records,
                "generation.model_missing",
                path,
                f"authoritative properties Model inputs missing: {path.relative_to(root)}",
            )
        services = None if scope is None else [entry[2] for entry in scope]
        stage_inputs(
            stage,
            root,
            plan.destinations,
            model_paths,
            markdown_paths,
            services,
            write,
            snapshot,
            definitions_root,
        )
        plan.generated = generate_views(
            stage,
            root,
            plan.destinations,
            plan.failure_records,
            definitions_root=definitions_root,
            warnings=plan.reference_warnings,
            unavailable=plan.unavailable,
            strict=strict,
        )
        return plan
    except BaseException:
        lifetime.close()
        raise


def validate_generation(plan, *, jobs=4, write=True):
    """Freeze generated bytes for publication or independent saved-View comparison."""
    for path, files in plan.generated.items():
        expected = {
            plan.root / file.relative_to(plan.stage): file.read_bytes().decode("utf-8")
            for file in files
        }
        expected[path] = markdown_newlines(path, expected[path])
        plan.expected_outputs[path] = expected
        if plan.snapshot is not None:
            for file in expected:
                plan.snapshot.read(file)


def planned_outputs(plan):
    """Actual publication bytes, excluding no-ops; never mutate Git change state."""
    return {
        path
        for outputs in plan.expected_outputs.values()
        for path, text in outputs.items()
        if plan.snapshot.read(path) != (None if text is None else text.encode("utf-8"))
    }


def publish_generation(plan):
    """Publish projected bytes after exactly one all-target input comparison."""
    root, stage = plan.root, plan.stage
    plan.snapshot.seal()
    with phase("publication"), publication_lock(root) as journal:
        # Compare even a no-op or wholly rejected batch, outside per-service error handling.
        plan.snapshot.verify()
        all_paths = {
            file for outputs in plan.expected_outputs.values() for file in outputs
        }
        task_revision(root)
        task = _imports_task_contract.task_snapshot(root, required=False)
        declared = (
            _imports_task_contract.paths_in(task.text, "## Modified files")
            if task
            else set()
        )
        allowed = (
            _imports_task_contract.paths_in(task.text, "## Allowed paths")
            if task
            else set()
        )
        for file in all_paths:
            safe(root, file)
        for file in planned_outputs(plan) if task is not None else ():
            relative = file.relative_to(root).as_posix()
            parts = file.relative_to(root / "docs/designs").parts
            identity = (*parts[:2], Path(parts[2]).stem)
            if (
                relative not in declared
                or not any(
                    _imports_task_contract.matches(relative, pattern)
                    for pattern in allowed
                )
                or task.scope is not None
                and identity not in task.scope
            ):
                raise ValueError("generated path is outside task scope: " + relative)
        for path, expected in plan.expected_outputs.items():
            changed = {
                p: text
                for p, text in expected.items()
                if plan.snapshot.read(p)
                != (None if text is None else text.encode("utf-8"))
            }
            originals = {p: plan.snapshot.read(p) for p in changed}
            try:
                if changed:
                    _publish_transaction(
                        root,
                        {p: text for p, text in changed.items() if text is not None},
                        {p for p, text in changed.items() if text is None},
                        journal,
                        originals=originals,
                    )
                plan.saved[path] = originals
            except (OSError, ValueError, KeyError, TypeError) as error:
                generation_failure(
                    root,
                    plan.failure_records,
                    "generation.publish",
                    path,
                    error,
                )
                if journal.is_file():
                    raise ValueError(
                        f"publication rollback incomplete; recovery journal retained: {journal}: {error}"
                    ) from error
                restore_view(stage, root, path)
                plan.generated.pop(path, None)


def generation_failed_services(root, diagnostics, paths):
    """Structured ownership is shared by validation, scheduling and reporting."""
    failed, unclassified = {}, []
    for diagnostic in diagnostics:
        affected = set(diagnostic.affected_services)
        if diagnostic.service is not None:
            affected.add(diagnostic.service)
        matched = False
        for path in paths:
            if service_scope(root, path) in affected:
                failed.setdefault(path, []).append(diagnostic.message)
                matched = True
        if not matched:
            unclassified.append(diagnostic.message)
    return failed, unclassified


def generation_failures(plan, selected=None):
    if selected is None:
        selected = (
            set(plan.markdown_paths)
            | set(plan.unavailable)
            | {
                (
                    plan.root / "docs/designs" / path.relative_to(plan.root / "model")
                ).with_suffix(".md")
                for path in plan.model_paths
            }
        )
    failed, unclassified = generation_failed_services(
        plan.root, plan.failure_records, selected
    )
    recorded = {diagnostic.message for diagnostic in plan.failure_records}
    unclassified.extend(message for message in plan.failures if message not in recorded)
    return failed, unclassified


def generation_unavailable(plan):
    """Service failures take precedence; individual wait diagnostics stay on the plan."""
    failed, unclassified = generation_failures(plan)
    if unclassified:
        return {}
    return {path: info for path, info in plan.unavailable.items() if path not in failed}


def generation_metadata(plan):
    unavailable = generation_unavailable(plan)
    return {
        "complete": not unavailable and not plan.failures,
        "status": "FAIL" if plan.failures else "NOT_RUN" if unavailable else "PASS",
        "failures": list(plan.failures),
        "generated": sorted("/".join(scope) for scope in plan.generated_scope),
        "unavailable_services": {
            "/".join(
                (*p.relative_to(plan.root / "docs/designs").parts[:2], p.stem)
            ): info
            for p, info in unavailable.items()
        },
        "unverified": [
            diagnostic
            for diagnostic in plan.reference_warnings
            if diagnostic.get("category") == "REFERENCE_PENDING_DEPLOY"
        ],
        "warnings": plan.reference_warnings,
    }


def report_generation(plan):
    for path in plan.saved:
        completed((*path.relative_to(plan.root / "docs/designs").parts[:2], path.stem))
        print(
            f"Design Markdown sync: PASS ({path.relative_to(plan.root)})",
            file=output_file(),
        )
    selected = set(plan.markdown_paths) | {
        (plan.root / "docs/designs" / p.relative_to(plan.root / "model")).with_suffix(
            ".md"
        )
        for p in plan.model_paths
    }
    not_run = set(generation_unavailable(plan))
    failed = selected - plan.saved.keys() - not_run
    summary = f"{len(plan.saved)} services succeeded; {len(failed)} services failed; {len(not_run)} services NOT_RUN"
    print("Design Markdown generation: " + summary, file=output_file())
    if plan.failures or not_run:
        diagnostics = [
            *plan.failures,
            *(
                f"NOT_RUN: {path.relative_to(plan.root)}: {plan.unavailable[path]['reason']}"
                for path in sorted(not_run)
            ),
        ]
        message = f"{summary}; {len(diagnostics)} diagnostics\n- " + "\n- ".join(
            diagnostics
        )
        if plan.failures:
            raise ValueError(message)
        causes = [
            diagnostic
            for info in plan.unavailable.values()
            for diagnostic in info.get("diagnostics", ())
        ]
        category = (
            "REFERENCE_PENDING_DEPLOY"
            if causes
            and all(d["category"] == "REFERENCE_PENDING_DEPLOY" for d in causes)
            else "REFERENCE_UNRESOLVED"
        )
        raise ReferenceResolutionError(
            message, category=category, code=category, diagnostics=causes or None
        )
    print(
        f"Design Markdown sync: PASS ({len(plan.saved)} services)", file=output_file()
    )


@input_scope
@import_scoped
@task_read_scope
def run_generation(
    root,
    scope,
    *,
    write=True,
    environment=None,
    target_directory=None,
    jobs=4,
    definitions_root=None,
    snapshot=None,
):
    plan = prepare_generation(
        root,
        scope,
        write=write,
        environment=environment,
        target_directory=target_directory,
        definitions_root=definitions_root,
        snapshot=snapshot,
    )
    try:
        validate_generation(plan, jobs=jobs, write=write)
        if write:
            publish_generation(plan)
        else:
            _compare_generation(plan)
        report_generation(plan)
        return 0
    finally:
        plan.close()


def _compare_generation(plan):
    root = plan.root
    for path, expected in plan.expected_outputs.items():
        stale = False
        source = (root / "model" / path.relative_to(root / "docs/designs")).with_suffix(
            ".properties"
        )
        for target, text in expected.items():
            saved_bytes = plan.snapshot.read(target)
            if saved_bytes != (None if text is None else text.encode("utf-8")):
                stale = True
                kind = "Markdown" if target.suffix == ".md" else "JSON"
                if (
                    target == path
                    and saved_bytes is not None
                    and target.suffix == ".md"
                ):
                    try:
                        saved = (
                            saved_bytes.decode("utf-8")
                            .replace("\r\n", "\n")
                            .replace("\r", "\n")
                        )
                        require_saved_identity(saved, text)
                    except ValueError:
                        pass  # Identity validation owns the structural failure.
                    else:
                        mismatch = DisplayMismatchError(target, saved, text)
                        plan.failure_records.extend(
                            diagnostic
                            for diagnostic in display_diagnostics(
                                root,
                                target,
                                mismatch,
                                "framework.generated-service-model",
                            )
                            if diagnostic.details["property"] != "$document"
                        )
                        if mismatch.positions and not mismatch.other_changes:
                            continue
                generation_failure(
                    root,
                    plan.failure_records,
                    "generation.mismatch",
                    source,
                    f"generated {kind} is stale or missing: {target.relative_to(root)}",
                    target=target,
                )
        if not stale:
            plan.saved[path] = {}


def compare_generation(
    root: Path, scope, *, jobs=4, definitions_root=None, findings=None
) -> tuple[str, ...]:
    """Own fresh caches for one independent read-only comparison."""
    with (
        input_context(fresh=True, read_only=True),
        generation_context(root, False, definitions_root),
    ):
        return _comparison(
            root, scope, jobs=jobs, definitions_root=definitions_root, findings=findings
        )


@task_read_scope
def _comparison(root, scope, *, jobs, definitions_root, findings):
    """Compare saved bytes with independently projected Model candidates."""
    if import_selection(root) is not None:
        require_import_changes = _imports_import_guard.require_import_changes
        require_import_changes(root, generation=True)
    plan = prepare_generation(
        root, scope, write=False, definitions_root=definitions_root
    )
    try:
        validate_generation(plan, jobs=jobs, write=False)
        _compare_generation(plan)
        if findings is not None:
            for warning in plan.reference_warnings:
                findings.warn(warning)
            findings.result("framework.generated-service-model", scope).metadata.update(
                generation_metadata(plan)
            )
            for diagnostic in plan.failure_records:
                if diagnostic.code != "generation.reference":
                    findings.add_diagnostic(diagnostic)
        return tuple(
            diagnostic.message
            for diagnostic in plan.failure_records
            if findings is None or diagnostic.code != "generation.reference"
        )
    finally:
        plan.close()
