"""Select, stage, validate and publish model views; independent of the CLI."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, field
import json
import re
import shutil
import tempfile
from pathlib import Path
from design_document import DesignIndex
from design_layout import STACK_DESIGN
from model_core import entries
from model_design import render_validated_model as markdown_for, validate_required_properties, validate_kms_policy_accounts
from aws_mapping_display import validate_mappings
from model_references import design_target
from model_projection import JSON_LINK
from model_files import load_model
from model_templates import publish, _publish_transaction, publication_lock, safe, source_inputs, service_source, model_paths as registered_models
from policy_tables import rendered_design, unique_object, invalid_constant
from task_contract import task_path, task_revision
from issue_gate import require_no_issues
from validation_scope import scoped_files
from validation_cache import input_scope, memo_table
from utils.aws_mappings import mapping_alias
from sync_files import changed_files, save_files, restore_files, markdown_newlines
import sync_views
from sync_progress import stage as progress_stage, phase, advance, consumers, completed, tracked_sync, total, output_file
from import_scope import selected as import_selection, scoped as import_scoped


@progress_stage("stage-placement/dependency-models")
def stage_inputs(stage, root, destinations, model_paths, markdown_paths, services, write, snapshot=None):
    def copy_file(source, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = snapshot.read(Path(source)) if snapshot is not None else Path(source).read_bytes()
        destination.write_bytes(data)
        return str(destination)

    def copy_tree(source, destination):
        if Path(destination).exists():
            return str(destination)
        return shutil.copytree(source, destination, copy_function=copy_file, ignore=shutil.ignore_patterns("__pycache__"))
    docs, models = root / "docs/designs", root / "model"
    for base in ('model/templates', 'model/parameters'):
        if base == 'model/parameters' and services is not None:
            continue
        if (root / base).is_dir():
            copy_tree(root / base, stage / base)
    targets = {path.parent.relative_to(docs) for path in destinations}
    if services is None:
        for target in targets:
            for base in (docs,):
                if (base / target).is_dir():
                    copy_tree(base / target, stage / base.relative_to(root) / target)
    else:
        views = set(markdown_paths)
        # Generation needs outgoing reference metadata; writes also report stale incoming links.
        if write:
            views.update(path for target in targets for path in (docs / target).glob("*.md"))
        for path, values in destinations.items():
            for value in values.values():
                for raw in re.findall(r"\[[^\]]+\]\(([^)]+)\)", value):
                    target_text = raw.partition("#")[0]
                    linked = (path.parent / target_text if target_text else path).resolve()
                    if linked.suffix == ".md" and linked.is_relative_to(docs) and linked.is_file():
                        views.add(linked)
        model_inputs = set()
        # Typed references need authoritative target metadata in the disposable stage.
        model_inputs.update(file for path in model_paths
                            if (docs / path.relative_to(models)).with_suffix('.md') in destinations
                            for file in source_inputs(path) if file.is_relative_to(root))
        # Stack delivery links need the selected bucket's authoritative name, not a full S3 validation.
        for path, values in destinations.items():
            if path.name == STACK_DESIGN and any(key.startswith("desired.artifact.") or key == "desired.deployment.templateBucket" for key in values):
                referenced = models / path.parent.relative_to(docs) / "s3.properties"
                if service_source(referenced) is not None:
                    model_inputs.update(file for file in source_inputs(referenced) if file.is_relative_to(root))
        for path, values in destinations.items():
            if any(key.endswith(".cfn-logicalId") for key in values):
                referenced = models / path.parent.relative_to(docs) / "cloudformation-stacks.properties"
                if service_source(referenced) is not None:
                    model_inputs.update(file for file in source_inputs(referenced) if file.is_relative_to(root))
        # Bound anchors in staged reference views also need their validated source inputs.
        for view in views:
            if not any(line.startswith('### ') for line in view.read_text(encoding='utf-8').splitlines()):
                continue
            referenced = models / view.relative_to(docs).with_suffix('.properties')
            if referenced in model_paths and view not in destinations:
                continue  # The selected invalid service is already reported; preserve independent saves.
            registered = service_source(referenced)
            if registered is not None:
                model_inputs.update(file for file in source_inputs(referenced) if file.is_relative_to(root))
        # Stack ownership validation reads every service in the same target.
        for view in views | destinations.keys():
            if view.name == STACK_DESIGN:
                environment, target = view.parent.relative_to(docs).parts
                model_inputs.update(file for model in registered_models(root, environment, target)
                                    for file in source_inputs(model) if file.is_relative_to(root))
        with phase("stage-placement", total=len(model_inputs) + len(views)):
            for path in [*model_inputs, *views]:
                destination = stage / path.relative_to(root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                copy_file(path, destination)
                advance()
        for path in markdown_paths:
            if path.with_suffix("").is_dir():
                copy_tree(path.with_suffix(""), stage / path.with_suffix("").relative_to(root))
    if (root / "project.json").is_file():
        copy_file(root / "project.json", stage / "project.json")
    # Reuse the existing invocation memo for staged logical handles and dependencies.
    memo = memo_table()
    if memo is not None:
        for key, value in list(memo.items()):
            if len(key) != 2 or not callable(key[0]):
                continue
            function, args = key
            if (function.__module__, function.__name__) in {('model_files', 'load_model'), ('model_templates', '_load_expansion')} and args[0].is_relative_to(root):
                staged = stage / args[0].relative_to(root)
                memo[(function, (staged, *args[1:]))] = value._replace(files={stage / p.relative_to(root): text for p, text in value.files.items()})
                if snapshot is not None:
                    for file, text in value.files.items():
                        snapshot.record(file, text.encode('utf-8'))
    failed_views = {(docs / path.relative_to(models)).with_suffix(".md") for path in model_paths} - destinations.keys()
    saved_paths = [root / path.relative_to(stage) for path in (stage / "docs/designs").rglob("*.md")
                   if root / path.relative_to(stage) not in failed_views
                   and path.parent.relative_to(stage / "docs/designs") in targets]
    # A sole selected candidate cannot become a retained source while another target saves.
    baseline_paths = [p for p in saved_paths if p not in destinations] if len(destinations) == 1 else saved_paths
    baseline_links = sync_views.broken_design_links(stage, root, [stage / path.relative_to(root) for path in baseline_paths]) if write else {}
    return saved_paths, baseline_links


@progress_stage("candidate-generation")
def generate_views(stage, root, destinations, failures):
    total(len(destinations))
    generated = {}
    # Render all valid base views before resolving cross-service links.
    for path, values in destinations.items():
        staged = stage / path.relative_to(root)
        artifacts = {}
        try:
            validate_mappings(values, root)
            validate_required_properties(values, root)
            validate_kms_policy_accounts(values, design_target(staged, stage))
            for identity, row in entries(values, "desired.row."):
                match = JSON_LINK.fullmatch(row.get("value", ""))
                if not match:
                    if "document" in row:
                        raise ValueError(f"JSON document requires an artifact link: {identity}")
                    continue
                if "document" not in row:
                    raise ValueError(f"authoritative JSON document missing: {path.name}: {identity}")
                document = json.loads(row["document"], object_pairs_hook=unique_object, parse_constant=invalid_constant)
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
            staged.write_text(markdown_for(staged, values, stage, definitions_root=root), encoding='utf-8', newline='')
            generated[path] = [*artifacts, staged]
        except (OSError, ValueError, KeyError, TypeError) as error:
            failures.append(f"{path.relative_to(root)}: {error}")
            restore_view(stage, root, path)
        advance()
    for path in list(generated):
        try:
            staged = stage / path.relative_to(root)
            if path.name != STACK_DESIGN:
                staged.write_text(rendered_design(staged, definitions_root=root), encoding='utf-8', newline='')
        except (OSError, ValueError, KeyError, TypeError) as error:
            failures.append(f"{path.relative_to(root)}: {error}")
            del generated[path]
            restore_view(stage, root, path)
    return generated


@progress_stage("candidate-validation")
def validate_candidates(stage, root, generated, destinations, failures, jobs, write, validation=None, accounts=None):
    # A rejected view falls back to its saved state; recheck dependent services.
    def validate(path):
        try:
            from import_scope import view_scope
            identities = {(*file.relative_to(root / 'docs/designs').parts[:2], file.stem) for file in destinations}
            if import_selection(root) is not None:
                identities.add(import_selection(root))
            with view_scope(identities):
                return_value = sync_views.validate_views(stage, root, [stage / path.relative_to(root)], destinations, design_index=design_index, **({"context": context} if validation is not None else {}))
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
            context = sync_views.validation_context(stage, root, generated, destinations, accounts)
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
    staged.unlink(missing_ok=True)
    if path.is_file():
        shutil.copyfile(path, staged)
    shutil.rmtree(staged.with_suffix(""), ignore_errors=True)
    if path.with_suffix("").is_dir():
        shutil.copytree(path.with_suffix(""), staged.with_suffix(""))


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


@tracked_sync
@input_scope
@import_scoped
def sync(
    root: Path,
    write: bool,
    environment: str | None = None,
    target_directory: str | None = None,
    services: list[str] | None = None,
    jobs: int = 4,
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
        from import_scope import readable
        expected = {import_selection(root)} if write else readable(root)
        requested = {(environment, target_directory, service) for service in services or []}
        if not requested or not requested <= expected:
            raise ValueError('IMPORT generation is outside selected environment/target/service')
        if write:
            from model_templates import load_for_edit
            from import_guard import finish_import, read_proof
            identity = import_selection(root)
            model = root / 'model' / identity[0] / identity[1] / (identity[2] + '.properties')
            document = root / 'docs/designs' / identity[0] / identity[1] / (identity[2] + '.md')
            proof = read_proof(root)
            if proof['model'] not in {'reflected', 'unchanged'}:
                raise ValueError('IMPORT display recovery requires a saved Model')
            managed = {root / name for name in proof['ownedArtifacts']}
            with publication_lock(root):
                expanded = load_for_edit(model)
                inputs = {p: text.encode('utf-8') for p, text in expanded.files.items()}
                inputs.setdefault(service_source(model)[2] / 'observed.json', None)
                output, view_inputs = view_plan(document, expanded.values, root, managed)
            with publication_lock(root):
                publish(root, output, inputs={**inputs, **view_inputs}, expected_task=expected_task)
                finish_import(root, markdown='generated' if output else 'unchanged')
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
                          target_directory=target_directory, jobs=jobs)


class GenerationInputs:
    """The bytes/file sets consumed by this operation, never a persistent receipt."""
    @progress_stage("snapshot")
    def __init__(self, root):
        self.root = root
        self.contents = {}
        self.conflicts = set()
        self.trees = {}
        self.lifetime = ExitStack()
        self.stage = None
        selected_task = task_path(root)
        raw_task = self.read(selected_task)
        self.expected_task = (selected_task.relative_to(root).as_posix(),
                              None if raw_task is None else raw_task.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n'))
        from task_contract import status
        name, text = self.expected_task
        if text is not None and status(text, name == 'tasks/active.md') != 'running':
            raise ValueError('completed task cannot write')
        for name in ('framework', '.agents', 'model', 'docs', 'issues', 'infra', 'tests'):
            directory = root / name
            paths = self.file_set(directory)
            self.trees[directory] = paths
            for path in paths:
                if not path.is_dir():
                    self.read(path)
                    if path.is_relative_to(root / 'model/parameters') and path.name in {'parameters.yaml', 'bindings.json'}:
                        self.read(path.parent / 'observed.json')
        runtime = Path(__file__).resolve().parents[2]
        if runtime != root:
            directory = runtime / 'framework'
            self.trees[directory] = self.file_set(directory)
            for path in self.trees[directory]:
                if not path.is_dir():
                    self.read(path)
        for name in ('project.json', 'AGENTS.md', 'README.md', self.expected_task[0]):
            self.read(root / name)

    @staticmethod
    def file_set(directory):
        return {p for p in directory.rglob('*')
                if (p.is_dir() and '__pycache__' not in p.parts) or
                (not p.is_dir() and not (p.suffix == '.pyc' and '__pycache__' in p.parts))}

    def record(self, path, content):
        if path in self.contents and self.contents[path] != content:
            self.conflicts.add(path)
            raise ValueError(f'generation inputs changed while reading: {path}')
        self.contents[path] = content
        return content

    def read(self, path):
        if path not in self.contents:
            self.record(path, path.read_bytes() if path.is_file() else None)
        return self.contents[path]

    def materialize(self):
        if self.stage is None:
            self.stage = Path(self.lifetime.enter_context(tempfile.TemporaryDirectory())).resolve()
            self.lifetime.enter_context(mapping_alias(self.root, self.stage))
            framework_root = self.root / "framework"
            for directory, paths in self.trees.items():
                if directory.is_relative_to(self.root) and not directory.is_relative_to(framework_root):
                    if directory.is_dir():
                        (self.stage / directory.relative_to(self.root)).mkdir(parents=True, exist_ok=True)
                    for path in paths:
                        if path.is_dir() and not path.is_relative_to(framework_root):
                            (self.stage / path.relative_to(self.root)).mkdir(parents=True, exist_ok=True)
            for path, content in self.contents.items():
                if content is not None and path.is_relative_to(self.root) and not path.is_relative_to(framework_root):
                    staged = self.stage / path.relative_to(self.root)
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    staged.write_bytes(content)
        return self.stage

    def close(self):
        self.lifetime.close()

    def verify(self):
        """One comparison phase inside publication_lock, before any service can save."""
        changed = self.conflicts | {p for p, data in self.contents.items()
                   if (p.read_bytes() if p.is_file() else None) != data}
        for directory, paths in self.trees.items():
            changed.update(self.file_set(directory) ^ paths)
        # The contract bytes are already part of contents; do not reread them here.
        if changed:
            raise ValueError('generation inputs changed before publication: ' +
                             ', '.join(str(p.relative_to(self.root)) if p.is_relative_to(self.root) else str(p) for p in sorted(changed)))


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
    candidate: object = field(default_factory=object)
    accounts: object = None

    @property
    def generated_scope(self):
        return {(*p.relative_to(self.root / 'docs/designs').parts[:2], p.stem) for p in self.generated}

    def close(self):
        self.lifetime.close()


def prepare_generation(root, scope, *, write=True, environment=None, target_directory=None, snapshot=None):
    """Prepare every selected target in a single disposable stage."""
    if scope == set():
        raise ValueError('--write requires service scope; framework scope cannot generate Models')
    lifetime = ExitStack()
    try:
        # Recover the journal before snapshotting inputs, differences or originals.
        with publication_lock(root):
            snapshot = snapshot or (GenerationInputs(root) if write else None)
        docs, models = root / 'docs/designs', root / 'model'
        model_paths = [p for p in scoped_files(root, 'model', '.properties', scope)
                       if selected(p, models, environment, target_directory)]
        markdown_paths = [p for p in scoped_files(root, 'docs/designs', '.md', scope)
                          if selected(p, docs, environment, target_directory)]
        if snapshot is not None:
            lifetime.callback(snapshot.close)
            stage = snapshot.materialize()
        else:
            stage = Path(lifetime.enter_context(tempfile.TemporaryDirectory())).resolve()
            lifetime.enter_context(mapping_alias(root, stage))
        plan = Generation(root, stage, scope, model_paths, markdown_paths, snapshot, lifetime)
        consumers((*p.relative_to(models).parts[:2], p.stem) for p in model_paths)
        for path in model_paths:
            destination = (docs / path.relative_to(models)).with_suffix('.md')
            try:
                with phase('dependency-model', total=1):
                    loaded = load_model(path)
                    advance()
                if snapshot is not None:
                    for file, text in loaded.files.items():
                        snapshot.record(file, text.encode('utf-8'))
                    registered = service_source(path)
                    snapshot.read(registered[2] / 'observed.json')
                plan.destinations[destination] = loaded.values
                if not write:
                    plan.read_inputs.update({p: text.encode("utf-8") for p, text in loaded.files.items()})
            except (OSError, ValueError, KeyError, TypeError) as error:
                plan.failures.append(f'{path.relative_to(root)}: {error}')
        for path in sorted(set(markdown_paths) - {(docs / p.relative_to(models)).with_suffix('.md') for p in model_paths}):
            plan.failures.append(f'authoritative YAML Model inputs missing: {path.relative_to(root)}')
        services = None if scope is None else [entry[2] for entry in scope]
        plan.saved_paths, plan.baseline_links = stage_inputs(stage, root, plan.destinations, model_paths,
                                                           markdown_paths, services, write, snapshot)
        if not write:
            for base in ('model', 'docs/designs'):
                for file in (stage / base).rglob('*'):
                    if file.is_file():
                        path, data = root / file.relative_to(stage), file.read_bytes()
                        if path in plan.read_inputs and plan.read_inputs[path] != data:
                            raise ValueError(f'generation inputs changed while reading: {path}')
                        plan.read_inputs[path] = data
                        if file.name == 'parameters.yaml' and not (file.parent / 'observed.json').is_file():
                            plan.read_inputs.setdefault(path.parent / 'observed.json', None)
        plan.generated = generate_views(stage, root, plan.destinations, plan.failures)
        return plan
    except BaseException:
        lifetime.close()
        raise


def validate_generation(plan, *, jobs=4, write=True):
    validate_candidates(plan.stage, plan.root, plan.generated, plan.destinations, plan.failures, jobs, write,
                        *([plan.validation, plan.accounts] if write else []))
    if write and plan.generated:
        common = plan.validation.get(None)
        required_common = {'design.collections', 'design.ownership', 'design.stacks', 'framework.policy-tables'}
        required_service = {'design.projection', 'design.names', 'design.tables', 'design.overviews',
                            'design.links', 'design.artifacts', 'design.observed'}
        if common is None or any(common.result(name, plan.generated_scope).status != 'PASS' for name in required_common):
            raise ValueError('required candidate scope validation is FAIL or NOT_RUN')
        for path in plan.generated:
            checked = plan.validation.get(path)
            identity = {(*path.relative_to(plan.root / 'docs/designs').parts[:2], path.stem)}
            if checked is None or checked.candidate is not common.candidate or any(
                    checked.result(name, identity).status != 'PASS' for name in required_service):
                raise ValueError(f'required candidate validation is FAIL or NOT_RUN: {path}')
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
                            [plan.stage / p.relative_to(plan.root) for p in retained])


def publish_generation(plan):
    """Publish validated bytes after exactly one all-target input comparison."""
    root, stage = plan.root, plan.stage
    save_failed = False
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
            context = sync_views.validation_context(stage, root, plan.saved, plan.destinations, plan.accounts)
            plan.candidate = context.findings.candidate
            plan.validation[None] = context.findings
            rejected = []
            for path in plan.saved:
                try:
                    if context.errors:
                        raise ValueError('\n- '.join(context.errors))
                    findings = sync_views.validate_views(stage, root, [stage / path.relative_to(root)],
                                                        plan.destinations, context=context)
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
            plan.warnings = sync_views.broken_design_links(stage, root, [stage / p.relative_to(root) for p in retained])
    for reference, target in plan.warnings.items():
        if reference not in plan.baseline_links and target in plan.saved:
            print(f'Design Markdown sync: WARNING ({target.relative_to(root)}: '
                  f'saved reference needs repair in a separate task: {reference})', file=output_file(error=True))


def report_generation(plan):
    for path in plan.saved:
        completed((*path.relative_to(plan.root / 'docs/designs').parts[:2], path.stem))
        print(f'Design Markdown sync: PASS ({path.relative_to(plan.root)})', file=output_file())
    if plan.failures:
        selected = set(plan.markdown_paths) | {(plan.root / 'docs/designs' / p.relative_to(plan.root / 'model')).with_suffix('.md') for p in plan.model_paths}
        raise ValueError(f'{len(plan.saved)} services succeeded; {len(selected - plan.saved.keys())} services failed; {len(plan.failures)} diagnostics\n- ' + '\n- '.join(plan.failures))
    print(f'Design Markdown sync: PASS ({len(plan.saved)} services)', file=output_file())


@input_scope
@import_scoped
def run_generation(root, scope, *, write=True, environment=None, target_directory=None, jobs=4):
    plan = prepare_generation(root, scope, write=write, environment=environment, target_directory=target_directory)
    try:
        validate_generation(plan, jobs=jobs, write=write)
        if write:
            publish_generation(plan)
        else:
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
        report_generation(plan)
        return 0
    finally:
        plan.close()




def generate_files(path, values, root):
    """Generate one service in memory, without validation or dependency publication."""
    from model_design import generate_markdown
    from model_templates import safe
    artifacts = {}
    for identity, row in entries(values, 'desired.row.'):
        if 'document' not in row:
            continue
        match = JSON_LINK.fullmatch(row.get('value', ''))
        if not match:
            raise ValueError('JSON document requires an artifact link: ' + identity)
        safe(root, path.parent / match[1])
        artifact = (path.parent / match[1]).resolve()
        safe(root, artifact)
        if artifact.parent != path.with_suffix('').resolve():
            raise ValueError('JSON artifact must belong to owning service')
        document = json.loads(row['document'], object_pairs_hook=unique_object, parse_constant=invalid_constant)
        content = json.dumps(document, ensure_ascii=False, indent=2) + '\n'
        if artifact in artifacts and artifacts[artifact] != content:
            raise ValueError('conflicting authoritative JSON documents')
        artifacts[artifact] = content
    artifacts[path] = generate_markdown(path, values, root)
    return artifacts


def owned_artifacts(path, values):
    return {(path.parent / link[1]).resolve() for _, row in entries(values, 'desired.row.')
            if 'document' in row and (link := JSON_LINK.fullmatch(row.get('value', '')))
            and (path.parent / link[1]).resolve().parent == path.with_suffix('').resolve()}


def view_plan(path, values, root, managed):
    """Plan one display transaction without taking ownership of unrelated JSON."""
    inputs = {p: p.read_bytes() for p in path.with_suffix('').rglob('*.json')}
    inputs[path] = path.read_bytes() if path.is_file() else None
    for file in inputs.keys() | managed:
        safe(root, file)
        if file != path and file.parent != path.with_suffix('').resolve():
            raise ValueError('JSON artifact must belong to owning service')
    files = generate_files(path, values, root)
    if any(file in inputs and file != path and file not in managed and inputs[file] != text.encode('utf-8')
           for file, text in files.items()):
        raise ValueError('unowned JSON output collision')
    inputs.update({file: file.read_bytes() if file.is_file() else None for file in files if file not in inputs})
    return {**changed_files(files), **{file: None for file in managed - files.keys() if file.is_file()}}, inputs
