"""Select, stage, validate and publish model views; independent of the CLI."""

from concurrent.futures import ThreadPoolExecutor
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from design_document import DesignIndex
from design_layout import STACK_DESIGN
from model_core import properties, entries
from model_design import markdown_for, validate_required_properties, validate_kms_policy_accounts
from model_references import design_target
from model_projection import JSON_LINK
from model_files import read_model, load_model
from model_templates import publish, publication_lock, safe, source_inputs, service_source, model_paths as registered_models
from policy_tables import rendered_design, unique_object, invalid_constant
from task_contract import task_path, task_revision
from issue_gate import require_no_issues
from validation_scope import scoped_files
from validation_cache import input_scope, memo_table
from utils.aws_mappings import mapping_alias
from sync_files import changed_files, save_files, restore_files, markdown_newlines
import sync_views
from sync_progress import stage as progress_stage, phase, advance, consumers, completed, tracked_sync, total
from import_scope import selected as import_selection, scoped as import_scoped


@progress_stage("stage-placement/dependency-models")
def stage_inputs(stage, root, destinations, model_paths, markdown_paths, services, write):
    docs, models = root / "docs/designs", root / "model"
    shutil.copytree(root / 'framework', stage / 'framework')
    for base in ('model/templates', 'model/parameters'):
        if base == 'model/parameters' and services is not None:
            continue
        if (root / base).is_dir():
            shutil.copytree(root / base, stage / base)
    targets = {path.parent.relative_to(docs) for path in destinations}
    if services is None:
        for target in targets:
            for base in (docs,):
                if (base / target).is_dir():
                    shutil.copytree(base / target, stage / base.relative_to(root) / target)
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
                shutil.copyfile(path, destination)
                advance()
        for path in markdown_paths:
            if path.with_suffix("").is_dir():
                shutil.copytree(path.with_suffix(""), stage / path.with_suffix("").relative_to(root))
    if (root / "project.json").is_file():
        shutil.copyfile(root / "project.json", stage / "project.json")
    failed_views = {(docs / path.relative_to(models)).with_suffix(".md") for path in model_paths} - destinations.keys()
    saved_paths = [root / path.relative_to(stage) for path in (stage / "docs/designs").rglob("*.md")
                   if root / path.relative_to(stage) not in failed_views]
    baseline_links = sync_views.broken_design_links(stage, root, [stage / path.relative_to(root) for path in saved_paths]) if write else {}
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
            save_files({staged: markdown_for(staged, values, stage)})
            generated[path] = [*artifacts, staged]
        except (OSError, ValueError, KeyError, TypeError) as error:
            failures.append(f"{path.relative_to(root)}: {error}")
            restore_view(stage, root, path)
        advance()
    for path in list(generated):
        try:
            staged = stage / path.relative_to(root)
            if path.name != STACK_DESIGN:
                save_files({staged: rendered_design(staged)})
        except (OSError, ValueError, KeyError, TypeError) as error:
            failures.append(f"{path.relative_to(root)}: {error}")
            del generated[path]
            restore_view(stage, root, path)
    return generated


@progress_stage("candidate-validation")
def validate_candidates(stage, root, generated, destinations, failures, jobs, write):
    # A rejected view falls back to its saved state; recheck dependent services.
    def validate(path):
        try:
            from import_scope import view_scope
            identities = {(*file.relative_to(root / 'docs/designs').parts[:2], file.stem) for file in destinations}
            if import_selection(root) is not None:
                identities.add(import_selection(root))
            with view_scope(identities):
                sync_views.validate_views(stage, root, [stage / path.relative_to(root)], destinations, design_index=design_index)
        except (OSError, ValueError, KeyError, TypeError) as error:
            return path, f"{path.relative_to(root)}: {error}"
        return path, None

    while generated:
        total(len(generated))
        design_index = DesignIndex()  # A new snapshot after each restore_view phase.
        rejected = []
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


@progress_stage("snapshot")
def generation_inputs(root):
    # Snapshot bytes, not validation results; include file sets and absent optional inputs.
    paths = {p for p in (root / 'framework').rglob('*')
             if p.is_file() and '__pycache__' not in p.parts}
    paths.update(root / name for name in ('project.json', 'AGENTS.md'))
    total(len(paths))
    snapshot = {}
    for p in paths:
        snapshot[p] = p.read_bytes() if p.is_file() else None
        advance()
    return snapshot


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
    docs = root / "docs" / "designs"
    models = root / "model"
    scope = {(environment, target_directory, service) for service in services} if services is not None else None
    if services is not None and (not environment or not target_directory):
        raise ValueError("service selection requires environment and target directory")
    if write:
        require_no_issues(root, scope, target=(environment, target_directory) if environment else None)
    input_paths = set((root / 'model').rglob('*')) if write else set()
    markdown_paths = [
        path
        for path in scoped_files(root, "docs/designs", ".md", scope)
        if selected(path, docs, environment, target_directory) and (services is None or path.stem in services)
    ]
    model_paths = sorted(
        path
        for path in scoped_files(root, "model", ".properties", scope)
        if selected(path, models, environment, target_directory) and (services is None or path.stem in services)
    )
    if services is not None:
        for service in services:
            if not any(path.stem == service for path in model_paths):
                raise ValueError(f"authoritative service model missing: {environment}/{target_directory}/{service}")
    consumers((*path.relative_to(models).parts[:2], path.stem) for path in model_paths)
    configuration = generation_inputs(root) if write else {}
    destinations = {}
    model_snapshots = {}
    failures = []
    for path in model_paths:
        destination = (docs / path.relative_to(models)).with_suffix(".md")
        try:
            with phase("dependency-model", total=1):
                loaded = load_model(path)
                advance()
            destinations[destination] = loaded.values
            model_snapshots[destination] = {file: content.encode("utf-8") for file, content in loaded.files.items()}
        except (OSError, ValueError, KeyError, TypeError) as error:
            failures.append(f"{path.relative_to(root)}: {error}")
    for path in sorted(set(markdown_paths) - {(docs / path.relative_to(models)).with_suffix(".md") for path in model_paths}):
        failures.append(f"authoritative YAML Model inputs missing: {path.relative_to(root)}")
    with tempfile.TemporaryDirectory() as directory, mapping_alias(root, Path(directory).resolve()):
        stage = Path(directory).resolve()
        saved_paths, baseline_links = stage_inputs(stage, root, destinations, model_paths, markdown_paths, services, write)
        with phase("snapshot"):
            staged_inputs = {root / file.relative_to(stage): file.read_bytes()
                             for file in (stage / 'model').rglob('*') if file.is_file()}
            for file in list(staged_inputs):
                if file.name in {'parameters.yaml', 'bindings.json'}:
                    staged_inputs.setdefault(file.parent / 'observed.json', None)
            # Staged reference views/JSON are inputs until this operation publishes them.
            reference_inputs = {root / file.relative_to(stage): file.read_bytes()
                                for file in (stage / 'docs/designs').rglob('*') if file.is_file()
                                and not any(file == stage / path.relative_to(root) or
                                            file.is_relative_to((stage / path.relative_to(root)).with_suffix(''))
                                            for path in destinations)}
        generated = generate_views(stage, root, destinations, failures)
        validate_candidates(stage, root, generated, destinations, failures, jobs, write)
        saved = {}
        save_failed = False
        with phase("file-comparison"):
            expected_outputs = {path: {root / file.relative_to(stage): file.read_bytes().decode("utf-8") for file in files}
                                for path, files in generated.items()}
            source_snapshots = {path: {**configuration, **staged_inputs, **reference_inputs, **model_snapshots[path]} for path in generated}
        for path in generated:
            try:
                expected = expected_outputs[path]
                if any((source.read_bytes() if source.is_file() else None) != original
                           for source, original in source_snapshots[path].items()):
                    raise ValueError("authoritative model inputs changed before publication; rerun generation")
                if write:
                    with phase("publication"), publication_lock(root):
                        if task_revision(root) != expected_task:
                            raise ValueError("task scope changed after planning; rerun generation")
                        for file in expected:
                            safe(root, file)
                        if any((source.read_bytes() if source.is_file() else None) != original
                               for source, original in source_snapshots[path].items()):
                            raise ValueError("authoritative model inputs changed before publication; rerun generation")
                        if (generation_inputs(root) != configuration or
                                set((root / 'model').rglob('*')) != input_paths):
                            raise ValueError('generation configuration inputs changed before publication')
                        planned = {file: markdown_newlines(file, content) if file.suffix == '.md' else content
                                   for file, content in expected.items()}
                        changed = changed_files(planned)
                        originals = {file: file.read_bytes() if file.is_file() else None for file in changed}
                        def verify():
                            verify_saved(planned)
                            if (generation_inputs(root) != configuration or
                                    set((root / 'model').rglob('*')) != input_paths):
                                raise ValueError('generation inputs changed during publication')
                        if changed:
                            publish(root, changed, inputs=source_snapshots[path], verify=verify, expected_task=expected_task)
                        else:
                            verify()
                    saved[path] = originals
                else:
                    stale = [str(file.relative_to(root)) for file, content in expected.items()
                             if not file.is_file() or file.read_bytes() != content.encode("utf-8")]
                    if stale:
                        raise ValueError("generated Markdown is stale or missing: " + ", ".join(stale))
                saved.setdefault(path, {})
            except (OSError, ValueError, KeyError, TypeError) as error:
                failures.append(f"{path.relative_to(root)}: {error}")
                save_failed = True
        # Publication ends the immutable input snapshot used to validate candidates.
        if write:
            memo_table().clear()
        # Filesystem failures can invalidate newly saved references, too.
        while write and save_failed and saved:
            design_index = DesignIndex()  # Publication/rollback changed the saved views.
            rejected = []
            for path in saved:
                try:
                    sync_views.validate_views(root, root, [path], destinations, design_index=design_index)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    failures.append(f"{path.relative_to(root)}: {error}")
                    rejected.append(path)
            if not rejected:
                break
            for path in sorted(set(rejected)):
                originals = saved[path]
                restore_files(originals)
                saved.pop(path)
        if write and saved:
            retained = [path for path in saved_paths if path not in saved]
            for reference, target in sync_views.broken_design_links(root, root, retained).items():
                if reference not in baseline_links and target in saved:
                    print(f"Design Markdown sync: WARNING ({target.relative_to(root)}: "
                          f"saved reference needs repair in a separate task: {reference})", file=sys.stderr)
        for path in saved:
            completed((*path.relative_to(docs).parts[:2], path.stem))
            print(f"Design Markdown sync: PASS ({path.relative_to(root)})")
    if failures:
        failed_services = (set(markdown_paths) | {
            (docs / path.relative_to(models)).with_suffix(".md") for path in model_paths
        }) - saved.keys()
        raise ValueError(f"{len(saved)} services succeeded; {len(failed_services)} services failed; {len(failures)} diagnostics\n- " + "\n- ".join(failures))
    print(f"Design Markdown sync: PASS ({len(saved)} services)")
    return 0




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
