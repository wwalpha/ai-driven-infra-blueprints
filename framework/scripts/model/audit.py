#!/usr/bin/env python3
"""Generate one standalone audit test from authoritative Model sources, offline."""

import argparse
import ast
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, replace
from functools import partial as _bind_framework_callback
from pathlib import Path

import aws_mapping as _imports_aws_mapping
import generation_inputs as _imports_generation_inputs
import task_contract_core as _imports_task_contract
import utils.aws_mappings as _imports_utils_aws_mappings
import utils.file_operations as _imports_utils_file_operations
import utils.iac_values as _imports_iac_values
import utils.input_cache as _imports_input_cache
from aws_mapping_catalog import under
from aws_mapping_compare import comparison
from comparison.rules.cloud_trail import cloudtrail_rows
from comparison.rules.code_pipeline import prepare_rows as pipeline_rows
from design.array_display import indexed_rows
from design.catalog import DesignSchemaCatalog
from design.layout import confirmed_display_name
from task_contract_core import SELECTOR as SELECTOR
from task_contract_core import status as status
from task_contract_core import task_revision as task_revision
from utils.aws_catalogs import catalog_outputs
from utils.aws_sdk import aws_runtime
from utils.comparison_rows import Unresolved
from utils.input_cache import input_scope, input_text
from utils.property_path import definition_path
from utils.script_loader import module

import model.identity as _imports_model_identity
import model.sources as _imports_model_sources
from model.audit_runtime import observed_identifier
from model.core import ReferenceDiagnosticError, entries, literal
from model.literal_values import value_shape
from model.projection import (
    document_references,
    reference_context_for,
    reference_resolver,
    resource_display_rows,
)
from model.reference_nodes import nodes, project
from model.reference_values import confirmed
from model.render import display_name
from model.sources import load_model, model_paths, publication_lock

ROOT = Path(__file__).resolve().parents[3]


def pipeline_indexed_rows(rows):
    """Accept only complete, consistently delimited Model action sequences."""
    kind = "CodePipeline.Pipeline"
    stage_rows = [
        (rid, row) for rid, row in rows if row["property"].startswith(kind + ".Stages")
    ]
    if not stage_rows:
        return {}
    if len(dict(stage_rows)) != len(stage_rows) or any(
        not re.fullmatch(r"\d+-\d+", rid) or value_shape(row) != "leaf"
        for rid, row in stage_rows
    ):
        return {}
    try:
        prepared = pipeline_rows(
            rows, index_rows=_bind_framework_callback(indexed_rows, root=ROOT)
        )
    except (ValueError, TypeError, KeyError):
        return {}
    original = dict(rows)
    paths = {}
    stages, actions, order = {}, {}, {}
    for rid, row in prepared:
        if rid not in dict(stage_rows):
            continue
        prop = row["property"]
        if rid in paths or definition_path(prop) != original[rid]["property"]:
            return {}
        match = re.fullmatch(
            r"CodePipeline\.Pipeline\.Stages\[([1-9]\d*)\]\.(?:Actions\[([1-9]\d*)\]\.)?(.+)",
            prop,
        )
        if not match:
            return {}
        stage, action, field = match.groups()
        order.setdefault(stage, []).append(bool(action))
        if action:
            actions.setdefault((stage, action), []).append(field)
        else:
            stages.setdefault(stage, []).append(field)
        paths[rid] = prop
    if list(paths) != [rid for rid, _ in stage_rows] or not actions:
        return {}
    if any(fields.count("Name") != 1 for fields in stages.values()) or set(stages) != {
        stage for stage, _ in actions
    }:
        return {}
    orientations = set()
    for stage, members in order.items():
        positions = [i for i, is_action in enumerate(members) if is_action]
        stage_name = next(
            i
            for i, (rid, path) in enumerate(
                (
                    item
                    for item in paths.items()
                    if item[1].startswith(kind + f".Stages[{stage}].")
                )
            )
            if path == kind + f".Stages[{stage}].Name"
        )
        if stage_name < positions[0]:
            orientations.add("first")
        elif stage_name > positions[-1]:
            orientations.add("last")
        else:
            return {}
    if len(orientations) != 1:
        return {}
    signatures = list(actions.values())
    if any(
        fields.count("Name") != 1 or fields.count("ActionTypeId.Category") != 1
        for fields in signatures
    ):
        return {}
    if not (
        all(fields[0] == "Name" for fields in signatures)
        or all(fields[0] == "ActionTypeId.Category" for fields in signatures)
    ):
        return {}
    for stage in stages:
        stage_actions = [
            fields for (owner, _), fields in actions.items() if owner == stage
        ]
        # Either boundary row moving across must collide with an existing field.
        for left, right in zip(stage_actions, stage_actions[1:], strict=False):
            if (
                "[]" in definition_path(left[-1])
                or "[]" in definition_path(right[0])
                or left[-1] not in right
                or right[0] not in left
            ):
                return {}
    return paths


def definitions(path, names):
    """Copy existing implementations verbatim; fail if an upstream name disappears."""
    source = input_text(path, encoding="utf-8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    found = {
        node.name: "".join(
            lines[
                min([node.lineno] + [d.lineno for d in node.decorator_list])
                - 1 : node.end_lineno
            ]
        ).rstrip()
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    missing = set(names) - found.keys()
    if missing:
        raise ValueError(
            f"missing runtime definitions in {path.name}: {sorted(missing)}"
        )
    nodes = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    selected = list(names)
    for name in selected:
        dependencies = sorted(
            {
                node.id
                for node in ast.walk(nodes[name])
                if isinstance(node, ast.Name)
                and node.id.startswith(("_recursive_", "_callback_"))
                and node.id in found
            }
        )
        selected.extend(
            dependency for dependency in dependencies if dependency not in selected
        )
    return "\n\n".join(found[name] for name in selected) + "\n"


def embed_adapter(source, service, engine_source):
    """Resolve adapter imports before embedding and reject unknown dependencies."""
    engine_tree = ast.parse(engine_source)
    available = set()
    for node in engine_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            available.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            ):
                if isinstance(target, ast.Name):
                    available.add(target.id)
    lines = source.splitlines(keepends=True)
    replacements = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        modules = (
            [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else [item.name for item in node.names]
        )
        for imported_module in modules:
            if (
                imported_module == "model.adapters.aws"
                and isinstance(node, ast.ImportFrom)
                and not node.level
            ):
                missing = [
                    item.name for item in node.names if item.name not in available
                ]
                if missing:
                    raise ValueError(
                        f"{service}: {imported_module}: unresolved dependency {', '.join(missing)}"
                    )
                replacement = ast.unparse(
                    ast.ImportFrom(module="audit_comparison", names=node.names, level=0)
                )
            elif (
                imported_module == "model.importing.sdk_inventory"
                and isinstance(node, ast.ImportFrom)
                and not node.level
            ):
                missing = [
                    item.name
                    for item in node.names
                    if item.name not in {"route53_pages", "route53_projection"}
                ]
                if missing:
                    raise ValueError(
                        f"{service}: {imported_module}: unresolved dependency {', '.join(missing)}"
                    )
                replacement = ast.unparse(
                    ast.ImportFrom(module="audit_comparison", names=node.names, level=0)
                )
            elif (
                imported_module == "model.adapters.aws"
                and isinstance(node, ast.Import)
                and len(node.names) == 1
                and node.names[0].asname
            ):
                replacement = node.names[0].asname + " = _audit_comparison"
            elif imported_module.split(".")[
                0
            ] in sys.stdlib_module_names and not getattr(node, "level", 0):
                continue
            else:
                raise ValueError(
                    f"{service}: {imported_module}: unresolved dependency {ast.unparse(node)}"
                )
            if len(node.names) != 1 and isinstance(node, ast.Import):
                raise ValueError(
                    f"{service}: {imported_module}: unresolved dependency {ast.unparse(node)}"
                )
            if (
                lines[node.lineno - 1][: node.col_offset].strip()
                or lines[node.end_lineno - 1][node.end_col_offset :].strip()
            ):
                raise ValueError(
                    f"{service}: {imported_module}: unresolved dependency {ast.unparse(node)}"
                )
            replacements.append(
                (
                    node.lineno - 1,
                    node.end_lineno,
                    " " * node.col_offset + replacement + "\n",
                )
            )
    for start, end, replacement in sorted(replacements, reverse=True):
        lines[start:end] = [replacement]
    return "".join(lines)


def _callback_dependencies_model_identity(root, /, path):
    return path.relative_to(root / "model").with_suffix("").as_posix()


def _callback_dependencies_read(cache, model_identity, reads, /, path):
    key = model_identity(path)
    if key not in cache:
        cache[key] = None if reads.kind(path) == "missing" else load_model(path, reads)
    return cache[key]


def _recursive_dependencies_logical_names(value):
    if isinstance(value, list):
        return (
            set().union(*(_recursive_dependencies_logical_names(v) for v in value))
            if value
            else set()
        )
    if not isinstance(value, dict):
        return set()
    names = set()
    if "Ref" in value:
        names.add(value["Ref"])
    if "Fn::GetAtt" in value:
        item = value["Fn::GetAtt"]
        names.add(item[0] if isinstance(item, list) else item.split(".")[0])
    if "Fn::Sub" in value:
        sub = value["Fn::Sub"]
        text, local = sub if isinstance(sub, list) else (sub, {})
        names.update(
            key.split(".")[0]
            for key in re.findall(r"\$\{([^}]+)\}", text)
            if key not in local and not key.startswith("!")
        )
    for child in value.values():
        names.update(_recursive_dependencies_logical_names(child))
    return {name for name in names if not name.startswith("AWS::")}


def dependencies(root, target, selected, *, model_references=True):
    """Embed only selected resources and explicitly referenced producer resources."""
    cfn_resource_identity = _imports_iac_values.cfn_resource_identity

    FileReads = _imports_model_sources.FileReads
    reads = FileReads()
    Resolver = _imports_model_identity.Resolver
    identity_resolver = Resolver(root, reads)
    cache, included, pending = {}, {}, [(selected, None)]

    model_identity = _bind_framework_callback(
        _callback_dependencies_model_identity, root
    )

    read = _bind_framework_callback(
        _callback_dependencies_read, cache, model_identity, reads
    )

    logical_names = _recursive_dependencies_logical_names

    while pending:
        path, numbers = pending.pop()
        data = read(path)
        specs = dict(entries(data.values, "desired.resource."))
        wanted = set(specs) if numbers is None else set(numbers)
        new = wanted - included.get(model_identity(path), set())
        if not new:
            continue
        included.setdefault(model_identity(path), set()).update(new)
        for number in sorted(new):
            spec = specs[number]
            stack = (
                cfn_resource_identity(spec["cfn-logicalId"])[0]
                if "cfn-logicalId" in spec
                else None
            )
            values = [
                value
                for key, value in data.values.items()
                if key.startswith("desired.row." + number + "-")
                or key == "desired.resource." + number + ".parentReference"
            ]
            for value in values:
                for node in (
                    nodes(literal(value), errors=[]) if model_references else ()
                ):
                    try:
                        source, rid, _ = identity_resolver.resolve_logical(
                            node.logical_id, data.scope
                        )
                    except ReferenceDiagnosticError:
                        # The row snapshot retains the classified resolution error.
                        continue
                    pending.append((source.scope.path, {rid}))
                try:
                    names = logical_names(json.loads(value.strip("`")))
                except (ValueError, TypeError):
                    names = set()
                if names:
                    for producer in model_paths(
                        root, data.scope.environment, data.scope.target
                    ):
                        matches = set()
                        for rid, item in entries(
                            read(producer).values, "desired.resource."
                        ):
                            identity = (
                                cfn_resource_identity(item["cfn-logicalId"])
                                if "cfn-logicalId" in item
                                else (None, None)
                            )
                            if identity[0] == stack and identity[1] in names:
                                matches.add(rid)
                        if matches:
                            pending.append((producer, matches))
    result = {}
    for name, numbers in included.items():
        data = cache[name]
        prefixes = tuple(
            prefix + number + suffix
            for number in sorted(numbers)
            for prefix, suffix in [
                ("desired.resource.", "."),
                ("desired.row.", "-"),
                ("observed.row.", "-"),
            ]
        )
        values = {
            key: value for key, value in data.values.items() if key.startswith(prefixes)
        }
        result[name] = data._replace(values=values)
    return result


def _callback_reference_rows_value(resolutions, /, node):
    return resolutions[node].value


def reference_rows(root, models):
    """Freeze typed references by service address and stable Model row ID."""
    result = {}
    for name, data in sorted(models.items()):
        resolver = reference_resolver(data.authoritative, data.scope, root)
        resources = dict(entries(data.values, "desired.resource."))
        rows = {}
        for rid, row in entries(data.values, "desired.row."):
            raw = literal(row.get("document", row["value"]))
            errors = []
            references = list(nodes(raw, errors=errors))
            if not references and not errors:
                continue
            document = json.loads(raw)
            resolutions, diagnostics = document_references(
                document,
                resolver=resolver,
                scope=data.scope,
                property_name=row["property"],
                logical_id=resources[rid.rpartition("-")[0]]["logicalId"],
                model_key="desired.row."
                + rid
                + (".document" if "document" in row else ".value"),
                context=reference_context_for(
                    data.values, rid, row, document, "", root
                ),
            )
            statuses = sorted({value.status for value in resolutions.values()})
            resolved = not diagnostics and statuses == ["resolved"]
            rows[rid] = {
                "status": "resolved"
                if resolved
                else statuses[0]
                if len(statuses) == 1
                and not any(
                    d.get("category") in {"MODEL_NEEDS_FIX", "FRAMEWORK_UNSUPPORTED"}
                    for d in diagnostics
                )
                else "unresolved",
                "value": project(
                    document,
                    _bind_framework_callback(
                        _callback_reference_rows_value, resolutions
                    ),
                )
                if resolved
                else None,
                "diagnostics": diagnostics,
                "reason": "; ".join(
                    dict.fromkeys(
                        (d.get("code", "reference.unresolved") + ": " + d["message"])
                        for d in diagnostics
                    )
                )
                or ("" if resolved else ", ".join(statuses) or "invalid reference"),
            }
        if rows:
            result[name] = rows
    return result


def disambiguate_names(names, kinds, identities, primary):
    counts = Counter((kinds[logical], name) for logical, name in names.items())
    for kind, name in counts:
        if counts[kind, name] < 2:
            continue
        group = [key for key in names if kinds[key] == kind and names[key] == name]
        fields = primary.get(kind, ())
        other = sorted(
            set.intersection(*(set(identities[key]) for key in group)) - set(fields)
        )
        choices = [(field,) for field in (*fields, *other)]
        if len(fields) > 1:
            choices.append(tuple(fields))
        candidates = {key: [] for key in group}
        best = []
        for choice in choices:
            values = [
                tuple(identities[key].get(field) for field in choice) for key in group
            ]
            confirmed = Counter(value for value in values if all(value))
            selected = [
                (key, value)
                for key, value in zip(group, values, strict=True)
                if all(value) and confirmed[value] == 1
            ]
            for key, value in selected:
                identity = ", ".join(value)
                if identity != name:
                    candidates[key].append(f"{name} ({identity})")
            if len(selected) > len(best):
                best = selected
        for key, value in best:
            identity = ", ".join(value)
            display = f"{name} ({identity})"
            if identity != name:
                candidates[key].remove(display)
                candidates[key].insert(0, display)
        pending = set(group)
        while pending:
            for key in pending:
                names[key] = candidates[key].pop(0) if candidates[key] else name
            display_counts = Counter(
                (kinds[key], display) for key, display in names.items()
            )
            pending = {
                key
                for key in group
                if names[key] != name and display_counts[kind, names[key]] > 1
            }


@input_scope
def generate(root, environment, selector, service):
    m = module("model/adapters/aws.py", "model.adapters.aws")
    project_source = (root / "project.json").read_bytes().decode("utf-8")
    (target,) = m.targets(root, environment, selector)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", selector):
        raise ValueError("unsafe target selector")
    _, path = m.inventory(root, [target], [service])[0]
    if service == "cloudformation-stacks":
        raise ValueError(
            "cloudformation-stacks has no resource-property Mapping; unsupported"
        )
    models = dependencies(root, target, path)
    # Typed producers are generation inputs; only legacy references need runtime Models.
    runtime_models = dependencies(root, target, path, model_references=False)
    resolved_rows = reference_rows(root, runtime_models)
    catalog = DesignSchemaCatalog(ROOT)
    mappings, schemas, outputs, exclusions = {}, {}, {}, {}
    for name in sorted({data.scope.service for data in runtime_models.values()}):
        selected_rows = [
            row
            for data in runtime_models.values()
            if data.scope.service == name
            for _, row in entries(data.values, "desired.row.")
        ]
        if name == "cloudformation-stacks":
            continue
        mapping, props = comparison(ROOT, name)
        props = dict(props)
        if name == "iam":
            # Audit-only projection: existing Compare keeps its CloudControl classification.
            response_shape = _imports_aws_mapping.response_shape
            get_session = aws_runtime().sdk_session
            sdk = get_session().get_service_model("iam")
            for kind, operation, result in [
                ("IAM.Role", "GetRole", "Role"),
                ("IAM.User", "GetUser", "User"),
            ]:
                response_shape(
                    sdk.operation_model(operation).output_shape,
                    result + ".PermissionsBoundary.PermissionsBoundaryArn",
                )
                key = kind + ".PermissionsBoundary"
                prop = props[key]
                props[key] = replace(
                    prop,
                    field=replace(
                        prop.field,
                        getter="base",
                        path="PermissionsBoundary.PermissionsBoundaryArn",
                        norm="arn",
                        classification="supported",
                        reason="",
                    ),
                )
        for row in selected_rows:
            key = row["property"]
            prop = props.get(key)
            kind = ".".join(key.split(".")[:2])
            property_path = definition_path(key[len(kind) + 1 :])
            if (
                prop
                and prop.source == "model"
                and prop.constraint
                and (
                    prop.field.classification == "sdk_unavailable"
                    or prop.field.classification == "local_metadata"
                    and "provider read cannot confirm" in prop.constraint.lower()
                )
                and not prop.field.getter
                and under(
                    property_path, catalog.schema(kind).get("writeOnlyProperties", [])
                )
            ):
                exclusions[key] = (
                    "CloudFormation write-only property; " + prop.constraint
                )
        Property = _imports_aws_mapping.Property
        for row in selected_rows:
            key = row["property"]
            if key not in props:
                props[key] = Property(
                    m.Field(
                        classification="unimplemented",
                        reason="no AWS Compare Mapping for selected attribute",
                    ),
                    False,
                    False,
                    key,
                    "model",
                )
        mappings[name] = {
            "getters": {k: dict(v) for k, v in mapping.getters.items()},
            "identities": {k: asdict(v) for k, v in mapping.identities.items()},
            "properties": {
                k: asdict(
                    replace(v, field=replace(v.field, default=v.field.copy_default()))
                )
                for k, v in props.items()
            },
        }
        for row in selected_rows:
            prop = row["property"]
            kind = ".".join(prop.split(".")[:2])
            try:
                schema = catalog.property_schema(
                    kind, definition_path(prop[len(kind) + 1 :])
                )
                schemas[prop] = {
                    k: schema[k]
                    for k in (
                        ("type", "minLength", "minimum", "maximum")
                        if prop == "KMS.Key.PendingWindowInDays"
                        else ("type", "minLength")
                    )
                    if k in schema
                }
                if prop in exclusions and isinstance(schema.get("items"), dict):
                    item_type = schema["items"].get("type")
                    if item_type:
                        schemas[prop]["items"] = {"type": item_type}
            except KeyError:
                pass  # Existing Resource.parse treats design-only properties as strings.
            outputs[kind] = sorted(catalog_outputs(ROOT, kind))
    files = {
        str(file.relative_to(root)): None
        if content is None
        else content.decode("utf-8")
        for data in models.values()
        for file, content in data.dependencies.items()
    }
    files["project.json"] = project_source
    model_hash = hashlib.sha256(
        m.stable({"sources": files, "target": target}).encode("utf-8")
    ).hexdigest()
    definition_root = _imports_utils_aws_mappings.definition_root
    scripts = definition_root(ROOT) / "framework/scripts"
    engine = (
        "from __future__ import annotations\n"
        "import argparse, hashlib, json, math, os, posixpath, re, subprocess, sys\n"
        "from collections import Counter, defaultdict\nfrom collections.abc import Mapping\n"
        "from copy import deepcopy\nfrom threading import RLock\nfrom concurrent.futures import Future\n"
        "from functools import partial as _bind_framework_callback\n"
        "from itertools import combinations\n"
        "from dataclasses import dataclass\nfrom pathlib import Path, PurePosixPath\nfrom types import SimpleNamespace\nfrom urllib.parse import unquote\n"
        'ROOT = Path("/model-test-snapshot")\n'
        'LINK = re.compile(r"^\\[([^\\]]+)\\]\\(([^)]*?)#([^)]+)\\)$")\n'
        "def memo_table(): return None\n"
    )
    engine += definitions(
        scripts / "validation/diagnostics.py", ["InputValidationError"]
    )
    engine += definitions(
        scripts / "utils/aws/identity.py",
        [
            "IdentityError",
            "validate_profile",
            "select_profile",
            "validate_account_id",
            "execution_account",
            "verify_account",
        ],
    )
    engine += definitions(scripts / "utils/lazy_definitions.py", ["load_once"])
    engine += definitions(
        scripts / "utils/json_format.py",
        [
            "AwsDocumentError",
            "validate_aws_document",
            "unique_object",
            "invalid_constant",
            "_number",
            "strict_json",
            "policy_json",
        ],
    )
    engine += definitions(
        scripts / "utils/cloudformation/format.py", ["boolean_literal"]
    )
    engine += definitions(scripts / "utils/iac_values.py", ["cfn_resource_identity"])
    engine += definitions(
        scripts / "model/core.py",
        [
            "ReferenceDiagnosticError",
            "ModelNeedsFixError",
            "ReferenceResolutionError",
            "SnapshotValues",
            "structural_entries",
            "entries",
            "literal",
        ],
    )
    engine += definitions(scripts / "design/layout.py", ["confirmed_display_name"])
    engine += definitions(scripts / "model/reference_values.py", ["confirmed"])
    engine += definitions(
        scripts / "model/reference_nodes.py",
        ["ReferenceNode", "is_reference", "parse", "nodes"],
    )
    engine += "parse_model_reference = parse\n"
    engine += definitions(
        scripts / "utils/cloudformation/schema.py", ["native_type_errors"]
    )
    engine += definitions(
        scripts / "utils/comparison_rows.py",
        ["Unresolved", "segment", "indexed_array", "select", "project", "put_row"],
    )
    engine += definitions(
        scripts / "model/literal_values.py",
        [
            "value_shape",
            "array_paths",
            "LiteralValues",
            "normalize",
            "typed_value",
            "projection_conflicts",
        ],
    ).replace("normalize(", "normalize_literals(")
    engine += 'MISSING = {"absent": True}\n'
    # Preserve the exact collection semantics maintained by the existing comparator.
    original = input_text(scripts / "model/adapters/aws.py", encoding="utf-8")
    tree = ast.parse(original)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in {"MAP_ARRAYS", "SET_ARRAYS"}
            for t in node.targets
        ):
            engine += ast.get_source_segment(original, node) + "\n"
    engine += definitions(
        scripts / "model/adapters/aws.py",
        [
            "copy_default",
            "Field",
            "AcquisitionError",
            "sdk_error",
            "one",
            "canonical",
            "stable",
            "policy",
            "redacted",
            "Context",
            "Model",
            "Resource",
            "normalize",
            "source",
            "compare_resource",
        ],
    )
    engine += definitions(
        scripts / "model/importing/sdk_inventory.py",
        ["identifier", "route53_pages", "route53_projection"],
    )
    projection = definitions(scripts / "aws_mapping_catalog.py", ["project"])
    mapped = definitions(scripts / "aws_mapping_compare.py", ["value"])
    adapters = {
        name: input_text(
            scripts / "aws-compare-services" / (name + ".py"), encoding="utf-8"
        )
        for name in sorted(set(mappings) | {"iam", "kms"})
    }
    adapters = {
        name: embed_adapter(source, name, engine) for name, source in adapters.items()
    }
    for label, source in [
        ("engine", engine),
        ("projection", projection),
        ("mapped", mapped),
    ]:
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = (
                    [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else [item.name for item in node.names]
                )
                for imported in modules:
                    if (
                        getattr(node, "level", 0)
                        or imported.split(".")[0] not in sys.stdlib_module_names
                    ):
                        raise ValueError(
                            f"{service}: {label}: unresolved dependency {imported}"
                        )
    selected_model = load_model(path)
    names = {}
    indexed_rows_by_resource = {}
    pipeline_indexed_rows_by_resource = {}
    identities = {}
    kinds = {}
    primary = {}
    selected_values = selected_model.values
    logical_ids = {
        resource["logicalId"]
        for _, resource in entries(selected_values, "desired.resource.")
    }
    for number, resource in entries(selected_values, "desired.resource."):
        if resource["resourceType"] == "CodePipeline.Pipeline":
            pipeline_indexed_rows_by_resource[number] = pipeline_indexed_rows(
                [
                    (rid, row)
                    for rid, row in entries(selected_values, "desired.row.")
                    if rid.startswith(number + "-")
                ]
            )
        if resource["resourceType"] == "CloudTrail.Trail":
            leaves = [
                (rid, row)
                for rid, row in entries(selected_values, "desired.row.")
                if rid.startswith(number + "-") and value_shape(row) == "leaf"
            ]
            try:
                prepared = cloudtrail_rows(
                    leaves, index_rows=_bind_framework_callback(indexed_rows, root=ROOT)
                )
            except Unresolved:
                prepared = leaves
            if any(
                re.sub(r"\[\d+\]", "[]", row["property"]) != original["property"]
                for (_, row), (_, original) in zip(prepared, leaves, strict=True)
            ):
                prepared = leaves
            indexed_rows_by_resource[number] = {
                rid: row["property"] for rid, row in prepared
            }
        rows = resource_display_rows(
            selected_values, number, resource, ROOT, scope=selected_model.scope
        )
        name, _ = display_name(
            selected_values, number, resource, rows, ROOT, projection=True
        )
        kind = resource["resourceType"]
        primary[kind] = tuple(
            kind + "." + pointer.removeprefix("/properties/").replace("/", ".")
            for pointer in catalog.schema(kind).get("primaryIdentifier", ())
            if pointer.startswith("/properties/")
        )
        candidates = {}
        for rid, row in entries(selected_values, "desired.row."):
            prop = row["property"]
            if not rid.startswith(number + "-") or prop not in outputs.get(kind, []):
                continue
            value = observed_identifier(
                selected_values.get("observed.row." + rid + ".value"),
                m.literal,
                confirmed_display_name,
                confirmed,
            )
            if prop in candidates:
                candidates[prop] = None
            else:
                candidates[prop] = value if value not in logical_ids else None
        valid = [value for value in candidates.values() if value]
        identity = valid[0] if len(valid) == 1 else None
        if (
            not name
            or name in logical_ids
            or name == resource["resourceType"]
            or not confirmed_display_name(name)
        ):
            name = identity or "（名前未設定）"
        logical = resource["logicalId"]
        names[logical] = name
        kinds[logical] = resource["resourceType"]
        identities[logical] = candidates
    disambiguate_names(names, kinds, identities, primary)
    snapshot = {
        "names": names,
        "target": target,
        "service": service,
        "modelHash": model_hash,
        "models": {
            name: dict(data.values) for name, data in sorted(runtime_models.items())
        },
        "referenceRows": resolved_rows,
        "cloudtrailIndexedRows": indexed_rows_by_resource,
        "pipelineIndexedRows": pipeline_indexed_rows_by_resource,
        "schemas": schemas,
        "exclusions": exclusions,
        "outputs": outputs,
        "mappings": mappings,
        "adapters": adapters,
        "engine": engine,
        "projection": projection,
        "mapped": mapped,
    }
    runtime = input_text(scripts / "model/audit_runtime.py", encoding="utf-8")
    result = (
        "#!/usr/bin/env python3\n# Generated offline by /model-test; regenerate after Model changes.\n"
        "import json\nSNAPSHOT = json.loads("
        + repr(m.stable(snapshot))
        + ")\n"
        + runtime
    )
    for node in ast.walk(ast.parse(result)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [item.name for item in node.names]
            )
            for imported in modules:
                if (
                    getattr(node, "level", 0)
                    or imported.split(".")[0] not in sys.stdlib_module_names
                ):
                    raise ValueError(
                        f"{service}: generated runtime: unresolved dependency {imported}"
                    )
    compile(result, f"{service}.py", "exec")
    unsupported = []
    for _, row in entries(
        models["/".join((environment, target["directory"], service))].values,
        "desired.row.",
    ):
        key = row["property"]
        field = mappings[service]["properties"][key]["field"]
        if field["classification"] != "supported":
            unsupported.append((key, field["reason"]))
    for number, resource in entries(selected_values, "desired.resource."):
        for prop in outputs.get(resource["resourceType"], []):
            rows = [
                (rid, row)
                for rid, row in entries(selected_values, "desired.row.")
                if rid.startswith(number + "-") and row["property"] == prop
            ]
            if not rows:
                continue
            observed = (
                selected_values.get("observed.row." + rows[0][0] + ".value")
                if len(rows) == 1
                else None
            )
            if (
                observed_identifier(
                    observed, m.literal, confirmed_display_name, confirmed
                )
                is None
            ):
                unsupported.append(
                    (prop, "observed identifier missing, unresolved or ambiguous")
                )
    return result, files, sorted(set(unsupported))


def main(argv=None):
    GenerationInputs = _imports_generation_inputs.GenerationInputs
    matches = _imports_task_contract.matches
    paths_in = _imports_task_contract.paths_in
    selected_task = _imports_task_contract.selected_task
    validate_contract = _imports_task_contract.validate_contract
    atomic_files = _imports_utils_file_operations.atomic_files
    recording_inputs = _imports_input_cache.recording_inputs
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--environment", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--task-file", required=True)
    args = parser.parse_args(argv)
    root = args.repository_root.resolve()
    inputs = None
    try:
        with (
            selected_task(root, args.task_file),
            _imports_task_contract.task_reads(root, live=True),
        ):
            expected_task = task_revision(root, args.task_file)
            name, text = expected_task
            if text is None or status(text) != "running":
                raise ValueError("audit generation requires a running Task")
            validate_contract(root, name, text)
            output = (
                root / "tests" / args.environment / args.target / (args.service + ".py")
            )
            safe = _imports_model_sources.safe
            safe(root, output)
            relative = output.relative_to(root).as_posix()
            if relative not in paths_in(text, "## Modified files") or not any(
                matches(relative, p) for p in paths_in(text, "## Allowed paths")
            ):
                raise ValueError("audit output is outside the registered Task paths")
            inputs = GenerationInputs(root, task_file=name)
            with recording_inputs(inputs):
                source, _, unsupported = generate(
                    root, args.environment, args.target, args.service
                )
                previous = inputs.read(output)
            with publication_lock(root):
                inputs.verify()
                if previous != source.encode("utf-8"):
                    atomic_files({output: source})
            print(f"Generated: {relative} (syntax OK; AWS not contacted)")
            for key, reason in unsupported:
                print(f"  ERROR check: {key}: {reason}")
            return 0
    except (OSError, ValueError, KeyError) as error:
        print(f"Model test generation: FAIL: {error}")
        return 2
    finally:
        if inputs is not None:
            inputs.close()
