#!/usr/bin/env python3
"""Offline raw producer names used by Logs: typed, traced and dependency-aware."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


from support.it_case_receipt import it_case
from support.producer_identifier_reference_fixtures import (
    Path,
    affected,
    dependency_hashes,
    design_source_digest,
    json,
    load_model,
    reference,
    resource,
    setup,
    tempfile,
    trace_model,
    warning,
    write_model,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@it_case
def check(root):
    specs = {
        "Configuration": ("glue", "006", "Glue.SecurityConfiguration", "Name"),
        "ExecutionRole": ("iam", "054", "IAM.Role", "RoleName"),
        "Function": ("lambda", "012", "Lambda.Function", "FunctionName"),
        "Trail": ("cloudtrail", "001", "CloudTrail.Trail", "TrailName"),
        "Project": ("codebuild", "008", "CodeBuild.Project", "Name"),
        "Repository": ("codecommit", "017", "CodeCommit.Repository", "RepositoryName"),
    }
    setup(
        root,
        [*{spec[0] for spec in specs.values()}, "cloudwatch-logs"],
        [*{spec[2] for spec in specs.values()}, "Logs.LogGroup"],
        ("preview", "later"),
    )
    records = {}
    for env, suffix in [("preview", "-Case_01"), ("later", "")]:
        names = {
            "Configuration": "glsc" + suffix,
            "ExecutionRole": "venusinf-" + env + "-IfInbound1802Role" + suffix,
            "Function": "lmda-" + env + "-inbound-detect" + suffix,
            "Trail": "trail-" + env + suffix,
            "Project": "cbld-" + env + suffix,
            "Repository": "ccmt-" + env + suffix,
        }
        producers = {}
        for name, (service, rid, kind, prop) in specs.items():
            producer = root / "model" / env / "team" / (service + ".properties")
            values = resource(
                rid, kind, service + "-original", [(prop, "`" + names[name] + "`")]
            )
            if name == "Project":
                values.update(
                    {
                        "desired.row.008-002.property": "CodeBuild.Project.Environment.EnvironmentVariables[].Name",
                        "desired.row.008-002.value": "`AWS_REGION`",
                        "desired.row.008-002.comment": "入れ子Nameは名前参照に使わない",
                        "desired.row.008-003.property": "CodeBuild.Project.LogsConfig.CloudWatchLogs.GroupName",
                        "desired.row.008-003.value": "[logs](cloudwatch-logs.md#cloudwatch-logs-original)",
                        "desired.row.008-003.comment": "循環する保存リンク",
                    }
                )
            write_model(producer, values)
            producers[producer] = values
        path = root / "model" / env / "team/cloudwatch-logs.properties"
        values = resource(
            "002",
            "Logs.LogGroup",
            "glue-log-002",
            [
                (
                    "LogGroupName",
                    "`/aws-glue/jobs/"
                    + names["Configuration"]
                    + "-role/"
                    + names["ExecutionRole"]
                    + "/error`",
                ),
                ("DataProtectionPolicy", "[names](cloudwatch-logs/names.json)"),
            ],
        )
        values.update(
            resource(
                "003",
                "Logs.LogGroup",
                "lambda-log-003",
                [("LogGroupName", "`/aws/lambda/" + names["Function"] + "`")],
            )
        )
        values["desired.note.trail.text"] = "`/aws/cloudtrail/" + names["Trail"] + "`"
        values["desired.note.project.text"] = (
            "`/aws/codebuild/" + names["Project"] + "`"
        )
        key = "desired.row.002-002.document"
        values[key] = json.dumps(
            {
                "Role": names["ExecutionRole"],
                "Resource": "arn:aws:codecommit:ap-northeast-1:111111111111:"
                + names["Repository"],
                "Enabled": True,
                "Count": 2,
            }
        )
        consumers = {
            "Configuration": [("desired.row.002-001.value", None)],
            "ExecutionRole": [("desired.row.002-001.value", None), (key, "/Role")],
            "Function": [("desired.row.003-001.value", None)],
            "Trail": [("desired.note.trail.text", None)],
            "Project": [("desired.note.project.text", None)],
            "Repository": [(key, "/Resource")],
        }
        for name, positions in consumers.items():
            service, rid, kind, prop = specs[name]
            for index, (consumer, pointer) in enumerate(positions):
                values.update(
                    reference(
                        name + "-" + str(index),
                        consumer,
                        names[name],
                        service,
                        rid,
                        kind,
                        prop=kind + "." + prop,
                        pointer=pointer,
                        environment=env,
                    )
                )
        for name in ("Project", "Repository", "ExecutionRole"):
            service, rid, kind, _ = specs[name]
            _ = "existing-role-label" if name == "ExecutionRole" else names[name]
            link = f"[{names[name]}]({service}.md#{service}-original)"
            consumer = "desired.note." + name + "Link.text"
            values[consumer] = link
            values.update(
                reference(
                    name + "Link",
                    consumer,
                    link,
                    service,
                    rid,
                    kind,
                    mode="link",
                    label="fixed" if name == "ExecutionRole" else "display-name",
                    environment=env,
                )
            )
        write_model(path, values)
        model = load_model(path)
        assert not model.warnings, model.warnings
        assert (
            model.authoritative["desired.row.002-001.value"]
            == "`/aws-glue/jobs/glsc"
            + suffix
            + "-role/venusinf-"
            + env
            + "-IfInbound1802Role"
            + suffix
            + "/error`"
        )
        assert (
            model.authoritative["desired.row.003-001.value"]
            == "`/aws/lambda/lmda-" + env + "-inbound-detect" + suffix + "`"
        )
        assert (
            model.authoritative["desired.note.trail.text"]
            == "`/aws/cloudtrail/trail-" + env + suffix + "`"
        )
        assert (
            model.authoritative["desired.note.project.text"]
            == "`/aws/codebuild/cbld-" + env + suffix + "`"
        )
        doc = json.loads(model.authoritative[key])
        assert doc == {
            "Role": names["ExecutionRole"],
            "Resource": "arn:aws:codecommit:ap-northeast-1:111111111111:"
            + names["Repository"],
            "Enabled": True,
            "Count": 2,
        }
        assert {file for file in producers} <= set(model.dependencies)
        trace = trace_model(path, "desired.row.002-001.value")
        assert set(trace["references"]) == {"Configuration-0", "ExecutionRole-0"}
        records[env] = path, dict(model.authoritative), producers
    path, before, producers = records["preview"]
    other, other_before, _ = records["later"]
    producer = root / "model/preview/team/iam.properties"
    original = producers[producer]
    initial, dependencies = design_source_digest(path), dependency_hashes(path)
    write_model(producer, {**original, "desired.row.054-001.value": "`RenamedRole`"})
    changed = warning(path, "differs from saved text")
    assert changed.authoritative == before
    assert load_model(other).authoritative == other_before
    assert (
        design_source_digest(path) == initial
        and dependency_hashes(path) != dependencies
    )
    assert affected(root, [producer.relative_to(root)]) == {
        ("preview", "team", "iam"),
        ("preview", "team", "cloudwatch-logs"),
        ("preview", "team", "codebuild"),
    }
    assert (
        trace_model(path, "desired.row.002-001.value")["references"]["ExecutionRole-0"][
            "format"
        ]
        == "name"
    )
    write_model(
        producer,
        {key.replace(".054", ".055", 1): value for key, value in original.items()},
    )
    assert not load_model(path).warnings
    write_model(producer, original)
    write_model(producer, original)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        check(Path(directory).resolve())
    print(
        "Producer names: PASS (six services/two environments; raw fragments; case/suffix; strict JSON; fixed labels; trace; dependencies; warnings)"
    )
