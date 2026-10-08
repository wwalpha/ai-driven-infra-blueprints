"""Validate a fixed Markdown snapshot with the existing scoped validator."""

import importlib.util
from pathlib import Path
from design_document import DesignIndex
from model_core import properties
from model_projection import model_for, identifier_outputs
from design_layout import STACK_DESIGN
from validation_cache import input_scope


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
def validate_views(stage: Path, root: Path, paths: list[Path], sources: dict[Path, dict[str, str]], *,
                   design_index: DesignIndex | None = None) -> None:
    """Use the existing parsers/schema validator before touching any saved view."""
    design_index = design_index or DesignIndex()
    for path in paths:
        source = sources[root / path.relative_to(stage)]
        actual = properties(model_for(path, root, source=source, design_index=design_index))
        # CFn identity is model-only and has no Markdown projection.
        formal = {key: value for key, value in source.items() if not key.startswith("display.") and not key.endswith((".document", ".artifactSha256", ".cfn-logicalId"))}
        actual = {key: value for key, value in actual.items() if not key.endswith(".artifactSha256")}
        if path.name == STACK_DESIGN:
            from model_core import stack_model, deployment_settings
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
    validator.design_sources = {path: sources[root / path.relative_to(stage)] for path in paths}
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
    validator.check_design_links(outputs, services, design_index=design_index)
    validator.check_design_artifacts(services)
    validator.check_observed_values([(stage / "model" / path.relative_to(stage / "docs/designs")).with_suffix(".properties") for path in paths])
    if validator.errors:
        raise ValueError("\n- ".join(validator.errors))


