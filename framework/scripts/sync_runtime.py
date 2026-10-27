"""Select, stage, validate and publish model views; independent of the CLI."""

import json
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState

import import_guard as _imports_import_guard
import model.change_scope as _change_scope
import model.importing.cli as _imports_model_importing_cli
import model.importing.scope as _imports_model_importing_scope
import model.projection as _imports_model_projection
import model.sources as _imports_model_sources
import model.validation as _imports_model_validation
import sync_views
import task_contract_core as _imports_task_contract
import validation_cache as _imports_validation_cache
from aws_mapping_display import validate_mappings as validate_mappings
from design.document import DesignIndex, DisplayMismatchError, require_saved_identity
from design.layout_schema import STACK_DESIGN
from design.policy_tables import rendered_design
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
    stable_id,
)
from validation.findings import Findings, FindingsError
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
        # Auxiliary Models are independently validated in the stage, including their producers.
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
    index = DesignIndex(root)
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
    # Bound anchors and ownership depend on authoritative models of retained views.
    for view in views:
        if any(line.startswith("### ") for line in index.get(view).text.splitlines()):
            referenced = models / view.relative_to(docs).with_suffix(".properties")
            if referenced not in model_paths or view in destinations:
                add_model(referenced)
    for view in views | destinations.keys():
        if view.name == STACK_DESIGN:
            environment, target = view.parent.relative_to(docs).parts
            for model in registered_models(root, environment, target):
                add_model(model)
    inputs.update(views)
    for path, texts in [(p, values.values()) for p, values in destinations.items()] + [
        (p, [index.get(p).text]) for p in views
    ]:
        inputs.update(
            linked
            for linked in local_design_links(root, path, texts)
            if linked.suffix != ".md"
        )
    # Include existing JSONs only for selected services: extra artifacts still fail validation.
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
    baseline_paths = (
        [p for p in saved_paths if p not in destinations]
        if len(destinations) == 1
        else saved_paths
    )
    baseline_links = (
        sync_views.broken_design_links(
            stage,
            root,
            [stage / p.relative_to(root) for p in baseline_paths],
            definitions_root=definitions_root,
        )
        if write
        else {}
    )
    return saved_paths, baseline_links


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
                    if structured:
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
                                context=_imports_model_validation.reference_context_for(
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
                        context=_imports_model_validation.reference_context_for(
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
                        context=_imports_model_validation.reference_context_for(
                            values, identity, row, raw_document, "", root
                        ),
                        warnings=warnings,
                    )
                if not isinstance(document, dict) or "$modelRef" in document:
                    raise ValueError(f"JSON document must be an object: {identity}")
                content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
                if artifact in artifacts and artifacts[artifact] != content:
                    raise ValueError(
                        f"conflicting authoritative JSON documents: {artifact.name}"
                    )
                artifacts[artifact] = content
            if strict or any(
                d["category"] != "REFERENCE_PENDING_DEPLOY" for d in diagnostics
            ):
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
            if not isinstance(error, ReferenceResolutionError):
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
    for path in list(generated):
        failure_start = len(failures)
        try:
            staged = stage / path.relative_to(root)
            if path.name != STACK_DESIGN:
                staged.write_text(
                    rendered_design(staged, definitions_root=definitions_root),
                    encoding="utf-8",
                    newline="",
                )
        except ReferenceDiagnosticError as error:
            warnings.extend(
                {**diagnostic, "source": str(path.relative_to(root))}
                for diagnostic in error.diagnostics
            )
            if not isinstance(error, ReferenceResolutionError):
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
            del generated[path]
            restore_view(stage, root, path)
    return generated


def _callback_validate_candidates_validate(
    _state_validate_candidates_260,
    definitions_root,
    destinations,
    root,
    stage,
    validation,
    task_inputs,
    /,
    path,
):
    with (
        input_context(
            fresh=True,
            read_only=True,
            inputs=_imports_model_sources.fork_model_inputs(
                _state_validate_candidates_260.model_inputs
            ),
        ),
        change_reads(
            metadata={
                key: dict(value)
                for key, value in _state_validate_candidates_260.metadata.items()
            }
        ),
        index_stage(root, stage),
        recording_inputs(_state_validate_candidates_260.recorder),
        task_reads(root, snapshot=task_inputs),
    ):
        try:
            view_scope = _imports_model_importing_scope.view_scope
            identities = {
                (*file.relative_to(root / "docs/designs").parts[:2], file.stem)
                for file in destinations
            }
            if import_selection(root) is not None:
                identities.add(import_selection(root))
            with view_scope(identities):
                return_value = sync_views.validate_views(
                    stage,
                    root,
                    [stage / path.relative_to(root)],
                    destinations,
                    design_index=_state_validate_candidates_260.design_index,
                    definitions_root=definitions_root,
                    candidate_paths=_state_validate_candidates_260.candidate_paths,
                    **(
                        {"context": _state_validate_candidates_260.context}
                        if validation is not None
                        else {}
                    ),
                )
                if validation is not None:
                    validation[path] = return_value
        except (OSError, ValueError, KeyError, TypeError) as error:
            return path, error
        return path, None


@progress_stage("candidate-validation")
def validate_candidates(
    stage,
    root,
    generated,
    destinations,
    failures,
    jobs,
    write,
    validation=None,
    accounts=None,
    definitions_root=None,
):
    with task_reads(root) as task_inputs:
        # A rejected view falls back to its saved state; recheck dependent services.
        _state_validate_candidates_260 = _CallbackState()
        selected_task = _imports_task_contract.selected_task
        selected = _imports_task_contract.task_snapshot(root, required=False)
        captured = task_inputs.catalog or selected
        name, text = (
            (None, None) if selected is None else (selected.name, selected.text)
        )
        validate = (selected_task(root, name if text is not None else None))(
            _bind_framework_callback(
                _callback_validate_candidates_validate,
                _state_validate_candidates_260,
                definitions_root,
                destinations,
                root,
                stage,
                validation,
                captured,
            )
        )

        while generated:
            _state_validate_candidates_260.candidate_paths = (
                {stage / p.relative_to(root) for p in generated} if write else None
            )
            total(len(generated))
            _state_validate_candidates_260.design_index = DesignIndex(
                definitions_root or root
            )  # A new snapshot after each restore_view phase.
            rejected = []
            _state_validate_candidates_260.context = None
            if validation is not None:
                _state_validate_candidates_260.context = sync_views.validation_context(
                    stage,
                    root,
                    generated,
                    destinations,
                    accounts,
                    definitions_root=definitions_root,
                )
                validation[None] = _state_validate_candidates_260.context.findings
                if _state_validate_candidates_260.context.errors:
                    findings = _state_validate_candidates_260.context.findings
                    failure_start = len(failures)
                    generation_failure(
                        root,
                        failures,
                        "generation.candidate",
                        None,
                        FindingsError(findings),
                        affected={service_scope(root, p) for p in generated},
                    )
                    failed, unclassified = generation_failed_services(
                        root,
                        [*findings.diagnostics, *failures[failure_start:]],
                        generated,
                    )
                    rejected = list(generated if unclassified else failed)
                    if not rejected:
                        rejected = list(generated)
                    for path in rejected:
                        del generated[path]
                        restore_view(stage, root, path)
                    continue
            _state_validate_candidates_260.recorder = (
                input_recorder(root) if write else None
            )
            with input_context(
                fresh=True, read_only=True, inputs=dict(memo_table() or {})
            ):
                for source_root in (root, stage):
                    _imports_model_sources._invocation_reads(source_root)
                _state_validate_candidates_260.model_inputs = dict(memo_table())
            _state_validate_candidates_260.metadata = {
                key: dict(value)
                for key, value in (_change_scope.metadata() or {}).items()
            }
            # All candidate views are fixed during this read-only phase.
            with ThreadPoolExecutor(
                max_workers=1 if write else min(jobs, len(generated))
            ) as executor:
                mapper = (
                    map if write or jobs == 1 or len(generated) == 1 else executor.map
                )
                for path, error in mapper(validate, sorted(generated)):
                    advance()
                    if error:
                        generation_failure(
                            root, failures, "generation.candidate", path, error
                        )
                        rejected.append(path)
            if not rejected:
                break
            for path in sorted(set(rejected)):
                del generated[path]
                restore_view(stage, root, path)


def restore_view(stage: Path, root: Path, path: Path) -> None:
    """Discard a failed service's temporary view and retain its saved reference state."""
    staged = stage / path.relative_to(root)
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.unlink(missing_ok=True)
    if path.is_file():
        staged.write_bytes(input_bytes(path))
    shutil.rmtree(staged.with_suffix(""), ignore_errors=True)
    files = set(
        input_select(
            path.with_suffix(""), "*.json", recursive=True, kinds=("file", "symlink")
        )
    )
    if input_is_file(path):
        files.update(
            linked
            for linked in local_design_links(
                root, path, [input_bytes(path).decode("utf-8")]
            )
            if linked.suffix != ".md"
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
    validation: dict = field(default_factory=dict)
    saved: dict = field(default_factory=dict)
    expected_outputs: dict = field(default_factory=dict)
    warnings: dict = field(default_factory=dict)
    reference_warnings: list = field(default_factory=list)
    unavailable: dict = field(default_factory=dict)
    candidate: object = field(default_factory=object)
    accounts: object = None
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
        plan.saved_paths, plan.baseline_links = stage_inputs(
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


def _candidate_validation_details(
    path: Path,
    checked: Findings | None,
    names: set[str],
    scope: set[tuple[str, str, str]],
) -> list[dict[str, object]]:
    """Report only evidence retained by the mandatory candidate checks."""
    if checked is None:
        return [
            dict(
                candidate=str(path), message="candidate validation findings unavailable"
            )
        ]
    details = []
    for name in sorted(names):
        result = checked.result(name, scope)
        if result.model_completion_allowed:
            continue
        detail = dict(candidate=str(path), check=name, status=result.status)
        if result.errors:
            detail["errors"] = result.errors
        metadata = {
            key: value
            for key, value in result.metadata.items()
            if key
            in {
                "complete",
                "status",
                "reason",
                "path",
                "phase",
                "exception",
                "message",
                "unverified",
                "unavailable_services",
            }
        }
        if metadata:
            detail["metadata"] = metadata
        cause_keys = {
            key
            for item in result.metadata.get("unverified", [])
            for key in item.get("cause_keys", [])
        }
        diagnostics = [
            dict(item.record(), diagnostic_id=stable_id(item.identity))
            for item in checked.diagnostics
            if item.check_id == name
            or item.check_id.startswith(name + ".")
            or item.cause_key in cause_keys
        ]
        if diagnostics:
            detail["diagnostics"] = diagnostics
        details.append(detail)
    return details


def validate_generation(plan, *, jobs=4, write=True):
    failed, unclassified = generation_failures(plan)
    for path in (
        list(plan.generated) if unclassified else failed.keys() & plan.generated.keys()
    ):
        del plan.generated[path]
        restore_view(plan.stage, plan.root, path)
    validate_candidates(
        plan.stage,
        plan.root,
        plan.generated,
        plan.destinations,
        plan.failure_records,
        jobs,
        write,
        *([plan.validation, plan.accounts] if write else []),
        definitions_root=plan.definitions_root,
    )
    if write and plan.generated:
        common = plan.validation.get(None)
        required_common = {
            "design.collections",
            "design.ownership",
            "design.stacks",
            "framework.policy-tables",
        }
        required_service = {
            "design.overviews",
            "design.links",
            "design.artifacts",
        }
        common_blocked = common is None or any(
            not common.result(name, plan.generated_scope).model_completion_allowed
            for name in required_common
        )
        details = []
        for path in plan.generated:
            checked = plan.validation.get(path)
            identity = {
                (*path.relative_to(plan.root / "docs/designs").parts[:2], path.stem)
            }
            if common_blocked:
                details.extend(
                    _candidate_validation_details(
                        path, common, required_common, plan.generated_scope
                    )
                )
            if (
                checked is None
                or common is None
                or checked.candidate is not common.candidate
            ):
                details.append(
                    dict(
                        candidate=str(path),
                        message="candidate validation findings missing or candidate identity differs",
                    )
                )
            details.extend(
                _candidate_validation_details(path, checked, required_service, identity)
            )
        if details:
            raise ValueError(
                "required candidate validation is FAIL or NOT_RUN:\n"
                + "\n".join(json.dumps(item, ensure_ascii=False) for item in details)
            )
    for checked in plan.validation.values():
        if checked is not None:
            plan.reference_warnings.extend(
                w for w in checked.warnings if w not in plan.reference_warnings
            )
    if write and plan.validation.get(None) is not None:
        plan.candidate = plan.validation[None].candidate
    for path, files in plan.generated.items():
        expected = {
            plan.root / file.relative_to(plan.stage): file.read_bytes().decode("utf-8")
            for file in files
        }
        # Validate canonical candidates, then preserve the saved view's newline format.
        expected[path] = markdown_newlines(path, expected[path])
        plan.expected_outputs[path] = expected
        if plan.snapshot is not None:
            for file in expected:
                plan.snapshot.read(file)
    if write:
        retained = [p for p in plan.saved_paths if p not in plan.generated]
        plan.warnings = sync_views.broken_design_links(
            plan.stage,
            plan.root,
            [plan.stage / p.relative_to(plan.root) for p in retained],
            definitions_root=plan.definitions_root,
        )


def planned_outputs(plan):
    """Actual publication bytes, excluding no-ops; never mutate Git change state."""
    return {
        path
        for outputs in plan.expected_outputs.values()
        for path, text in outputs.items()
        if plan.snapshot.read(path) != (None if text is None else text.encode("utf-8"))
    }


def publish_generation(plan):
    """Publish validated bytes after exactly one all-target input comparison."""
    root, stage = plan.root, plan.stage
    save_failed = False
    plan.snapshot.seal()
    with phase("publication"), publication_lock(root) as journal:
        # Compare even a no-op or wholly rejected batch, outside per-service error handling.
        plan.snapshot.verify()
        all_paths = {
            file for outputs in plan.expected_outputs.values() for file in outputs
        }
        for file in all_paths:
            safe(root, file)
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
                save_failed = True
        # Only I/O rollback changes the reference state after candidate validation.
        if save_failed:
            plan.candidate = object()
            plan.validation.clear()
        while save_failed and plan.saved:
            context = sync_views.validation_context(
                stage,
                root,
                plan.saved,
                plan.destinations,
                plan.accounts,
                definitions_root=plan.definitions_root,
            )
            plan.candidate = context.findings.candidate
            plan.validation[None] = context.findings
            rejected = []
            for path in plan.saved:
                try:
                    if context.errors:
                        raise ValueError("\n- ".join(context.errors))
                    findings = sync_views.validate_views(
                        stage,
                        root,
                        [stage / path.relative_to(root)],
                        plan.destinations,
                        context=context,
                        definitions_root=plan.definitions_root,
                        candidate_paths={
                            stage / p.relative_to(root) for p in plan.saved
                        },
                    )
                    plan.validation[path] = findings
                    plan.reference_warnings.extend(
                        w for w in findings.warnings if w not in plan.reference_warnings
                    )
                except (OSError, ValueError, KeyError, TypeError) as error:
                    generation_failure(
                        root,
                        plan.failure_records,
                        "generation.publish",
                        path,
                        error,
                    )
                    rejected.append(path)
            if not rejected:
                break
            for path in rejected:
                restore_files(plan.saved.pop(path))
                restore_view(stage, root, path)
                plan.generated.pop(path, None)
        if save_failed:
            retained = [p for p in plan.saved_paths if p not in plan.saved]
            plan.warnings = sync_views.broken_design_links(
                stage,
                root,
                [stage / p.relative_to(root) for p in retained],
                definitions_root=plan.definitions_root,
            )


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
    for warning in plan.reference_warnings:
        print(
            ("ERROR [" if warning.get("status") == "FAIL" else "WARNING [")
            + warning["code"]
            + "] "
            + json.dumps(warning, ensure_ascii=False),
            file=output_file(error=True),
        )
    if plan.unavailable or any(
        d.get("category") == "REFERENCE_PENDING_DEPLOY" for d in plan.reference_warnings
    ):
        print(
            "View generation: "
            + json.dumps(generation_metadata(plan), ensure_ascii=False),
            file=output_file(),
        )
    for reference, target in plan.warnings.items():
        if reference not in plan.baseline_links and target in plan.saved:
            print(
                f"Design Markdown sync: WARNING ({target.relative_to(plan.root)}: "
                f"saved reference needs repair: {reference})",
                file=output_file(error=True),
            )

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
    """Compare saved bytes with the existing validated generation candidates."""
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
