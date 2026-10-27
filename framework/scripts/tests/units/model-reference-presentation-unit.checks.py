"""Shared position-bound links through existing service displays; no AWS access."""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from design.common import code
from design.document import DesignIndex
from design.layout import expanded_display_rows
from design.policy_tables import (
    Policy,
    policy_document_lines,
    policy_lines,
    rendered_design,
)
from model.core import literal
from model.identity import COUNTERS
from model.projection import reference_display
from model.reference_presentation import Position, Presentation
from model.render import generate_files, generate_markdown
from model.sources import Scope, load_model
from support.model_reference_fixtures import (
    FRAMEWORK,
    project,
    reference,
    resource,
    save,
)
from support.pytest_cli import run
from utils.aws_mappings import mapping_alias

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.fixture
def models(tmp_path):
    with (
        mapping_alias(FRAMEWORK, tmp_path),
        patch("socket.socket", side_effect=AssertionError("network forbidden")),
    ):
        project(tmp_path)
        for service, kind, field, name in (
            ("s3", "S3.Bucket", "BucketName", "shared-name"),
            ("codebuild", "CodeBuild.Project", "Name", "shared-name"),
            ("codecommit", "CodeCommit.Repository", "RepositoryName", "repository"),
            ("ssm", "SSM.Parameter", "Name", "/build/parameter"),
            ("secretsmanager", "SecretsManager.Secret", "Name", "build-secret"),
        ):
            scope, values = resource(tmp_path, service, kind, attribute=field)
            values["desired.row.001-001.value"] = "`" + name + "`"
            values["desired.resource.001.anchor"] = service + "-saved-anchor"
            save(scope, values)
        yield tmp_path


def consumer(root, service="glue", kind="Glue.Job"):
    scope, values = resource(root, service, kind, attribute="Name")
    values["desired.row.001-001.value"] = "`consumer`"
    return scope, values, root / "docs/designs/qa/team" / (service + ".md")


def add(values, kind, field, value, *, number=2, comment="参照元"):
    rid = f"001-{number:03d}"
    values[f"desired.row.{rid}.property"] = kind + "." + field
    values[f"desired.row.{rid}.value"] = (
        "`"
        + (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
        + "`"
    )
    values[f"desired.row.{rid}.comment"] = comment
    return rid


def restore(path, markdown, values):
    document = DesignIndex(FRAMEWORK).get(path, text=markdown, values=values)
    return "\n".join(document.raw.display_lines)


def test_positions_glue_equal_names_escaping_and_roundtrip(models):
    scope, values, path = consumer(models)
    args = {
        "--bucket/~": reference("S3_Bucket_001", "BucketName"),
        "--project": reference("CodeBuild_Project_001", "Name"),
        "--literal": "shared-name",
    }
    rid = add(values, "Glue.Job", "DefaultArguments", args)
    exact_link = "[shared-name](s3.md#s3-saved-anchor)"
    add(values, "Glue.Job", "Description", exact_link, number=3, comment=exact_link)
    _, other = resource(models, "glue", "Glue.Job", attribute="Name", number="002")
    other["desired.row.002-001.value"] = "`other-job`"
    other["desired.row.002-002.property"] = "Glue.Job.Description"
    other["desired.row.002-002.value"] = "`" + exact_link + "`"
    other["desired.row.002-002.comment"] = exact_link
    values.update(other)
    save(scope, values)
    before = copy.deepcopy(values)
    presentation = Presentation(values, path, models)
    assert set(presentation.references) == {
        Position(rid, "value", "/--bucket~1~0"),
        Position(rid, "value", "/--project"),
    }
    markdown = generate_markdown(path, values, FRAMEWORK)
    assert "[shared-name](s3.md#s3-saved-anchor)" in markdown
    assert "[shared-name](codebuild.md#codebuild-saved-anchor)" in markdown
    literal_line = next(
        line
        for line in markdown.splitlines()
        if 'DefaultArguments["--literal"]' in line
    )
    assert "| `shared-name` |" in literal_line
    descriptions = [line for line in markdown.splitlines() if "| Description |" in line]
    assert len(descriptions) == 2
    assert all(
        "| `" + exact_link + "` | " + exact_link + " |" in line for line in descriptions
    )
    assert "glue-arguments-source:" in markdown
    assert "$modelRef" not in markdown
    assert generate_markdown(path, values, FRAMEWORK) == markdown
    semantic = restore(path, markdown, values)
    assert json.dumps(args, ensure_ascii=False) in semantic
    assert "参照元" in semantic and values == before
    for target in ("s3.md#s3-saved-anchor", "codebuild.md#codebuild-saved-anchor"):
        changed = markdown.replace(target, "s3.md#wrong-anchor", 1)
        with pytest.raises(ValueError, match="Model expected display"):
            restore(path, changed, values)


@pytest.mark.parametrize("decorated", [False, True])
def test_exact_link_literals_and_typed_positions_in_shared_cell(models, decorated):
    scope, values, path = consumer(models, "lambda", "Lambda.Function")
    values["desired.row.001-001.property"] = "Lambda.Function.FunctionName"
    link = "[shared-name](s3.md#s3-saved-anchor)"
    args = {
        "typed": reference("S3_Bucket_001", "BucketName"),
        "literal": link,
        "other": reference("CodeBuild_Project_001", "Name"),
    }
    if decorated:
        args["decoration"] = "<tag>&`text`"
    rid = add(values, "Lambda.Function", "Environment.Variables", args, comment=link)
    before = copy.deepcopy(values)
    presentation = Presentation(values, path, models)
    assert set(presentation.references) == {
        Position(rid, "value", "/typed"),
        Position(rid, "value", "/other"),
    }
    # Exercise the shared display boundary directly: JSON authority validation
    # independently rejects Markdown links inside JSON and is not weakened here.
    projected = reference_display(values, path, models)
    baseline_row = [
        rid,
        values[f"desired.row.{rid}.property"],
        projected[f"desired.row.{rid}.value"],
        link,
    ]
    marked_row = presentation.rows([baseline_row])[0]
    baseline = ["| " + code(literal(baseline_row[2])) + " | " + link + " |"]
    marked = ["| " + code(literal(marked_row[2])) + " | " + link + " |"]
    displayed = presentation.lines(baseline, marked)
    mixed = displayed[0]
    opening, closing = ("<code>", "</code>") if decorated else ("`", "`")
    assert closing + link + opening in mixed
    assert opening + '", "literal": "' + link + '", "other": "' + closing in mixed
    assert (
        closing + "[shared-name](codebuild.md#codebuild-saved-anchor)" + opening
        in mixed
    )
    assert mixed.endswith(" | " + link + " |")
    if decorated:
        assert "&lt;tag&gt;&amp;`text`" in mixed
    assert not any(token in mixed for token in presentation.tokens)
    assert presentation.lines(baseline, marked) == displayed
    assert values == before


def test_marker_collision_and_comment_source_preservation(models):
    scope, values, path = consumer(models)
    collision = "[blueprint-reference-0](#blueprint-reference-0)"
    add(
        values,
        "Glue.Job",
        "DefaultArguments",
        {"--input": reference("S3_Bucket_001", "BucketName")},
    )
    add(values, "Glue.Job", "Description", collision, number=3)
    # Also cover a candidate marker authored with JSON Unicode escapes.
    values["desired.row.001-003.comment"] = (
        '{"collision": "\\u0062lueprint-reference-x0"}'
    )
    presentation = Presentation(values, path, models)
    assert all(
        "blueprint-reference-xx" in marker for marker in presentation.marker_links
    )
    marker = next(iter(presentation.marker_links))
    link = presentation.marker_links[marker]
    baseline = ["| `ordinary` | <!-- source: " + link + " --> comment " + link + " |"]
    marked = [
        "| `" + marker + "` | <!-- source: " + marker + " --> comment " + link + " |"
    ]
    assert presentation.lines(baseline, marked) == [
        "| " + link + " | <!-- source: " + link + " --> comment " + link + " |"
    ]
    markdown = generate_markdown(path, values, FRAMEWORK)
    assert "| `" + collision + "` |" in markdown
    assert "glue-arguments-source:" in markdown
    assert not any(token in markdown for token in presentation.tokens)
    assert (
        presentation.cell(
            "``<br><code>ordinary</code><br>`resolved`",
            "``<br><code>ordinary</code><br>`" + marker + "`",
        )
        == "``<br><code>ordinary</code><br>" + link
    )
    assert "$modelRef" in restore(path, markdown, values)


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "pending",
        "invalid-attribute",
        "ambiguous-anchor",
        "unconfirmed-name",
    ],
)
def test_no_guessed_destination(models, fault):
    scope, values, path = consumer(models)
    logical, attribute = "S3_Bucket_001", "BucketName"
    producer_path = models / "model/qa/team/s3.properties"
    # Each fault changes only the synthetic producer, never a live Model.
    if fault == "missing":
        logical = "S3_Bucket_999"
    elif fault == "duplicate":
        resource(models, "duplicate", "S3.Bucket", attribute="BucketName")
    elif fault == "invalid-attribute":
        attribute = "RoleName"
    else:
        from_values = dict(load_model(producer_path).authoritative)
        if fault == "pending":
            from_values["observed.row.001-001.value"] = "`PENDING_DEPLOY`"
        elif fault == "unconfirmed-name":
            from_values["desired.row.001-001.value"] = "`UNSET`"
        else:
            for key, value in list(from_values.items()):
                if ".resource.001." in key or ".row.001-" in key:
                    from_values[
                        key.replace(".001.", ".002.").replace(".001-", ".002-")
                    ] = value.replace("S3_Bucket_001", "S3_Bucket_002")
            from_values[COUNTERS] = json.dumps({"S3.Bucket": 2})
        save(Scope(models, "qa", "team", "s3"), from_values)
    rid = add(
        values,
        "Glue.Job",
        "DefaultArguments",
        {"--input": reference(logical, attribute)},
    )
    presentation = Presentation(values, path, models)
    markdown = generate_markdown(path, values, FRAMEWORK)
    assert "[shared-name]" not in markdown
    if fault in {"missing", "duplicate", "invalid-attribute", "unconfirmed-name"}:
        assert "$modelRef" in markdown
    else:
        ref = presentation.references[Position(rid, "value", "/--input")]
        assert ref.link is None
        if fault == "pending":
            assert ref.value == "shared-name"


def test_array_indexes_duplicates_and_generic_service(models):
    producer, first = resource(
        models, "subnet", "EC2.Subnet", attribute="SubnetId", observed="subnet-11111111"
    )
    _, second = resource(
        models,
        "subnet",
        "EC2.Subnet",
        attribute="SubnetId",
        observed="subnet-22222222",
        number="002",
    )
    first.update(second)
    for number in ("001", "002"):
        first[f"desired.resource.{number}.resourceMode"] = "IMPORT"
        first[f"desired.row.{number}-002.property"] = "EC2.Subnet.Name"
        first[f"desired.row.{number}-002.value"] = "`shared-subnet`"
        first[f"desired.row.{number}-002.comment"] = "名前"
    save(producer, first)
    scope, values, path = consumer(models, "lambda", "Lambda.Function")
    values["desired.row.001-001.property"] = "Lambda.Function.FunctionName"
    items = [
        reference("EC2_Subnet_001", "SubnetId"),
        "subnet-11111111",
        reference("EC2_Subnet_002", "SubnetId"),
        reference("EC2_Subnet_001", "SubnetId"),
    ]
    rid = add(values, "Lambda.Function", "VpcConfig.SubnetIds", items)
    presentation = Presentation(values, path, models)
    assert [pos.pointer for pos in presentation.references] == ["/0", "/2", "/3"]
    markdown = generate_markdown(path, values, FRAMEWORK)
    lines = [line for line in markdown.splitlines() if "| VpcConfig.SubnetIds[" in line]
    assert len(lines) == 4
    assert "[shared-subnet](subnet.md#saved-001)" in lines[0]
    assert "| `subnet-11111111` |" in lines[1]
    assert "[shared-subnet](subnet.md#saved-002)" in lines[2]
    assert "[shared-subnet](subnet.md#saved-001)" in lines[3]
    assert json.dumps(items) in restore(path, markdown, values)
    assert Position(rid, "value", "/3") in presentation.references


def test_same_file_and_existing_link(models):
    scope, values, path = consumer(models)
    add(
        values,
        "Glue.Job",
        "DefaultArguments",
        {"--self": reference("Glue_Job_001", "Name")},
    )
    add(values, "Glue.Job", "Role", "placeholder", number=3)
    values["desired.row.001-003.value"] = "[existing](iam.md#saved-role)"
    markdown = generate_markdown(path, values, FRAMEWORK)
    assert "| [consumer](#saved-001) | <!-- glue-arguments-source:" in markdown
    assert "[existing](iam.md#saved-role)" in markdown
    assert "$modelRef" in restore(path, markdown, values)


@pytest.mark.parametrize(
    "variable_type,logical,attribute",
    [
        ("PARAMETER_STORE", "SSM_Parameter_001", "Name"),
        ("SECRETS_MANAGER", "SecretsManager_Secret_001", "Name"),
    ],
)
def test_codebuild_variable_connection(models, variable_type, logical, attribute):
    scope, values, path = consumer(models, "codebuild", "CodeBuild.Project")
    for number, field, value in (
        (2, "Name", "TOKEN"),
        (3, "Type", variable_type),
        (4, "Value", reference(logical, attribute)),
    ):
        add(
            values,
            "CodeBuild.Project",
            "Environment.EnvironmentVariables[]." + field,
            value,
            number=number,
        )
    if variable_type == "PARAMETER_STORE":
        assert "$modelRef" in generate_markdown(path, values, FRAMEWORK)
        return
    markdown = generate_markdown(path, values, FRAMEWORK)
    line = next(
        line
        for line in markdown.splitlines()
        if "Environment.Variables[1].TOKEN" in line
    )
    assert "](" in line and "codebuild-variable-type:" in line
    assert "$modelRef" in restore(path, markdown, values)
    values["desired.row.001-003.value"] = "`PLAINTEXT`"
    with pytest.raises(ValueError, match="PLAINTEXT"):
        generate_markdown(path, values, FRAMEWORK)


@pytest.mark.parametrize(
    "key,logical,attribute,category,provider,service,label",
    [
        (
            "RepositoryName",
            "CodeCommit_Repository_001",
            "Name",
            "Source",
            "CodeCommit",
            "codecommit",
            "repository",
        ),
        (
            "ProjectName",
            "CodeBuild_Project_001",
            "Name",
            "Build",
            "CodeBuild",
            "codebuild",
            "shared-name",
        ),
        (
            "S3Bucket",
            "S3_Bucket_001",
            "BucketName",
            "Source",
            "S3",
            "s3",
            "shared-name",
        ),
    ],
)
def test_pipeline_configuration_positions(
    models, key, logical, attribute, category, provider, service, label
):
    scope, values, path = consumer(models, "codepipeline", "CodePipeline.Pipeline")
    number = 2
    for index in (1, 2):
        for field, value in (
            ("Name", f"action-{index}"),
            ("ActionTypeId.Category", category),
            ("ActionTypeId.Owner", "AWS"),
            ("ActionTypeId.Provider", provider),
            ("ActionTypeId.Version", "1"),
            ("Configuration", {key: reference(logical, attribute), "Literal": label}),
        ):
            add(
                values,
                "CodePipeline.Pipeline",
                "Stages[].Actions[]." + field,
                value,
                number=number,
                comment=f"{key}: 参照 / Literal: 通常"
                if field == "Configuration"
                else "アクション",
            )
            number += 1
    add(values, "CodePipeline.Pipeline", "Stages[].Name", "stage", number=number)
    markdown = generate_markdown(path, values, FRAMEWORK)
    for index in (1, 2):
        line = next(
            line
            for line in markdown.splitlines()
            if f"Actions[{index}].Configuration.{key} |" in line
        )
        assert f"[{label}]({service}.md#{service}-saved-anchor)" in line
        line = next(
            line
            for line in markdown.splitlines()
            if f"Actions[{index}].Configuration.Literal |" in line
        )
        assert f"| `{label}` |" in line
    semantic = restore(path, markdown, values)
    assert semantic.count("$modelRef") == 2


@pytest.mark.parametrize(
    "field,producer_kind,attribute",
    [
        ("VpcId", "EC2.VPC", "VpcId"),
        ("Subnets", "EC2.Subnet", "SubnetId"),
        ("SecurityGroupIds", "EC2.SecurityGroup", "GroupId"),
    ],
)
def test_codebuild_vpc_connection(models, field, producer_kind, attribute):
    producer, props = resource(
        models,
        "network",
        producer_kind,
        attribute=attribute,
        observed="vpc-11111111"
        if field == "VpcId"
        else "subnet-11111111"
        if field == "Subnets"
        else "sg-11111111",
    )
    props["desired.resource.001.resourceMode"] = "IMPORT"
    props["display.resource.001.label"] = "network-resource"
    save(producer, props)
    scope, values, path = consumer(models, "codebuild", "CodeBuild.Project")
    node = reference(producer_kind.replace(".", "_") + "_001", attribute)
    add(
        values,
        "CodeBuild.Project",
        "VpcConfig." + field,
        node if field == "VpcId" else [node],
    )
    markdown = generate_markdown(path, values, FRAMEWORK)
    line = next(
        line for line in markdown.splitlines() if f"| VpcConfig.{field}" in line
    )
    assert "[network-resource](network.md#saved-001)" in line
    assert "$modelRef" in restore(path, markdown, values)


def test_policy_display_artifact_regeneration_and_raw_fallback(models):
    scope, values, path = consumer(models, "iam", "IAM.ManagedPolicy")
    values["desired.row.001-001.property"] = "IAM.ManagedPolicy.ManagedPolicyName"
    document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "s3:GetObject",
                "Resource": reference("S3_Bucket_001", "Arn"),
            }
        ],
    }
    rid = add(values, "IAM.ManagedPolicy", "PolicyDocument", "placeholder")
    values[f"desired.row.{rid}.value"] = "[Policy](iam/policy.json)"
    values[f"desired.row.{rid}.document"] = json.dumps(document)
    save(scope, values)
    before = copy.deepcopy(values)
    files = generate_files(path, values, models)
    artifact = path.with_suffix("") / "policy.json"
    assert json.loads(files[artifact])["Statement"][0]["Resource"] == (
        "arn:aws:s3:::shared-name"
    )
    assert "[shared-name](s3.md#s3-saved-anchor)" in files[path]
    assert "](" not in files[artifact] and "$modelRef" not in files[artifact]
    for file, text in files.items():
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
    assert rendered_design(path, definitions_root=FRAMEWORK) == files[path]
    restore(path, files[path], values)
    with pytest.raises(ValueError, match="Model expected display"):
        restore(
            path,
            files[path].replace("s3.md#s3-saved-anchor", "s3.md#wrong-anchor"),
            values,
        )
    assert values == before
    policy = Policy(
        "Policy",
        "iam/policy.json",
        "raw",
        "ポリシー",
        "IAM.ManagedPolicy.PolicyDocument",
    )
    presentation = Presentation(values, path, models)
    rows = {
        (policy.property_name, policy.link): [
            (rid, {"property": policy.property_name, "document": json.dumps(document)})
        ]
    }
    assert "[shared-name](s3.md#s3-saved-anchor)" in "\n".join(
        policy_lines(path, policy, presentation=presentation, policy_rows=rows)
    )
    artifact.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from authoritative Model"):
        policy_lines(path, policy, presentation=presentation, policy_rows=rows)
    artifact.write_text(files[artifact], encoding="utf-8")
    original = {"Unsupported": reference("S3_Bucket_001", "Arn")}
    values[f"desired.row.{rid}.document"] = json.dumps(original)
    presentation = Presentation(values, path, models)
    baseline = policy_document_lines(
        {"Unsupported": "arn:aws:s3:::shared-name"}, policy
    )
    marked = policy_document_lines(
        {"Unsupported": "[shared-name](s3.md#s3-saved-anchor)"}, policy
    )
    assert presentation.lines(baseline, marked) == baseline
    assert "```json" in baseline and not any("](" in line for line in baseline)
    path.unlink()
    # Without source authority the artifact renderer keeps ordinary AWS values.
    scope.path.unlink()
    path.write_text(files[path], encoding="utf-8")
    assert "[shared-name](s3.md#s3-saved-anchor)" not in rendered_design(
        path, definitions_root=FRAMEWORK
    )


@pytest.mark.parametrize(
    ("service", "kind", "attribute", "fields"),
    [
        ("s3", "S3.Bucket", "BucketName", ["LifecycleConfiguration.Rules[1].Status"]),
        (
            "cloudtrail",
            "CloudTrail.Trail",
            "TrailName",
            ["EventSelectors[1].ReadWriteType"],
        ),
        ("quicksight", "QuickSight.DataSource", "Name", ["Permissions[1].Principal"]),
        ("codepipeline", "CodePipeline.Pipeline", "Name", ["Stages[1].Name"]),
        (
            "codepipeline",
            "CodePipeline.Pipeline",
            "Name",
            ["Stages[1].Actions[1].Name", "Stages[1].Actions[2].Name"],
        ),
        (
            "s3",
            "S3.Bucket",
            "BucketName",
            [
                "BucketEncryption.ServerSideEncryptionConfiguration[1].BucketKeyEnabled",
                "BucketEncryption.ServerSideEncryptionConfiguration[2].BucketKeyEnabled",
            ],
        ),
    ],
)
def test_indexed_model_reference_tables(models, service, kind, attribute, fields):
    scope, values = resource(models, service, kind, attribute=attribute)
    values["desired.row.001-001.value"] = "`example`"
    for number, field in enumerate(fields, 2):
        add(values, kind, field, "value-" + str(number), number=number)
    save(scope, values)
    path = models / "docs/designs/qa/team" / (service + ".md")
    tables = []
    markdown = generate_markdown(path, values, FRAMEWORK, reference_tables=tables)
    assert len(tables) == 1
    if "BucketEncryption" in fields[0]:
        assert any(
            "BucketEncryption[1].BucketKeyEnabled" in line
            for line in tables[0].expected
        )
        assert any(
            "BucketEncryption[2].BucketKeyEnabled" in line
            for line in tables[0].expected
        )
    semantic = "\n".join(tables[0].semantic)
    for number, field in enumerate(fields, 2):
        assert kind + "." + field in semantic
        assert "value-" + str(number) in semantic
    expanded = "\n".join(
        expanded_display_rows(markdown.splitlines(), FRAMEWORK, reference_tables=tables)
    )
    assert semantic in expanded
    assert semantic in restore(path, markdown, values)
    expected_row = next(line for line in tables[0].expected if "value-2" in line)
    for changed in (
        expected_row.replace("value-2", "changed"),
        expected_row.replace(expected_row.split(" | ")[1], "Altered.Property", 1),
        "",
        expected_row + "\n" + expected_row,
    ):
        with pytest.raises(ValueError, match="Model expected display"):
            expanded_display_rows(
                markdown.replace(expected_row, changed, 1).splitlines(),
                FRAMEWORK,
                reference_tables=tables,
            )
    if service == "s3" and len(fields) == 1:
        indexed = [
            "### " + kind + ": example",
            *tables[0].baseline[:2],
            "| 1 | " + kind + "." + fields[0] + " | `value` | |",
        ]
        with pytest.raises(
            ValueError, match="indexed array display requires Model source rows"
        ):
            expanded_display_rows(indexed, FRAMEWORK)


def test_undefined_indexed_property_is_rejected(models):
    scope, values = resource(models, "s3", "S3.Bucket", attribute="BucketName")
    add(values, "S3.Bucket", "LifecycleConfiguration.Rules[1].Missing", "value")
    with pytest.raises(ValueError):
        generate_markdown(models / "docs/designs/qa/team/s3.md", values, FRAMEWORK)


def test_security_group_horizontal_display_and_restoration(models):
    producer, network = resource(
        models, "network", "EC2.VPC", attribute="VpcId", observed="vpc-11111111"
    )
    network["desired.resource.001.resourceMode"] = "IMPORT"
    network["display.resource.001.label"] = "network"
    save(producer, network)
    scope, values = resource(
        models,
        "security-group",
        "EC2.SecurityGroup",
        attribute="Id",
        observed="sg-11111111",
    )
    values["desired.resource.001.resourceMode"] = "IMPORT"
    add(values, "EC2.SecurityGroup", "GroupDescription", "description")
    add(values, "EC2.SecurityGroup", "GroupName", "consumer-group", number=3)
    add(
        values,
        "EC2.SecurityGroup",
        "VpcId",
        reference("EC2_VPC_001", "VpcId"),
        number=4,
    )
    path = models / "docs/designs/qa/team/security-group.md"
    markdown = generate_markdown(path, values, FRAMEWORK)
    assert "[network](network.md#saved-001)" in markdown
    assert "$modelRef" in restore(path, markdown, values)
    with pytest.raises(ValueError, match="Model expected display"):
        restore(
            path, markdown.replace("network.md#saved-001", "network.md#wrong"), values
        )


def test_policy_enum_reference_is_validated_before_presentation(models):
    producer = Scope(models, "qa", "team", "codebuild")
    source = dict(load_model(producer).authoritative)
    source["desired.resource.001.resourceMode"] = "IMPORT"
    source["desired.row.001-001.value"] = "`Allow`"
    save(producer, source)
    scope, values, path = consumer(models, "iam", "IAM.ManagedPolicy")
    values["desired.row.001-001.property"] = "IAM.ManagedPolicy.ManagedPolicyName"
    add(values, "IAM.ManagedPolicy", "PolicyDocument", "placeholder")
    values["desired.row.001-002.value"] = "[Policy](iam/policy.json)"
    values["desired.row.001-002.document"] = json.dumps(
        {
            "Statement": [
                {
                    "Effect": reference("CodeBuild_Project_001", "Name"),
                    "Action": "s3:GetObject",
                    "Resource": "*",
                }
            ]
        }
    )
    files = generate_files(path, values, models)
    assert "[Allow](codebuild.md#codebuild-saved-anchor)" in files[path]
    assert (
        json.loads(files[path.with_suffix("") / "policy.json"])["Statement"][0][
            "Effect"
        ]
        == "Allow"
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
