"""Offline saved-anchor and scoped Markdown reference regression."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import model.adapters.observed as _imports_model_adapters_observed
import model.audit as _imports_model_audit
import model.identity as _imports_model_identity
import model.importing.references as _imports_model_importing_references
import model.render as _imports_model_render
import model.sources as _imports_model_sources
import model.validation as _imports_model_validation
from design.array_display import indexed_rows, verified_rows
from design.document import DesignIndex
from model.core import (
    ReferenceResolutionError,
    entries,
    validate_model_keys,
    validate_runtime_keys,
)
from model.format import parse, serialize
from model.identity import (
    COUNTERS,
    Resolver,
    allocate,
    parse_reference,
    preserve_allocation,
)
from model.importing.references import Resolver as ImportResolver
from model.projection import execution_document, reference_display
from model.references import diagnose, incoming, symbolic, usages
from model.render import generate_markdown
from model.sources import Scope, load_model
from support.import_model_fixtures import resource_values, service_values
from support.model_sources import write_model
from utils.reference_contracts import contract
from utils.source_reads import FileReads

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_receiving_contracts(root):
    check_model_inputs = _imports_model_validation.check_model_inputs
    validate_json_settings = _imports_model_validation.validate_json_settings

    definitions = Path(__file__).resolve().parents[4]
    scope = Scope(root, "dev", "cde", "glue")
    links = [
        "[Connection 001](glue.md#connection-001)",
        "[Connection 002](glue.md#connection-002)",
    ]
    prop, key = "Glue.Job.Connections.Connections", "desired.row.009-004.value"
    values = service_values("glue", ["Glue.Connection", "Glue.Job"])
    for number, link in enumerate(links, 1):
        rid = f"{number:03d}"
        values.update(
            resource_values(
                rid,
                "Glue.Connection",
                "connection-" + rid,
                "IMPORT",
                [
                    ("Name", link),
                    ("ConnectionInput.Name", "`physical-connection-" + rid + "`"),
                    ("ConnectionInput.ConnectionType", "`JDBC`"),
                    ("CatalogId", "`123456789012`"),
                ],
            )
        )
        values[f"observed.row.{rid}-001.value"] = "`physical-connection-" + rid + "`"
    values.update(
        resource_values(
            "009",
            "Glue.Job",
            "job",
            "IMPORT",
            [
                ("Name", "`job`"),
                ("Role", "`existing-role`"),
                ("Command.Name", "`glueetl`"),
                ("Connections.Connections", json.dumps(links)),
            ],
        )
    )
    values[COUNTERS] = '{"Glue.Connection":2,"Glue.Job":9}'
    values["observed.row.009-004.value"] = json.dumps(
        ["physical-connection-001", "physical-connection-002"]
    )
    bucket = Scope(root, "dev", "cde", "s3")
    write_model(
        bucket.path,
        resource_values(
            "001", "S3.Bucket", "bucket", "IMPORT", [("BucketName", "`bucket`")]
        ),
    )
    write_model(scope.path, values)
    saved = scope.path.read_bytes()
    assert contract(prop) == contract(prop + "[17]") == {"Glue.Connection": ("Name",)}
    snapshot = load_model(scope)
    assert not snapshot.warnings and dict(snapshot.authoritative) == values
    findings = check_model_inputs(
        scope.path, values, root, definitions_root=definitions
    )
    assert not findings.errors, findings.errors
    for index in (0, 1):
        wrong = links.copy()
        wrong[index] = "[Bucket](s3.md#bucket)"
        candidate = {**values, key: json.dumps(wrong)}
        findings = check_model_inputs(
            scope.path, candidate, root, definitions_root=definitions
        )
        result = findings.result("model.references", None)
        assert result.status == "FAIL", (index, result)
        assert len(result.errors) == 1 and all(
            text in result.errors[0]
            for text in (
                prop,
                wrong[index],
                "ExpectedResourceType=Glue.Connection",
                "ActualResourceType=S3.Bucket",
            )
        ), result.errors
    indexed = {
        **values,
        "desired.row.009-004.property": prop + "[12]",
        key: json.dumps(wrong),
    }
    assert (
        check_model_inputs(scope.path, indexed, root, definitions_root=definitions)
        .result("model.references", None)
        .status
        == "FAIL"
    )
    mixed = {
        **values,
        key: json.dumps(["[Missing](glue.md#missing)", "[Bucket](s3.md#bucket)"]),
    }
    assert (
        check_model_inputs(scope.path, mixed, root, definitions_root=definitions)
        .result("model.references", None)
        .status
        == "FAIL"
    )
    for text in ("[Missing](glue.md#missing)", "[Missing Model](absent.md#missing)"):
        candidate = {**values, key: json.dumps([links[0], text])}
        findings = check_model_inputs(
            scope.path, candidate, root, definitions_root=definitions
        )
        assert findings.result("model.references", None).status == "PASS"
        assert any("absent" in warning["message"] for warning in findings.warnings), (
            findings.warnings
        )
    duplicate = {**values, "desired.resource.002.anchor": "connection-001"}
    write_model(scope.path, duplicate)
    findings = check_model_inputs(
        scope.path, duplicate, root, definitions_root=definitions
    )
    assert findings.result("model.references", None).status == "PASS"
    assert any("ambiguous" in warning["message"] for warning in findings.warnings)
    scope.path.write_bytes(saved)
    # Conflicting metadata remains a warning; the saved link supplies the proven type.
    metadata = {
        "consumerKey": key,
        "text": links[0],
        "occurrence": "1",
        "producerKind": "resource",
        "producerScope": "dev/cde/s3",
        "producerLogicalId": "S3_Bucket_001",
        "resourceType": "S3.Bucket",
        "format": "link",
        "labelPolicy": "fixed",
    }
    candidate = {
        **values,
        **{
            "desired.reference.conflict." + field: value
            for field, value in metadata.items()
        },
    }
    errors = []
    warnings, _ = diagnose(snapshot._replace(authoritative=candidate), errors=errors)
    assert not errors and any(
        "both meanings are retained" in warning["message"] for warning in warnings
    )
    # No inferred contracts; JSON documents retain their separate validation boundary.
    for candidate in (
        {
            **values,
            "desired.row.009-004.property": "Glue.Job.Command.ScriptLocation",
            key: json.dumps(["[Bucket](s3.md#bucket)"]),
        },
        {
            **values,
            "desired.row.009-004.document": json.dumps(["[Bucket](s3.md#bucket)"]),
        },
    ):
        errors = []
        diagnose(snapshot._replace(authoritative=candidate), errors=errors)
        assert not errors, errors
    for link in links:
        resolver = Resolver(root)
        assert resolver.operand(link, scope, field=prop)[3] == "Name"
    importer = ImportResolver(
        root, "dev", "cde", definitions_root=definitions, read_context=FileReads()
    )
    importer.verify_resource(values, "009", scope=scope, properties={prop})
    assert not importer.warnings, importer.warnings
    # Explicit backtick JSON still hits the existing prohibition; ordinary arrays do not.
    validate_json_settings(values, scope.path)
    try:
        validate_json_settings({**values, key: "`" + values[key] + "`"}, scope.path)
    except ValueError as error:
        assert "JSON setting contains a Markdown Resource link" in str(
            error
        ) and "'/0'" in str(error)
    else:
        raise AssertionError("explicit JSON prohibition changed")
    view = root / "docs/designs/dev/cde/glue.md"
    markdown = generate_markdown(view, values, definitions)
    view.parent.mkdir(parents=True, exist_ok=True)
    view.write_text(markdown, encoding="utf-8")
    expanded, _ = DesignIndex().get(view).view().expanded
    assert any(prop in line and values[key] in line for line in expanded), markdown
    row = ["009-004", prop, values[key], "合成配列"]
    assert verified_rows(
        indexed_rows([row], "Glue.Job", definitions), [row], "Glue.Job", definitions
    ) == [row]
    assert parse(serialize(values)).values[key] == values[key]
    assert json.loads(load_model(scope).authoritative[key]) == links
    assert generate_markdown(view, values, definitions) == markdown
    assert scope.path.read_bytes() == saved
    print(
        "ordinary array receiving contracts, unresolved warnings, Name observations and unchanged generation: PASS"
    )


def main():
    assert __debug__, "run without -O"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "project.json").write_text(
            json.dumps(
                {
                    "projectName": "synthetic",
                    "targets": [
                        {
                            "environment": "dev",
                            "alias": "cde",
                            "awsAccountId": "123456789012",
                            "awsRegion": "ap-northeast-1",
                            "iacEngine": "cloudformation",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        scope = Scope(root, "dev", "cde", "lambda")
        scope.path.parent.mkdir(parents=True)
        anchor = "lambda-lmda-venusinf-dev-inbound-detect"
        original = f"[lmda-venusinf-dev-inbound-detect](lambda.md#{anchor})"
        values = {
            COUNTERS: '{"Lambda.Function":2}',
            "desired.service.lambda.serviceId": "lambda",
            "desired.resource.017.resourceType": "Lambda.Function",
            "desired.resource.017.logicalId": "Lambda_Function_002",
            "desired.resource.017.anchor": anchor,
            "desired.resource.017.resourceMode": "IMPORT",
            "desired.row.017-008.property": "Lambda.Function.FunctionName",
            "desired.row.017-008.value": original,
            "desired.row.017-008.comment": "合成参照",
            "observed.row.017-008.value": "`physical-function`",
        }
        scope.path.write_text(serialize(values), encoding="utf-8")
        before = scope.path.read_bytes()
        validate_model_keys(values)
        validate_runtime_keys(values)
        assert parse(serialize(values)).values == values
        snapshot = load_model(scope)
        assert snapshot.authoritative == values and not snapshot.warnings
        resolver = Resolver(root)
        sources = _imports_model_sources
        with patch.object(sources, "_read_model", wraps=sources._read_model) as read:
            for text in [
                original,
                f"[other](#{anchor})",
                f"[other](./lambda.md#{anchor})",
            ]:
                producer, number, resource = resolver.resolve(text, scope)
                assert (
                    number == "017" and resource["logicalId"] == "Lambda_Function_002"
                )
            assert read.call_count == 1, read.call_count
        assert usages(snapshot)[0].producer_id == "017"
        assert incoming(snapshot, "017")[0][1].text == original
        for filename in ["", "./lambda.md", "lambda.md"]:
            alternative = snapshot._replace(
                authoritative={
                    **values,
                    "desired.row.017-008.value": f"[lmda-venusinf-dev-inbound-detect]({filename}#{anchor})",
                }
            )
            assert symbolic(alternative) == symbolic(snapshot)
        assert (
            reference_display(values, root / "docs/designs/dev/cde/lambda.md", root)
            == values
        )
        ordinary = {
            "Description": "[guide](guide.md#section)",
            "artifact": "[file](lambda/file.json)",
        }
        assert execution_document(ordinary, root, scope=scope) == ordinary
        display_anchor = _imports_model_identity.display_anchor
        try:
            display_anchor({"logicalId": "Lambda_Function_002"})
        except ReferenceResolutionError:
            pass
        else:
            raise AssertionError("missing saved anchor was guessed")
        # A distinct consumer resolves the producer through its saved anchor.

        other = Scope(root, "dev", "cde", "consumer")
        other_values = {
            COUNTERS: '{"CloudTrail.Trail":1}',
            "desired.service.consumer.serviceId": "consumer",
            "desired.resource.003.resourceType": "CloudTrail.Trail",
            "desired.resource.003.logicalId": "CloudTrail_Trail_001",
            "desired.resource.003.anchor": "cloudtrail-ctrail-venusinf-dev-p4x8r2",
            "desired.resource.003.resourceMode": "IMPORT",
            "desired.row.003-001.property": "CloudTrail.Trail.Name",
            "desired.row.003-001.value": original,
            "desired.row.003-001.comment": "合成",
        }
        other.path.write_text(serialize(other_values), encoding="utf-8")
        assert resolver.resolve(original, other)[1] == "017"
        propagate_references = _imports_model_adapters_observed.propagate_references
        changes = {}
        key = ("dev", "cde", "lambda", "Lambda_Function_002")
        propagate_references(
            root,
            {scope.path: values, other.path: other_values},
            changes,
            {key: "new-function"},
        )
        assert changes[other.path]["observed.row.003-001.value"] == "new-function"
        assert scope.path.read_bytes() == before
        ImportResolver = _imports_model_importing_references.Resolver
        matching = ImportResolver(root, "dev", "cde")
        matching.consumer_scope = other
        candidate = {"scope": scope, "anchor": anchor}
        assert matching.candidate_matches(candidate, original)
        matching.consumer_scope = scope
        assert matching.candidate_matches(candidate, f"[different label](#{anchor})")
        missing = snapshot._replace(
            authoritative={
                **values,
                "desired.row.017-008.value": "[missing](lambda.md#missing)",
            }
        )
        assert usages(missing)[0].producer_id is None
        assert diagnose(missing)[0]
        duplicate = {
            **values,
            "desired.resource.019.resourceType": "Lambda.Function",
            "desired.resource.019.logicalId": "Lambda_Function_003",
            "desired.resource.019.anchor": anchor,
            COUNTERS: '{"Lambda.Function":3}',
        }
        scope.path.write_text(serialize(duplicate), encoding="utf-8")
        try:
            Resolver(root).resolve(original, scope)
        except ReferenceResolutionError:
            pass
        else:
            raise AssertionError("ambiguous anchor accepted")
        scope.path.write_bytes(before)
        for text in [
            "[web](https://example.com/page.md#x)",
            "[artifact](lambda/file.json)",
            "[plain](readme.md)",
        ]:
            ordinary = snapshot._replace(
                authoritative={**values, "desired.row.017-008.value": text}
            )
            assert usages(ordinary) == (), text
        for filename in ["../../../escape.md", "/absolute.md"]:
            try:
                parse_reference(f"[unsafe]({filename}#anchor)", scope)
            except ValueError:
                pass
            else:
                raise AssertionError("unsafe scope accepted")
        preserve_allocation(values, values)
        new = allocate(
            {**values, "desired.resource.021.resourceType": "Lambda.Function"}, ["021"]
        )
        assert new["desired.resource.021.logicalId"] == "Lambda_Function_003"
        preserve_allocation(values, new)
        # Render actual Resource anchors, with catalog presentation isolated from naming fixtures.
        render_markdown = _imports_model_render.render_markdown
        resource_details = _imports_model_render.resource_details
        for service, model_values in [("lambda", values), ("consumer", other_values)]:
            resources = entries(model_values, "desired.resource.")
            kind = resources[0][1]["resourceType"]
            with patch(
                "model.render.resource_presentation",
                return_value=("confirmed", "confirmed", []),
            ):
                details, by_anchor = resource_details(
                    model_values, root, service, [kind], resources, {}
                )
            assert details[0][1]["anchor"] == resources[0][1]["anchor"]
            displayed = {
                **model_values,
                "display.service.title": "# Synthetic",
                "display.resource." + resources[0][0] + ".comment": "合成",
            }
            with (
                patch("model.render.resource_table_lines", return_value=[]),
                patch("model.render.model_policy_views", return_value=[]),
            ):
                markdown = render_markdown(
                    root / "docs/designs/dev/cde" / (service + ".md"),
                    displayed,
                    root,
                    [kind],
                    details,
                    {},
                )
            assert '<a id="' + resources[0][1]["anchor"] + '"></a>' in markdown
        # Generate the standalone engine and resolve under isolated Python without Framework imports.
        generate = _imports_model_audit.generate
        program, metadata, unsupported = generate(root, "dev", "cde", "lambda")
        audit = root / "audit.py"
        audit.write_text(program, encoding="utf-8")
        code = (
            "import runpy, sys; n=runpy.run_path(" + repr(str(audit)) + "); "
            'm=n["engine"](n["SNAPSHOT"]); '
            'assert "utils" not in sys.modules and "iac_values" not in sys.modules; '
            "assert m._imports_iac_values is m; "
            'assert n["masked"]({"Password": "secret"}) == {"Password": "[REDACTED]"}; '
            'ctx=m.Context(m.ROOT, n["SNAPSHOT"]["target"], None); '
            'model=m.Model(ctx,m.ROOT/"model/dev/cde/lambda.properties"); '
            "ctx.models[model.path]=model; "
            "assert model.resources[0].reference("
            + repr(original)
            + ').number == "017"'
        )
        code += '\ntry:\n model.resources[0].reference("[missing](lambda.md#missing)")\nexcept m.Unresolved:\n pass\nelse:\n raise AssertionError("missing audit anchor accepted")\n'
        result = subprocess.run(
            [sys.executable, "-I", "-c", code], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr

        print(
            "saved Markdown references, anchors, scope, incoming, observed, JSON and allocation: PASS"
        )
        check_receiving_contracts(root)


if __name__ == "__main__":
    main()
