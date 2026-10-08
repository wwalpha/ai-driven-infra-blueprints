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
from model_projection import imported_model, JSON_LINK
from model_files import read_model, model_parts, model_file_contents
from policy_tables import rendered_design, unique_object, invalid_constant
from task_contract import task_path, require_writable, reserved_batches, DeferredExhausted
from issue_gate import require_no_issues
from validation_scope import scoped_files
from validation_cache import input_scope
from sync_files import save_files, restore_files
import sync_views


def stage_inputs(stage, root, destinations, model_paths, markdown_paths, services, write):
    docs, models = root / "docs/designs", root / "model"
    shutil.copytree(root / "framework", stage / "framework")
    targets = {path.parent.relative_to(docs) for path in destinations}
    if services is None:
        for target in targets:
            for base in (docs, models):
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
        model_inputs = {file for path in model_paths
                        if (docs / path.relative_to(models)).with_suffix(".md") in destinations
                        for file in [path, *model_parts(path)]}
        # Stack delivery links need the selected bucket's authoritative name, not a full S3 validation.
        for path, values in destinations.items():
            if path.name == STACK_DESIGN and any(key.startswith("desired.artifact.") or key == "desired.deployment.templateBucket" for key in values):
                referenced = models / path.parent.relative_to(docs) / "s3.properties"
                if referenced.is_file():
                    model_inputs.update([referenced, *model_parts(referenced)])
        for path, values in destinations.items():
            if any(key.endswith(".cfn-logicalId") for key in values):
                referenced = models / path.parent.relative_to(docs) / "cloudformation-stacks.properties"
                if referenced.is_file():
                    model_inputs.update([referenced, *model_parts(referenced)])
        for path in [*model_inputs, *views]:
            destination = stage / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
        for path in markdown_paths:
            if path.with_suffix("").is_dir():
                shutil.copytree(path.with_suffix(""), stage / path.with_suffix("").relative_to(root))
    if (root / "project.json").is_file():
        shutil.copyfile(root / "project.json", stage / "project.json")
    saved_paths = [root / path.relative_to(stage) for path in (stage / "docs/designs").rglob("*.md")]
    baseline_links = sync_views.broken_design_links(stage, root, [stage / path.relative_to(root) for path in saved_paths]) if write else {}
    return saved_paths, baseline_links


def generate_views(stage, root, destinations, failures):
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
            staged.write_text(markdown_for(staged, values, stage), encoding="utf-8")
            generated[path] = [*artifacts, staged]
        except (OSError, ValueError, KeyError, TypeError) as error:
            failures.append(f"{path.relative_to(root)}: {error}")
            restore_view(stage, root, path)
    for path in list(generated):
        try:
            staged = stage / path.relative_to(root)
            if path.name != STACK_DESIGN:
                staged.write_text(rendered_design(staged), encoding="utf-8")
        except (OSError, ValueError, KeyError, TypeError) as error:
            failures.append(f"{path.relative_to(root)}: {error}")
            del generated[path]
            restore_view(stage, root, path)
    return generated


def validate_candidates(stage, root, generated, destinations, failures, jobs, write):
    # A rejected view falls back to its saved state; recheck dependent services.
    def validate(path):
        try:
            sync_views.validate_views(stage, root, [stage / path.relative_to(root)], destinations, design_index=design_index)
        except (OSError, ValueError, KeyError, TypeError) as error:
            return path, f"{path.relative_to(root)}: {error}"
        return path, None

    while generated:
        design_index = DesignIndex()  # A new snapshot after each restore_view phase.
        rejected = []
        # All candidate views are fixed during this read-only phase.
        with ThreadPoolExecutor(max_workers=1 if write else min(jobs, len(generated))) as executor:
            mapper = map if write or jobs == 1 else executor.map
            for path, error in mapper(validate, sorted(generated)):
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


@input_scope
def sync(
    root: Path,
    write: bool,
    environment: str | None = None,
    target_directory: str | None = None,
    import_markdown: bool = False,
    services: list[str] | None = None,
    jobs: int = 4,
) -> int:
    root = root.resolve()
    docs = root / "docs" / "designs"
    models = root / "model"
    scope = {(environment, target_directory, service) for service in services} if services is not None else None
    if services is not None and (not environment or not target_directory):
        raise ValueError("service selection requires environment and target directory")
    if write:
        require_no_issues(root, scope, target=(environment, target_directory) if environment else None)
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
    if services is not None and not import_markdown:
        for service in services:
            if not any(path.stem == service for path in model_paths):
                raise ValueError(f"authoritative service model missing: {environment}/{target_directory}/{service}")
    if import_markdown:
        if not write:
            raise ValueError("--import-markdown requires --write and an explicitly authorized migration task")
        contract = task_path(root)
        if not contract.is_file() or "- Task type: `migration`" not in contract.read_text(encoding="utf-8"):
            raise ValueError("Markdown import is allowed only in an explicit migration task")
        import_inputs = {path: path.read_bytes() for path in markdown_paths}
        expected_models = {(models / path.relative_to(docs)).with_suffix(".properties"): imported_model(path, root) for path in markdown_paths}
        if any(path.is_file() for path in expected_models):
            raise ValueError("Markdown import must not overwrite an existing authoritative model")
        outputs = {file: content for path, text in expected_models.items()
                   for file, content in model_file_contents(path, text).items()}
        for _ in reserved_batches(root, {"import": outputs}):
            require_writable(root, outputs)
            if any(path.is_file() for path in expected_models):
                raise ValueError("Markdown import must not overwrite an existing authoritative model")
            if any(not path.is_file() or path.read_bytes() != original for path, original in import_inputs.items()):
                raise ValueError("Markdown import inputs changed before publication; rerun import")
            save_files(outputs)
        print(f"Service model import: PASS ({len(expected_models)} files); verify and generate Markdown next")
        return 0
    destinations = {}
    failures = []
    for path in model_paths:
        destination = (docs / path.relative_to(models)).with_suffix(".md")
        try:
            destinations[destination] = properties(read_model(path))
        except (OSError, ValueError, KeyError, TypeError) as error:
            failures.append(f"{path.relative_to(root)}: {error}")
    for path in sorted(set(markdown_paths) - {(docs / path.relative_to(models)).with_suffix(".md") for path in model_paths}):
        failures.append(f"authoritative model missing; explicit migration required: {path.relative_to(root)}")
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory).resolve()
        saved_paths, baseline_links = stage_inputs(stage, root, destinations, model_paths, markdown_paths, services, write)
        generated = generate_views(stage, root, destinations, failures)
        validate_candidates(stage, root, generated, destinations, failures, jobs, write)
        saved = {}
        save_failed = False
        expected_outputs = {path: {root / file.relative_to(stage): file.read_text(encoding="utf-8") for file in files}
                            for path, files in generated.items()}
        source_inputs = {}
        if write:
            for path in generated:
                source = (stage / "model" / path.relative_to(docs)).with_suffix(".properties")
                source_inputs[path] = {root / part.relative_to(stage): part.read_bytes()
                                       for part in {source, *model_parts(source)}}
        pending_error = None
        batches = reserved_batches(root, expected_outputs) if write else iter(generated)
        try:
            for path in batches:
                try:
                    expected = expected_outputs[path]
                    if write:
                        require_writable(root, expected)
                        if any(not source.is_file() or source.read_bytes() != original
                               for source, original in source_inputs[path].items()):
                            raise ValueError("authoritative model inputs changed before publication; rerun generation")
                        originals = {file: file.read_bytes() if file.is_file() else None for file in expected}
                        save_files(expected)
                        saved[path] = originals
                    else:
                        stale = [str(file.relative_to(root)) for file, content in expected.items()
                                 if not file.is_file() or file.read_text(encoding="utf-8") != content]
                        if stale:
                            raise ValueError("generated Markdown is stale or missing: " + ", ".join(stale))
                    saved.setdefault(path, {})
                except (OSError, ValueError, KeyError, TypeError) as error:
                    failures.append(f"{path.relative_to(root)}: {error}")
                    save_failed = True
        except DeferredExhausted as error:
            pending_error = error
            save_failed = True  # Validate saved references against retained Deferred outputs, too.
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
                restore_files(saved.pop(path))
        if write and saved:
            retained = [path for path in saved_paths if path not in saved]
            for reference, target in sync_views.broken_design_links(root, root, retained).items():
                if reference not in baseline_links and target in saved:
                    print(f"Design Markdown sync: WARNING ({target.relative_to(root)}: "
                          f"saved reference needs repair in a separate task: {reference})", file=sys.stderr)
        for path in saved:
            print(f"Design Markdown sync: PASS ({path.relative_to(root)})")
    if failures:
        failed_services = (set(markdown_paths) | {
            (docs / path.relative_to(models)).with_suffix(".md") for path in model_paths
        }) - saved.keys()
        raise ValueError(f"{len(saved)} services succeeded; {len(failed_services)} services failed; {len(failures)} diagnostics\n- " + "\n- ".join(failures))
    if pending_error:
        raise pending_error
    print(f"Design Markdown sync: PASS ({len(saved)} services)")
    return 0


