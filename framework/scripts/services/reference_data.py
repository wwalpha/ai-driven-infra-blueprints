"""Build Registry contracts from the service-owned reference declarations."""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field, fields
from functools import partial
from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING, TypeVar

from utils.type_contracts import JsonValue

from .contracts import (
    AccountPolicyCheck,
    ArnExtension,
    ArnForm,
    ArnShape,
    AwsAdapter,
    ConfigurationContext,
    ContextReferenceHook,
    ContextSelector,
    DesignDefinition,
    DisplayExtension,
    ProducerReference,
    ReceiverReference,
    ReferenceForms,
    ReferenceMode,
    ReferencePolicyHook,
    ReferenceTarget,
    ResourceDefinition,
    RowContextHook,
    ServiceDefinition,
)

if TYPE_CHECKING:
    from comparison.methods import RuleSet
    from utils.iac_values import Expression

    from .import_contracts import ImportProfile

Attr = TypeVar("Attr")

TypeForms = Mapping[str, set[str]]
FormatNames = Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class ReferenceTables:
    """Shared declarations for formal attribute, comparison and IMPORT views."""

    ref_attributes: Mapping[str, str] = field(default_factory=dict)
    getatt_attributes: Mapping[str, set[str]] = field(default_factory=dict)
    arn_attributes: Mapping[str, str] = field(default_factory=dict)
    model_attributes: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    return_attribute_properties: Mapping[tuple[str, str], str] = field(
        default_factory=dict
    )
    return_types: Mapping[tuple[str, str], str] = field(default_factory=dict)
    arn_shapes: Mapping[str, ArnShape] = field(default_factory=dict)
    reference_properties: Mapping[str, ReferenceTarget] = field(default_factory=dict)
    reference_forms: Mapping[str, set[str]] = field(default_factory=dict)
    import_properties: Mapping[str, ReferenceTarget] = field(default_factory=dict)
    special_properties: Mapping[str, ReferenceTarget] = field(default_factory=dict)
    unproven_document: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    linked_references: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    linked_subnets: set[str] = field(default_factory=set)
    type_forms: TypeForms = field(default_factory=dict)
    format_names: FormatNames = field(default_factory=dict)
    format_limits: Mapping[str, set[str]] = field(default_factory=dict)
    arn_defaults: Mapping[tuple[str, str], str] = field(default_factory=dict)
    arn_forms: Mapping[tuple[str, str], ArnForm] = field(default_factory=dict)
    attribute_suffixes: Mapping[tuple[str, str], tuple[str, str]] = field(
        default_factory=dict
    )
    value_identities: Mapping[tuple[str, str], str] = field(default_factory=dict)
    local_comparison: Mapping[str, ReferenceForms] = field(default_factory=dict)
    context_properties: Mapping[str, ContextSelector] = field(default_factory=dict)
    row_contexts: Mapping[str, RowContextHook] = field(default_factory=dict)
    contextual: Mapping[str, ContextReferenceHook] = field(default_factory=dict)
    reference_policy: Mapping[str, ReferencePolicyHook] = field(default_factory=dict)
    context_paths: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    context_suffixes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    split_reference_operands: Mapping[str, tuple[str, str, str]] = field(
        default_factory=dict
    )
    configurations: Mapping[str, ConfigurationContext] = field(default_factory=dict)
    context_targets: Mapping[str, frozenset[str]] = field(default_factory=dict)
    equivalent_forms: Mapping[tuple[str, str, str], set[str]] = field(
        default_factory=dict
    )
    default_on_mismatch: frozenset[str] = frozenset()
    arn_components: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    arn_without_forms: frozenset[str] = frozenset()
    verified_symbolic_arn_attributes: Mapping[str, frozenset[str]] = field(
        default_factory=dict
    )


def reference_forms(
    target: ReferenceTarget,
    forms: set[str] | None,
    *,
    type_forms: TypeForms,
    format_names: FormatNames,
    limit: set[str] | None = None,
) -> ReferenceForms:
    kinds, attribute = target
    kinds = (kinds,) if isinstance(kinds, str) else kinds
    declared = (
        forms
        if forms is not None
        else (
            set(attribute)
            if isinstance(attribute, tuple)
            else {attribute}
            if attribute
            else None
        )
    )
    result = {}
    for kind in kinds:
        allowed = (
            type_forms.get(kind, set())
            if declared is None
            else declared & type_forms.get(kind, declared)
        )
        if limit is not None:
            names = format_names.get(kind, {})
            allowed = {form for form in allowed if names.get(form, form) in limit}
        if allowed:
            result[kind] = tuple(sorted(allowed))
    return result


def context_target(
    declaration: ContextSelector, context: Mapping[str, JsonValue] | None
) -> ReferenceTarget | None:
    selector, choices = declaration
    context = context if context is not None else {}
    value = context.get(selector, context.get(selector.rsplit(".", 1)[-1]))
    return choices.get(value) if isinstance(value, str) else None


def _context_forms(
    by_path: Mapping[str, ContextSelector],
    evaluate: Callable[[str, ReferenceTarget], ReferenceForms],
    path: str,
    context: Mapping[str, JsonValue] | None,
    mode: ReferenceMode,
    /,
) -> ReferenceForms | None:
    declaration = next(
        (
            by_path[candidate]
            for candidate in (path, path + "[]", path.removesuffix("[]"))
            if candidate in by_path
        ),
        None,
    )
    if declaration is None:
        return None
    target = context_target(declaration, context)
    return evaluate(path, target) if target is not None else {}


def arn_pattern(shape: ArnShape) -> str:
    _, template, identity_patterns = shape
    patterns = {
        "partition": r"aws(?:-[a-z]+)*",
        "region": r"[a-z]{2}(?:-[a-z]+)+-\d+",
        "account": r"\d{12}",
        **identity_patterns,
    }
    result = re.escape(template)
    for name, pattern in patterns.items():
        result = result.replace(
            re.escape("{" + name + "}"), "(?P<" + name + ">" + pattern + ")"
        )
    return result


def arn_reference_forms(shape: ArnShape, alias: str | None) -> dict[str, ArnForm]:
    pattern = (shape[0], arn_pattern(shape))
    return {"Arn": pattern, alias: pattern} if alias is not None else {"Arn": pattern}


def policy_reference_path(path: str, style: str) -> str | None:
    if style == "wrapped-statement":
        return path + ".PolicyDocument"
    return path if style == "statement" else None


def supports_getatt(
    attribute: str, extensions: Collection[str], readable: Collection[str]
) -> bool:
    return (
        attribute in extensions
        or "/properties/" + attribute.replace(".", "/") in readable
    )


def policy_source_vpc_paths(root: str, style: str) -> tuple[str, ...]:
    prefix = policy_reference_path(root, style)
    if prefix is None:
        return ()
    return tuple(
        f"{prefix}.Statement{statement}.Condition.StringEquals.aws:SourceVpc{values}"
        for statement in ("", "[]")
        for values in ("", "[]")
    )


def document_requires_context(path: str, patterns: tuple[str, ...]) -> bool:
    return any(
        path.startswith(item) if item.endswith(".") else path == item
        for item in patterns
    )


def _comparison(service: str, kind: str) -> RuleSet:
    return import_module(f"services.{service}.comparison").RULES[kind]


def _attributes_for(
    kind: str, pairs: Mapping[tuple[str, str], Attr]
) -> dict[str, Attr]:
    return {attr: value for (owner, attr), value in pairs.items() if owner == kind}


def _producer(kind: str, tables: ReferenceTables) -> ProducerReference | None:
    ref = tables.ref_attributes.get(kind)
    attributes = frozenset(tables.getatt_attributes.get(kind, ()))
    arn = tables.arn_attributes.get(kind, "Arn" if kind in tables.arn_shapes else None)
    properties = _attributes_for(kind, tables.return_attribute_properties)
    types = _attributes_for(kind, tables.return_types)
    identities = _attributes_for(kind, tables.value_identities)
    suffixes = _attributes_for(kind, tables.attribute_suffixes)
    model_attributes = dict(tables.model_attributes.get(kind, {}))
    if kind in tables.arn_shapes:
        fields = tables.arn_shapes[kind][0]
        model_attributes.update(
            (name, name) for name in ((fields,) if isinstance(fields, str) else fields)
        )
    model_attributes.update(
        (form, form) for form in identities.keys() | suffixes.keys()
    )
    model_attributes.update((prop, attr) for attr, prop in properties.items())
    if ref is None and arn is None and not (attributes or model_attributes or types):
        return None
    return ProducerReference(
        ref_attribute=ref,
        getatt_attributes=attributes,
        arn_attribute=arn,
        model_attributes=model_attributes,
        return_properties=properties,
        return_types=types,
        type_forms=frozenset(tables.type_forms.get(kind, ())),
        format_names=tables.format_names.get(kind, {}),
        value_identities=identities,
        attribute_suffixes=suffixes,
    )


def _receiver(
    kind: str,
    tables: ReferenceTables,
    design: DesignDefinition,
    type_forms: TypeForms,
    format_names: FormatNames,
) -> ReceiverReference | None:
    prefix = kind + "."
    direct = {
        path: target
        for path, target in tables.reference_properties.items()
        if path.startswith(prefix)
    }
    imports = {
        path: target
        for path, target in tables.import_properties.items()
        if path.startswith(prefix)
    } | direct
    imports.update(
        {
            path: ("EC2.Subnet", "SubnetId")
            for path in tables.linked_subnets
            if path.startswith(prefix)
        }
    )
    imports.update(
        {
            path: target
            for path, target in tables.linked_references.items()
            if path.startswith(prefix)
        }
    )
    comparison = direct | {
        path: imports[path]
        for path in tables.reference_forms.keys() | tables.format_limits.keys()
        if path in imports
    }
    special = {
        path: target
        for path, target in tables.special_properties.items()
        if path.startswith(prefix)
    }
    comparison.update(special)
    formats = design.get("POLICY_FORMATS", {})
    policy = {
        path: ("EC2.VPC", "VpcId")
        for root, style in formats.items()
        for path in policy_source_vpc_paths(root, style)
    }
    comparison.update(policy)
    unproven = tuple(
        path.removeprefix(prefix) for path in tables.unproven_document.get(kind, ())
    )
    conditions = tuple(
        f"{root.removeprefix(prefix)}.Statement{statement}.Condition."
        for path, style in formats.items()
        if (root := policy_reference_path(path, style)) is not None
        for statement in ("", "[]")
    )
    local = {
        path: forms
        for path, forms in tables.local_comparison.items()
        if path.startswith(prefix)
    }
    contextual = {
        path.removeprefix(prefix): declaration
        for path, declaration in tables.context_properties.items()
        if path.startswith(prefix)
    }
    configuration = tables.configurations.get(kind)
    hook = tables.contextual.get(kind)
    policy_hook = tables.reference_policy.get(kind)
    context_paths = tables.context_paths.get(kind, ())
    context_suffixes = tables.context_suffixes.get(kind, ())
    split_operands = {
        path.removeprefix(prefix): value
        for path, value in tables.split_reference_operands.items()
        if path.startswith(prefix)
    }
    if not (
        imports
        or special
        or unproven
        or conditions
        or local
        or contextual
        or hook
        or policy_hook
        or context_paths
        or context_suffixes
        or split_operands
    ):
        return None
    evaluate = partial(_path_forms, tables, type_forms, format_names)
    return ReceiverReference(
        exact_properties={
            path: evaluate(path, target) for path, target in (special | policy).items()
        },
        local_comparison=local,
        direct_properties={
            path.removeprefix(prefix): value for path, value in direct.items()
        },
        declared_forms={
            path.removeprefix(prefix): value
            for path, value in tables.reference_forms.items()
            if path.startswith(prefix)
        },
        format_limits={
            path.removeprefix(prefix): value
            for path, value in tables.format_limits.items()
            if path.startswith(prefix)
        },
        selectors=contextual,
        default_on_mismatch=frozenset(
            path.removeprefix(prefix)
            for path in tables.default_on_mismatch
            if path.startswith(prefix)
        ),
        linked_lists={
            path.removeprefix(prefix): target
            for path, target in (
                dict.fromkeys(tables.linked_subnets, "EC2.Subnet")
                | {path: target[0] for path, target in tables.linked_references.items()}
            ).items()
            if path.startswith(prefix)
        },
        policy_paths=conditions,
        document_paths=unproven,
        import_properties={
            path: evaluate(path, target) for path, target in imports.items()
        },
        comparison_properties={
            path: evaluate(path, target) for path, target in comparison.items()
        }
        | local,
        contextual=hook
        if hook is not None
        else (partial(_context_forms, contextual, evaluate) if contextual else None),
        unproven_paths=unproven
        + conditions
        + (
            (configuration.property_prefix.removeprefix(prefix) + ".",)
            if configuration
            else ()
        )
        + tuple(
            variant
            for path in contextual
            for variant in (
                path,
                path.removesuffix("[]") if path.endswith("[]") else path + "[]",
            )
        ),
        row_contexts=tables.row_contexts.get(kind),
        reference_policy=policy_hook,
        configuration=configuration,
        context_paths=context_paths,
        context_suffixes=context_suffixes,
        split_reference_operands=split_operands,
        equivalent_forms={
            (path.removeprefix(prefix), target, form): allowed
            for (path, target, form), allowed in tables.equivalent_forms.items()
            if path.startswith(prefix)
        },
        context_producers=tables.context_targets.get(kind, frozenset())
        | frozenset(
            producer
            for _, choices in contextual.values()
            for producers, _ in choices.values()
            for producer in ((producers,) if isinstance(producers, str) else producers)
        ),
    )


def _path_forms(
    tables: ReferenceTables,
    type_forms: TypeForms,
    format_names: FormatNames,
    path: str,
    target: ReferenceTarget,
) -> ReferenceForms:
    return reference_forms(
        target,
        tables.reference_forms.get(path),
        type_forms=type_forms,
        format_names=format_names,
        limit=tables.format_limits.get(path),
    )


def _arn_components(
    package: str,
    kind: str,
    properties: Mapping[str, JsonValue | Expression],
    evaluate: Callable[[JsonValue | Expression], JsonValue | Expression],
    /,
) -> dict[str, str]:
    return import_module(f"services.{package}.arn").COMPONENTS[kind](
        properties, evaluate
    )


def _arn(kind: str, tables: ReferenceTables, package: str) -> ArnExtension | None:
    shape = tables.arn_shapes.get(kind)
    forms = _attributes_for(kind, tables.arn_forms)
    defaults = _attributes_for(kind, tables.arn_defaults)
    if shape is None:
        return None
    dependencies = tables.arn_components.get(kind, ())
    components = (
        partial(_arn_components, package, kind)
        if kind in tables.arn_components
        else None
    )
    return ArnExtension(
        shape=shape,
        components=components,
        depends_on=dependencies,
        forms=(
            arn_reference_forms(shape, tables.arn_attributes.get(kind))
            if kind not in tables.arn_without_forms
            else {}
        )
        | forms,
        defaults=defaults,
        verified_symbolic_attributes=tables.verified_symbolic_arn_attributes.get(
            kind, frozenset()
        ),
    )


def _design_for(kind: str, module: ModuleType | None) -> DesignDefinition:
    if module is None:
        return {}
    result = {}
    for name in DesignDefinition.__optional_keys__:
        entries = getattr(module, name, ())
        keys = [key for key in entries if key == kind or key.startswith(kind + ".")]
        if keys:
            result[name] = (
                {key: entries[key] for key in keys}
                if isinstance(entries, Mapping)
                else type(entries)(keys)
            )
    return result


@dataclass(frozen=True)
class ServiceDeclaration:
    name: str
    resource_types: tuple[str, ...]
    tables: ReferenceTables
    design: ModuleType | None = None
    displays: Mapping[str, Callable[[], DisplayExtension]] = field(default_factory=dict)
    without_comparison: tuple[str, ...] = ()
    package: str | None = None
    aws_adapters: Mapping[str, str] = field(default_factory=dict)
    account_policies: Mapping[str, Callable[[], AccountPolicyCheck]] = field(
        default_factory=dict
    )

    import_profiles: Mapping[str, ImportProfile] = field(default_factory=dict)

    def build(
        self, type_forms: TypeForms, format_names: FormatNames
    ) -> ServiceDefinition:
        kinds = set(self.resource_types)
        declared = (
            set(self.displays)
            | set(self.without_comparison)
            | set(self.account_policies)
            | set(self.import_profiles)
        )
        for section in fields(self.tables):
            for key in getattr(self.tables, section.name):
                path = key[0] if isinstance(key, tuple) else key
                declared.add(".".join(path.split(".")[:2]))
        if self.design is not None:
            for name in DesignDefinition.__optional_keys__:
                for key in getattr(self.design, name, ()):
                    declared.add(".".join(key.split(".")[:2]))
        if missing := declared - kinds:
            raise ValueError(
                f"{self.name} has unregistered ResourceTypes: {', '.join(sorted(missing))}"
            )
        definitions = []
        for kind in self.resource_types:
            fixed = _design_for(kind, self.design)
            definitions.append(
                ResourceDefinition(
                    resource_type=kind,
                    producer=_producer(kind, self.tables),
                    receiver=_receiver(
                        kind, self.tables, fixed, type_forms, format_names
                    ),
                    comparison=None
                    if kind in self.without_comparison
                    else partial(_comparison, self.package or self.name, kind),
                    design=fixed or None,
                    display=self.displays.get(kind),
                    arn=_arn(kind, self.tables, self.package or self.name),
                    account_policy=self.account_policies.get(kind),
                    importing=self.import_profiles.get(kind),
                )
            )
        adapters = {
            alias: AwsAdapter(f"services.{self.package or self.name}.{module}")
            for alias, module in self.aws_adapters.items()
        }
        return ServiceDefinition(self.name, tuple(definitions), adapters)
