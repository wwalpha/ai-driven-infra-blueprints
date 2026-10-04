#!/usr/bin/env python3
"""Generate detailed-design Markdown from authoritative service properties."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import argparse
import hashlib
import json
import os
import re
import sys
import importlib.util
import shutil
import tempfile
from pathlib import Path

from design_catalog import design_material_files
from validation_scope import active_scope, reference_lines, scoped_files
from task_contract import task_path, require_writable
from issue_gate import require_no_issues
from design_layout import CODEBUILD_FORMAL_VARIABLE, HIDDEN_PROPERTIES, RESOURCE, STACK_DESIGN, GROUPED, expanded_design, resource_logical_ids, resource_display_name, stack_design, stack_deployment_policy
from policy_tables import without_policy_tables, rendered_design, resources_in, unique_object, invalid_constant
from model_design import properties, entries, markdown_for, resource_rows, resource_display_rows, validate_required_properties, validate_kms_policy_accounts, design_target
from model_files import read_model, model_parts, model_file_contents
from validation_cache import input_scope, memoized
from design_layout import resource_mode, resource_modes


SERVICE_ID = re.compile(r"^- Design service ID: `([^`]+)`$")
OWNED_TYPES = re.compile(r"^- Owned catalog resource types: (`[^`]+`(?:, `[^`]+`)*)$")
ANCHOR = re.compile(r'^<a\s+id="([^"]+)"\s*></a>$')
TABLE_HEADER = "| No. | Property | Value | Source / Comment |"
TABLE_ALIGNMENT = "| ---: | --- | --- | --- |"
JSON_LINK = re.compile(r"^\[[^\]]+\]\(([^)#]+\.json)\)$")
RESOURCE_LINK = re.compile(r"^\[([^\]]+)\]\(([^)]*?)#([^)]+)\)$")


def json_sha256(path: Path) -> str:
    content = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@memoized
def identifier_outputs(root: Path) -> dict[str, set[str]]:
    outputs: dict[str, set[str]] = {}
    for path in design_material_files(root):
        resource_type = path.stem.replace("_", ".", 1)
        outputs[resource_type] = {
            line.partition("=")[0]
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.endswith("=IDENTIFIER_OUTPUT") and line.partition("=")[0] not in HIDDEN_PROPERTIES
        }
    return outputs


def linked_resource(path: Path, value: str) -> tuple[str, str] | None:
    match = RESOURCE_LINK.fullmatch(value)
    if not match:
        return None
    _, target_text, fragment = match.groups()
    target = path if not target_text else path.parent / target_text
    if not target.is_file():
        return None
    pending_anchor = ""
    source = reference_lines(target, {fragment})
    identities = resource_logical_ids(source)
    lines, _ = expanded_design(source)
    for line in lines:
        if anchor := ANCHOR.fullmatch(line):
            pending_anchor = anchor.group(1)
        elif resource := RESOURCE.fullmatch(line):
            if pending_anchor == fragment:
                return resource.group(1), identities.get(resource.groups(), resource.group(2))
            pending_anchor = ""
    return None


def logical_link(value: str, logical_id: str) -> str:
    match = RESOURCE_LINK.fullmatch(value)
    if not match:
        return value
    return f"[{logical_id}]({match.group(2)}#{match.group(3)})"


def one_match(pattern: re.Pattern[str], lines: list[str], label: str, path: Path) -> re.Match[str]:
    matches = [match for line in lines if (match := pattern.fullmatch(line))]
    if len(matches) != 1:
        raise ValueError(f"{label} must appear exactly once: {path}")
    return matches[0]


def model_for(path: Path, root: Path | None = None) -> str:
    """Read-only projection for verification and explicit migration; never save it by default."""
    if path.name == STACK_DESIGN:
        from design_layout import stack_delivery
        stacks = stack_design(path)
        output = ["# Stack design projection", f"desired.deployment.maxConcurrentStacks={stack_deployment_policy(path)}"]
        output += [f"{key}={value}" for key, value in stack_delivery(path).items()]
        for number, stack in enumerate(stacks, 1):
            key = f"desired.stack.{number:03d}"
            output.extend((
                f'{key}.name={stack["name"]}',
                f'{key}.template={stack["template"]}',
                f'{key}.parameters={stack["parameters"]}',
                f'{key}.deployOrder={stack["deployOrder"]}',
            ))
        return "\n".join(output) + "\n"
    catalog_outputs = identifier_outputs(root or Path(__file__).resolve().parents[2])
    lines = path.read_text(encoding="utf-8").splitlines()
    modes = resource_modes(lines)
    from design_layout import resource_identity_metadata
    resource_numbers, cfn_ids = resource_identity_metadata(lines)
    lines = [line for line in lines if not line.startswith(("<!-- resource-mode:", "<!-- resource-entry:", "<!-- cfn-logical-id:"))]
    identities = resource_logical_ids(lines)
    lines, children = expanded_design(without_policy_tables(lines))
    service_id = one_match(SERVICE_ID, lines, "Design service ID", path).group(1)
    owned = ",".join(
        re.findall(
            r"`([^`]+)`",
            one_match(OWNED_TYPES, lines, "Owned catalog resource types", path).group(1),
        )
    )
    output = [
        "# Generated by framework/scripts/sync-model.py; do not edit.",
        f"desired.service.{service_id}.serviceId={service_id}",
        f"desired.service.{service_id}.ownedCatalogResourceTypes={owned}",
    ]
    pending_anchor = ""
    resource_anchors = set()
    current_type = ""
    current_logical_id = ""
    current_anchor = ""
    resource_number = 0
    note_number = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if match := ANCHOR.fullmatch(line):
            pending_anchor = match.group(1)
            index += 1
            continue
        if match := RESOURCE.fullmatch(line):
            resource_number += 1
            current_type, current_logical_id = match.groups()
            current_logical_id = identities.get(match.groups(), current_logical_id)
            current_anchor = pending_anchor
            resource_anchors.add(current_anchor)
            key = resource_numbers.get(current_anchor, f"{resource_number:03d}")
            current_resource_number = key
            output.extend(
                (
                    f"desired.resource.{key}.resourceType={current_type}",
                    f"desired.resource.{key}.anchor={pending_anchor}",
                )
            )
            if current_anchor not in resource_numbers:
                output.append(f"desired.resource.{key}.logicalId={current_logical_id}")
            if current_anchor in cfn_ids:
                output.append(f"desired.resource.{key}.cfn-logicalId={cfn_ids.pop(current_anchor)}")
            if child := children.get(current_anchor):
                output.extend((
                    f'desired.resource.{key}.parentProperty={child["parentProperty"]}',
                    f'desired.resource.{key}.parentReference=[{child["parentLogicalId"]}](#{child["parentAnchor"]})',
                ))
            if current_anchor in modes:
                output.append(f"desired.resource.{key}.resourceMode={modes.pop(current_anchor)}")
            pending_anchor = ""
            index += 1
            continue
        if line == TABLE_HEADER:
            if not current_type:
                raise ValueError(f"resource table has no resource heading: {path}")
            if index + 1 >= len(lines) or lines[index + 1] != TABLE_ALIGNMENT:
                raise ValueError(f"invalid resource table alignment: {path}")
            index += 2
            row_number = 0
            while index < len(lines) and lines[index].startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
                if len(cells) != 4:
                    raise ValueError(f"resource table row must have four cells: {path}")
                row_number += 1
                key = f"{current_resource_number}-{row_number:03d}"
                linked = linked_resource(path, cells[2])
                is_identifier_output = cells[1] in catalog_outputs.get(current_type, set())
                is_identifier_reference = bool(
                    linked and catalog_outputs.get(linked[0])
                    and cells[1] != CODEBUILD_FORMAL_VARIABLE + "Value"
                )
                desired_value = cells[2]
                if is_identifier_output:
                    desired_value = f"[{current_logical_id}](#{current_anchor})"
                elif is_identifier_reference and linked:
                    desired_value = logical_link(cells[2], linked[1])
                output.extend(
                    (
                        f"desired.row.{key}.property={cells[1]}",
                        f"desired.row.{key}.value={desired_value}",
                        f"desired.row.{key}.comment={cells[3]}",
                    )
                )
                if is_identifier_output or is_identifier_reference:
                    observed_value = RESOURCE_LINK.fullmatch(cells[2]).group(1) if is_identifier_reference else cells[2]
                    output.extend(
                        (
                            f"observed.row.{key}.property={cells[1]}",
                            f"observed.row.{key}.value={observed_value}",
                            f"observed.row.{key}.comment={cells[3]}",
                        )
                    )
                if match := JSON_LINK.fullmatch(cells[2]):
                    artifact = path.parent / match.group(1)
                    if not artifact.is_file():
                        raise ValueError(f"linked JSON artifact is missing: {artifact}")
                    digest = json_sha256(artifact)
                    output.append(f"desired.row.{key}.artifactSha256={digest}")
                index += 1
            continue
        if line.startswith("|"):
            while index < len(lines) and lines[index].startswith("|"):
                index += 1
            continue
        if line and not (
            line.startswith("#")
            or line.startswith("- Design service ID:")
            or line.startswith("- Owned catalog resource types:")
            or line.startswith("```")
        ):
            note_number += 1
            output.append(f"desired.note.{note_number:03d}.text={line}")
        index += 1
    if set(resource_numbers) - resource_anchors:
        raise ValueError("resource entry metadata must identify a resource anchor")
    if cfn_ids:
        raise ValueError(f"cfn-logicalId metadata must identify a resource anchor: {sorted(cfn_ids)}")
    if modes:
        raise ValueError(f"resource mode metadata must identify a resource anchor: {sorted(modes)}")
    return "\n".join(output) + "\n"


def imported_model(path: Path, root: Path) -> str:
    """Preserve display inputs when explicitly migrating an existing design."""
    model = model_for(path, root)
    source = path.read_text(encoding="utf-8").splitlines()
    output = []
    if path.name == STACK_DESIGN:
        for number, stack in enumerate(stack_design(path), 1):
            output.append(f'display.stack.{number:03d}.comment={stack["comment"]}')
    else:
        output.append("display.service.title=" + next(line for line in source if line.startswith("# ")))
        values = properties(model)
        overview = {}
        for line in source:
            if line.startswith("|"):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if len(cells) == 3 and (match := RESOURCE_LINK.fullmatch(cells[1])):
                    overview[match.group(3)] = cells[2]
        headings = {anchor: name for anchor, kind, name in (
            (resource.anchor, resource.resource_type, resource.logical_id)
            for resource in resources_in(without_policy_tables(source))
        )}
        _, children = expanded_design(without_policy_tables(source))
        headings.update({anchor: child["displayName"] for anchor, child in children.items() if "displayName" in child})
        for identity, resource in entries(values, "desired.resource."):
            rows = resource_display_rows(values, identity, resource, root)
            label = headings.get(resource["anchor"])
            configured_name = resource_display_name(resource["resourceType"], rows, label, resource_mode(resource))
            multiple_aliases = resource["resourceType"] == "KMS.Key" and len({row[2] for row in rows if row[1] == "KMS.Alias.AliasName"}) > 1
            if (configured_name is None or multiple_aliases) and GROUPED.get(resource["resourceType"], {}).get("display") != "rule-table":
                if label is None:
                    raise ValueError(f"confirmed display label required for grouped resource: {resource['logicalId']}")
                if label != resource["resourceType"]:
                    output.append(f"display.resource.{identity}.label={label}")
            if resource["resourceType"] not in GROUPED:
                if resource["anchor"] not in overview:
                    raise ValueError(f"resource overview comment is missing: {resource['anchor']}")
                output.append(f"display.resource.{identity}.comment={overview[resource['anchor']]}")
        for identity, row in entries(values, "desired.row."):
            if match := JSON_LINK.fullmatch(row["value"]):
                document = json.loads((path.parent / match.group(1)).read_text(encoding="utf-8"), object_pairs_hook=unique_object, parse_constant=invalid_constant)
                output.append(f"desired.row.{identity}.document=" + json.dumps(document, ensure_ascii=False, separators=(",", ":")))
    return model.replace("# Generated by framework/scripts/sync-model.py; do not edit.", "# Authoritative design values; Markdown is generated by framework/scripts/sync-model.py.") + "\n".join(output) + "\n"


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
        expected_models = {(models / path.relative_to(docs)).with_suffix(".properties"): imported_model(path, root) for path in markdown_paths}
        if any(path.is_file() for path in expected_models):
            raise ValueError("Markdown import must not overwrite an existing authoritative model")
        outputs = {file: content for path, text in expected_models.items()
                   for file, content in model_file_contents(path, text).items()}
        require_writable(root, outputs)
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
        baseline_links = broken_design_links(stage, root, [stage / path.relative_to(root) for path in saved_paths]) if write else {}
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
        # A rejected view falls back to its saved state; recheck dependent services.
        def validate(path):
            try:
                validate_views(stage, root, [stage / path.relative_to(root)], destinations)
            except (OSError, ValueError, KeyError, TypeError) as error:
                return path, f"{path.relative_to(root)}: {error}"
            return path, None

        while generated:
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
        saved = {}
        save_failed = False
        for path, files in generated.items():
            try:
                expected = {root / file.relative_to(stage): file.read_text(encoding="utf-8") for file in files}
                if write:
                    require_writable(root, expected)
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
        # Filesystem failures can invalidate newly saved references, too.
        while write and save_failed and saved:
            rejected = []
            for path in saved:
                try:
                    validate_views(root, root, [path], destinations)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    failures.append(f"{path.relative_to(root)}: {error}")
                    rejected.append(path)
            if not rejected:
                break
            for path in sorted(set(rejected)):
                restore_files(saved.pop(path))
        if write and saved:
            retained = [path for path in saved_paths if path not in saved]
            for reference, target in broken_design_links(root, root, retained).items():
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
    print(f"Design Markdown sync: PASS ({len(saved)} services)")
    return 0


def restore_view(stage: Path, root: Path, path: Path) -> None:
    """Discard a failed service's temporary view and retain its saved reference state."""
    staged = stage / path.relative_to(root)
    staged.unlink(missing_ok=True)
    if path.is_file():
        shutil.copyfile(path, staged)
    shutil.rmtree(staged.with_suffix(""), ignore_errors=True)
    if path.with_suffix("").is_dir():
        shutil.copytree(path.with_suffix(""), staged.with_suffix(""))


def view_validator(stage: Path, root: Path):
    spec = importlib.util.spec_from_file_location("blueprint_view_validator", Path(__file__).with_name("validate-blueprint.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    validator = module.Validator(stage)
    validator.schema_catalog = module.DesignSchemaCatalog(root)
    return validator


def broken_design_links(stage: Path, root: Path, paths: list[Path]) -> dict[str, Path]:
    """Use existing link diagnostics, keyed by source/link independently of failure kind."""
    if not paths:
        return {}
    validator = view_validator(stage, root)
    validator.check_design_links(identifier_outputs(root), paths)
    broken = {}
    for error in validator.errors:
        kind, _, reference = error.partition(": ")
        if kind not in {"broken design link", "missing design anchor"}:
            continue
        source_text, raw = reference.split(": ", 1)
        source = stage / source_text
        target_text = raw.partition("#")[0]
        target = (source.parent / target_text if target_text else source).resolve()
        if target.parent == source.parent:
            broken[reference] = root / target.relative_to(stage)
    return broken


@input_scope
def validate_views(stage: Path, root: Path, paths: list[Path], sources: dict[Path, dict[str, str]]) -> None:
    """Use the existing parsers/schema validator before touching any saved view."""
    for path in paths:
        actual = properties(model_for(path, root))
        source = sources[root / path.relative_to(stage)]
        formal = {key: value for key, value in source.items() if not key.startswith("display.") and not key.endswith((".document", ".artifactSha256"))}
        actual = {key: value for key, value in actual.items() if not key.endswith(".artifactSha256")}
        if path.name == STACK_DESIGN:
            from model_design import stack_model, deployment_settings
            # Display numbering is independent of authoritative entry IDs.
            actual_limit, actual_stacks = stack_model(actual)
            formal_limit, formal_stacks = stack_model(formal)
            actual_delivery, actual_artifacts = deployment_settings(actual)
            formal_delivery, formal_artifacts = deployment_settings(formal)
            if actual_limit != formal_limit or [s for _, s in actual_stacks] != [s for _, s in formal_stacks] or \
                    actual_delivery != formal_delivery or [a for _, a in actual_artifacts] != [a for _, a in formal_artifacts]:
                raise ValueError(f"model/display projection mismatch: {path.name}")
            continue
        if actual != formal:
            differences = sorted(key for key in actual.keys() | formal.keys() if actual.get(key) != formal.get(key))
            raise ValueError(f"model/display projection mismatch: {path.name}: {', '.join(differences)}")
    if not paths:
        return
    validator = view_validator(stage, root)
    validator.check_project_topology()
    for path in paths:
        validator.check_target_file(path, stage / "docs/designs")
        validator.check_target_file((stage / "model" / path.relative_to(stage / "docs/designs")).with_suffix(".properties"), stage / "model")
    validator.check_stack_designs([path for path in paths if path.name == STACK_DESIGN])
    services = [path for path in paths if path.name != STACK_DESIGN]
    metadata, types, owners, outputs = validator.check_design_service_ownership(services)
    validator.check_resource_names(metadata, services)
    validator.check_design_tables(metadata, types, owners, outputs, services)
    validator.check_design_overviews(services)
    validator.check_design_links(outputs, services)
    validator.check_design_artifacts(services)
    validator.check_observed_values([(stage / "model" / path.relative_to(stage / "docs/designs")).with_suffix(".properties") for path in paths])
    if validator.errors:
        raise ValueError("\n- ".join(validator.errors))


def save_files(expected: dict[Path, str]) -> None:
    """Rollback this service if a filesystem write fails after successful generation."""
    originals = {path: path.read_bytes() if path.is_file() else None for path in expected}
    written = []
    try:
        for path, content in expected.items():
            if originals[path] == content.encode("utf-8"):
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            written.append(path)
            path.write_text(content, encoding="utf-8")
    except OSError as error:
        try:
            restore_files({path: originals[path] for path in reversed(written)})
        except OSError as rollback_error:
            raise OSError(f"{error}; generated-file rollback failed: {rollback_error}") from error
        raise


def restore_files(originals: dict[Path, bytes | None]) -> None:
    errors = []
    for path, content in originals.items():
        try:
            if content is None:
                path.unlink(missing_ok=True)
            elif not path.is_file() or path.read_bytes() != content:
                path.write_bytes(content)
        except OSError as error:
            errors.append(f"{path}: {error}")
    if errors:
        raise OSError("; ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--import-markdown", action="store_true", help="Explicit one-time migration; requires a migration task and absent models")
    parser.add_argument("--environment")
    parser.add_argument("--aws-account-id")
    parser.add_argument("--alias")
    parser.add_argument("--service", action="append", help="Exact design service ID (repeatable)")
    parser.add_argument("--all", action="store_true", help="Explicit full generation/validation")
    parser.add_argument("--jobs", type=int, choices=(1, 2, 4), default=4, help="Read-only service/target validation workers")
    args = parser.parse_args()
    selectors = bool(args.aws_account_id) + bool(args.alias)
    if (args.environment and selectors != 1) or (not args.environment and selectors):
        parser.error(
            "--environment must be used with exactly one of --aws-account-id or --alias"
        )
    try:
        root = args.repository_root.resolve()
        if args.all:
            if args.service or args.environment:
                parser.error("--all cannot be combined with target/service selectors")
            return sync(root, args.write, import_markdown=args.import_markdown, jobs=args.jobs)
        contract_scope = active_scope(root)
        if args.service:
            if not args.environment or any(not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", service) for service in args.service):
                parser.error("--service requires a complete environment/target and valid service ID")
            scope = {(args.environment, args.alias or args.aws_account_id, service) for service in args.service}
            if contract_scope is not None and not scope <= contract_scope:
                raise ValueError("requested services are outside active task validation scope")
        else:
            scope = contract_scope
            if scope is None:
                return sync(root, args.write, args.environment, args.alias or args.aws_account_id, args.import_markdown, jobs=args.jobs)
            if args.environment:
                scope = {item for item in scope if item[:2] == (args.environment, args.alias or args.aws_account_id)}
            if not scope:
                raise ValueError("no service validation scope; specify environment/target/service")
        groups = {}
        for environment, target, service in sorted(scope):
            groups.setdefault((environment, target), []).append(service)
        def generate(item):
            (environment, target), services = item
            try:
                sync(root, args.write, environment, target, args.import_markdown, services,
                     jobs=args.jobs if len(groups) == 1 else 1)
            except (OSError, ValueError, KeyError, TypeError) as error:
                return str(error)
            return None
        with ThreadPoolExecutor(max_workers=min(args.jobs, len(groups))) as executor:
            failures = [error for error in executor.map(generate, groups.items()) if error]
        if failures:
            raise ValueError("\n- ".join(failures))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Design Markdown sync: FAIL\n- {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if directory := os.environ.get("BLUEPRINT_PROFILE_DIR"):
        import cProfile
        import pstats
        profile = cProfile.Profile()
        identity = hashlib.sha256("\0".join(sys.argv[1:]).encode()).hexdigest()[:12]
        try:
            raise SystemExit(profile.runcall(main))
        finally:
            profile.dump_stats(str(Path(directory) / f"sync-model-{identity}.prof"))
            pstats.Stats(profile).strip_dirs().sort_stats("cumulative").print_stats(25)
    raise SystemExit(main())
