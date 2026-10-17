"""Validate a fixed Markdown snapshot with the existing scoped validator."""

import importlib.util
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from design_document import DesignIndex
from model_core import properties
from model_projection import model_for, identifier_outputs
from design_layout import STACK_DESIGN
from aws_mapping_display import projection
from validation_cache import input_scope


_saved_design_validation = ContextVar("saved_design_validation", default=None)


@contextmanager
def saved_design_validation(root, entry):
    """Defer common candidate checks to the caller's saved single-service validation."""
    token = _saved_design_validation.set((root.resolve(), entry))
    try:
        yield
    finally:
        _saved_design_validation.reset(token)


def view_validator(stage: Path, root: Path):
    spec = importlib.util.spec_from_file_location("blueprint_view_validator", Path(__file__).with_name("validate-blueprint.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    validator = module.Validator(stage, definitions_root=root)
    validator.schema_catalog = module.DesignSchemaCatalog(root)
    return validator


def broken_design_links(stage: Path, root: Path, paths: list[Path]) -> dict[str, Path]:
    """Use existing link diagnostics, keyed by source/link independently of failure kind."""
    if not paths:
        return {}
    validator = view_validator(stage, root)
    validator.check_design_links(identifier_outputs(root), paths, design_index=DesignIndex(root))
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


def validation_context(stage, root, generated, sources, accounts=None):
    """Whole-candidate scope metadata/ownership/stack checks, once per fixed state."""
    validator = view_validator(stage, root)
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
    evaluate('design.stacks', lambda: validator.check_stack_designs([p for p in paths if p.name == STACK_DESIGN]))
    validator.check_policy_tables()
    return validator


def check_projection(stage, root, paths, sources, design_index):
    for path in paths:
        source = sources[root / path.relative_to(stage)]
        actual = properties(model_for(path, root, source=source, design_index=design_index))
        formal = {key: value for key, value in projection(source, root).items() if not key.startswith("display.") and not key.endswith((".document", ".artifactSha256", ".cfn-logicalId"))}
        actual = {key: value for key, value in actual.items() if not key.endswith(".artifactSha256")}
        if path.name == STACK_DESIGN:
            from model_core import stack_model, deployment_settings
            actual_limit, actual_stacks = stack_model(actual)
            formal_limit, formal_stacks = stack_model(formal)
            actual_delivery, actual_artifacts = deployment_settings(actual)
            formal_delivery, formal_artifacts = deployment_settings(formal)
            if actual_limit != formal_limit or [s for _, s in actual_stacks] != [s for _, s in formal_stacks] or \
                    actual_delivery != formal_delivery or [a for _, a in actual_artifacts] != [a for _, a in formal_artifacts]:
                raise ValueError(f"model/display projection mismatch: {path.name}")
        elif actual != formal:
            differences = sorted(key for key in actual.keys() | formal.keys() if actual.get(key) != formal.get(key))
            raise ValueError(f"model/display projection mismatch: {path.name}: {', '.join(differences)}")


@input_scope
def validate_views(stage: Path, root: Path, paths: list[Path], sources: dict[Path, dict[str, str]], *,
                   design_index: DesignIndex | None = None, context=None):
    """Return this candidate's domain results; never rerun Task/Git/common checks."""
    deferred = _saved_design_validation.get()
    if deferred is not None:
        expected = stage / 'docs/designs' / deferred[1][0] / deferred[1][1] / (deferred[1][2] + '.md')
        if root.resolve() != deferred[0] or paths != [expected]:
            raise ValueError('saved design validation requires the selected single service')
    design_index = design_index or DesignIndex(root)
    validator = view_validator(stage, root)
    validator.design_sources = {path: sources[root / path.relative_to(stage)] for path in paths}
    validator.scope = {(*p.relative_to(stage / "docs/designs").parts[:2], p.stem) for p in paths}
    if context is not None:
        validator.findings.candidate = context.findings.candidate
        validator.accounts = context.accounts
    else:
        validator.check_project_topology()
    evaluate = lambda name, handler: validator.findings.evaluate(name, validator.scope, handler)
    def projection_check():
        check_projection(stage, root, paths, sources, design_index)
        for path in paths:
            validator.check(True, f'model/display projection matches: {path.name}')
    evaluate('design.projection', projection_check)
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
