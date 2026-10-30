#!/usr/bin/env python3
"""Generate one standalone audit test from authoritative Model sources, offline."""

import argparse
import ast
import hashlib
import json
import re
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
from aws_mapping_compare import comparison
from design.catalog import DesignSchemaCatalog
from design.layout import confirmed_display_name
from task_contract_core import SELECTOR as SELECTOR
from task_contract_core import status as status
from task_contract_core import task_revision as task_revision
from utils.aws_catalogs import catalog_outputs
from utils.aws_sdk import aws_runtime
from utils.input_cache import input_scope, input_text
from utils.property_path import definition_path
from utils.script_loader import module

import model.identity as _imports_model_identity
import model.sources as _imports_model_sources
from model.core import entries
from model.projection import resource_display_rows
from model.render import display_name
from model.sources import load_model, model_paths, publication_lock

ROOT = Path(__file__).resolve().parents[3]


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


def dependencies(root, target, selected):
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
                reference_tokens = _imports_model_identity.reference_tokens
                resolver = identity_resolver
                for uri in reference_tokens(value):
                    source, rid, _ = resolver.resolve(uri[0], data.scope)
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
    catalog = DesignSchemaCatalog(ROOT)
    mappings, schemas, outputs = {}, {}, {}
    for name in sorted({data.scope.service for data in models.values()}):
        selected_rows = [
            row
            for data in models.values()
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
                    k: schema[k] for k in ("type", "minLength") if k in schema
                }
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
        scripts / "model/identity.py",
        ["parse_reference", "anchor_index", "select_anchor"],
    ).replace("    from model.references import link_scope\n", "")
    engine += definitions(
        scripts / "validation/diagnostics.py", ["InputValidationError"]
    )
    engine += definitions(scripts / "model/format.py", ["link_scope"])
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
        ["unique_object", "invalid_constant", "_number", "strict_json", "policy_json"],
    )
    engine += definitions(scripts / "utils/iac_values.py", ["cfn_resource_identity"])
    engine += definitions(
        scripts / "model/core.py",
        [
            "ReferenceDiagnosticError",
            "ReferenceResolutionError",
            "resource_link",
            "SnapshotValues",
            "structural_entries",
            "entries",
            "literal",
        ],
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
    projection = definitions(scripts / "aws_mapping_catalog.py", ["project"])
    mapped = definitions(scripts / "aws_mapping_compare.py", ["value"])
    adapters = {
        name: input_text(
            scripts / "aws-compare-services" / (name + ".py"), encoding="utf-8"
        )
        for name in sorted(set(mappings) | {"iam", "kms"})
    }
    selected_model = load_model(path)
    names = {}
    selected_values = selected_model.values
    for number, resource in entries(selected_values, "desired.resource."):
        rows = resource_display_rows(
            selected_values, number, resource, ROOT, scope=selected_model.scope
        )
        name, _ = display_name(
            selected_values, number, resource, rows, ROOT, projection=True
        )
        if (
            not name
            or name in {resource["logicalId"], resource["resourceType"]}
            or not confirmed_display_name(name)
        ):
            candidates = [
                selected_values.get("observed.row." + rid + ".value")
                for rid, row in entries(selected_values, "desired.row.")
                if rid.startswith(number + "-")
                and row["property"] in outputs.get(resource["resourceType"], [])
            ]
            candidates = [
                m.literal(value)
                for value in candidates
                if value and confirmed_display_name(value)
            ]
            name = candidates[0] if len(candidates) == 1 else "（名前未設定）"
        names[resource["logicalId"]] = name
    snapshot = {
        "names": names,
        "target": target,
        "service": service,
        "modelHash": model_hash,
        "models": {name: dict(data.values) for name, data in sorted(models.items())},
        "schemas": schemas,
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
                not observed
                or not confirmed_display_name(observed)
                or m.literal(observed).startswith(("[", "{"))
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
