"""Offline fixed identity allocation checks; no project or AWS inputs."""

import json
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from functools import partial
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import model.projection as _imports_model_projection
import model.render as _imports_model_render
import model.sources as _imports_model_sources
import model.sources as sources
from model.cli import main as cli
from model.core import entries
from model.format import parse, serialize, split
from model.identity import (
    COUNTERS,
    Resolver,
    allocate,
    parse_reference,
    preserve_allocation,
    resource_index,
)
from model.sources import Scope
from model.validations.identity import validate_resource_identities
from support.model_v2_fixtures import format_fixture
from utils.aws_mappings import mapping_alias

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

_CALLBACK_DEFAULT = object()


def rejects(function):
    try:
        function()
    except (ValueError, KeyError):
        return
    raise AssertionError("invalid identity accepted")


def main():
    values = {COUNTERS: '{"EC2.VPC":999}'}
    for i in range(500):
        values[f"desired.resource.{i:03d}.resourceType"] = "EC2.VPC"
    assigned = allocate(values, [f"{i:03d}" for i in range(500)])
    assert len(resource_index(assigned)) == 500
    assert assigned["desired.resource.000.logicalId"] == "EC2_VPC_1000"
    assert assigned["desired.resource.499.logicalId"] == "EC2_VPC_1499"
    preserve_allocation({COUNTERS: '{"EC2.VPC":999}'}, assigned)
    deleted = {
        key: value
        for key, value in assigned.items()
        if not key.startswith("desired.resource.499.")
    }
    preserve_allocation(assigned, deleted)
    deleted["desired.resource.500.resourceType"] = "EC2.VPC"
    added = allocate(deleted, ["500"])
    assert added["desired.resource.500.logicalId"] == "EC2_VPC_1500"
    preserve_allocation(assigned, added)
    rejects(lambda: allocate(assigned, ["000"]))
    rejects(
        lambda: resource_index(
            {**assigned, "desired.resource.001.logicalId": "EC2_VPC_1000"}
        )
    )
    rejects(lambda: resource_index({**assigned, COUNTERS: "{}"}))
    rejects(
        lambda: preserve_allocation(
            assigned, {**assigned, "desired.resource.000.logicalId": "EC2_VPC_2000"}
        )
    )
    for invalid in ["https://dev/cde/vpc/EC2_VPC_001"]:
        rejects(
            lambda *, invalid=invalid: parse_reference(
                invalid, Scope(Path("/synthetic"), "test", "team", "vpc")
            )
        )
    assert parse_reference(
        "[vpc](#anchor)", Scope(Path("/synthetic"), "test", "team", "vpc")
    ) == ("test", "team", "vpc", "anchor")
    print("fixed identity allocation: PASS")


def run_allocate(scope, *options, directory, error=None):
    stdout, stderr = StringIO(), StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = cli(["allocate", str(scope.path), "--candidate", str(directory), *options])
    if error is not None:
        assert code == 1, stdout.getvalue()
        result = json.loads(stderr.getvalue())
        assert error in result["reason"], result
        return
    assert code == 0, stderr.getvalue()
    return json.loads(stdout.getvalue())


def fail_second_replace(replace, replacements, source, destination):
    replacements.append(destination)
    if len(replacements) == 2:
        raise OSError("injected replacement failure")
    replace(source, destination)


def check_allocate_cli():
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory).resolve()
        root = temporary / "repository"
        root.mkdir()
        scope, saved = format_fixture(root)
        original = scope.path.read_bytes()
        candidate = temporary / "candidate"
        relative = scope.path.relative_to(root)
        entrance = candidate / relative
        entrance.parent.mkdir(parents=True)
        vpc_type = "desired.resource.009.resourceType"
        vpc_id = "desired.resource.009.logicalId"
        saved_id = "desired.resource.007.logicalId"
        single = {**saved, vpc_type: "EC2.VPC"}
        entrance.write_bytes(serialize(single).replace("\n", "\r\n").encode("utf-8"))
        initial = entrance.read_bytes()

        run = partial(run_allocate, scope, directory=candidate)
        select = ("--resource", "009")
        result = run(*select)
        assert result["status"] == "preview"
        assert result["allocations"] == [{"resource": "009", "logicalId": "EC2_VPC_002"}]
        assert entrance.read_bytes() == initial
        assert run(*select, "--write-candidate")["status"] == "updated"
        updated = entrance.read_bytes()
        assert updated == initial.replace(
            b"lastAllocated={\"EC2.VPC\":1}", b"lastAllocated={\"EC2.VPC\":2}"
        ) + (vpc_id + "=EC2_VPC_002\r\n").encode()
        assert scope.path.read_bytes() == original

        entrance.write_bytes(initial)
        run(*select, *select, "--write-candidate", error="duplicate allocation selection")
        run("--resource", "999", error="999")
        run("--resource", "007", error="cannot reallocate a saved logicalId")
        assert entrance.read_bytes() == initial
        for invalid, number, reason in (
            ({**single, saved_id: ""}, "007", "cannot reallocate a saved logicalId"),
            ({**single, COUNTERS: '{"EC2.VPC":false}'}, "009", "nonnegative integers"),
            ({**single, COUNTERS: '{"EC2.VPC":0}'}, "009", "duplicate logicalId"),
            ({**single, COUNTERS: '{"EC2.VPC":2}'}, "009", "allocation state does not match"),
        ):
            raw = serialize(invalid).encode()
            entrance.write_bytes(raw)
            run("--resource", number, "--write-candidate", error=reason)
            assert entrance.read_bytes() == raw

        run(*select, directory=root, error="outside the repository")
        run(*select, directory=scope.path.parent, error="outside the repository")
        extra = entrance.with_name("outside.properties")
        extra.write_bytes(initial)
        run(*select, error="outside the selected service")
        extra.unlink()
        if os.name != "nt":
            link = temporary / "link"
            link.symlink_to(candidate, target_is_directory=True)
            run(*select, directory=link, error="unsafe Model source path")
            entrance.unlink()
            entrance.symlink_to(scope.path)
            run(*select, "--write-candidate", error="unsafe Model source path")
            entrance.unlink()

        candidate_values = {
            **saved,
            vpc_type: "EC2.VPC",
            "desired.resource.008.resourceType": "EC2.VPC",
            "desired.resource.010.resourceType": "EC2.Subnet",
        }
        files = {
            candidate / path.relative_to(root): (
                text.replace("\n", "\r\n") + "# 保持するコメント\r\n"
            ).encode("utf-8")
            for path, text in split(scope.path, candidate_values, limit=2).items()
        }
        for path, raw in files.items():
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(raw)

        selected = (*select, "--resource", "010", "--resource", "008")
        replacements = []
        with patch(
            "utils.file_operations.os.replace",
            side_effect=partial(fail_second_replace, os.replace, replacements),
        ):
            run(*selected, "--write-candidate", error="injected replacement failure")
        assert len(replacements) == 3
        assert files == {path: path.read_bytes() for path in files}
        assert set(files) == {path for path in candidate.rglob("*") if path.is_file()}

        result = run(*selected, "--write-candidate")
        assert result["allocations"] == [
            {"resource": "009", "logicalId": "EC2_VPC_002"},
            {"resource": "010", "logicalId": "EC2_Subnet_001"},
            {"resource": "008", "logicalId": "EC2_VPC_003"},
        ]
        assert result["lastAllocated"] == {"EC2.VPC": 3, "EC2.Subnet": 1}
        changed = {path for path, raw in files.items() if path.read_bytes() != raw}
        assert changed == {Path(path) for path in result["paths"]}
        assert len(changed) == 4
        for path in changed:
            raw = path.read_bytes()
            assert raw.endswith("# 保持するコメント\r\n".encode("utf-8"))
            assert b"\n" not in raw.replace(b"\r\n", b"")
            values = parse(raw.decode()).values
            assert saved_id not in values
        assert scope.path.read_bytes() == original
    print("Model allocation CLI: PASS")


def check_snapshots():
    with tempfile.TemporaryDirectory() as directory:
        old, new = Path(directory) / "before", Path(directory) / "after"
        scopes = ["qa/one/vpc", "qa/two/vpc", "live/one/vpc"]
        project = {
            "projectName": "synthetic",
            "targets": [
                {
                    "environment": env,
                    "alias": alias,
                    "awsAccountId": "123456789012",
                    "awsRegion": "ap-northeast-1",
                    "iacEngine": "cloudformation",
                }
                for env, alias in [("qa", "one"), ("qa", "two"), ("live", "one")]
            ],
        }
        for root in (old, new):
            root.mkdir()
            (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
        for scope in scopes:
            values = {"desired.service.vpc.serviceId": "vpc"}
            for i in range(500):
                values.update(
                    {
                        f"desired.resource.{i:03d}.resourceType": "EC2.VPC",
                        f"desired.resource.{i:03d}.logicalId": "old-" + str(i),
                        f"desired.resource.{i:03d}.anchor": "anchor-" + str(i),
                        f"desired.resource.{i:03d}.resourceMode": "IMPORT",
                    }
                )
            values.update(
                {
                    "desired.row.000-001.property": "EC2.VPC.VpcId",
                    "desired.row.000-001.value": '`{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}`',
                    "desired.row.000-001.comment": "unchanged",
                    "observed.row.000-001.value": "`vpc-fixed`",
                }
            )
            after = {
                key: value
                for key, value in values.items()
                if not key.endswith(".logicalId")
            }
            after = allocate(after, [f"{i:03d}" for i in range(500)])
            after["desired.row.000-001.value"] = (
                '`{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}`'
            )
            for root, data in [(old, after), (new, after)]:
                path = root / "model" / (scope + ".properties")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(serialize(data), encoding="utf-8")
        resolver = Resolver(new)
        with patch.object(sources, "_read_model", wraps=sources._read_model) as read:
            for i in range(500):
                snapshot, number, resource = resolver.resolve(
                    json.dumps(
                        {
                            "$modelRef": {
                                "logicalId": f"EC2_VPC_{i + 1:03d}",
                                "attribute": "VpcId",
                            }
                        }
                    ),
                    Scope(new, "qa", "one", "vpc"),
                )
                assert number == f"{i:03d}"
            assert read.call_count == 1, read.call_count
        assert (
            resolver.resolve(
                '`{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}`',
                Scope(new, "qa", "two", "vpc"),
            )[0].scope.target
            == "two"
        )
        assert (
            resolver.resolve(
                '`{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}`',
                Scope(new, "live", "one", "vpc"),
            )[0].scope.environment
            == "live"
        )
        rejects(
            lambda: resolver.resolve(
                '`{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}`',
                Scope(new, "unknown", "one", "vpc"),
            )
        )
        print("baseline preservation and 500 indexed resolutions: PASS")


def check_cfn_and_outputs():
    reference_display = _imports_model_projection.reference_display
    framework = Path(__file__).resolve().parents[4]
    with tempfile.TemporaryDirectory() as directory:
        after = Path(directory).resolve() / "current"
        new = allocate(
            {
                "desired.resource.007.resourceType": "EC2.VPC",
                "desired.resource.007.anchor": "network",
                "desired.resource.007.resourceMode": "CREATE",
            },
            ["007"],
        )
        new["desired.resource.007.cfn-logicalId"] = "existing-stack-ExistingVpc"
        stacks = {
            "desired.stack.004.name": "existing-stack",
            "desired.stack.004.template": "network.yaml",
            "desired.stack.004.parameters": "network.json",
            "desired.stack.004.deployOrder": "1",
            "desired.stack.004.placementName": "unchanged",
        }
        after.mkdir()
        (after / "project.json").write_text(
            json.dumps(
                {
                    "targets": [
                        {
                            "environment": "qa",
                            "alias": "team",
                            "awsAccountId": "123456789012",
                            "awsRegion": "ap-northeast-1",
                            "iacEngine": "cloudformation",
                        }
                    ]
                }
            )
        )
        files = {
            "model/qa/team/vpc.properties": serialize(new),
            "model/qa/team/cloudformation-stacks.properties": serialize(stacks),
            "infra/cloudformation/templates/team/network.yaml": "Resources:\n  ExistingVpc:\n    Type: AWS::EC2::VPC\n    Properties:\n      CidrBlock: 10.0.0.0/16\n",
            "infra/cloudformation/parameters/qa/team/network.json": "[]",
        }
        for name, content in files.items():
            path = after / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        with mapping_alias(framework, after):
            missing = {
                key: value
                for key, value in new.items()
                if not key.endswith(".cfn-logicalId")
            }
            rejects(
                lambda: validate_resource_identities(
                    after / "docs/designs/qa/team/vpc.md",
                    missing,
                    after,
                    list(entries(missing, "desired.resource.")),
                    definitions_root=framework,
                )
            )
            bucket = {
                "desired.service.s3.serviceId": "s3",
                "desired.service.s3.ownedCatalogResourceTypes": "S3.Bucket",
                "display.service.title": "# Buckets",
                "display.resource.007.comment": "confirmed",
                "desired.resource.007.resourceType": "S3.Bucket",
                "desired.resource.007.resourceMode": "IMPORT",
                "desired.row.007-001.property": "S3.Bucket.BucketName",
                "desired.row.007-001.value": "`physical-bucket`",
                "desired.row.007-001.comment": "literal stays literal",
            }
            bucket["desired.resource.007.anchor"] = "saved-bucket"
            bucket = allocate(bucket, ["007"])
            path = after / "model/qa/team/s3.properties"
            path.write_text(serialize(bucket))
            saved = path.read_bytes()
            document = {
                "Statement": [
                    {"Resource": "arn:aws:s3:::physical-bucket", "Effect": "Allow"}
                ]
            }
            result = document
            displayed = reference_display(
                bucket, after / "docs/designs/qa/team/s3.md", after
            )
            assert displayed["desired.resource.007.anchor"] == "saved-bucket"
            assert displayed == bucket
            assert bucket["desired.row.007-001.value"] == "`physical-bucket`"
            assert bucket["desired.resource.007.anchor"] == "saved-bucket"
            renamed = {**bucket, "desired.row.007-001.value": "`renamed-bucket`"}
            renamed_display = reference_display(
                renamed, after / "docs/designs/qa/team/s3.md", after
            )
            assert renamed_display == renamed
            generate_files = _imports_model_render.generate_files
            runtime_values = _imports_model_sources.runtime_values
            policy = allocate(
                {
                    "desired.service.iam.serviceId": "iam",
                    "desired.service.iam.ownedCatalogResourceTypes": "IAM.ManagedPolicy",
                    "display.service.title": "# Policies",
                    "desired.resource.009.resourceType": "IAM.ManagedPolicy",
                    "desired.resource.009.resourceMode": "IMPORT",
                    "desired.resource.009.anchor": "saved-policy",
                    "display.resource.009.comment": "policy fixture",
                    "desired.row.009-001.property": "IAM.ManagedPolicy.ManagedPolicyName",
                    "desired.row.009-001.value": "`policy-fixture`",
                    "desired.row.009-001.comment": "unchanged name",
                    "desired.row.009-002.property": "IAM.ManagedPolicy.PolicyDocument",
                    "desired.row.009-002.value": "[Policy](iam/policy.json)",
                    "desired.row.009-002.comment": "confirmed policy",
                    "desired.row.009-002.document": json.dumps(document),
                },
                ["009"],
            )
            design = after / "docs/designs/qa/team/iam.md"
            # Definitions are redirected using the same alias as a staged consumer.

            renderer = _imports_model_render
            original_markdown = renderer.generate_markdown
            with patch.object(
                renderer,
                "generate_markdown",
                lambda path, values, root: original_markdown(path, values, framework),
            ):
                files = generate_files(design, runtime_values(policy), after)
            assert json.loads(files[design.with_suffix("") / "policy.json"]) == result
            assert '<a id="saved-policy"></a>' in files[design]
            assert json.loads(policy["desired.row.009-002.document"]) == document
            display = reference_display(policy, design, after)
            assert json.loads(display["desired.row.009-002.document"]) == result
            assert "artifactSha256" not in serialize(policy)
            assert path.read_bytes() == saved

    print("CFn correspondence and output projections: PASS")


if __name__ == "__main__":
    main()
    check_allocate_cli()
    check_snapshots()
    check_cfn_and_outputs()
