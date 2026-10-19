"""Validate a fixed Markdown snapshot with the existing scoped validator."""

import importlib.util
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from design_document import DesignIndex
from design_layout import STACK_DESIGN
from validation_cache import input_scope
from utils.aws_mappings import definition_root


_saved_design_validation = ContextVar("saved_design_validation", default=None)


@contextmanager
def saved_design_validation(root, entry):
    """Defer common candidate checks to the caller's saved single-service validation."""
    token = _saved_design_validation.set((root.resolve(), entry))
    try:
        yield
    finally:
        _saved_design_validation.reset(token)


def view_validator(stage: Path, root: Path, definitions_root=None):
    definitions_root = definitions_root or definition_root(root)
    spec = importlib.util.spec_from_file_location("blueprint_view_validator", Path(__file__).with_name("validate-blueprint.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    validator = module.Validator(stage, definitions_root=definitions_root)
    validator.schema_catalog = module.DesignSchemaCatalog(definitions_root)
    return validator


def broken_design_links(stage: Path, root: Path, paths: list[Path], *, definitions_root=None) -> dict[str, Path]:
    """Use existing link diagnostics, keyed by source/link independently of failure kind."""
    if not paths:
        return {}
    validator = view_validator(stage, root, definitions_root)
    validator.check_design_links(validator.catalog_design_properties()[2], paths, design_index=DesignIndex(root))
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


def validation_context(stage, root, generated, sources, accounts=None, definitions_root=None):
    """Whole-candidate scope metadata/ownership/stack checks, once per fixed state."""
    validator = view_validator(stage, root, definitions_root)
    paths = [stage / p.relative_to(root) for p in generated]
    validator.scope = {(*p.relative_to(stage / 'docs/designs').parts[:2], p.stem) for p in paths}
    validator.design_sources = {stage / p.relative_to(root): values for p, values in sources.items()}
    if accounts is None:
        validator.check_project_topology()
    else:
        validator.accounts = accounts
    services = [p for p in paths if p.name != STACK_DESIGN]
    from validation_scope import scoped_files
    evaluate = lambda name, handler: validator.findings.evaluate(name, validator.scope, handler)
    evaluate('design.collections', lambda: validator.check(
        set(services) == set(validator.design_files()) and
        {p.with_suffix('').relative_to(stage / 'docs/designs') for p in services} ==
        {p.with_suffix('').relative_to(stage / 'model') for p in scoped_files(stage, 'model', '.properties', validator.scope) if p.stem != Path(STACK_DESIGN).stem},
        'design/model group mismatch in generation candidates'))
    metadata = evaluate('design.ownership', lambda: {'ownership': validator.check_design_service_ownership(services)})
    validator.ownership = metadata.metadata['ownership']
    evaluate('design.stacks', lambda: {'stack_definitions': validator.check_stack_designs([p for p in paths if p.name == STACK_DESIGN])})
    validator.check_policy_tables()
    return validator


@input_scope
def validate_views(stage: Path, root: Path, paths: list[Path], sources: dict[Path, dict[str, str]], *,
                   design_index: DesignIndex | None = None, context=None, definitions_root=None):
    """Return this candidate's domain results; never rerun Task/Git/common checks."""
    deferred = _saved_design_validation.get()
    if deferred is not None:
        expected = stage / 'docs/designs' / deferred[1][0] / deferred[1][1] / (deferred[1][2] + '.md')
        if root.resolve() != deferred[0] or paths != [expected]:
            raise ValueError('saved design validation requires the selected single service')
    design_index = design_index or DesignIndex(root)
    validator = view_validator(stage, root, definitions_root)
    validator.design_sources = {path: sources[root / path.relative_to(stage)] for path in paths}
    validator.scope = {(*p.relative_to(stage / "docs/designs").parts[:2], p.stem) for p in paths}
    if context is not None:
        validator.findings.candidate = context.findings.candidate
        validator.accounts = context.accounts
    else:
        validator.check_project_topology()
    evaluate = lambda name, handler: validator.findings.evaluate(name, validator.scope, handler)
    for path in paths:
        validator.check_target_file(path, stage / "docs/designs")
        validator.check_target_file((stage / "model" / path.relative_to(stage / "docs/designs")).with_suffix(".properties"), stage / "model")
    services = [path for path in paths if path.name != STACK_DESIGN]
    if context is None:
        evaluate('design.stacks', lambda: validator.check_stack_designs([path for path in paths if path.name == STACK_DESIGN]))
        metadata, types, owners, outputs = validator.check_design_service_ownership(services)
        if deferred is None:
            validator.check_policy_tables()
    else:
        metadata, types, owners, outputs = context.ownership
    if deferred is None:
        evaluate('design.names', lambda: validator.check_resource_names(metadata, services))
        evaluate('design.tables', lambda: validator.check_design_tables(metadata, types, owners, outputs, services))
        evaluate('design.overviews', lambda: validator.check_design_overviews(services))
        evaluate('design.links', lambda: validator.check_design_links(outputs, services, design_index=design_index))
        evaluate('design.artifacts', lambda: validator.check_design_artifacts(services))
        evaluate('design.observed', lambda: validator.check_observed_values([
            (stage / "model" / path.relative_to(stage / "docs/designs")).with_suffix(".properties") for path in paths]))
    if validator.errors:
        raise ValueError("\n- ".join(validator.errors))
    return validator.findings
