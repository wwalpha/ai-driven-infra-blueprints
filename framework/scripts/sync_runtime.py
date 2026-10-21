"""Select, stage, validate and publish model views; independent of the CLI."""
from utils.json_format import policy_json

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass, field
import json
import re
import shutil
import tempfile
from pathlib import Path
from design_document import DesignIndex
from design_layout import STACK_DESIGN
from model.core import entries, ReferenceResolutionError
from model.render import render_validated_model as markdown_for
from model.validation import validate_required_properties, validate_kms_policy_accounts
from aws_mapping_display import validate_mappings
from model.projection import design_target, resource_row_scope
from model.projection import JSON_LINK
from model.sources import load_model
from model.sources import _publish_transaction, publication_lock, safe, model_exists, model_paths as registered_models
from policy_tables import rendered_design
from task_contract import task_path, task_revision
from issue_gate import require_no_issues
from validation_scope import scoped_files
from validation_cache import input_scope, memo_table, recording_inputs, input_context, input_recorder, input_bytes, input_is_file, input_select
from utils.aws_mappings import mapping_alias, definition_root
from sync_files import changed_files, save_files, restore_files, markdown_newlines
import sync_views
from sync_progress import stage as progress_stage, phase, advance, consumers, completed, tracked_sync, total, output_file
from model.importing.scope import selected as import_selection, scoped as import_scoped


def local_design_links(root, path, texts):
    """Existing local link targets, read through the generation input recorder."""
    result = set()
    for text in texts:
        for raw in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if raw.startswith(('https://', 'http://', 'mailto:')):
                continue
            target = raw.partition('#')[0]
            linked = (path.parent / target if target else path).resolve()
            if linked.is_relative_to(root / 'docs/designs') and input_is_file(linked):
                safe(root, path.parent / target if target else path)
                result.add(linked)
    return result


@progress_stage("stage-placement/dependency-models")
def stage_inputs(stage, root, destinations, model_paths, markdown_paths, services, write, snapshot=None, definitions_root=None):
    """Copy the consumed project dependencies; definitions always stay at their source."""
    docs, models = root / 'docs/designs', root / 'model'
    views = set(markdown_paths)
    targets = {p.parent.relative_to(docs) for p in destinations}
    index = DesignIndex(root)
    def links(path, texts):
        return {linked for linked in local_design_links(root, path, texts) if linked.suffix == '.md'}
    for path, values in destinations.items():
        views.update(links(path, values.values()))
    # Discover incoming links without copying every scanned Markdown file.
    if write:
        for target in targets:
            for path in input_select(docs / target, '*.md', kinds=('file',)):
                if path not in destinations and links(path, [index.get(path).text]) & destinations.keys():
                    views.add(path)
    inputs, visited = set(), set()
    from model.sources import FileReads, source_scope
    reads = snapshot or FileReads()
    registered_models(root)  # Record the reverse-dependency discovery set, without copying its models.
    def add_model(model):
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
            pending.extend(source_scope(root, path).path for path in dependencies if path.is_relative_to(models))
    for path in model_paths:
        if (docs / path.relative_to(models)).with_suffix('.md') in destinations:
            add_model(path)
    for path, values in destinations.items():
        target = models / path.parent.relative_to(docs)
        if path.name == STACK_DESIGN and any(key.startswith('desired.artifact.') or key == 'desired.deployment.templateBucket' for key in values):
            add_model(target / 's3.properties')
        if any(key.endswith('.cfn-logicalId') for key in values):
            add_model(target / 'cloudformation-stacks.properties')
    # Bound anchors and ownership depend on authoritative models of retained views.
    for view in views:
        if any(line.startswith('### ') for line in index.get(view).text.splitlines()):
            referenced = models / view.relative_to(docs).with_suffix('.properties')
            if referenced not in model_paths or view in destinations:
                add_model(referenced)
    for view in views | destinations.keys():
        if view.name == STACK_DESIGN:
            environment, target = view.parent.relative_to(docs).parts
            for model in registered_models(root, environment, target):
                add_model(model)
    inputs.update(views)
    for path, texts in [(p, values.values()) for p, values in destinations.items()] + [
            (p, [index.get(p).text]) for p in views]:
        inputs.update(linked for linked in local_design_links(root, path, texts) if linked.suffix != '.md')
    # Include existing JSONs only for selected services: extra artifacts still fail validation.
    for view in set(markdown_paths) | destinations.keys():
        inputs.update(input_select(view.with_suffix(''), '*.json', recursive=True, kinds=('file', 'symlink')))
    if input_is_file(root / 'project.json'):
        inputs.add(root / 'project.json')
    with phase('stage-placement', total=len(inputs)):
        for path in sorted(inputs):
            if snapshot is not None:
                snapshot.copy_to_stage([path])
            else:
                destination = stage / path.relative_to(root)
                if input_is_file(path):
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(input_bytes(path))
            advance()
    failed_views = {(docs / p.relative_to(models)).with_suffix('.md') for p in model_paths} - destinations.keys()
    saved_paths = sorted(p for p in views if p not in failed_views and p.parent.relative_to(docs) in targets)
    baseline_paths = [p for p in saved_paths if p not in destinations] if len(destinations) == 1 else saved_paths
    baseline_links = sync_views.broken_design_links(stage, root, [stage / p.relative_to(root) for p in baseline_paths], definitions_root=definitions_root) if write else {}
    return saved_paths, baseline_links


@progress_stage("candidate-generation")
@resource_row_scope()
def generate_views(stage, root, destinations, failures, definitions_root=None, *, warnings=None, unavailable=None):
    warnings = warnings if warnings is not None else []
    unavailable = unavailable if unavailable is not None else {}
    definitions_root = definitions_root or definition_root(root)
    total(len(destinations))
    generated = {}
    from model.identity import Resolver
    resolver = Resolver(root)
    # Render all valid base views before resolving cross-service links.
    for path, values in destinations.items():
        staged = stage / path.relative_to(root)
        artifacts = {}
        try:
            from model.validation import check_model_inputs
            model = load_model((root / 'model' / path.relative_to(root / 'docs/designs')).with_suffix('.properties'))
            independent = check_model_inputs(path, model.authoritative, root, definitions_root=definitions_root)
            warnings.extend(warning for warning in (*model.warnings, *independent.warnings) if warning not in warnings)
            if independent.errors:
                if independent.unverified or model.warnings:
                    unavailable[path] = {'reason': 'reference', 'status': 'NOT_RUN',
                                         'retainedView': str(path.relative_to(root)) if input_is_file(path) else None}
                raise ValueError("\n- ".join(independent.errors))
            validate_kms_policy_accounts(values, design_target(staged, stage))
            for identity, row in entries(values, "desired.row."):
                match = JSON_LINK.fullmatch(row.get("value", ""))
                if not match:
                    if "document" in row:
                        raise ValueError(f"JSON document requires an artifact link: {identity}")
                    continue
                if "document" not in row:
                    raise ValueError(f"authoritative JSON document missing: {path.name}: {identity}")
                from model.projection import execution_document
                document = execution_document(policy_json(row["document"]), root, property_name=row["property"], resolver=resolver)
                if not isinstance(document, dict):
                    raise ValueError(f"JSON document must be an object: {identity}")
                artifact = (staged.parent / match.group(1)).resolve()
                if artifact.parent != staged.with_suffix("").resolve():
                    raise ValueError(f"JSON artifact must belong to owning service: {identity}")
                content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
                if artifact in artifacts and artifacts[artifact] != content:
                    raise ValueError(f"conflicting authoritative JSON documents: {artifact.name}")
                artifacts[artifact] = content
            save_files(artifacts)
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_text(markdown_for(staged, values, stage, definitions_root=definitions_root), encoding='utf-8', newline='')
            generated[path] = [*artifacts, staged]
        except ReferenceResolutionError as error:
            warnings.append({**error.diagnostic, 'source': str(path.relative_to(root))})
            unavailable[path] = {'reason': 'reference', 'status': 'NOT_RUN',
                                 'retainedView': str(path.relative_to(root)) if input_is_file(path) else None}
            generated.pop(path, None)
            restore_view(stage, root, path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            failures.append(f"{path.relative_to(root)}: {error}")
            restore_view(stage, root, path)
        advance()
    for path in list(generated):
        try:
            staged = stage / path.relative_to(root)
            if path.name != STACK_DESIGN:
                staged.write_text(rendered_design(staged, definitions_root=definitions_root), encoding='utf-8', newline='')
        except ReferenceResolutionError as error:
            warnings.append({**error.diagnostic, 'source': str(path.relative_to(root))})
            unavailable[path] = {'reason': 'reference', 'status': 'NOT_RUN',
                                 'retainedView': str(path.relative_to(root)) if input_is_file(path) else None}
            generated.pop(path, None)
            restore_view(stage, root, path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            failures.append(f"{path.relative_to(root)}: {error}")
            del generated[path]
            restore_view(stage, root, path)
    return generated


@progress_stage("candidate-validation")
def validate_candidates(stage, root, generated, destinations, failures, jobs, write, validation=None, accounts=None, definitions_root=None):
    # A rejected view falls back to its saved state; recheck dependent services.
    from task_contract import selected_task
    name, text = task_revision(root)
    @selected_task(root, name if text is not None else None)
    def validate(path):
        try:
            from model.importing.scope import view_scope
            identities = {(*file.relative_to(root / 'docs/designs').parts[:2], file.stem) for file in destinations}
            if import_selection(root) is not None:
                identities.add(import_selection(root))
            with view_scope(identities):
                return_value = sync_views.validate_views(stage, root, [stage / path.relative_to(root)], destinations, design_index=design_index, definitions_root=definitions_root, **({"context": context} if validation is not None else {}))
                if validation is not None:
                    validation[path] = return_value
        except (OSError, ValueError, KeyError, TypeError) as error:
            return path, f"{path.relative_to(root)}: {error}"
        return path, None

    while generated:
        total(len(generated))
        design_index = DesignIndex(root)  # A new snapshot after each restore_view phase.
        rejected = []
        context = None
        if validation is not None:
            context = sync_views.validation_context(stage, root, generated, destinations, accounts, definitions_root=definitions_root)
            validation[None] = context.findings
            if context.errors:
                # Ownership/stack checks concern the fixed whole scope, not repeated services.
                for error in context.errors:
                    failures.append(error)
                rejected = [p for p in generated if any(p.relative_to(root).as_posix() in e for e in context.errors)]
                if not rejected:
                    rejected = list(generated)
                for path in rejected:
                    del generated[path]
                    restore_view(stage, root, path)
                continue
        # All candidate views are fixed during this read-only phase.
        with ThreadPoolExecutor(max_workers=1 if write else min(jobs, len(generated))) as executor:
            mapper = map if write or jobs == 1 or len(generated) == 1 else executor.map
            for path, error in mapper(validate, sorted(generated)):
                advance()
                if error:
                    failures.append(error)
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
    files = set(input_select(path.with_suffix(''), '*.json', recursive=True, kinds=('file', 'symlink')))
    if input_is_file(path):
        files.update(linked for linked in local_design_links(root, path, [input_bytes(path).decode('utf-8')])
                     if linked.suffix != '.md')
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
        if not file.is_file() or file.read_bytes() != content.encode('utf-8'):
            raise ValueError(f'generated output was not saved correctly: {file}')
    for view in (file for file in expected if file.suffix == '.md'):
        artifacts = {file for file in expected if file.suffix == '.json' and file.is_relative_to(view.with_suffix(''))}
        if set(view.with_suffix('').rglob('*.json')) != artifacts:
            raise ValueError(f'generated output file set changed: {view}')


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
    root = root.resolve()
    deferred = sync_views._saved_design_validation.get()
    if deferred is not None and (write or deferred != (root, (environment, target_directory, (services or [None])[0]))
                                 or services != [deferred[1][2]]):
        raise ValueError('saved design validation requires read-only generation of the selected single service')
    expected_task = task_revision(root) if write else None
    from import_guard import require_import_changes
    with phase("import-guard"):
        require_import_changes(root, generation=True)
    if import_selection(root) is not None:
        from model.importing.scope import readable
        expected = {import_selection(root)} if write else readable(root)
        requested = {(environment, target_directory, service) for service in services or []}
        if not requested or not requested <= expected:
            raise ValueError('IMPORT generation is outside selected environment/target/service')
        if write:
            from model.importing.cli import recover_display
            identity = import_selection(root)
            recover_display(root, identity[0], identity[2], identity[1])
            consumers({identity})
            completed(identity)
            return 0
        jobs = 1
    scope = {(environment, target_directory, service) for service in services} if services is not None else None
    if services is not None and (not environment or not target_directory):
        raise ValueError("service selection requires environment and target directory")
    if write:
        require_no_issues(root, scope, target=(environment, target_directory) if environment else None)
    return run_generation(root, scope, write=write, environment=environment,
                          target_directory=target_directory, jobs=jobs, definitions_root=definitions_root, snapshot=snapshot)


@contextmanager
def generation_context(root, write, definitions_root=None):
    """The outer execution owns recording/aliases, including IMPORT preflight reads."""
    definitions_root = definitions_root or definition_root(root)
    with ExitStack() as lifetime:
        lifetime.enter_context(input_context() if write else nullcontext())
        if definitions_root != root and definition_root(root) != definitions_root:
            lifetime.enter_context(mapping_alias(definitions_root, root))
        snapshot = input_recorder(root)
        if write and snapshot is None and import_selection(root) is None:
            with publication_lock(root):
                snapshot = GenerationInputs(root, definitions_root)
            lifetime.callback(snapshot.close)
            lifetime.enter_context(recording_inputs(snapshot))
            from validation_cache import PassCache
            PassCache(root, definitions_root=definitions_root).common_inputs(snapshot)
        yield snapshot


@tracked_sync
@input_scope
@import_scoped
def sync(root, write, environment=None, target_directory=None, services=None, jobs=4, definitions_root=None):
    root = root.resolve()
    with generation_context(root, write, definitions_root) as snapshot:
        return _sync(root, write, environment, target_directory, services, jobs, definitions_root, snapshot)


from generation_inputs import GenerationInputs


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
    failures: list = field(default_factory=list)
    validation: dict = field(default_factory=dict)
    read_inputs: dict = field(default_factory=dict)
    saved: dict = field(default_factory=dict)
    expected_outputs: dict = field(default_factory=dict)
    warnings: dict = field(default_factory=dict)
    reference_warnings: list = field(default_factory=list)
    unavailable: dict = field(default_factory=dict)
    candidate: object = field(default_factory=object)
    accounts: object = None
    definitions_root: Path | None = None

    @property
    def generated_scope(self):
        return {(*p.relative_to(self.root / 'docs/designs').parts[:2], p.stem) for p in self.generated}

    def close(self):
        self.lifetime.close()


@progress_stage("snapshot")
def prepare_generation(root, scope, *, write=True, environment=None, target_directory=None, snapshot=None, definitions_root=None):
    """Prepare every selected target in a single disposable stage."""
    if scope == set():
        raise ValueError('--write requires service scope; framework scope cannot generate Models')
    lifetime = ExitStack()
    try:
        # Recover the journal before snapshotting inputs, differences or originals.
        definitions_root = definitions_root or definition_root(root)
        snapshot = snapshot or input_recorder(root)
        if snapshot is not None and input_recorder(root) is not snapshot:
            lifetime.enter_context(recording_inputs(snapshot))
        if snapshot is None and write:
            with publication_lock(root):
                snapshot = GenerationInputs(root, definitions_root)
            lifetime.callback(snapshot.close)
            lifetime.enter_context(recording_inputs(snapshot))
            # Common fingerprints are guarded even when the standalone writer has no cache.
            from validation_cache import PassCache
            PassCache(root, definitions_root=definitions_root).common_inputs(snapshot)
        if definitions_root != root and definition_root(root) != definitions_root:
            lifetime.enter_context(mapping_alias(definitions_root, root))
        docs, models = root / 'docs/designs', root / 'model'
        model_paths = [p for p in scoped_files(root, 'model', '.properties', scope)
                       if selected(p, models, environment, target_directory)]
        markdown_paths = [p for p in scoped_files(root, 'docs/designs', '.md', scope)
                          if selected(p, docs, environment, target_directory)]
        if snapshot is not None:
            stage = snapshot.open_stage()
        else:
            stage = Path(lifetime.enter_context(tempfile.TemporaryDirectory())).resolve()
            lifetime.enter_context(mapping_alias(definitions_root, stage))
        plan = Generation(root, stage, scope, model_paths, markdown_paths, snapshot, lifetime, definitions_root=definitions_root)
        consumers((*p.relative_to(models).parts[:2], p.stem) for p in model_paths)
        for path in model_paths:
            destination = (docs / path.relative_to(models)).with_suffix('.md')
            try:
                with phase('dependency-model', total=1):
                    loaded = load_model(path)
                    advance()
                plan.reference_warnings.extend(getattr(loaded, "warnings", ()))
                plan.destinations[destination] = loaded.values
                if not write:
                    plan.read_inputs.update(loaded.dependencies)
            except (OSError, ValueError, KeyError, TypeError) as error:
                plan.failures.append(f'{path.relative_to(root)}: {error}')
        for path in sorted(set(markdown_paths) - {(docs / p.relative_to(models)).with_suffix('.md') for p in model_paths}):
            plan.failures.append(f'authoritative properties Model inputs missing: {path.relative_to(root)}')
        services = None if scope is None else [entry[2] for entry in scope]
        plan.saved_paths, plan.baseline_links = stage_inputs(stage, root, plan.destinations, model_paths,
                                                           markdown_paths, services, write, snapshot, definitions_root)
        if not write:
            for base in ('model', 'docs/designs'):
                for file in (stage / base).rglob('*'):
                    if file.is_file():
                        path, data = root / file.relative_to(stage), file.read_bytes()
                        if path in plan.read_inputs and plan.read_inputs[path] != data:
                            raise ValueError(f'generation inputs changed while reading: {path}')
                        plan.read_inputs[path] = data
        plan.generated = generate_views(stage, root, plan.destinations, plan.failures, definitions_root=definitions_root, warnings=plan.reference_warnings, unavailable=plan.unavailable)
        return plan
    except BaseException:
        lifetime.close()
        raise


def validate_generation(plan, *, jobs=4, write=True):
    validate_candidates(plan.stage, plan.root, plan.generated, plan.destinations, plan.failures, jobs, write,
                        *([plan.validation, plan.accounts] if write else []), definitions_root=plan.definitions_root)
    if write and plan.generated:
        common = plan.validation.get(None)
        required_common = {'design.collections', 'design.ownership', 'design.stacks', 'framework.policy-tables'}
        required_service = {'design.names', 'design.tables', 'design.overviews',
                            'design.links', 'design.artifacts', 'design.observed'}
        if common is None or any(not common.result(name, plan.generated_scope).model_completion_allowed for name in required_common):
            raise ValueError('required candidate scope validation is FAIL or NOT_RUN')
        for path in plan.generated:
            checked = plan.validation.get(path)
            identity = {(*path.relative_to(plan.root / 'docs/designs').parts[:2], path.stem)}
            if checked is None or checked.candidate is not common.candidate or any(
                    not checked.result(name, identity).model_completion_allowed for name in required_service):
                raise ValueError(f'required candidate validation is FAIL or NOT_RUN: {path}')
    for checked in plan.validation.values():
        if checked is not None:
            plan.reference_warnings.extend(w for w in checked.warnings if w not in plan.reference_warnings)
    if write and plan.validation.get(None) is not None:
        plan.candidate = plan.validation[None].candidate
    for path, files in plan.generated.items():
        expected = {plan.root / file.relative_to(plan.stage): file.read_bytes().decode('utf-8') for file in files}
        # Validate canonical candidates, then preserve the saved view's newline format.
        expected[path] = markdown_newlines(path, expected[path])
        plan.expected_outputs[path] = expected
        if plan.snapshot is not None:
            for file in expected:
                plan.snapshot.read(file)
    if write:
        retained = [p for p in plan.saved_paths if p not in plan.generated]
        plan.warnings = sync_views.broken_design_links(plan.stage, plan.root,
                            [plan.stage / p.relative_to(plan.root) for p in retained], definitions_root=plan.definitions_root)


def planned_outputs(plan):
    """Actual publication bytes, excluding no-ops; never mutate Git change state."""
    return {path for outputs in plan.expected_outputs.values() for path, text in outputs.items()
            if plan.snapshot.read(path) != (None if text is None else text.encode('utf-8'))}


def publish_generation(plan):
    """Publish validated bytes after exactly one all-target input comparison."""
    root, stage = plan.root, plan.stage
    save_failed = False
    plan.snapshot.seal()
    with phase('publication'), publication_lock(root) as journal:
        # Compare even a no-op or wholly rejected batch, outside per-service error handling.
        plan.snapshot.verify()
        all_paths = {file for outputs in plan.expected_outputs.values() for file in outputs}
        for file in all_paths:
            safe(root, file)
        for path, expected in plan.expected_outputs.items():
            changed = {p: text for p, text in expected.items() if plan.snapshot.read(p) != text.encode('utf-8')}
            originals = {p: plan.snapshot.read(p) for p in changed}
            try:
                if changed:
                    _publish_transaction(root, changed, (), journal, originals=originals)
                plan.saved[path] = originals
            except (OSError, ValueError, KeyError, TypeError) as error:
                plan.failures.append(f'{path.relative_to(root)}: {error}')
                if journal.is_file():
                    raise ValueError(f'publication rollback incomplete; recovery journal retained: {journal}: {error}') from error
                restore_view(stage, root, path)
                plan.generated.pop(path, None)
                save_failed = True
        # Only I/O rollback changes the reference state after candidate validation.
        if save_failed:
            plan.candidate = object()
            plan.validation.clear()
        while save_failed and plan.saved:
            context = sync_views.validation_context(stage, root, plan.saved, plan.destinations, plan.accounts, definitions_root=plan.definitions_root)
            plan.candidate = context.findings.candidate
            plan.validation[None] = context.findings
            rejected = []
            for path in plan.saved:
                try:
                    if context.errors:
                        raise ValueError('\n- '.join(context.errors))
                    findings = sync_views.validate_views(stage, root, [stage / path.relative_to(root)],
                                                        plan.destinations, context=context, definitions_root=plan.definitions_root)
                    plan.validation[path] = findings
                except (OSError, ValueError, KeyError, TypeError) as error:
                    plan.failures.append(f'{path.relative_to(root)}: {error}')
                    rejected.append(path)
            if not rejected:
                break
            for path in rejected:
                restore_files(plan.saved.pop(path))
                restore_view(stage, root, path)
                plan.generated.pop(path, None)
        if save_failed:
            retained = [p for p in plan.saved_paths if p not in plan.saved]
            plan.warnings = sync_views.broken_design_links(stage, root, [stage / p.relative_to(root) for p in retained], definitions_root=plan.definitions_root)


def generation_metadata(plan):
    return {'complete': not plan.unavailable, 'generated': sorted('/'.join(scope) for scope in plan.generated_scope),
            'unverified': {'/'.join((*p.relative_to(plan.root / 'docs/designs').parts[:2], p.stem)): info
                           for p, info in plan.unavailable.items()},
            'warnings': plan.reference_warnings}


def report_generation(plan):
    for warning in plan.reference_warnings:
        print('WARNING [' + warning['code'] + '] ' + json.dumps(warning, ensure_ascii=False), file=output_file(error=True))
    if plan.unavailable:
        print('View generation: ' + json.dumps(generation_metadata(plan), ensure_ascii=False), file=output_file())
    for reference, target in plan.warnings.items():
        if reference not in plan.baseline_links and target in plan.saved:
            print(f'Design Markdown sync: WARNING ({target.relative_to(plan.root)}: '
                  f'saved reference needs repair: {reference})', file=output_file(error=True))

    for path in plan.saved:
        completed((*path.relative_to(plan.root / 'docs/designs').parts[:2], path.stem))
        print(f'Design Markdown sync: PASS ({path.relative_to(plan.root)})', file=output_file())
    if plan.failures:
        selected = set(plan.markdown_paths) | {(plan.root / 'docs/designs' / p.relative_to(plan.root / 'model')).with_suffix('.md') for p in plan.model_paths}
        raise ValueError(f'{len(plan.saved)} services succeeded; {len(selected - plan.saved.keys())} services failed; {len(plan.failures)} diagnostics\n- ' + '\n- '.join(plan.failures))
    print(f'Design Markdown sync: PASS ({len(plan.saved)} services)', file=output_file())


@input_scope
@import_scoped
def run_generation(root, scope, *, write=True, environment=None, target_directory=None, jobs=4, definitions_root=None, snapshot=None):
    plan = prepare_generation(root, scope, write=write, environment=environment, target_directory=target_directory, definitions_root=definitions_root, snapshot=snapshot)
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




from model.render import generate_files






def _compare_generation(plan):
    root = plan.root
    changed = [p for p, data in plan.read_inputs.items() if (p.read_bytes() if p.is_file() else None) != data]
    if changed:
        raise ValueError('generation inputs changed before comparison: ' + ', '.join(str(p) for p in changed))
    for path, expected in plan.expected_outputs.items():
        stale = [str(p.relative_to(root)) for p, text in expected.items()
                 if not p.is_file() or p.read_bytes() != text.encode('utf-8')]
        if stale:
            plan.failures.append('generated Markdown is stale or missing: ' + ', '.join(stale))
        else:
            plan.saved[path] = {}


def compare_generation(root: Path, scope, *, jobs=4, definitions_root=None, findings=None) -> tuple[str, ...]:
    """Read-only source/view comparison using the existing generation candidates."""
    if import_selection(root) is not None:
        from import_guard import require_import_changes
        require_import_changes(root, generation=True)
    plan = prepare_generation(root, scope, write=False, definitions_root=definitions_root)
    try:
        validate_generation(plan, jobs=jobs, write=False)
        _compare_generation(plan)
        if findings is not None:
            for warning in plan.reference_warnings:
                findings.warn(warning)
            findings.result('framework.generated-service-model', scope).metadata.update(generation_metadata(plan))
        return tuple(plan.failures)
    finally:
        plan.close()

from model.render import owned_artifacts, view_plan
